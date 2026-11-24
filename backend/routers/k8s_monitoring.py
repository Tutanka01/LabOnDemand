"""Monitoring endpoints: cluster stats, ping, namespaces, pod listing, per-app usage.

Every handler is a plain ``def``: FastAPI runs it in its threadpool, so the
blocking Kubernetes client never stalls the event loop. When the cluster
cannot be reached, list endpoints answer 503 (see ``raise_k8s_http``) instead
of an empty 200; only ``/ping`` reports reachability as a boolean.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from kubernetes import client

from ..k8s_utils import parse_cpu_to_millicores, parse_memory_to_mi, validate_k8s_name
from ..models import User
from ..security import get_current_user, is_admin, is_teacher_or_admin
from ..ttl_cache import TTLCache
from ._helpers import raise_k8s_http

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])
logger = logging.getLogger("labondemand.k8s")

# Polled every 30 s by every open tab (ping) and by the admin stats page
# (cluster stats, three cluster-wide lists per call). Neither is user-specific.
PING_CACHE: TTLCache[bool] = TTLCache(ttl_seconds=10)
CLUSTER_STATS_CACHE: TTLCache[Dict[str, Any]] = TTLCache(ttl_seconds=15)
_PING_KEY = "ping"
_CLUSTER_STATS_KEY = "cluster"


def _parse_cpu_metrics_to_millicores(cpu: str) -> float:
    """Convert a metrics-server CPU value ('123456789n', '250m', '1') to millicores."""
    try:
        s = str(cpu).strip()
        if s.endswith("n"):
            return float(s[:-1]) / 1_000_000.0
        if s.endswith("u"):
            return float(s[:-1]) / 1000.0
        if s.endswith("m"):
            return float(s[:-1])
        return float(s) * 1000.0
    except ValueError:
        return 0.0


def _safe_cpu_m(value: Any) -> float:
    try:
        return parse_cpu_to_millicores(str(value))
    except ValueError:
        return 0.0


def _safe_mem_mi(value: Any) -> float:
    try:
        return parse_memory_to_mi(str(value))
    except ValueError:
        return 0.0


def _pct(part: float, whole: float) -> float:
    return round((part / whole * 100.0), 1) if whole and part >= 0 else 0.0


def _requested_resources(pod: Any) -> tuple[float, float]:
    """Sum of CPU (m) / memory (Mi) requests over the pod's containers."""
    cpu_m = 0.0
    mem_mi = 0.0
    for container in getattr(pod.spec, "containers", None) or []:
        res = getattr(container, "resources", None)
        if res and res.requests:
            cpu_req = res.requests.get("cpu")
            mem_req = res.requests.get("memory")
            if cpu_req:
                cpu_m += _safe_cpu_m(cpu_req)
            if mem_req:
                mem_mi += _safe_mem_mi(mem_req)
    return cpu_m, mem_mi


def k8s_reachable() -> bool:
    """Whether the Kubernetes API answers (cached ~10 s, shared by all callers)."""

    def _probe() -> bool:
        try:
            client.CoreV1Api().list_namespace(limit=1)
            return True
        except Exception as exc:  # any failure means "not reachable"
            logger.info(
                "k8s_ping_failed",
                extra={"extra_fields": {"error": f"{type(exc).__name__}: {exc}"}},
            )
            return False

    return PING_CACHE.get_or_set(_PING_KEY, _probe)


def _node_metrics_index() -> Dict[str, Dict[str, Any]]:
    """Live node usage from metrics-server; empty when it is not installed."""
    try:
        metrics_nodes = client.CustomObjectsApi().list_cluster_custom_object(
            group="metrics.k8s.io", version="v1beta1", plural="nodes"
        )
    except Exception as exc:  # metrics-server is optional: fall back to requests
        logger.debug("node_metrics_unavailable", extra={"extra_fields": {"error": str(exc)}})
        return {}
    index: Dict[str, Dict[str, Any]] = {}
    for item in metrics_nodes.get("items", []):
        name = (item.get("metadata") or {}).get("name")
        if name:
            index[name] = item.get("usage") or {}
    return index


def _compute_cluster_stats() -> Dict[str, Any]:
    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()

    nodes = core_v1.list_node().items
    deployments = apps_v1.list_deployment_for_all_namespaces().items
    pods = core_v1.list_pod_for_all_namespaces().items
    namespaces = core_v1.list_namespace().items

    pods_by_node: Dict[str, list] = {}
    for pod in pods:
        node_name = getattr(pod.spec, "node_name", None)
        if node_name:
            pods_by_node.setdefault(node_name, []).append(pod)

    metrics_index = _node_metrics_index()

    ready_deployments = sum(1 for d in deployments if (getattr(d.status, "ready_replicas", 0) or 0) > 0)
    lab_apps_count = sum(
        1 for d in deployments if (getattr(d.metadata, "labels", {}) or {}).get("managed-by") == "labondemand"
    )

    nodes_data: list[Dict[str, Any]] = []
    for node in nodes:
        name = node.metadata.name
        labels = node.metadata.labels or {}
        allocatable = node.status.allocatable or {}
        capacity = node.status.capacity or {}
        alloc_cpu_m = _safe_cpu_m(allocatable.get("cpu", "0"))
        cap_cpu_m = _safe_cpu_m(capacity.get("cpu", "0"))
        alloc_mem_mi = _safe_mem_mi(allocatable.get("memory", "0Mi"))
        cap_mem_mi = _safe_mem_mi(capacity.get("memory", "0Mi"))

        usage = metrics_index.get(name)
        if usage:
            usage_cpu_m = _parse_cpu_metrics_to_millicores(str(usage.get("cpu", "0")))
            usage_mem_mi = _safe_mem_mi(usage.get("memory", "0Mi"))
        else:
            usage_cpu_m = 0.0
            usage_mem_mi = 0.0
            for pod in pods_by_node.get(name, []):
                cpu_m, mem_mi = _requested_resources(pod)
                usage_cpu_m += cpu_m
                usage_mem_mi += mem_mi

        ready = False
        for cond in node.status.conditions or []:
            if getattr(cond, "type", "") == "Ready":
                ready = getattr(cond, "status", "") == "True"
                break

        roles = [
            key.split("/", 1)[1] or "worker"
            for key in labels
            if key.startswith("node-role.kubernetes.io/")
        ] or ["worker"]

        nodes_data.append({
            "name": name,
            "ready": ready,
            "roles": roles,
            "kubelet_version": getattr(getattr(node.status, "node_info", None), "kubelet_version", ""),
            "pods": len(pods_by_node.get(name, [])),
            "cpu": {
                "usage_m": round(usage_cpu_m, 1),
                "allocatable_m": round(alloc_cpu_m, 1),
                "capacity_m": round(cap_cpu_m, 1),
                "usage_pct": _pct(usage_cpu_m, alloc_cpu_m or cap_cpu_m),
            },
            "memory": {
                "usage_mi": round(usage_mem_mi, 1),
                "allocatable_mi": round(alloc_mem_mi, 1),
                "capacity_mi": round(cap_mem_mi, 1),
                "usage_pct": _pct(usage_mem_mi, alloc_mem_mi or cap_mem_mi),
            },
        })

    return {
        "k8s_available": True,
        "cluster": {
            "nodes": len(nodes),
            "deployments": len(deployments),
            "deployments_ready": ready_deployments,
            "lab_apps": lab_apps_count,
            "pods": len(pods),
            "namespaces": len(namespaces),
        },
        "total_deployments": len(deployments),
        "ready_deployments": ready_deployments,
        "total_lab_apps": lab_apps_count,
        "total_pods": len(pods),
        "total_namespaces": len(namespaces),
        "nodes": nodes_data,
    }


def _pod_row(pod: Any) -> Dict[str, Any]:
    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "ip": pod.status.pod_ip,
        "status": pod.status.phase,
        "phase": pod.status.phase,
        "node_name": pod.spec.node_name,
    }


@router.get("/stats/cluster")
def get_cluster_stats(
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
) -> Dict[str, Any]:
    """Cluster-wide and per-node statistics (admin only, cached ~15 s)."""
    try:
        return CLUSTER_STATS_CACHE.get_or_set(_CLUSTER_STATS_KEY, _compute_cluster_stats)
    except Exception as e:
        raise_k8s_http(e)


@router.get("/ping")
def ping_k8s(current_user: User = Depends(get_current_user)) -> Dict[str, bool]:
    """Lightweight Kubernetes availability check; always 200 with a boolean."""
    return {"k8s": k8s_reachable()}


@router.get("/pods")
def get_pods(current_user: User = Depends(get_current_user), _: bool = Depends(is_admin)) -> Dict[str, Any]:
    """List every pod (admin only)."""
    try:
        ret = client.CoreV1Api().list_pod_for_all_namespaces(watch=False)
    except Exception as e:
        raise_k8s_http(e)
    return {"pods": [_pod_row(pod) for pod in ret.items], "k8s_available": True}


@router.get("/namespaces")
def get_namespaces(
    current_user: User = Depends(get_current_user), _: bool = Depends(is_teacher_or_admin)
) -> Dict[str, Any]:
    """List namespaces (admin or teacher)."""
    try:
        ret = client.CoreV1Api().list_namespace(watch=False)
    except Exception as e:
        raise_k8s_http(e)
    return {"namespaces": [ns.metadata.name for ns in ret.items], "k8s_available": True}


@router.get("/deployments")
def get_deployments(
    current_user: User = Depends(get_current_user), _: bool = Depends(is_teacher_or_admin)
) -> Dict[str, Any]:
    """List every deployment (admin or teacher)."""
    try:
        ret = client.AppsV1Api().list_deployment_for_all_namespaces(watch=False)
    except Exception as e:
        raise_k8s_http(e)
    deployments = [{"name": dep.metadata.name, "namespace": dep.metadata.namespace} for dep in ret.items]
    return {"deployments": deployments, "k8s_available": True}


def _pod_metrics_by_namespace(namespaces: set[str]) -> Optional[Dict[tuple[str, str], list]]:
    """Live container usage per ``(namespace, pod)``; ``None`` if metrics-server is unavailable."""
    custom_api = client.CustomObjectsApi()
    index: Dict[tuple[str, str], list] = {}
    for ns in sorted(namespaces):
        try:
            listing = custom_api.list_namespaced_custom_object(
                group="metrics.k8s.io", version="v1beta1", namespace=ns, plural="pods"
            )
        except Exception as exc:  # metrics-server is optional: fall back to requests
            logger.debug("pod_metrics_unavailable", extra={"extra_fields": {"namespace": ns, "error": str(exc)}})
            return None
        for item in listing.get("items", []):
            meta = item.get("metadata") or {}
            index[(meta.get("namespace") or ns, meta.get("name"))] = item.get("containers", [])
    return index


@router.get("/usage/my-apps")
def get_my_apps_usage(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """CPU/memory usage per application of the current user."""
    label_selector = f"managed-by=labondemand,user-id={current_user.id}"
    try:
        pods = client.CoreV1Api().list_pod_for_all_namespaces(label_selector=label_selector).items
    except Exception as e:
        raise_k8s_http(e)

    usage_index: Dict[tuple[str, str], Dict[str, Any]] = {}

    def _group_for(pod: Any) -> Dict[str, Any]:
        labels = pod.metadata.labels or {}
        namespace = pod.metadata.namespace
        group = labels.get("stack-name") or labels.get("app") or pod.metadata.name
        return usage_index.setdefault((namespace, group), {
            "name": group,
            "namespace": namespace,
            "app_type": labels.get("app-type", labels.get("component", "custom")),
            "cpu_m": 0.0,
            "mem_mi": 0.0,
            "pods": set(),
        })

    # Metrics are only read for the user's own namespaces, not the whole cluster.
    metrics = _pod_metrics_by_namespace({pod.metadata.namespace for pod in pods}) if pods else None
    metrics_ok = metrics is not None

    for pod in pods:
        if metrics_ok:
            containers = metrics.get((pod.metadata.namespace, pod.metadata.name))
            if containers is None:
                continue
            agg = _group_for(pod)
            for container in containers:
                usage = container.get("usage", {})
                agg["cpu_m"] += _parse_cpu_metrics_to_millicores(str(usage.get("cpu", "0")))
                agg["mem_mi"] += _safe_mem_mi(usage.get("memory", "0Mi"))
        else:
            agg = _group_for(pod)
            cpu_m, mem_mi = _requested_resources(pod)
            agg["cpu_m"] += cpu_m
            agg["mem_mi"] += mem_mi
        agg["pods"].add(pod.metadata.name)

    items = [
        {
            "name": v["name"],
            "namespace": v["namespace"],
            "app_type": v["app_type"],
            "cpu_m": round(v["cpu_m"], 1),
            "mem_mi": round(v["mem_mi"], 1),
            "pods": len(v["pods"]),
            "source": "live" if metrics_ok else "requests",
        }
        for v in usage_index.values()
    ]
    items.sort(key=lambda x: x["cpu_m"], reverse=True)
    return {"items": items, "k8s_available": True, "metrics": metrics_ok}


@router.get("/pods/{namespace}")
def get_pods_by_namespace(
    namespace: str,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_teacher_or_admin),
) -> Dict[str, Any]:
    """List the pods of one namespace."""
    namespace = validate_k8s_name(namespace)
    try:
        ret = client.CoreV1Api().list_namespaced_pod(namespace, watch=False)
    except Exception as e:
        raise_k8s_http(e)
    return {"namespace": namespace, "pods": [_pod_row(pod) for pod in ret.items], "k8s_available": True}
