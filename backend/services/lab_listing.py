"""The current user's lab list: Kubernetes view, access URL and DB records.

``list_user_labs`` makes a bounded number of Kubernetes calls whatever the
number of labs (deployments, services, pods when NodePort URLs follow the
pod's node, ingresses when Ingress is enabled, plus the cached node list).
``reconcile_lab_records`` creates the DB rows missing for labs that exist in
Kubernetes (e.g. when the DB was unavailable at creation time).

The ``deployments`` table has no uniqueness constraint (MariaDB cannot express
"unique among non-deleted rows" without a generated column, and existing data
may already hold duplicates), so row creation is serialised in-process by the
user's lab lock instead (see ``backend.lab_locks``).
"""

import datetime
import logging
from typing import Any, Dict, List, Optional, Tuple

from kubernetes import client
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..config import settings
from ..error_handlers import K8S_TRANSPORT_ERRORS
from ..lab_locks import LabLockTimeout, user_lab_lock
from ..models import Deployment as DeploymentRecord, User
from .access_urls import build_endpoints, get_node_addresses, primary_access_url

logger = logging.getLogger("labondemand.k8s")

# (namespace, "stack" | "app", value): how /details selects a lab's objects.
LabKey = Tuple[str, str, str]


def _lab_selector_keys(namespace: str, labels: Dict[str, str]) -> List[LabKey]:
    keys: List[LabKey] = []
    if labels.get("stack-name"):
        keys.append((namespace, "stack", labels["stack-name"]))
    if labels.get("app"):
        keys.append((namespace, "app", labels["app"]))
    return keys


def _index_by_lab(items: List[Any]) -> Dict[LabKey, List[Any]]:
    """Group objects the way /details label selectors would select them."""
    index: Dict[LabKey, List[Any]] = {}
    for item in items:
        meta = item.metadata
        for key in _lab_selector_keys(meta.namespace, meta.labels or {}):
            index.setdefault(key, []).append(item)
    return index


def _component_entry(dep: Any, lifecycle: Dict[str, Any]) -> Dict[str, Any]:
    containers = dep.spec.template.spec.containers
    return {
        "name": dep.metadata.name,
        "namespace": dep.metadata.namespace,
        "type": (dep.metadata.labels or {}).get("app-type", "custom"),
        "labels": dep.metadata.labels or {},
        "replicas": dep.spec.replicas,
        "ready_replicas": dep.status.ready_replicas or 0,
        "image": containers[0].image if containers else "Unknown",
        "lifecycle": lifecycle,
        "is_paused": lifecycle.get("paused", False),
    }


def _creation_timestamp(dep: Any) -> Optional[datetime.datetime]:
    value = getattr(dep.metadata, "creation_timestamp", None)
    return value if isinstance(value, datetime.datetime) else None


def is_terminating(dep: Any) -> bool:
    """True when Kubernetes is deleting this object (``deletion_timestamp`` set)."""
    value = getattr(getattr(dep, "metadata", None), "deletion_timestamp", None)
    return isinstance(value, datetime.datetime)


def _stack_name(dep: Any) -> Optional[str]:
    labels = dep.metadata.labels or {}
    stack_name = labels.get("stack-name")
    if not stack_name and labels.get("app-type", "custom") == "wordpress":
        stack_name = (dep.metadata.name or "").removesuffix("-mariadb")
    return stack_name or None


def lab_name(dep: Any) -> str:
    """Name of the lab a deployment belongs to (the DB row's ``name``)."""
    return _stack_name(dep) or dep.metadata.name or ""


def group_user_deployments(deployments: List[Any], service: Any) -> List[Dict[str, Any]]:
    """Aggregate stack components into one lab; single deployments stay as is.

    ``service`` is the DeploymentService (lifecycle helpers). Each lab carries
    a private ``_key`` (to find its services) and ``_k8s_created_at``.
    """
    stacks: Dict[str, Dict[str, Any]] = {}
    singles: List[Dict[str, Any]] = []
    for dep in deployments:
        labels = dep.metadata.labels or {}
        stack_name = _stack_name(dep)
        app_type = labels.get("app-type", "custom")
        dep_name = dep.metadata.name or ""

        lifecycle = service.describe_component_lifecycle(dep)
        entry = _component_entry(dep, lifecycle)
        created_at = _creation_timestamp(dep)

        if not stack_name:
            entry["_key"] = (dep.metadata.namespace, "app", dep_name)
            entry["_k8s_created_at"] = created_at
            singles.append(entry)
            continue

        agg = stacks.get(stack_name)
        if agg is None:
            stacks[stack_name] = {
                "name": stack_name,
                "namespace": dep.metadata.namespace,
                "type": app_type,
                "labels": labels,
                "replicas": dep.spec.replicas or 0,
                "ready_replicas": dep.status.ready_replicas or 0,
                "lifecycle": service.summarize_lifecycle([lifecycle]),
                "components": [entry],
                "is_paused": lifecycle.get("paused", False),
                "_key": (
                    (dep.metadata.namespace, "stack", stack_name)
                    if labels.get("stack-name")
                    else (dep.metadata.namespace, "app", dep_name)
                ),
                "_k8s_created_at": created_at,
            }
            continue
        agg["components"].append(entry)
        agg["replicas"] = (agg["replicas"] or 0) + (dep.spec.replicas or 0)
        agg["ready_replicas"] = (agg["ready_replicas"] or 0) + (dep.status.ready_replicas or 0)
        agg["lifecycle"] = service.summarize_lifecycle(
            [component["lifecycle"] for component in agg["components"]]
        )
        agg["is_paused"] = agg["lifecycle"].get("paused", False)
    return list(stacks.values()) + singles


def _attach_access_urls(labs: List[Dict[str, Any]], label_selector: str) -> None:
    """Set ``access_url`` on every lab (best-effort: ``None`` on failure)."""
    for lab in labs:
        lab["access_url"] = None
    if not labs:
        return
    try:
        core_v1 = client.CoreV1Api()
        services = list(
            core_v1.list_service_for_all_namespaces(label_selector=label_selector).items or []
        )
        pods: List[Any] = []
        if settings.NODEPORT_USE_POD_NODE_IP:
            pods = list(
                core_v1.list_pod_for_all_namespaces(label_selector=label_selector).items or []
            )
        ingresses: List[Any] = []
        if settings.INGRESS_ENABLED:
            ingresses = list(
                client.NetworkingV1Api()
                .list_ingress_for_all_namespaces(label_selector=label_selector)
                .items
                or []
            )
        node_addresses = get_node_addresses(pod.spec.node_name for pod in pods)
        services_by_lab = _index_by_lab(services)
        pods_by_lab = _index_by_lab(pods)
        ingresses_by_lab = _index_by_lab(ingresses)
    except Exception as exc:
        logger.warning(
            "lab_access_urls_unavailable",
            extra={"extra_fields": {"error": f"{type(exc).__name__}: {exc}"}},
        )
        return

    for lab in labs:
        key = lab["_key"]
        try:
            endpoints = build_endpoints(
                services_by_lab.get(key, []),
                pods_by_lab.get(key, []),
                ingresses_by_lab.get(key, []),
                node_addresses,
            )
            lab["access_url"] = primary_access_url(endpoints)
        except Exception as exc:
            logger.warning(
                "lab_access_url_failed",
                extra={"extra_fields": {"lab": lab.get("name"), "error": str(exc)}},
            )


def list_user_labs(user: User, service: Any) -> List[Dict[str, Any]]:
    """Kubernetes view of the user's labs with their ``access_url``.

    Kubernetes errors on the deployment list propagate to the caller; the
    access URL lookup is best-effort.
    """
    label_selector = _user_selector(user)
    labs = group_user_deployments(_live_deployments(label_selector), service)
    _attach_access_urls(labs, label_selector)
    return labs


def _user_selector(user: User) -> str:
    return f"managed-by=labondemand,user-id={user.id}"


def _live_deployments(label_selector: str) -> List[Any]:
    """The user's deployments, without those Kubernetes is deleting."""
    deployments = client.AppsV1Api().list_deployment_for_all_namespaces(
        label_selector=label_selector
    )
    return [dep for dep in (deployments.items or []) if not is_terminating(dep)]


def _expires_at_for(user: User, k8s_created_at: Optional[datetime.datetime]):
    from ..tasks.cleanup import compute_expires_at, get_ttl_days_for_role

    role_val = getattr(user.role, "value", str(user.role))
    if k8s_created_at is None:
        return compute_expires_at(role_val)
    # Based on the Kubernetes creation date so re-creating a missing row
    # never extends the lab's TTL.
    if k8s_created_at.tzinfo is None:
        k8s_created_at = k8s_created_at.replace(tzinfo=datetime.timezone.utc)
    ttl = get_ttl_days_for_role(role_val)
    return k8s_created_at + datetime.timedelta(days=ttl) if ttl is not None else None


def _live_rows_by_name(db: Session, user_id: int) -> Dict[str, DeploymentRecord]:
    records = (
        db.query(DeploymentRecord)
        .filter(
            DeploymentRecord.user_id == user_id,
            DeploymentRecord.deleted_at.is_(None),
        )
        .order_by(DeploymentRecord.id)
        .all()
    )
    by_name: Dict[str, DeploymentRecord] = {}
    for record in records:
        by_name.setdefault(record.name, record)  # oldest row wins on duplicates
    return by_name


def reconcile_lab_records(
    db: Session, user: User, labs: List[Dict[str, Any]]
) -> Dict[str, DeploymentRecord]:
    """Return the user's active DB rows by name, creating the missing ones.

    ``labs`` is a Kubernetes snapshot taken before this call, so it may be
    stale: a creation may be between its Kubernetes calls and its DB row, or
    a deletion may have removed the lab and soft-deleted its row since. Rows
    are therefore only inserted under the user's lab lock (held by creation
    and deletion for their whole duration), after re-reading the DB in a
    fresh transaction and re-listing the user's live deployments.
    """
    user_id = int(user.id)
    by_name = _live_rows_by_name(db, user_id)
    missing = [lab for lab in labs if lab["name"] not in by_name]
    if not missing:
        return by_name

    # End the read transaction: frees the pooled connection while waiting for
    # the lock, and the re-read below gets a snapshot taken after it.
    db.rollback()
    try:
        with user_lab_lock(user_id):
            by_name = _live_rows_by_name(db, user_id)
            missing = [lab for lab in missing if lab["name"] not in by_name]
            if not missing:
                return by_name
            live_names = {lab_name(dep) for dep in _live_deployments(_user_selector(user))}
            for lab in missing:
                if lab["name"] not in live_names:
                    continue  # deleted since the snapshot: never resurrect its row
                record = _insert_missing_row(db, user, lab)
                if record is not None:
                    by_name[lab["name"]] = record
    except LabLockTimeout:
        logger.warning(
            "deployment_record_reconcile_skipped_busy",
            extra={"extra_fields": {"user_id": user_id}},
        )
        return _live_rows_by_name(db, user_id)
    except (client.exceptions.ApiException, *K8S_TRANSPORT_ERRORS) as exc:
        # Cannot confirm the labs still exist: insert nothing this time.
        logger.warning(
            "deployment_record_reconcile_skipped_k8s",
            extra={"extra_fields": {"user_id": user_id, "error": f"{type(exc).__name__}: {exc}"}},
        )
        db.rollback()
        return _live_rows_by_name(db, user_id)
    return by_name


def _insert_missing_row(
    db: Session, user: User, lab: Dict[str, Any]
) -> Optional[DeploymentRecord]:
    """Insert (and commit) the row of a lab that exists in Kubernetes.

    Called under the user's lab lock. Returns ``None`` when the DB write
    fails: the lab is still listed (without DB dates) rather than failing the
    whole list on one bad row.
    """
    record = DeploymentRecord(
        user_id=user.id,
        name=lab["name"],
        deployment_type=lab.get("type", "custom"),
        namespace=lab.get("namespace", ""),
        stack_name=(lab.get("labels") or {}).get("stack-name"),
        status="active",
        expires_at=_expires_at_for(user, lab.get("_k8s_created_at")),
    )
    try:
        db.add(record)
        db.commit()
        db.refresh(record)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.warning(
            "deployment_record_reconcile_failed",
            extra={"extra_fields": {"name": lab["name"], "user_id": user.id, "error": str(exc)}},
        )
        return None
    logger.info(
        "deployment_record_reconciled",
        extra={"extra_fields": {"name": lab["name"], "user_id": user.id}},
    )
    return record


def to_public_lab(lab: Dict[str, Any], record: Optional[DeploymentRecord]) -> Dict[str, Any]:
    """Drop private keys and add the DB dates (``expires_at``, ``created_at``)."""
    public = {key: value for key, value in lab.items() if not key.startswith("_")}
    public["expires_at"] = record.expires_at.isoformat() if record and record.expires_at else None
    public["created_at"] = record.created_at.isoformat() if record and record.created_at else None
    return public
