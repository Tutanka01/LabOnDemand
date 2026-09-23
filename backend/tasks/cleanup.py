"""
Tâche de fond : nettoyage des déploiements expirés et des namespaces orphelins.

TTL par défaut (configurables via env) :
  - student  → LAB_TTL_STUDENT_DAYS  (défaut : 7 jours)
  - teacher  → LAB_TTL_TEACHER_DAYS  (défaut : 30 jours)
  - admin    → illimité (expires_at reste NULL)

Grace period avant suppression définitive :
  - LAB_GRACE_PERIOD_DAYS  (défaut : 3 jours après mise en pause)

La tâche tourne toutes les CLEANUP_INTERVAL_MINUTES minutes (défaut : 60).

Exécution :
  - chaque cycle tourne dans un thread (``asyncio.to_thread``) : les accès DB et
    Kubernetes sont synchrones et ne doivent pas bloquer la boucle de l'API ;
  - un seul processus (worker/réplica) exécute les cycles : il détient un verrou
    Redis de leader (``backend.redis_lock``), prolongé à chaque itération et
    pendant le cycle. Les autres processus sautent leur itération ; si le leader
    disparaît, le verrou expire (CLEANUP_LOCK_TTL_SECONDS) et un autre le reprend.
    Redis injoignable → l'itération est sautée avec un avertissement.

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
from typing import Any, Optional

import redis

from ..config import settings
from ..redis_lock import RedisLock

logger = logging.getLogger("labondemand.cleanup")

# ── Paramètres ──────────────────────────────────────────────────────────────
LAB_TTL_STUDENT_DAYS = int(os.getenv("LAB_TTL_STUDENT_DAYS", "7"))
LAB_TTL_TEACHER_DAYS = int(os.getenv("LAB_TTL_TEACHER_DAYS", "30"))
LAB_GRACE_PERIOD_DAYS = int(
    os.getenv("LAB_GRACE_PERIOD_DAYS", "3")
)  # délai avant suppression après pause
CLEANUP_INTERVAL_MINUTES = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "60"))
# Délai au-delà duquel un Grading Run encore queued/running est considéré bloqué.
GRADING_RUN_STUCK_MINUTES = int(os.getenv("GRADING_RUN_STUCK_MINUTES", "15"))

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


def _run_cleanup_cycle() -> None:
    """Exécute un cycle de nettoyage complet (synchrone : appelé dans un thread)."""
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
                    deployment_service.pause_application(
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
                user = db.query(User).filter(User.id == dep.user_id).first()
                if user:
                    deployment_service.delete_labondemand_resources(
                        namespace=dep.namespace,
                        name=dep.stack_name or dep.name,
                        current_user=user,
                        delete_services=True,
                        delete_persistent=False,
                    )
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

        # ── 1c. Réconciliation des Grading Runs bloqués ─────────────────────
        #    Un run resté en queued/running au-delà d'un délai max (le Job a pu
        #    disparaître, le watcher a pu mourir avec l'API) est marqué en error,
        #    et son Job grader éventuel est supprimé (filet en plus du TTL K8s).
        try:
            from ..models import GradingRun
            from .. import grader_service

            stuck_limit = now - timedelta(minutes=GRADING_RUN_STUCK_MINUTES)
            stuck_runs = (
                db.query(GradingRun)
                .filter(GradingRun.status.in_(["queued", "running"]))
                .all()
            )
            for run in stuck_runs:
                started = run.started_at or run.created_at
                if started is not None and started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if started is None or started > stuck_limit:
                    continue
                run.status = "error"
                run.error = "Run interrompu (réconciliation automatique)"
                run.finished_at = now
                db.commit()
                logger.info(
                    "grading_run_reconciled_stuck",
                    extra={"extra_fields": {"run_id": run.id}},
                )
                try:
                    grader_service._delete_job(grader_service.job_name_for_run(run.id))
                except Exception as exc:
                    logger.warning(
                        "grading_job_cleanup_failed",
                        extra={"extra_fields": {"run_id": run.id, "error": str(exc)}},
                    )
        except Exception as exc:
            db.rollback()
            logger.warning(
                "grading_run_reconcile_failed",
                extra={"extra_fields": {"error": str(exc)}},
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


# ── Boucle de fond et élection du leader ──────────────────────────────────────

CLEANUP_LOCK_KEY = "labondemand:lock:cleanup"
# Délais du client Redis dédié au verrou (un Redis figé ne bloque pas un thread).
_REDIS_TIMEOUT_SECONDS = 5

# Références fortes vers la boucle en cours : bootstrap() la crée sans garder
# de référence, or la boucle asyncio ne tient que des références faibles.
_loop_tasks: "set[asyncio.Task[Any]]" = set()


def _lock_ttl_seconds(interval_seconds: int) -> float:
    """TTL du verrou : doit dépasser une itération (intervalle + cycle)."""
    configured = settings.CLEANUP_LOCK_TTL_SECONDS
    if configured > 0:
        return float(configured)
    return max(120.0, 2.0 * interval_seconds)


def _make_redis_client() -> redis.Redis:
    return redis.from_url(
        settings.REDIS_URL,
        socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_TIMEOUT_SECONDS,
    )


async def _hold_leadership(lock: RedisLock) -> bool:
    """Prolonge le verrou s'il est détenu, sinon tente de le prendre.

    Retourne True si ce processus est leader pour l'itération courante.
    """
    try:
        if lock.owned and await asyncio.to_thread(lock.extend):
            return True
        return await asyncio.to_thread(lock.acquire)
    except redis.RedisError as exc:
        logger.warning(
            "cleanup_skipped_redis_unavailable",
            extra={"extra_fields": {"error": str(exc)}},
        )
        return False


async def _run_cycle_with_heartbeat(lock: RedisLock) -> None:
    """Exécute un cycle dans un thread en prolongeant le verrou tant qu'il tourne."""
    cycle = asyncio.ensure_future(asyncio.to_thread(_run_cleanup_cycle))
    period = lock.ttl_seconds / 3
    lost = False
    try:
        while True:
            done, _ = await asyncio.wait({cycle}, timeout=period)
            if done:
                cycle.result()  # propage une éventuelle exception du cycle
                return
            if lost:
                continue
            try:
                still_owned = await asyncio.to_thread(lock.extend)
            except redis.RedisError as exc:
                logger.warning(
                    "cleanup_lock_extend_failed",
                    extra={"extra_fields": {"error": str(exc)}},
                )
                continue
            if not still_owned:
                # Impossible d'interrompre le thread : le cycle se termine,
                # mais un autre processus a pu prendre la main.
                lost = True
                logger.warning(
                    "cleanup_lock_lost",
                    extra={"extra_fields": {"key": lock.key}},
                )
    except asyncio.CancelledError:
        if not cycle.done():
            # Le thread continue jusqu'à la fin du cycle : on ne relâche pas le
            # verrou (il expirera seul) pour éviter un cycle concurrent ailleurs.
            lock.abandon()
            logger.warning(
                "cleanup_cancelled_during_cycle",
                extra={"extra_fields": {"key": lock.key}},
            )
        raise


async def _cleanup_iteration(lock: RedisLock) -> bool:
    """Une itération : leadership puis cycle. Retourne True si un cycle a tourné."""
    if not await _hold_leadership(lock):
        return False
    await _run_cycle_with_heartbeat(lock)
    return True


async def _release_quietly(lock: RedisLock) -> None:
    if not lock.owned:
        return
    try:
        await asyncio.to_thread(lock.release)
    except redis.RedisError as exc:
        logger.warning(
            "cleanup_lock_release_failed",
            extra={"extra_fields": {"error": str(exc)}},
        )


async def run_cleanup_loop(lock: Optional[RedisLock] = None) -> None:
    """Boucle infinie : attend l'intervalle configuré entre chaque itération."""
    interval_seconds = CLEANUP_INTERVAL_MINUTES * 60
    task = asyncio.current_task()
    if task is not None:
        _loop_tasks.add(task)
    if lock is None:
        lock = RedisLock(
            _make_redis_client(), CLEANUP_LOCK_KEY, _lock_ttl_seconds(interval_seconds)
        )
    logger.info(
        "cleanup_task_started",
        extra={
            "extra_fields": {
                "interval_minutes": CLEANUP_INTERVAL_MINUTES,
                "lock_ttl_seconds": lock.ttl_seconds,
            }
        },
    )
    try:
        while True:
            try:
                await _cleanup_iteration(lock)
            except Exception as exc:
                logger.exception(
                    "cleanup_cycle_error", extra={"extra_fields": {"error": str(exc)}}
                )
            await asyncio.sleep(interval_seconds)
    finally:
        if task is not None:
            _loop_tasks.discard(task)
        # Arrêt propre : rend la main tout de suite à un autre processus.
        await _release_quietly(lock)
