"""Endpoints de monitoring: stats cluster, ping, namespaces, pods listing, usage par app."""
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends
from kubernetes import client

from ..security import get_current_user, is_admin, is_teacher_or_admin
from ..models import User
from ..k8s_utils import parse_cpu_to_millicores, parse_memory_to_mi, validate_k8s_name
from ._helpers import raise_k8s_http

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])
logger = logging.getLogger("labondemand.k8s")


def _parse_cpu_metrics_to_millicores(cpu: str) -> float:
    """Convertit une valeur CPU des metrics (ex: '123456789n', '250m', '1') en millicores."""
    try:
        s = str(cpu).strip()
        if s.endswith('n'):
            return float(s[:-1]) / 1_000_000.0
        if s.endswith('u'):
            return float(s[:-1]) / 1000.0
        if s.endswith('m'):
            return float(s[:-1])
        return float(s) * 1000.0
    except Exception:
        return 0.0


@router.get("/stats/cluster")
async def get_cluster_stats(
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin)
):
    """Statistiques globales du cluster et par noeud (admin seulement)."""
    try:
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        nodes_resp = core_v1.list_node()
        deployments_resp = apps_v1.list_deployment_for_all_namespaces()
        pods_resp = core_v1.list_pod_for_all_namespaces()
        namespaces_resp = core_v1.list_namespace()

        pods_by_node: Dict[str, list] = {}
        for pod in pods_resp.items:
            node_name = getattr(pod.spec, 'node_name', None) or getattr(pod.spec, 'nodeName', None)
            if node_name:
                pods_by_node.setdefault(node_name, []).append(pod)

        metrics_index: Dict[str, Dict[str, Any]] = {}
        try:
            custom_api = client.CustomObjectsApi()
            metrics_nodes = custom_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="nodes"
            )
            for item in metrics_nodes.get('items', []):
                name = (item.get('metadata') or {}).get('name')
                if name:
                    metrics_index[name] = item.get('usage') or {}
        except Exception:
            metrics_index = {}

        deployments = deployments_resp.items
        pods = pods_resp.items
        namespaces = namespaces_resp.items

        deployments_count = len(deployments)
        pods_count = len(pods)
        namespaces_count = len(namespaces)
        nodes_count = len(nodes_resp.items)
        ready_deployments = sum(1 for d in deployments if (getattr(d.status, 'ready_replicas', 0) or 0) > 0)
        lab_apps_count = sum(1 for d in deployments if (getattr(d.metadata, 'labels', {}) or {}).get('managed-by') == 'labondemand')

        nodes_data: list[Dict[str, Any]] = []
        for node in nodes_resp.items:
            name = node.metadata.name
            labels = node.metadata.labels or {}
            alloc_cpu_m = parse_cpu_to_millicores(node.status.allocatable.get('cpu', '0')) if node.status.allocatable else 0.0
            cap_cpu_m = parse_cpu_to_millicores(node.status.capacity.get('cpu', '0')) if node.status.capacity else 0.0
            alloc_mem_mi = parse_memory_to_mi(node.status.allocatable.get('memory', '0Mi')) if node.status.allocatable else 0.0
            cap_mem_mi = parse_memory_to_mi(node.status.capacity.get('memory', '0Mi')) if node.status.capacity else 0.0

            usage_cpu_m = 0.0
            usage_mem_mi = 0.0
            m = metrics_index.get(name)
            if m:
                usage_cpu_m = _parse_cpu_metrics_to_millicores(str(m.get('cpu', '0')))
                usage_mem_mi = parse_memory_to_mi(str(m.get('memory', '0Mi')))
            else:
                for pod in pods_by_node.get(name, []):
                    for c in (getattr(pod.spec, 'containers', None) or []):
                        res = getattr(c, 'resources', None)
                        if res and res.requests:
                            cpu_req = res.requests.get('cpu')
                            mem_req = res.requests.get('memory')
                            if cpu_req:
                                try:
                                    usage_cpu_m += parse_cpu_to_millicores(str(cpu_req))
                                except Exception:
                                    pass
                            if mem_req:
                                try:
                                    usage_mem_mi += parse_memory_to_mi(str(mem_req))
                                except Exception:
                                    pass

            ready = False
            for cond in (node.status.conditions or []):
                if getattr(cond, 'type', '') == 'Ready':
                    ready = (getattr(cond, 'status', '') == 'True')
                    break

            roles: list[str] = []
            for k, v in labels.items():
                if k.startswith('node-role.kubernetes.io/'):
                    role = k.split('/', 1)[1] or 'worker'
                    roles.append(role)
            if not roles:
                roles = ['control-plane'] if labels.get('node-role.kubernetes.io/control-plane') is not None else ['worker']

            pods_on_node = len(pods_by_node.get(name, []))
            version = getattr(getattr(node.status, 'node_info', None), 'kubelet_version', '')

            def pct(part: float, whole: float) -> float:
                return round((part / whole * 100.0), 1) if whole and part >= 0 else 0.0

            nodes_data.append({
                "name": name,
                "ready": ready,
                "roles": roles,
                "kubelet_version": version,
                "pods": pods_on_node,
                "cpu": {
                    "usage_m": round(usage_cpu_m, 1),
                    "allocatable_m": round(alloc_cpu_m, 1),
                    "capacity_m": round(cap_cpu_m, 1),
                    "usage_pct": pct(usage_cpu_m, alloc_cpu_m or cap_cpu_m)
                },
                "memory": {
                    "usage_mi": round(usage_mem_mi, 1),
                    "allocatable_mi": round(alloc_mem_mi, 1),
                    "capacity_mi": round(cap_mem_mi, 1),
                    "usage_pct": pct(usage_mem_mi, alloc_mem_mi or cap_mem_mi)
                }
            })

        return {
            "k8s_available": True,
            "cluster": {
                "nodes": nodes_count,
                "deployments": deployments_count,
                "deployments_ready": ready_deployments,
                "lab_apps": lab_apps_count,
                "pods": pods_count,
                "namespaces": namespaces_count,
            },
            "nodes": nodes_data,
        }
    except Exception as e:
        logger.exception(
            "cluster_stats_error",
            extra={"extra_fields": {"user_id": getattr(current_user, "id", None), "error": str(e)}},
        )
        return {
            "k8s_available": False,
            "cluster": {"nodes": 0, "deployments": 0, "deployments_ready": 0, "lab_apps": 0, "pods": 0, "namespaces": 0},
            "nodes": []
        }


@router.get("/ping")
async def ping_k8s(current_user: User = Depends(get_current_user)):
    """Vérifie la disponibilité de l'API Kubernetes (léger)."""
    try:
        v1 = client.CoreV1Api()
        v1.list_namespace(_preload_content=False, limit=1)
        return {"k8s": True}
    except Exception:
        return {"k8s": False}


@router.get("/pods")
async def get_pods(current_user: User = Depends(get_current_user), _: bool = Depends(is_admin)):
    """Lister tous les pods (admin uniquement)."""
    try:
        v1 = client.CoreV1Api()
        ret = v1.list_pod_for_all_namespaces(watch=False)
        pods = [
            {"name": pod.metadata.name, "namespace": pod.metadata.namespace, "ip": pod.status.pod_ip}
            for pod in ret.items
        ]
        return {"pods": pods, "k8s_available": True}
    except Exception:
        return {"pods": [], "k8s_available": False}


@router.get("/namespaces")
async def get_namespaces(current_user: User = Depends(get_current_user), _: bool = Depends(is_teacher_or_admin)):
    """Lister les namespaces (admin ou enseignant)."""
    try:
        v1 = client.CoreV1Api()
        ret = v1.list_namespace(watch=False)
        namespaces = [ns.metadata.name for ns in ret.items]
        return {"namespaces": namespaces, "k8s_available": True}
    except Exception:
        return {"namespaces": [], "k8s_available": False}


@router.get("/deployments")
async def get_deployments(current_user: User = Depends(get_current_user), _: bool = Depends(is_teacher_or_admin)):
    """Lister tous les déploiements (admin ou enseignant)."""
    try:
        v1 = client.AppsV1Api()
        ret = v1.list_deployment_for_all_namespaces(watch=False)
        deployments = [
            {"name": dep.metadata.name, "namespace": dep.metadata.namespace}
            for dep in ret.items
        ]
        return {"deployments": deployments, "k8s_available": True}
    except Exception:
        return {"deployments": [], "k8s_available": False}


@router.get("/usage/my-apps")
async def get_my_apps_usage(current_user: User = Depends(get_current_user)):
    """Retourne l'usage CPU/Mémoire par application de l'utilisateur courant."""
    try:
        core_v1 = client.CoreV1Api()
        label_selector = f"managed-by=labondemand,user-id={current_user.id}"
        pods_list = core_v1.list_pod_for_all_namespaces(label_selector=label_selector)

        tracked_pods = {}
        for pod in pods_list.items:
            labels = pod.metadata.labels or {}
            namespace = pod.metadata.namespace
            name = pod.metadata.name
            group_key = labels.get("stack-name") or labels.get("app") or name
            app_type = labels.get("app-type", labels.get("component", "custom"))
            tracked_pods[(namespace, name)] = {
                "group": group_key,
                "namespace": namespace,
                "app_type": app_type,
            }

        usage_index: dict[tuple[str, str], dict] = {}

        metrics_ok = False
        try:
            custom_api = client.CustomObjectsApi()
            pods_metrics = custom_api.list_cluster_custom_object(
                group="metrics.k8s.io", version="v1beta1", plural="pods"
            )
            for item in pods_metrics.get("items", []):
                ns = (item.get("metadata") or {}).get("namespace")
                pod_name = (item.get("metadata") or {}).get("name")
                key = (ns, pod_name)
                if key not in tracked_pods:
                    continue
                entry = tracked_pods[key]
                grp = (entry["namespace"], entry["group"])
                agg = usage_index.setdefault(grp, {
                    "name": entry["group"],
                    "namespace": entry["namespace"],
                    "app_type": entry["app_type"],
                    "cpu_m": 0.0,
                    "mem_mi": 0.0,
                    "pods": set(),
                })
                for c in item.get("containers", []):
                    usage = c.get("usage", {})
                    cpu = _parse_cpu_metrics_to_millicores(str(usage.get("cpu", "0")))
                    mem_mi = parse_memory_to_mi(str(usage.get("memory", "0Mi")))
                    agg["cpu_m"] += cpu
                    agg["mem_mi"] += mem_mi
                agg["pods"].add(pod_name)
            metrics_ok = True
        except Exception:
            metrics_ok = False

        if not metrics_ok:
            for pod in pods_list.items:
                key = (pod.metadata.namespace, pod.metadata.name)
                entry = tracked_pods.get(key)
                if not entry:
                    continue
                grp = (entry["namespace"], entry["group"])
                agg = usage_index.setdefault(grp, {
                    "name": entry["group"],
                    "namespace": entry["namespace"],
                    "app_type": entry["app_type"],
                    "cpu_m": 0.0,
                    "mem_mi": 0.0,
                    "pods": set(),
                })
                for c in (getattr(pod.spec, 'containers', None) or []):
                    res = getattr(c, 'resources', None)
                    if res and res.requests:
                        cpu_req = res.requests.get('cpu')
                        mem_req = res.requests.get('memory')
                        if cpu_req:
                            try:
                                agg["cpu_m"] += parse_cpu_to_millicores(str(cpu_req))
                            except Exception:
                                pass
                        if mem_req:
                            try:
                                agg["mem_mi"] += parse_memory_to_mi(str(mem_req))
                            except Exception:
                                pass
                agg["pods"].add(pod.metadata.name)

        items = []
        for (_, _), v in usage_index.items():
            items.append({
                "name": v["name"],
                "namespace": v["namespace"],
                "app_type": v["app_type"],
                "cpu_m": round(v["cpu_m"], 1),
                "mem_mi": round(v["mem_mi"], 1),
                "pods": len(v["pods"]),
                "source": "live" if metrics_ok else "requests"
            })
        items.sort(key=lambda x: x["cpu_m"], reverse=True)
        return {"items": items, "k8s_available": True, "metrics": metrics_ok}

    except Exception as e:
        logger.exception(
            "my_apps_usage_error",
            extra={"extra_fields": {"user_id": getattr(current_user, "id", None), "error": str(e)}},
        )
        return {"items": [], "k8s_available": False, "metrics": False}


@router.get("/pods/{namespace}")
async def get_pods_by_namespace(
    namespace: str,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_teacher_or_admin)
):
    """Lister les pods d'un namespace spécifique."""
    namespace = validate_k8s_name(namespace)
    try:
        v1 = client.CoreV1Api()
        ret = v1.list_namespaced_pod(namespace, watch=False)
        pods = [{"name": pod.metadata.name, "ip": pod.status.pod_ip} for pod in ret.items]
        return {"namespace": namespace, "pods": pods, "k8s_available": True}
    except Exception:
        return {"namespace": namespace, "pods": [], "k8s_available": False}
