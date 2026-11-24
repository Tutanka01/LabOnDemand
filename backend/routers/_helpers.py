"""Helpers shared by the routers (Kubernetes error mapping, assignment labs)."""

import logging
from typing import Dict, Iterable, NoReturn, Tuple

from fastapi import HTTPException
from kubernetes import client
from sqlalchemy.orm import Session

# Re-exported: the routers import them from here.
from ..error_handlers import K8S_TRANSPORT_ERRORS, k8s_unavailable  # noqa: F401
from ..models import AssignmentDeployment, Deployment

logger = logging.getLogger("labondemand.k8s")
audit_logger = logging.getLogger("labondemand.audit")


def raise_k8s_http(e: Exception) -> NoReturn:
    """Map a Kubernetes client error onto a clean HTTPException (always raises)."""
    if isinstance(e, HTTPException):
        raise e

    if isinstance(e, client.exceptions.ApiException):
        status = getattr(e, "status", 0) or 0
        reason = getattr(e, "reason", None) or str(e)
        if not 100 <= status <= 599:
            # `kubernetes.stream` wraps every network error (exec stream cut
            # without a CLOSE frame, websocket handshake refused...) into
            # ApiException(status=0): a transport failure, never an app error.
            logger.warning(
                "k8s_transport_error: %s",
                reason,
                extra={"extra_fields": {"reason": reason}},
            )
            raise HTTPException(
                status_code=502,
                detail="Connexion au pod interrompue. Réessayez dans un instant.",
            )
        if status == 503:
            raise k8s_unavailable()
        if status == 401:
            # The platform's own cluster credentials were rejected (expired
            # kubeconfig token...). Never forward it as 401: the browser would
            # read it as an expired user session and bounce to the login page.
            logger.error(
                "k8s_credentials_rejected",
                extra={"extra_fields": {"reason": reason}},
            )
            raise k8s_unavailable()
        raise HTTPException(status_code=status, detail=reason)

    if isinstance(e, K8S_TRANSPORT_ERRORS):
        logger.warning(
            "k8s_unreachable",
            extra={"extra_fields": {"error": f"{type(e).__name__}: {e}"}},
        )
        raise k8s_unavailable()

    logger.error(
        "k8s_unexpected_error",
        exc_info=e,
        extra={"extra_fields": {"error": f"{type(e).__name__}: {e}"}},
    )
    raise HTTPException(status_code=500, detail="Erreur Kubernetes inattendue")


def resolve_assignment_labs(
    db: Session, assignment_ids: Iterable[int], user_ids: Iterable[int]
) -> Dict[Tuple[int, int], Deployment]:
    """Lab of each ``(assignment_id, user_id)`` pair, in two queries.

    ``AssignmentDeployment`` is the source of truth: the most recent link with a
    deployment wins, and the lab counts only while it is active or paused.
    """
    aids = set(assignment_ids)
    uids = set(user_ids)
    if not aids or not uids:
        return {}
    links = (
        db.query(
            AssignmentDeployment.assignment_id,
            AssignmentDeployment.user_id,
            AssignmentDeployment.deployment_id,
        )
        .filter(
            AssignmentDeployment.assignment_id.in_(aids),
            AssignmentDeployment.user_id.in_(uids),
            AssignmentDeployment.deployment_id.isnot(None),
        )
        .order_by(AssignmentDeployment.created_at.desc(), AssignmentDeployment.id.desc())
        .all()
    )
    latest: Dict[Tuple[int, int], int] = {}
    for aid, uid, dep_id in links:
        latest.setdefault((aid, uid), dep_id)
    if not latest:
        return {}
    deployments = {
        dep.id: dep
        for dep in db.query(Deployment).filter(
            Deployment.id.in_(set(latest.values())),
            Deployment.status.in_(["active", "paused"]),
        )
    }
    return {key: deployments[dep_id] for key, dep_id in latest.items() if dep_id in deployments}
