"""
Router — Logs d'audit (admin only)

Expose GET /api/v1/audit-logs avec :
  - pagination  : page, page_size
  - filtres     : event, username, level, date_from, date_to, search (fulltext)
  - export      : ?export=json  → téléchargement du fichier complet filtré
  - stats       : GET /api/v1/audit-logs/stats → résumé par event / level
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..config import settings
from ..security import is_admin

audit_router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit"])

# ── Chemin du fichier audit.log ────────────────────────────────────────────────
_LOG_PATH = Path(settings.LOG_DIR) / "audit.log"

# ── Mapping event → catégorie lisible ─────────────────────────────────────────
EVENT_LABELS: dict[str, str] = {
    "login_success": "Connexion",
    "login_failed": "Échec connexion",
    "logout": "Déconnexion",
    "user_registered": "Création utilisateur",
    "user_updated": "Modification utilisateur",
    "user_deleted": "Suppression utilisateur",
    "user_self_update": "Mise à jour profil",
    "password_changed": "Changement mot de passe",
    "quota_override_set": "Dérogation quota",
    "users_imported_csv": "Import CSV",
    "deployment_created": "Déploiement créé",
    "deployment_deleted": "Déploiement supprimé",
    "deployment_paused": "Déploiement mis en pause",
    "deployment_resumed": "Déploiement repris",
}

# ── Catégories regroupées ──────────────────────────────────────────────────────
CATEGORIES: dict[str, list[str]] = {
    "auth": ["login_success", "login_failed", "logout"],
    "users": [
        "user_registered",
        "user_updated",
        "user_deleted",
        "user_self_update",
        "password_changed",
        "quota_override_set",
        "users_imported_csv",
    ],
    "deployments": [
        "deployment_created",
        "deployment_deleted",
        "deployment_paused",
        "deployment_resumed",
    ],
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _read_log_entries() -> list[dict]:
    """Lit le fichier audit.log et retourne les lignes JSON parsées."""
    if not _LOG_PATH.exists():
        return []
    entries: list[dict] = []
    try:
        with _LOG_PATH.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    entries.append(obj)
                except json.JSONDecodeError:
                    # ligne malformée — on l'ignore gracieusement
                    entries.append(
                        {
                            "timestamp": None,
                            "level": "UNKNOWN",
                            "message": line[:200],
                            "_raw": True,
                        }
                    )
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Impossible de lire audit.log : {exc}",
        )
    return entries


def _parse_ts(entry: dict) -> Optional[datetime]:
    """Convertit le champ timestamp d'une entrée en datetime UTC."""
    raw = entry.get("timestamp")
    if not raw:
        return None
    try:
        # La JsonFormatter génère un ISO 8601 avec 'Z' → remplacer pour fromisoformat
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _filter_entries(
    entries: list[dict],
    *,
    event: Optional[str],
    category: Optional[str],
    username: Optional[str],
    level: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
    search: Optional[str],
) -> list[dict]:
    """Applique tous les filtres sur la liste d'entrées."""
    result: list[dict] = []

    search_lower = search.lower() if search else None

    # Catégorie → liste d'events
    category_events: Optional[set[str]] = None
    if category and category in CATEGORIES:
        category_events = set(CATEGORIES[category])

    for e in entries:
        msg = e.get("message", "")

        # Filtre event exact
        if event and msg != event:
            continue

        # Filtre catégorie
        if category_events and msg not in category_events:
            continue

        # Filtre niveau
        if level and e.get("level", "").upper() != level.upper():
            continue

        # Filtre username (dans plusieurs champs possibles)
        if username:
            ul = username.lower()
            found = False
            for field in ("username", "target_username"):
                val = e.get(field, "")
                if isinstance(val, str) and ul in val.lower():
                    found = True
                    break
            if not found:
                continue

        # Filtre plage de dates
        ts = _parse_ts(e)
        if date_from and ts and ts < date_from:
            continue
        if date_to and ts and ts > date_to:
            continue

        # Fulltext search sur la ligne JSON sérialisée
        if search_lower:
            line_str = json.dumps(e, ensure_ascii=False).lower()
            if search_lower not in line_str:
                continue

        result.append(e)

    return result


# ── Endpoints ──────────────────────────────────────────────────────────────────


@audit_router.get("/stats", dependencies=[Depends(is_admin)])
async def get_audit_stats():
    """
    Retourne les statistiques globales des logs d'audit :
      - total d'entrées
      - répartition par event (message)
      - répartition par niveau (INFO / WARNING / ERROR)
      - répartition par catégorie
      - date du dernier event
      - activité des 7 derniers jours (un bucket par jour)
    """
    entries = _read_log_entries()

    by_event: dict[str, int] = {}
    by_level: dict[str, int] = {}
    by_category: dict[str, int] = {"auth": 0, "users": 0, "deployments": 0, "other": 0}
    last_ts: Optional[str] = None
    last_dt: Optional[datetime] = None

    # Activité sur 7 jours — index [0] = aujourd'hui, [6] = il y a 6 jours
    now_utc = datetime.now(timezone.utc)
    activity_7d: list[dict] = []
    for i in range(6, -1, -1):
        from datetime import timedelta

        d = (now_utc - timedelta(days=i)).date()
        activity_7d.append({"date": d.isoformat(), "count": 0})

    date_to_idx = {item["date"]: idx for idx, item in enumerate(activity_7d)}

    for e in entries:
        msg = e.get("message", "unknown")
        level = e.get("level", "UNKNOWN").upper()

        by_event[msg] = by_event.get(msg, 0) + 1
        by_level[level] = by_level.get(level, 0) + 1

        # Catégorie
        found_cat = False
        for cat, events in CATEGORIES.items():
            if msg in events:
                by_category[cat] += 1
                found_cat = True
                break
        if not found_cat:
            by_category["other"] += 1

        # Dernier event
        ts = _parse_ts(e)
        if ts and (last_dt is None or ts > last_dt):
            last_dt = ts
            last_ts = e.get("timestamp")

        # Activité 7 jours
        if ts:
            day_str = ts.date().isoformat()
            if day_str in date_to_idx:
                activity_7d[date_to_idx[day_str]]["count"] += 1

    # Top 10 events
    top_events = sorted(by_event.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total": len(entries),
        "last_event_at": last_ts,
        "by_level": by_level,
        "by_category": by_category,
        "top_events": [
            {
                "event": ev,
                "label": EVENT_LABELS.get(ev, ev),
                "count": cnt,
            }
            for ev, cnt in top_events
        ],
        "activity_7d": activity_7d,
    }


@audit_router.get("", dependencies=[Depends(is_admin)])
async def list_audit_logs(
    # Pagination
    page: int = Query(1, ge=1, description="Page (commence à 1)"),
    page_size: int = Query(50, ge=1, le=500, description="Entrées par page"),
    # Filtres
    event: Optional[str] = Query(None, description="Filtrer par event exact"),
    category: Optional[str] = Query(None, description="auth | users | deployments"),
    username: Optional[str] = Query(None, description="Filtrer par nom d'utilisateur"),
    level: Optional[str] = Query(None, description="INFO | WARNING | ERROR"),
    date_from: Optional[datetime] = Query(None, description="Date de début (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="Date de fin (ISO 8601)"),
    search: Optional[str] = Query(None, description="Recherche fulltext"),
    # Export
    export: Optional[str] = Query(None, description="'json' pour télécharger"),
):
    """
    Liste paginée des entrées du fichier audit.log avec filtres.

    Les entrées sont retournées du plus récent au plus ancien.
    """
    raw_entries = _read_log_entries()

    # Les logs sont en ordre chronologique — on inverse pour avoir le plus récent en premier
    entries_desc = list(reversed(raw_entries))

    filtered = _filter_entries(
        entries_desc,
        event=event,
        category=category,
        username=username,
        level=level,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )

    total = len(filtered)

    # Export JSON complet (toutes les entrées filtrées, sans pagination)
    if export == "json":
        payload = json.dumps(filtered, ensure_ascii=False, indent=2)
        return StreamingResponse(
            iter([payload]),
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="audit-export-'
                    f'{datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}.json"'
                )
            },
        )

    # Pagination
    offset = (page - 1) * page_size
    page_entries = filtered[offset : offset + page_size]

    # Enrichir chaque entrée avec le label lisible de l'event
    enriched = []
    for e in page_entries:
        item = dict(e)
        item["event_label"] = EVENT_LABELS.get(
            e.get("message", ""), e.get("message", "—")
        )
        enriched.append(item)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, -(-total // page_size)),  # division plafond
        "entries": enriched,
        # Méta pour les filtres disponibles côté front
        "available_events": list(EVENT_LABELS.keys()),
        "categories": list(CATEGORIES.keys()),
    }
