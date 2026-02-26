"""
Tâche de fond : nettoyage des déploiements expirés et des namespaces orphelins.

TTL par défaut (configurables via env) :
  - student  → LAB_TTL_STUDENT_DAYS  (défaut : 7 jours)
  - teacher  → LAB_TTL_TEACHER_DAYS  (défaut : 30 jours)
  - admin    → illimité (expires_at reste NULL)

La tâche tourne toutes les CLEANUP_INTERVAL_MINUTES minutes (défaut : 60).
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("labondemand.cleanup")

# ── Paramètres ──────────────────────────────────────────────────────────────
LAB_TTL_STUDENT_DAYS = int(os.getenv("LAB_TTL_STUDENT_DAYS", "7"))
LAB_TTL_TEACHER_DAYS = int(os.getenv("LAB_TTL_TEACHER_DAYS", "30"))
CLEANUP_INTERVAL_MINUTES = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "60"))

_ROLE_TTL_DAYS = {
    "student": LAB_TTL_STUDENT_DAYS,
    "teacher": LAB_TTL_TEACHER_DAYS,
    "admin": None,  # illimité
}


def get_ttl_days_for_role(role: str) -> int | None:
    """Retourne le TTL en jours pour un rôle donné, ou None pour admin."""
    return _ROLE_TTL_DAYS.get(role, LAB_TTL_STUDENT_DAYS)


def compute_expires_at(role: str) -> datetime | None:
    """Calcule la date d'expiration pour un nouveau déploiement selon le rôle."""
    ttl = get_ttl_days_for_role(role)
    if ttl is None:
        return None
    return datetime.now(timezone.utc) + timedelta(days=ttl)


async def _run_cleanup_cycle() -> None:
    """Exécute un cycle de nettoyage complet."""
    from ..database import SessionLocal
    from ..models import Deployment, User
    from ..deployment_service import deployment_service

    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        # ── 1. Labs expirés → pause automatique ──────────────────────────────
        expired = (
            db.query(Deployment)
            .filter(
                Deployment.status == "active",
                Deployment.expires_at != None,  # noqa: E711
                Deployment.expires_at <= now,
            )
            .all()
        )
        for dep in expired:
            try:
                user = db.query(User).filter(User.id == dep.user_id).first()
                if user:
                    await deployment_service.pause_application(dep.namespace, dep.name, user)
                dep.status = "paused"
                db.commit()
                logger.info(
                    "deployment_auto_paused_expired",
                    extra={"extra_fields": {"deployment_id": dep.id, "name": dep.name, "namespace": dep.namespace}},
                )
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "deployment_auto_pause_failed",
                    extra={"extra_fields": {"deployment_id": dep.id, "error": str(exc)}},
                )

        # ── 2. Namespaces orphelins ──────────────────────────────────────────
        #    Lister tous les namespaces labondemand-user-*, vérifier si l'user existe
        try:
            from kubernetes import client as k8s_client
            core_v1 = k8s_client.CoreV1Api()
            prefix = "labondemand-user-"
            ns_list = core_v1.list_namespace(label_selector=f"managed-by=labondemand")
            for ns in ns_list.items:
                ns_name = ns.metadata.name or ""
                if not ns_name.startswith(prefix):
                    continue
                try:
                    user_id_str = ns_name[len(prefix):]
                    user_id = int(user_id_str)
                except ValueError:
                    continue
                user = db.query(User).filter(User.id == user_id).first()
                if user is None:
                    logger.info(
                        "orphan_namespace_found",
                        extra={"extra_fields": {"namespace": ns_name, "user_id": user_id}},
                    )
                    try:
                        core_v1.delete_namespace(ns_name)
                        logger.info(
                            "orphan_namespace_deleted",
                            extra={"extra_fields": {"namespace": ns_name}},
                        )
                    except Exception as del_exc:
                        logger.warning(
                            "orphan_namespace_delete_failed",
                            extra={"extra_fields": {"namespace": ns_name, "error": str(del_exc)}},
                        )
        except Exception as k8s_exc:
            logger.debug("orphan_ns_check_skipped", extra={"extra_fields": {"error": str(k8s_exc)}})

    finally:
        db.close()


async def run_cleanup_loop() -> None:
    """Boucle infinie : attend l'intervalle configuré entre chaque cycle."""
    interval_seconds = CLEANUP_INTERVAL_MINUTES * 60
    logger.info(
        "cleanup_task_started",
        extra={"extra_fields": {"interval_minutes": CLEANUP_INTERVAL_MINUTES}},
    )
    while True:
        try:
            await _run_cleanup_cycle()
        except Exception as exc:
            logger.exception("cleanup_cycle_error", extra={"extra_fields": {"error": str(exc)}})
        await asyncio.sleep(interval_seconds)
