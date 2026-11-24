"""How a lab is reached: NodePort / Ingress URLs and the noVNC endpoint.

Pure functions over Kubernetes objects (services, pods, ingresses) plus a
cached view of node addresses. Used by ``GET .../details`` (full payload) and
by the lab list (``access_url`` = first URL, what "Open" uses).
"""

import logging
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from kubernetes import client

from ..config import settings
from ..ttl_cache import TTLCache

logger = logging.getLogger("labondemand.k8s")

NODE_ADDRESS_TTL_SECONDS = 60
# After a failed node listing (RBAC, outage), wait this long before retrying,
# so a failing lookup is not retried by every request but heals quickly.
NODE_LIST_RETRY_SECONDS = 5
# Minimum delay between two refreshes forced by a node missing from the cache.
NODE_FORCED_REFRESH_SECONDS = 5
_node_address_cache: TTLCache[Dict[str, str]] = TTLCache(NODE_ADDRESS_TTL_SECONDS)
_node_list_failed: TTLCache[bool] = TTLCache(NODE_LIST_RETRY_SECONDS)
_node_forced_refresh: TTLCache[bool] = TTLCache(NODE_FORCED_REFRESH_SECONDS)


def _preferred_node_address(node: Any) -> Optional[str]:
    """ExternalIP when present, otherwise InternalIP."""
    external_ip = None
    internal_ip = None
    status = getattr(node, "status", None)
    for address in getattr(status, "addresses", None) or []:
        if address.type == "ExternalIP" and address.address:
            external_ip = address.address
        elif address.type == "InternalIP" and address.address:
            internal_ip = address.address
    return external_ip or internal_ip


def _load_node_addresses() -> Optional[Dict[str, str]]:
    """Node name -> preferred IP, or ``None`` when the nodes cannot be listed."""
    try:
        nodes = client.CoreV1Api().list_node()
    except Exception as exc:
        # Best-effort (RBAC may forbid listing nodes, the cluster may be down).
        logger.warning("node_list_failed", extra={"extra_fields": {"error": str(exc)}})
        return None
    addresses: Dict[str, str] = {}
    for node in getattr(nodes, "items", None) or []:
        ip = _preferred_node_address(node)
        if ip:
            addresses[node.metadata.name] = ip
    return addresses


def _refresh_node_addresses(fallback: Dict[str, str]) -> Dict[str, str]:
    fresh = _load_node_addresses()
    if fresh is None:
        # Failures are never cached as "no nodes": keep the last good view and
        # only back off for NODE_LIST_RETRY_SECONDS.
        _node_list_failed.set("nodes", True)
        return fallback
    _node_list_failed.invalidate("nodes")
    _node_address_cache.set("nodes", fresh)
    return fresh


def get_node_addresses(required_nodes: Iterable[Optional[str]] = ()) -> Dict[str, str]:
    """Node name -> preferred IP, cached for ``NODE_ADDRESS_TTL_SECONDS``.

    ``required_nodes`` are the nodes the caller's pods run on: when one of
    them is missing from the cached view (node added since), the view is
    refreshed once (at most every ``NODE_FORCED_REFRESH_SECONDS``) instead of
    silently falling back to another address.
    """
    cached = _node_address_cache.get("nodes")
    if cached is None:
        if _node_list_failed.get("nodes"):
            return {}
        return _refresh_node_addresses({})
    missing = {name for name in required_nodes if name and name not in cached}
    if not missing or _node_forced_refresh.get("nodes") or _node_list_failed.get("nodes"):
        return cached
    _node_forced_refresh.set("nodes", True)
    logger.info(
        "node_addresses_refresh_missing_node",
        extra={"extra_fields": {"missing": sorted(missing)}},
    )
    return _refresh_node_addresses(cached)


def invalidate_node_addresses() -> None:
    """Drop every cached node view (tests, configuration changes)."""
    _node_address_cache.invalidate()
    _node_list_failed.invalidate()
    _node_forced_refresh.invalidate()


def _kubeconfig_api_host() -> Optional[str]:
    host = getattr(client.Configuration.get_default_copy(), "host", None)
    if not host:
        return None
    parsed = urlparse(host) if "://" in host else urlparse(f"https://{host}")
    hostname = parsed.hostname
    if not hostname or hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return None
    return hostname


def resolve_cluster_ip(node_addresses: Dict[str, str]) -> str:
    """Address used for NodePort URLs when the pod's node is unknown."""
    if settings.CLUSTER_EXTERNAL_IP:
        return settings.CLUSTER_EXTERNAL_IP
    if node_addresses:
        return next(iter(node_addresses.values()))
    return _kubeconfig_api_host() or "localhost"


def _node_for_service(service: Any, pods: List[Any]) -> Optional[str]:
    """Node of a pod selected by the service, preferring Running pods."""
    selector = getattr(service.spec, "selector", None)
    if not selector:
        return None
    matching = [
        pod
        for pod in pods
        if pod.spec.node_name
        and all((pod.metadata.labels or {}).get(k) == v for k, v in selector.items())
    ]
    for pod in matching:
        if pod.status and pod.status.phase == "Running":
            return pod.spec.node_name
    return matching[0].spec.node_name if matching else None


def _nodeport_label(service: Any, port: Any) -> str:
    labels = service.metadata.labels or {}
    component = labels.get("component", "")
    app_type = labels.get("app-type", "")
    if app_type == "lamp":
        if component == "web":
            return "Web (Apache/PHP)"
        if component == "phpmyadmin":
            return "phpMyAdmin"
    elif app_type == "eclipse" and port.name == "tomcat":
        return "Application web (Tomcat)"
    return ""


def describe_ingresses(ingresses: Iterable[Any]) -> List[Dict[str, Any]]:
    """One entry per (ingress, host, path) routed to a service."""
    entries: List[Dict[str, Any]] = []
    for ingress in ingresses:
        meta = getattr(ingress, "metadata", None)
        spec = getattr(ingress, "spec", None)
        ingress_class = getattr(spec, "ingress_class_name", None) if spec else None
        tls_hosts = {
            host
            for tls_block in (getattr(spec, "tls", None) or [])
            for host in (getattr(tls_block, "hosts", None) or [])
            if host
        }
        for rule in getattr(spec, "rules", None) or []:
            host = getattr(rule, "host", None)
            http_block = getattr(rule, "http", None)
            if not host or not http_block:
                continue
            for path in getattr(http_block, "paths", None) or []:
                backend = getattr(path, "backend", None)
                service_ref = getattr(backend, "service", None) if backend else None
                service_name = getattr(service_ref, "name", None) if service_ref else None
                if not service_name:
                    continue
                port_ref = getattr(service_ref, "port", None)
                service_port = getattr(port_ref, "number", None) if port_ref else None
                if service_port is None:
                    service_port = getattr(port_ref, "name", None)
                path_value = getattr(path, "path", None) or settings.INGRESS_DEFAULT_PATH
                tls_enabled = host in tls_hosts or bool(settings.INGRESS_TLS_SECRET)
                scheme = "https" if tls_enabled else "http"
                entries.append(
                    {
                        "ingress": getattr(meta, "name", None),
                        "host": host,
                        "path": path_value,
                        "service": service_name,
                        "service_port": service_port,
                        "class": ingress_class,
                        "tls": tls_enabled,
                        "annotations": dict(getattr(meta, "annotations", None) or {}),
                        "url": f"{scheme}://{host}{path_value}",
                    }
                )
    return entries


def build_endpoints(
    services: Iterable[Any],
    pods: Iterable[Any],
    ingresses: Iterable[Any],
    node_addresses: Dict[str, str],
) -> Dict[str, Any]:
    """Services, ingresses, access URLs and noVNC endpoint of one lab.

    Returns the ``services``, ``ingresses``, ``access_urls`` and
    ``novnc_endpoint`` fields of the ``/details`` payload. Access URLs list
    NodePort URLs first (in service order), then Ingress URLs.
    """
    pods = list(pods)
    cluster_ip = resolve_cluster_ip(node_addresses)
    ingress_entries = describe_ingresses(ingresses)
    ingress_by_service: Dict[str, List[Dict[str, Any]]] = {}
    for entry in ingress_entries:
        ingress_by_service.setdefault(entry["service"], []).append(entry)

    access_urls: List[Dict[str, Any]] = []
    service_data: List[Dict[str, Any]] = []
    for svc in services:
        service_info: Dict[str, Any] = {
            "name": svc.metadata.name,
            "type": svc.spec.type,
            "cluster_ip": svc.spec.cluster_ip,
            "ports": [],
            "ingresses": ingress_by_service.get(svc.metadata.name, []),
        }
        node_name = _node_for_service(svc, pods)
        if settings.NODEPORT_USE_POD_NODE_IP and node_name in node_addresses:
            nodeport_ip = node_addresses[node_name]
        else:
            nodeport_ip = cluster_ip

        for port in svc.spec.ports or []:
            port_info: Dict[str, Any] = {
                "name": port.name,
                "port": port.port,
                "target_port": str(port.target_port) if port.target_port else str(port.port),
                "protocol": port.protocol,
            }
            if port.node_port:
                port_info["node_port"] = port.node_port
                if svc.spec.type == "NodePort":
                    access_urls.append(
                        {
                            "url": f"http://{nodeport_ip}:{port.node_port}",
                            "service": svc.metadata.name,
                            "node_port": port.node_port,
                            "node_ip": nodeport_ip,
                            "node_name": node_name,
                            "cluster_ip": cluster_ip,
                            "label": _nodeport_label(svc, port) or None,
                            "protocol": "http",
                            "secure": False,
                        }
                    )
            service_info["ports"].append(port_info)
        service_data.append(service_info)

    access_urls.extend(
        {
            "url": entry["url"],
            "service": entry["service"],
            "ingress": entry["ingress"],
            "host": entry["host"],
            "protocol": "https" if entry["tls"] else "http",
            "secure": entry["tls"],
            "path": entry["path"],
        }
        for entry in ingress_entries
    )

    novnc_services = {
        svc["name"]
        for svc in service_data
        if any(port.get("name") == "novnc" for port in svc["ports"])
    }
    novnc_endpoint = next(
        (url["url"] for url in access_urls if url.get("service") in novnc_services),
        None,
    )
    return {
        "services": service_data,
        "ingresses": ingress_entries,
        "access_urls": access_urls,
        "novnc_endpoint": novnc_endpoint,
    }


def primary_access_url(endpoints: Dict[str, Any]) -> Optional[str]:
    """The URL "Open" uses: the first known access URL."""
    return next((a["url"] for a in endpoints["access_urls"] if a.get("url")), None)
