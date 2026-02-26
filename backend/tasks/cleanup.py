"""
Tâche de fond : nettoyage des déploiements expirés et des namespaces orphelins.

TTL par défaut (configurables via env) :
  - student  → LAB_TTL_STUDENT_DAYS  (défaut : 7 jours)
  - teacher  → LAB_TTL_TEACHER_DAYS  (défaut : 30 jours)
  - admin    → illimité (expires_at reste NULL)

Grace period avant suppression définitive :
  - LAB_GRACE_PERIOD_DAYS  (défaut : 3 jours après mise en pause)

La tâche tourne toutes les CLEANUP_INTERVAL_MINUTES minutes (défaut : 60).

Atomicité :
  - La création de l'enregistrement DB suit la création K8s dans deployment_service.
    Si la DB est indisponible à ce moment, _track_deployment_in_db() attrape l'erreur
    silencieusement : le lab existe dans K8s mais pas encore en DB. L'auto-healing du
    GET /deployments/labondemand le rattrapera lors du prochain listing.
  - Il n'y a pas de rollback K8s car un lab sans enregistrement DB est préférable à
    un lab supprimé de K8s sans que l'utilisateur le sache.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("labondemand.cleanup")

# ── Paramètres ──────────────────────────────────────────────────────────────
LAB_TTL_STUDENT_DAYS = int(os.getenv("LAB_TTL_STUDENT_DAYS", "7"))
LAB_TTL_TEACHER_DAYS = int(os.getenv("LAB_TTL_TEACHER_DAYS", "30"))
LAB_GRACE_PERIOD_DAYS = int(
    os.getenv("LAB_GRACE_PERIOD_DAYS", "3")
)  # délai avant suppression après pause
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
                    await deployment_service.pause_application(
                        dep.namespace, dep.name, user
                    )
                dep.status = "paused"
                dep.last_seen_at = (
                    now  # horodatage de la mise en pause pour la grace period
                )
                db.commit()
                logger.info(
                    "deployment_auto_paused_expired",
                    extra={
                        "extra_fields": {
                            "deployment_id": dep.id,
                            "name": dep.name,
                            "namespace": dep.namespace,
                        }
                    },
                )
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "deployment_auto_pause_failed",
                    extra={
                        "extra_fields": {"deployment_id": dep.id, "error": str(exc)}
                    },
                )

        # ── 1b. Labs en pause depuis trop longtemps → suppression définitive ─
        grace_limit = now - timedelta(days=LAB_GRACE_PERIOD_DAYS)
        grace_expired = (
            db.query(Deployment)
            .filter(
                Deployment.status == "paused",
                Deployment.last_seen_at != None,  # noqa: E711
                Deployment.last_seen_at <= grace_limit,
                Deployment.deleted_at.is_(None),
            )
            .all()
        )
        for dep in grace_expired:
            try:
                from kubernetes import client as k8s_client

                apps_v1 = k8s_client.AppsV1Api()
                core_v1 = k8s_client.CoreV1Api()
                # Suppression du déploiement K8s (best-effort, ignorer 404)
                try:
                    apps_v1.delete_namespaced_deployment(dep.name, dep.namespace)
                except Exception:
                    pass
                # Suppression du service associé (best-effort)
                try:
                    core_v1.delete_namespaced_service(
                        f"{dep.name}-service", dep.namespace
                    )
                except Exception:
                    pass
                # Soft delete : on conserve l'historique
                dep.status = "deleted"
                dep.deleted_at = now
                db.commit()
                logger.info(
                    "deployment_auto_deleted_grace_expired",
                    extra={
                        "extra_fields": {
                            "deployment_id": dep.id,
                            "name": dep.name,
                            "namespace": dep.namespace,
                            "paused_since": dep.last_seen_at.isoformat()
                            if dep.last_seen_at
                            else None,
                        }
                    },
                )
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "deployment_auto_delete_failed",
                    extra={
                        "extra_fields": {"deployment_id": dep.id, "error": str(exc)}
                    },
                )

        # ── 2. Rétro-remplissage expires_at manquant ────────────────────────
        #    Pour les enregistrements actifs sans expires_at (créés avant ce correctif),
        #    on leur attribue une date d'expiration basée sur la date de création + TTL du rôle.
        try:
            orphan_expires = (
                db.query(Deployment)
                .filter(
                    Deployment.status == "active",
                    Deployment.expires_at == None,  # noqa: E711
                )
                .all()
            )
            for dep in orphan_expires:
                user = db.query(User).filter(User.id == dep.user_id).first()
                if user is None:
                    continue
                role_val = getattr(user.role, "value", str(user.role))
                ttl = get_ttl_days_for_role(role_val)
                if ttl is None:
                    # admin → pas d'expiration, on laisse NULL
                    continue
                # Calculer depuis created_at si disponible, sinon depuis maintenant
                base = dep.created_at if dep.created_at else now
                # S'assurer que base est timezone-aware
                if base.tzinfo is None:
                    base = base.replace(tzinfo=timezone.utc)
                dep.expires_at = base + timedelta(days=ttl)
                logger.info(
                    "deployment_expires_at_backfilled",
                    extra={
                        "extra_fields": {
                            "deployment_id": dep.id,
                            "name": dep.name,
                            "expires_at": dep.expires_at.isoformat(),
                        }
                    },
                )
            if orphan_expires:
                try:
                    db.commit()
                except Exception:
                    # Race condition : un autre processus a pu modifier ces lignes entre-temps
                    db.rollback()
                    logger.debug("deployment_expires_at_backfill_race_ignored")
        except Exception as exc:
            db.rollback()
            logger.warning(
                "deployment_expires_at_backfill_failed",
                extra={"extra_fields": {"error": str(exc)}},
            )

        # ── 3. Namespaces orphelins ──────────────────────────────────────────
        #    Lister tous les namespaces labondemand-user-*, vérifier si l'user existe.
        #
        #    SÉCURITÉ SSO : un utilisateur SSO peut se voir attribuer un nouvel id en DB
        #    si son email change côté IdP (nouvelle ligne User créée, ancienne conservée).
        #    Pour éviter de supprimer le namespace d'un user SSO encore actif, on applique
        #    deux garde-fous :
        #      a) On vérifie si le namespace a des déploiements actifs en DB (user_id orphelin
        #         mais deployments rattachés à ce user_id → on ne supprime pas).
        #      b) On applique un délai de grâce de ORPHAN_NS_GRACE_DAYS jours : un namespace
        #         dont l'utilisateur DB n'existe plus n'est supprimé que s'il a été créé
        #         il y a plus de ORPHAN_NS_GRACE_DAYS jours, laissant le temps à un
        #         éventuel re-login SSO de réconcilier les comptes.
        ORPHAN_NS_GRACE_DAYS = int(os.getenv("ORPHAN_NS_GRACE_DAYS", "7"))
        try:
            from kubernetes import client as k8s_client
            from ..models import Deployment as DeploymentModel

            core_v1 = k8s_client.CoreV1Api()
            prefix = "labondemand-user-"
            ns_list = core_v1.list_namespace(label_selector=f"managed-by=labondemand")
            for ns in ns_list.items:
                ns_name = ns.metadata.name or ""
                if not ns_name.startswith(prefix):
                    continue
                try:
                    user_id_str = ns_name[len(prefix) :]
                    user_id = int(user_id_str)
                except ValueError:
                    continue
                user = db.query(User).filter(User.id == user_id).first()
                if user is not None:
                    # Utilisateur trouvé → namespace légitime, on ne touche pas
                    continue

                # Utilisateur introuvable en DB. Vérifier les garde-fous avant suppression.

                # Garde-fou (a) : des déploiements actifs sont encore associés à ce user_id
                active_deployments = (
                    db.query(DeploymentModel)
                    .filter(
                        DeploymentModel.user_id == user_id,
                        DeploymentModel.deleted_at.is_(None),
                        DeploymentModel.status != "deleted",
                    )
                    .count()
                )
                if active_deployments > 0:
                    logger.info(
                        "orphan_namespace_skipped_active_deployments",
                        extra={
                            "extra_fields": {
                                "namespace": ns_name,
                                "user_id": user_id,
                                "active_deployments": active_deployments,
                            }
                        },
                    )
                    continue

                # Garde-fou (b) : délai de grâce basé sur la date de création du namespace
                ns_creation = ns.metadata.creation_timestamp  # datetime ou None
                if ns_creation is not None:
                    # s'assurer que c'est timezone-aware
                    if ns_creation.tzinfo is None:
                        ns_creation = ns_creation.replace(tzinfo=timezone.utc)
                    age_days = (now - ns_creation).days
                    if age_days < ORPHAN_NS_GRACE_DAYS:
                        logger.info(
                            "orphan_namespace_skipped_grace_period",
                            extra={
                                "extra_fields": {
                                    "namespace": ns_name,
                                    "user_id": user_id,
                                    "age_days": age_days,
                                    "grace_days": ORPHAN_NS_GRACE_DAYS,
                                }
                            },
                        )
                        continue

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
                        extra={
                            "extra_fields": {
                                "namespace": ns_name,
                                "error": str(del_exc),
                            }
                        },
                    )
        except Exception as k8s_exc:
            logger.debug(
                "orphan_ns_check_skipped",
                extra={"extra_fields": {"error": str(k8s_exc)}},
            )

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
            logger.exception(
                "cleanup_cycle_error", extra={"extra_fields": {"error": str(exc)}}
            )
        await asyncio.sleep(interval_seconds)
