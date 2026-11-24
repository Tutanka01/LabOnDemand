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
from typing import Callable, Tuple

from sqlalchemy.orm import Session

from ..models import Deployment, User

logger = logging.getLogger("labondemand.cleanup")

# ── Paramètres ──────────────────────────────────────────────────────────────
LAB_TTL_STUDENT_DAYS = int(os.getenv("LAB_TTL_STUDENT_DAYS", "7"))
LAB_TTL_TEACHER_DAYS = int(os.getenv("LAB_TTL_TEACHER_DAYS", "30"))
LAB_GRACE_PERIOD_DAYS = int(
    os.getenv("LAB_GRACE_PERIOD_DAYS", "3")
)  # délai avant suppression après pause
CLEANUP_INTERVAL_MINUTES = int(os.getenv("CLEANUP_INTERVAL_MINUTES", "60"))
# A running Grading Run (picked up by a worker, clock = started_at) still not
# finished after this long is considered stuck (job gone, watcher dead).
GRADING_RUN_STUCK_MINUTES = int(os.getenv("GRADING_RUN_STUCK_MINUTES", "15"))
# A queued run legitimately waits for a free grader worker (a class-wide run
# on unresponsive labs keeps every worker busy for timeout + grace each), so
# it is only given up after this much larger bound (clock = created_at).
GRADING_RUN_QUEUED_MAX_MINUTES = int(os.getenv("GRADING_RUN_QUEUED_MAX_MINUTES", "180"))

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


ORPHAN_NS_GRACE_DAYS = int(os.getenv("ORPHAN_NS_GRACE_DAYS", "7"))
_USER_NAMESPACE_PREFIX = "labondemand-user-"


def _lab_not_found(exc: BaseException) -> bool:
    """True when Kubernetes says the lab no longer exists."""
    from fastapi import HTTPException
    from kubernetes import client as k8s_client

    if isinstance(exc, HTTPException):
        return exc.status_code == 404
    if isinstance(exc, k8s_client.exceptions.ApiException):
        return exc.status == 404
    return False


def _mark_row_deleted(db: Session, dep: Deployment, now: datetime, step: str) -> None:
    """Heal a row whose lab is gone from the cluster (instead of retrying forever)."""
    dep.status = "deleted"
    dep.deleted_at = now
    db.commit()
    logger.info(
        "deployment_row_healed_missing_lab",
        extra={
            "extra_fields": {
                "deployment_id": dep.id,
                "name": dep.name,
                "namespace": dep.namespace,
                "step": step,
            }
        },
    )


def _pause_expired_labs(db: Session, now: datetime) -> None:
    """Active labs past ``expires_at`` are paused (grace period starts).

    A row whose lab no longer exists in Kubernetes (404) is marked deleted.
    Each lab is handled under its owner's lab lock, re-checking the row, so a
    lab being (re)created or deleted concurrently is never mis-healed.
    """
    from ..deployment_service import deployment_service
    from ..lab_locks import user_lab_lock

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
        dep_id, owner_id = dep.id, dep.user_id
        try:
            with user_lab_lock(owner_id):
                # New transaction: see what concurrent requests committed.
                db.rollback()
                db.refresh(dep)
                expires_at = _as_utc(dep.expires_at)
                if (
                    dep.status != "active"
                    or dep.deleted_at is not None
                    or expires_at is None
                    or expires_at > now
                ):
                    db.rollback()
                    continue  # changed meanwhile (re-created, deleted, paused...)
                user = db.query(User).filter(User.id == dep.user_id).first()
                try:
                    if user:
                        deployment_service.pause_application(dep.namespace, dep.name, user)
                except Exception as exc:
                    if not _lab_not_found(exc):
                        raise
                    _mark_row_deleted(db, dep, now, "pause_expired")
                    continue
                dep.status = "paused"
                dep.last_seen_at = now  # pause time, start of the grace period
                db.commit()
            logger.info(
                "deployment_auto_paused_expired",
                extra={"extra_fields": {"deployment_id": dep_id}},
            )
        except Exception as exc:
            db.rollback()
            logger.warning(
                "deployment_auto_pause_failed",
                extra={"extra_fields": {"deployment_id": dep_id, "error": str(exc)}},
            )


def _delete_grace_expired_labs(db: Session, now: datetime) -> None:
    """Labs paused for longer than the grace period are deleted (soft delete in DB).

    A lab already gone from Kubernetes (404) gets its row soft-deleted too,
    instead of failing on every cycle.
    """
    from ..deployment_service import deployment_service
    from ..lab_locks import user_lab_lock

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
        dep_id, owner_id = dep.id, dep.user_id
        try:
            # Same lock as delete_labondemand_resources (re-entrant).
            with user_lab_lock(owner_id):
                db.rollback()  # new transaction: see concurrent changes
                db.refresh(dep)
                if dep.status != "paused" or dep.deleted_at is not None:
                    db.rollback()
                    continue  # resumed or deleted meanwhile
                user = db.query(User).filter(User.id == dep.user_id).first()
                try:
                    if user:
                        deployment_service.delete_labondemand_resources(
                            namespace=dep.namespace,
                            name=dep.stack_name or dep.name,
                            current_user=user,
                            delete_services=True,
                            delete_persistent=False,
                        )
                except Exception as exc:
                    if not _lab_not_found(exc):
                        raise
                    _mark_row_deleted(db, dep, now, "delete_grace_expired")
                    continue
                dep.status = "deleted"
                dep.deleted_at = now
                db.commit()
            logger.info(
                "deployment_auto_deleted_grace_expired",
                extra={"extra_fields": {"deployment_id": dep_id}},
            )
        except Exception as exc:
            db.rollback()
            logger.warning(
                "deployment_auto_delete_failed",
                extra={"extra_fields": {"deployment_id": dep_id, "error": str(exc)}},
            )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _reconcile_stuck_grading_runs(db: Session, now: datetime) -> None:
    """Runs stuck in queued/running (job gone, watcher died with the API) become
    ``error`` and their grader Job is deleted (on top of the Kubernetes TTL).

    - ``running``: stuck once ``started_at`` (when a worker picked it up) is
      older than ``GRADING_RUN_STUCK_MINUTES``;
    - ``queued``: waiting for a free worker is normal, so the bound is the much
      larger ``GRADING_RUN_QUEUED_MAX_MINUTES`` from ``created_at``.

    Each flip is a conditional UPDATE on the observed status, so a run a worker
    picks up (queued -> running) at the same moment is left alone.
    """
    from sqlalchemy import update

    from ..models import GradingRun
    from .. import grader_service

    limits = {
        "running": now - timedelta(minutes=GRADING_RUN_STUCK_MINUTES),
        "queued": now - timedelta(minutes=GRADING_RUN_QUEUED_MAX_MINUTES),
    }
    candidates = (
        db.query(GradingRun.id, GradingRun.status, GradingRun.started_at, GradingRun.created_at)
        .filter(GradingRun.status.in_(list(limits)))
        .all()
    )
    for run_id, status, started_at, created_at in candidates:
        clock = _as_utc(started_at or created_at) if status == "running" else _as_utc(created_at)
        if clock is None or clock > limits[status]:
            continue
        result = db.execute(
            update(GradingRun)
            .where(GradingRun.id == run_id, GradingRun.status == status)
            .values(
                status="error",
                error=(
                    "Run interrompu (réconciliation automatique)"
                    if status == "running"
                    else "Run abandonné : aucun worker disponible (réconciliation automatique)"
                ),
                finished_at=now,
            )
        )
        db.commit()
        if not result.rowcount:
            continue  # picked up or finished meanwhile
        logger.info(
            "grading_run_reconciled_stuck",
            extra={"extra_fields": {"run_id": run_id, "status": status}},
        )
        if status != "running":
            continue  # no Job was ever created for a queued run
        try:
            grader_service._delete_job(grader_service.job_name_for_run(run_id))
        except Exception as exc:
            logger.warning(
                "grading_job_delete_failed",
                extra={"extra_fields": {"run_id": run_id, "error": str(exc)}},
            )


def _backfill_missing_expires_at(db: Session, now: datetime) -> None:
    """Active rows without ``expires_at`` (created before TTLs existed) get
    ``created_at + role TTL``."""
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
        ttl = get_ttl_days_for_role(getattr(user.role, "value", str(user.role)))
        if ttl is None:  # admin: no expiry
            continue
        base = dep.created_at if dep.created_at else now
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
        db.commit()


def _delete_orphan_namespaces(db: Session, now: datetime) -> None:
    """Delete ``labondemand-user-<id>`` namespaces whose user no longer exists.

    SSO safety: a user can get a new DB id when their email changes at the
    IdP. A namespace is therefore kept while (a) active deployments still
    reference its user id, or (b) it is younger than ORPHAN_NS_GRACE_DAYS,
    leaving time for an SSO re-login to reconcile the accounts.
    """
    from kubernetes import client as k8s_client

    core_v1 = k8s_client.CoreV1Api()
    ns_list = core_v1.list_namespace(label_selector="managed-by=labondemand")
    for ns in ns_list.items:
        ns_name = ns.metadata.name or ""
        if not ns_name.startswith(_USER_NAMESPACE_PREFIX):
            continue
        try:
            user_id = int(ns_name[len(_USER_NAMESPACE_PREFIX) :])
        except ValueError:
            continue
        if db.query(User).filter(User.id == user_id).first() is not None:
            continue

        active_deployments = (
            db.query(Deployment)
            .filter(
                Deployment.user_id == user_id,
                Deployment.deleted_at.is_(None),
                Deployment.status != "deleted",
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

        ns_creation = ns.metadata.creation_timestamp
        if ns_creation is not None:
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
                extra={"extra_fields": {"namespace": ns_name, "error": str(del_exc)}},
            )


_CLEANUP_STEPS: Tuple[Tuple[str, Callable[[Session, datetime], None]], ...] = (
    ("pause_expired_labs", _pause_expired_labs),
    ("delete_grace_expired_labs", _delete_grace_expired_labs),
    ("reconcile_stuck_grading_runs", _reconcile_stuck_grading_runs),
    ("backfill_missing_expires_at", _backfill_missing_expires_at),
    ("delete_orphan_namespaces", _delete_orphan_namespaces),
)


def run_cleanup_cycle() -> None:
    """Run every cleanup step once (blocking: DB + Kubernetes calls).

    A failing step is logged and rolled back; the next steps still run.
    """
    from ..database import SessionLocal

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for step_name, step in _CLEANUP_STEPS:
            try:
                step(db, now)
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "cleanup_step_failed",
                    extra={"extra_fields": {"step": step_name, "error": str(exc)}},
                )


async def run_cleanup_loop() -> None:
    """Periodic loop; each cycle runs in a worker thread so the blocking DB and
    Kubernetes calls never freeze the API's event loop."""
    interval_seconds = CLEANUP_INTERVAL_MINUTES * 60
    logger.info(
        "cleanup_task_started",
        extra={"extra_fields": {"interval_minutes": CLEANUP_INTERVAL_MINUTES}},
    )
    while True:
        try:
            await asyncio.to_thread(run_cleanup_cycle)
        except Exception as exc:
            logger.exception(
                "cleanup_cycle_error", extra={"extra_fields": {"error": str(exc)}}
            )
        await asyncio.sleep(interval_seconds)
