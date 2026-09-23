"""
Protection CSRF (défense en profondeur) de l'API LabOnDemand.

Modèle
------
L'API est authentifiée par un cookie de session HttpOnly : le navigateur le
joint automatiquement à toute requête, y compris celles déclenchées par un
site tiers. Chaque requête mutante (toute méthode hors GET/HEAD/OPTIONS/TRACE)
sous ``/api/`` doit donc satisfaire DEUX contrôles indépendants :

1. **En-tête personnalisé obligatoire** ``X-Requested-With: XMLHttpRequest``.
   Un formulaire HTML ou un ``fetch`` « simple » ne peut pas le poser ; un
   ``fetch`` inter-origines qui le pose déclenche un preflight CORS que
   ``CORSMiddleware`` refuse pour toute origine non listée. La valeur est
   comparée exactement (insensible à la casse) : l'en-tête que certaines
   WebView Android ajoutent d'office (nom du paquet) n'est pas accepté.
2. **Vérification de l'origine** : si ``Origin`` est présent, il doit être de
   confiance (``null`` est refusé) ; à défaut, l'origine de ``Referer`` est
   vérifiée. En l'absence des deux (client non navigateur, Referer masqué),
   seul l'en-tête personnalisé fait foi.

Le « double submit cookie » est volontairement écarté : les labs étudiants
sont servis sur des sous-domaines frères (contenu contrôlé par l'étudiant)
qui peuvent poser des cookies sur le domaine parent (« cookie tossing »).

Origines de confiance
---------------------
- chaque entrée de ``CORS_ORIGINS``. ``*`` y est refusé au démarrage
  (:func:`validate_cors_origins`) et, par défense en profondeur, ignoré ici :
  ce n'est pas une origine et il ne doit jamais valider une requête
  authentifiée ;
- l'origine de ``FRONTEND_BASE_URL`` si elle est définie ;
- l'origine de la requête elle-même : schéma (``X-Forwarded-Proto`` via
  uvicorn ``--proxy-headers``, proxy de confiance uniquement) + en-tête
  ``Host`` transmis par nginx (``Host: $http_host``, port inclus).
  ``X-Forwarded-Host`` n'est jamais utilisé.
- la variante ``https://`` de ce même ``Host`` : derrière un terminateur TLS
  placé devant nginx, la requête arrive en http alors que le navigateur
  annonce ``Origin: https://…``. Accepter https pour une requête http est
  sans risque (un navigateur ne ment pas sur ``Origin``, et une page https
  du même hôte est au moins aussi fiable) ; l'inverse (http pour une
  requête https) est refusé, une page http pouvant être injectée par un
  attaquant réseau. Définir tout de même ``FRONTEND_BASE_URL`` en
  production : c'est la source explicite et la plus robuste.

La connexion (``POST /api/v1/auth/login``) est protégée comme le reste pour
empêcher le « login CSRF » (connecter la victime au compte de l'attaquant).

Le terminal WebSocket réutilise la même liste via
:func:`reject_untrusted_websocket_origin` (l'en-tête ``Origin`` y est
obligatoire, les navigateurs l'envoyant toujours).
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import FrozenSet, Iterable, Optional, Tuple
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from .config import settings
from .i18n import get_locale, t

logger = logging.getLogger("labondemand.csrf")
audit_logger = logging.getLogger("labondemand.audit")

# En-tête exigé sur toute requête mutante (valeur comparée sans casse).
CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "XMLHttpRequest"

# Méthodes sans effet de bord (RFC 9110) : jamais contrôlées.
SAFE_METHODS: FrozenSet[str] = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Préfixe des routes protégées (toutes les routes mutantes sont sous /api/).
PROTECTED_PATH_PREFIX = "/api/"

# Exemptions explicites : réservées aux endpoints machine-à-machine
# authentifiés par jeton (pas par cookie), p. ex. un callback de correcteur.
# Il n'en existe aucun aujourd'hui : le grader fonctionne en mode « pull »
# (l'API lit les logs du Job) et ne rappelle jamais l'API. Toute future
# exemption doit être listée ici avec sa justification.
CSRF_EXEMPT_PATHS: FrozenSet[str] = frozenset()

# Code de fermeture WebSocket « politique » (convention 44xx ≈ HTTP 4xx,
# cohérente avec 4401/4404 déjà utilisés par le terminal).
WS_POLICY_VIOLATION_CODE = 4403

_DEFAULT_PORTS = {"http": 80, "https": 443}
_WS_TO_HTTP = {"ws": "http", "wss": "https"}
_MULTI_SLASH = re.compile(r"/{2,}")
_MAX_LOGGED_LEN = 200


def normalize_origin(value: Optional[str], *, strict: bool = True) -> Optional[str]:
    """Normalise une origine en ``scheme://host[:port]`` (ou ``None`` si invalide).

    Schéma et hôte en minuscules, port par défaut (80/443) supprimé, IPv6
    entre crochets. Seuls http et https sont acceptés, sans identifiants.

    Args:
        value: valeur brute (en-tête ``Origin``, URL de ``Referer``, config).
        strict: si vrai (en-tête ``Origin``), refuse tout chemin, requête ou
            fragment ; sinon (``Referer``, configuration) ne garde que
            l'origine de l'URL.
    """
    if not value:
        return None
    raw = value.strip()
    try:
        parts = urlsplit(raw)
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if strict and (parts.path not in ("", "/") or parts.query or parts.fragment or "?" in raw or "#" in raw):
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def validate_cors_origins(cors_origins: Iterable[str]) -> None:
    """Refuse de démarrer si ``CORS_ORIGINS`` contient ``*``.

    Le CORS de l'API autorise les cookies (``allow_credentials=True``) : avec
    ``*``, Starlette renvoie l'origine de l'appelant dans
    ``Access-Control-Allow-Origin``, si bien que n'importe quel site pourrait
    lire les réponses authentifiées d'un utilisateur connecté.

    Raises:
        RuntimeError: ``*`` figure dans la liste.
    """
    if any(entry.strip() == "*" for entry in cors_origins):
        raise RuntimeError(
            "CORS_ORIGINS=* est refusé : les cookies de session étant autorisés "
            "en CORS, tout site pourrait lire les réponses authentifiées. "
            "Listez explicitement les origines du frontend "
            "(ex. CORS_ORIGINS=https://labondemand.example.org)."
        )


@lru_cache(maxsize=8)
def _configured_origins(cors_origins: Tuple[str, ...], frontend_base_url: Optional[str]) -> FrozenSet[str]:
    """Origines de confiance issues de la configuration (mises en cache)."""
    trusted = set()
    for entry in cors_origins:
        if entry.strip() == "*":
            logger.warning(
                "csrf_wildcard_origin_ignored",
                extra={"extra_fields": {"setting": "CORS_ORIGINS"}},
            )
            continue
        origin = normalize_origin(entry, strict=False)
        if origin:
            trusted.add(origin)
        else:
            logger.warning(
                "csrf_invalid_trusted_origin",
                extra={"extra_fields": {"setting": "CORS_ORIGINS", "value": entry[:_MAX_LOGGED_LEN]}},
            )
    if frontend_base_url:
        origin = normalize_origin(frontend_base_url, strict=False)
        if origin:
            trusted.add(origin)
    return frozenset(trusted)


def configured_trusted_origins() -> FrozenSet[str]:
    """Origines de confiance statiques : ``CORS_ORIGINS`` + ``FRONTEND_BASE_URL``."""
    return _configured_origins(tuple(settings.CORS_ORIGINS or ()), settings.FRONTEND_BASE_URL)


def request_origin(scope: Scope) -> Optional[str]:
    """Origine « same-origin » de la requête : schéma effectif + en-tête Host."""
    host = Headers(scope=scope).get("host")
    if not host:
        return None
    scheme = str(scope.get("scheme") or "http").lower()
    scheme = _WS_TO_HTTP.get(scheme, scheme)
    return normalize_origin(f"{scheme}://{host.strip()}")


def request_origins(scope: Scope) -> FrozenSet[str]:
    """Origines « same-origin » acceptées : celle de la requête + sa variante https.

    La variante https couvre un terminateur TLS placé devant nginx (voir
    l'en-tête du module) ; aucune variante http n'est jamais ajoutée.
    """
    host = Headers(scope=scope).get("host")
    if not host:
        return frozenset()
    origins = {request_origin(scope), normalize_origin(f"https://{host.strip()}")}
    return frozenset(origin for origin in origins if origin)


def is_trusted_origin(origin: Optional[str], scope: Scope) -> bool:
    """Vrai si l'origine (déjà normalisée) est de confiance pour cette requête."""
    if not origin:
        return False
    if origin in configured_trusted_origins():
        return True
    return origin in request_origins(scope)


def _origin_rejection_reason(headers: Headers, scope: Scope, *, require_origin: bool) -> Optional[str]:
    """Retourne la raison du refus lié à l'origine, ou ``None`` si acceptée."""
    raw_origin = headers.get("origin")
    if raw_origin is not None:
        if raw_origin.strip().lower() == "null":
            return "null_origin"
        if not is_trusted_origin(normalize_origin(raw_origin), scope):
            return "untrusted_origin"
        return None
    if require_origin:
        return "missing_origin"
    raw_referer = headers.get("referer")
    if raw_referer is not None:
        if not is_trusted_origin(normalize_origin(raw_referer, strict=False), scope):
            return "untrusted_referer"
    return None


def csrf_rejection_reason(scope: Scope) -> Optional[str]:
    """Évalue une requête HTTP ; retourne la raison du refus ou ``None``."""
    method = str(scope.get("method", "GET")).upper()
    if method in SAFE_METHODS:
        return None
    path = _MULTI_SLASH.sub("/", scope.get("path") or "/")
    if not path.startswith(PROTECTED_PATH_PREFIX) or path in CSRF_EXEMPT_PATHS:
        return None
    headers = Headers(scope=scope)
    if headers.get(CSRF_HEADER_NAME, "").strip().lower() != CSRF_HEADER_VALUE.lower():
        return "missing_custom_header"
    return _origin_rejection_reason(headers, scope, require_origin=False)


def _log_rejection(event: str, scope: Scope, reason: str) -> None:
    """Journalise un refus sans cookie ni URL complète du Referer."""
    headers = Headers(scope=scope)
    client = scope.get("client")
    raw_origin = headers.get("origin")
    audit_logger.warning(
        event,
        extra={
            "extra_fields": {
                "method": scope.get("method", "WEBSOCKET" if scope.get("type") == "websocket" else None),
                "path": scope.get("path"),
                "reason": reason,
                "origin": raw_origin[:_MAX_LOGGED_LEN] if raw_origin is not None else None,
                # Seule l'origine du Referer est journalisée (le chemin ou la
                # requête peuvent contenir des données sensibles).
                "referer_origin": normalize_origin(headers.get("referer"), strict=False),
                "host": (headers.get("host") or "")[:_MAX_LOGGED_LEN] or None,
                "client_ip": client[0] if client else None,
                "user_agent": (headers.get("user-agent") or "")[:_MAX_LOGGED_LEN] or None,
            }
        },
    )


class CSRFMiddleware:
    """Middleware ASGI pur : refuse (403) les requêtes mutantes non fiables.

    Implémenté en ASGI brut (et non ``BaseHTTPMiddleware``) : aucun effet sur
    le streaming, les tâches de fond ni les handlers synchrones ou
    asynchrones ; les WebSockets sont contrôlés dans leur handler.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        reason = csrf_rejection_reason(scope)
        if reason is None:
            await self.app(scope, receive, send)
            return
        _log_rejection("csrf_rejected", scope, reason)
        locale = get_locale(Request(scope))
        response = JSONResponse(
            status_code=403,
            content={"detail": t("error.csrf_failed", locale), "error": "csrf_failed"},
        )
        await response(scope, receive, send)


def websocket_origin_rejection_reason(scope: Scope) -> Optional[str]:
    """Évalue la poignée de main WebSocket : ``Origin`` obligatoire et de confiance."""
    return _origin_rejection_reason(Headers(scope=scope), scope, require_origin=True)


async def reject_untrusted_websocket_origin(websocket: WebSocket) -> bool:
    """Ferme la poignée de main (code 4403) si l'origine n'est pas de confiance.

    À appeler en tout premier dans un handler WebSocket, avant ``accept()``
    et avant toute authentification : protège contre le « Cross-Site
    WebSocket Hijacking » (le cookie de session est joint par le navigateur
    quelle que soit la page à l'origine de la connexion).

    Returns:
        True si la connexion a été refusée (le handler doit alors retourner).
    """
    reason = websocket_origin_rejection_reason(websocket.scope)
    if reason is None:
        return False
    _log_rejection("websocket_origin_rejected", websocket.scope, reason)
    await websocket.close(code=WS_POLICY_VIOLATION_CODE)
    return True

