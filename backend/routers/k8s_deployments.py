"""Endpoints CRUD déploiements, pause/resume, pods, détails, credentials."""

import base64
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from kubernetes import client
from sqlalchemy.orm import Session

from ..security import get_current_user, is_admin, is_teacher_or_admin, limiter
from ..models import User, UserRole, Deployment as DeploymentModel
from ..database import get_db
from ..k8s_utils import validate_k8s_name
from ..deployment_service import deployment_service
from ..config import settings
from ._helpers import raise_k8s_http, audit_logger
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/api/v1/k8s", tags=["kubernetes"])
logger = logging.getLogger("labondemand.k8s")


# ============= VUE GLOBALE ADMIN — TOUS LES LABS (JOIN deployments × users) =============


@router.get("/deployments/all", dependencies=[Depends(is_admin)])
def list_all_deployments(
    status: Optional[str] = Query(
        None, description="Filtrer par statut (active/paused/expired/deleted)"
    ),
    db: Session = Depends(get_db),
):
    """Liste tous les labs enregistrés en base avec les infos propriétaire (admin seulement).

    Effectue un JOIN entre ``deployments`` et ``users`` pour renvoyer un tableau
    complet permettant à l'admin de surveiller et administrer le parc des labs.
    """
    query = db.query(DeploymentModel, User).join(
        User, DeploymentModel.user_id == User.id
    )
    if status:
        query = query.filter(DeploymentModel.status == status)

    rows = query.order_by(DeploymentModel.created_at.desc()).all()

    result = []
    for dep, user in rows:
        result.append(
            {
                "id": dep.id,
                "name": dep.name,
                "deployment_type": dep.deployment_type,
                "namespace": dep.namespace,
                "stack_name": dep.stack_name,
                "status": dep.status,
                "created_at": dep.created_at.isoformat() if dep.created_at else None,
                "deleted_at": dep.deleted_at.isoformat() if dep.deleted_at else None,
                "expires_at": dep.expires_at.isoformat() if dep.expires_at else None,
                "last_seen_at": dep.last_seen_at.isoformat()
                if dep.last_seen_at
                else None,
                "cpu_requested": dep.cpu_requested,
                "mem_requested": dep.mem_requested,
                "owner": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role.value
                    if hasattr(user.role, "value")
                    else str(user.role),
                },
            }
        )

    return {"deployments": result, "total": len(result)}


def _soft_delete_deployment(db: Session, user_id: int, name: str) -> None:
    """Marque un enregistrement Deployment comme supprimé (soft delete).

    Appelé après chaque suppression K8s réussie pour maintenir la cohérence
    historique en base. Silencieux en cas d'erreur pour ne pas bloquer la réponse.
    """
    from datetime import datetime, timezone

    try:
        rec = (
            db.query(DeploymentModel)
            .filter(
                DeploymentModel.user_id == user_id,
                DeploymentModel.name == name,
                DeploymentModel.deleted_at.is_(None),
            )
            .first()
        )
        if rec:
            rec.status = "deleted"
            rec.deleted_at = datetime.now(timezone.utc)
            db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(
            "deployment_soft_delete_failed",
            extra={
                "extra_fields": {"name": name, "user_id": user_id, "error": str(exc)}
            },
        )


# ============= LISTING DES DÉPLOIEMENTS LABONDEMAND =============


@router.get("/deployments/labondemand")
async def get_labondemand_deployments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Récupérer uniquement les déploiements LabOnDemand."""
    try:
        v1 = client.AppsV1Api()
        label_selector = f"managed-by=labondemand,user-id={current_user.id}"
        ret = v1.list_deployment_for_all_namespaces(label_selector=label_selector)

        stacks: Dict[str, Dict[str, Any]] = {}
        singles: list = []

        for dep in ret.items:
            labels = dep.metadata.labels or {}
            stack_name = labels.get("stack-name")
            app_type = labels.get("app-type", "custom")
            dep_name = dep.metadata.name or ""

            if not stack_name and app_type == "wordpress":
                if dep_name.endswith("-mariadb"):
                    stack_name = dep_name[: -len("-mariadb")]
                else:
                    stack_name = dep_name

            lifecycle = deployment_service.describe_component_lifecycle(dep)
            entry = {
                "name": dep.metadata.name,
                "namespace": dep.metadata.namespace,
                "type": app_type,
                "labels": labels,
                "replicas": dep.spec.replicas,
                "ready_replicas": dep.status.ready_replicas or 0,
                "image": dep.spec.template.spec.containers[0].image
                if dep.spec.template.spec.containers
                else "Unknown",
                "lifecycle": lifecycle,
                "is_paused": lifecycle.get("paused", False),
            }

            if stack_name:
                agg = stacks.get(stack_name)
                if not agg:
                    stacks[stack_name] = {
                        "name": stack_name,
                        "namespace": dep.metadata.namespace,
                        "type": app_type,
                        "labels": labels,
                        "replicas": dep.spec.replicas or 0,
                        "ready_replicas": dep.status.ready_replicas or 0,
                        "lifecycle": deployment_service.summarize_lifecycle(
                            [lifecycle]
                        ),
                        "components": [entry],
                        "is_paused": lifecycle.get("paused", False),
                    }
                else:
                    agg["components"].append(entry)
                    agg["replicas"] = (agg.get("replicas", 0) or 0) + (
                        dep.spec.replicas or 0
                    )
                    agg["ready_replicas"] = (agg.get("ready_replicas", 0) or 0) + (
                        dep.status.ready_replicas or 0
                    )
                    agg["lifecycle"] = deployment_service.summarize_lifecycle(
                        [component.get("lifecycle") for component in agg["components"]]
                    )
                    agg["is_paused"] = agg["lifecycle"].get("paused", False)
            else:
                singles.append(entry)

        deployments = list(stacks.values()) + singles

        # Enrichir avec les métadonnées DB (expires_at, created_at)
        # et créer les enregistrements manquants avec expires_at calculé selon le rôle
        from ..tasks.cleanup import compute_expires_at

        db_records = (
            db.query(DeploymentModel)
            .filter(
                DeploymentModel.user_id == current_user.id,
                DeploymentModel.deleted_at.is_(None),
            )
            .all()
        )
        db_index = {r.name: r for r in db_records}
        for dep in deployments:
            dep_name = dep["name"]
            rec = db_index.get(dep_name)
            if rec is None:
                # Créer l'enregistrement manquant avec expires_at
                role_val = getattr(current_user.role, "value", str(current_user.role))
                new_rec = DeploymentModel(
                    user_id=current_user.id,
                    name=dep_name,
                    deployment_type=dep.get("type", "custom"),
                    namespace=dep.get("namespace", ""),
                    stack_name=dep.get("labels", {}).get("stack-name"),
                    status="active",
                    expires_at=compute_expires_at(role_val),
                )
                try:
                    db.add(new_rec)
                    db.commit()
                    db.refresh(new_rec)
                    rec = new_rec
                except IntegrityError:
                    # Race condition : un autre processus a créé l'enregistrement entre-temps
                    db.rollback()
                    rec = (
                        db.query(DeploymentModel)
                        .filter(
                            DeploymentModel.user_id == current_user.id,
                            DeploymentModel.name == dep_name,
                            DeploymentModel.deleted_at.is_(None),
                        )
                        .first()
                    )
            dep["expires_at"] = (
                rec.expires_at.isoformat() if rec and rec.expires_at else None
            )
            dep["created_at"] = (
                rec.created_at.isoformat() if rec and rec.created_at else None
            )

        return {"deployments": deployments, "k8s_available": True}
    except Exception:
        return {"deployments": [], "k8s_available": False}


# ============= DÉTAILS D'UN DÉPLOIEMENT =============


@router.get("/deployments/{namespace}/{name}/details")
async def get_deployment_details(
    namespace: str, name: str, current_user: User = Depends(get_current_user)
):
    """Obtenir les détails d'un déploiement."""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)

    try:
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        networking_v1 = client.NetworkingV1Api()

        # Résoudre le déploiement avec fallbacks
        try:
            deployment = apps_v1.read_namespaced_deployment(name, namespace)
        except client.exceptions.ApiException:
            label_selector = (
                f"managed-by=labondemand,user-id={current_user.id},stack-name={name}"
            )
            lst = apps_v1.list_namespaced_deployment(
                namespace, label_selector=label_selector
            )
            if lst.items:
                wp = [
                    d
                    for d in lst.items
                    if (d.metadata.labels or {}).get("component") == "wordpress"
                ]
                deployment = wp[0] if wp else lst.items[0]
                name = deployment.metadata.name
            else:
                lst2 = apps_v1.list_namespaced_deployment(
                    namespace, label_selector=f"app={name}"
                )
                if lst2.items:
                    deployment = lst2.items[0]
                    name = deployment.metadata.name
                else:
                    raise HTTPException(
                        status_code=404, detail="Déploiement non trouvé"
                    )

        if current_user.role == UserRole.student:
            labels = deployment.metadata.labels or {}
            owner_id = labels.get("user-id")
            if owner_id != str(current_user.id):
                raise HTTPException(
                    status_code=403, detail="Accès refusé à ce déploiement"
                )

        dep_labels = deployment.metadata.labels or {}
        stack_name = dep_labels.get("stack-name")

        component_deployments: List[client.V1Deployment] = []
        if stack_name:
            try:
                comp_list = apps_v1.list_namespaced_deployment(
                    namespace,
                    label_selector=f"managed-by=labondemand,stack-name={stack_name}",
                )
                component_deployments = comp_list.items or []
            except Exception:
                component_deployments = []
        if not component_deployments:
            component_deployments = [deployment]

        lifecycle_components = [
            deployment_service.describe_component_lifecycle(dep)
            for dep in component_deployments
        ]
        lifecycle_summary = deployment_service.summarize_lifecycle(lifecycle_components)

        if stack_name:
            pods = core_v1.list_namespaced_pod(
                namespace,
                label_selector=f"managed-by=labondemand,stack-name={stack_name}",
            )
        else:
            pods = core_v1.list_namespaced_pod(namespace, label_selector=f"app={name}")

        if stack_name:
            services = core_v1.list_namespaced_service(
                namespace,
                label_selector=f"managed-by=labondemand,stack-name={stack_name}",
            )
        else:
            services = core_v1.list_namespaced_service(
                namespace, label_selector=f"app={name}"
            )

        # Build node IP cache
        node_ip_cache: Dict[str, str] = {}
        try:
            nodes = core_v1.list_node()
            for node in nodes.items:
                node_name = node.metadata.name
                if node.status and node.status.addresses:
                    external_ip = None
                    internal_ip = None
                    for address in node.status.addresses:
                        if address.type == "ExternalIP" and address.address:
                            external_ip = address.address
                        elif address.type == "InternalIP" and address.address:
                            internal_ip = address.address
                    if external_ip or internal_ip:
                        node_ip_cache[node_name] = external_ip or internal_ip
        except Exception as e:
            logger.warning(
                "node_list_failed", extra={"extra_fields": {"error": str(e)}}
            )

        def get_node_external_ip(node_name: str) -> Optional[str]:
            if not node_name:
                return None
            try:
                node = core_v1.read_node(node_name)
                if node.status and node.status.addresses:
                    external_ip = None
                    internal_ip = None
                    for address in node.status.addresses:
                        if address.type == "ExternalIP" and address.address:
                            external_ip = address.address
                        elif address.type == "InternalIP" and address.address:
                            internal_ip = address.address
                    return external_ip or internal_ip
            except Exception as e:
                logger.warning(
                    "node_ip_resolution_failed",
                    extra={"extra_fields": {"node_name": node_name, "error": str(e)}},
                )
            return None

        def get_cluster_external_ip():
            try:
                if settings.CLUSTER_EXTERNAL_IP:
                    return settings.CLUSTER_EXTERNAL_IP

                def _fallback_from_kubeconfig_host() -> Optional[str]:
                    try:
                        cfg = client.Configuration.get_default_copy()
                        host = getattr(cfg, "host", None)
                        if not host:
                            return None
                        parsed = (
                            urlparse(host)
                            if "://" in host
                            else urlparse(f"https://{host}")
                        )
                        hostname = parsed.hostname
                        if not hostname:
                            return None
                        if hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
                            return None
                        return hostname
                    except Exception:
                        return None

                if node_ip_cache:
                    return list(node_ip_cache.values())[0]

                kube_host = _fallback_from_kubeconfig_host()
                if kube_host:
                    return kube_host

                return "localhost"
            except Exception:
                return "localhost"

        cluster_ip = get_cluster_external_ip()

        def get_node_for_service(service_name: str) -> Optional[str]:
            svc_labels = None
            for svc in services.items:
                if svc.metadata.name == service_name:
                    svc_labels = svc.spec.selector
                    break
            if not svc_labels:
                return None
            for pod in pods.items:
                pod_labels = pod.metadata.labels or {}
                matches = all(
                    pod_labels.get(k) == v for k, v in (svc_labels or {}).items()
                )
                if matches and pod.spec.node_name:
                    pod_phase = pod.status.phase if pod.status else None
                    if pod_phase == "Running":
                        return pod.spec.node_name
            for pod in pods.items:
                pod_labels = pod.metadata.labels or {}
                matches = all(
                    pod_labels.get(k) == v for k, v in (svc_labels or {}).items()
                )
                if matches and pod.spec.node_name:
                    return pod.spec.node_name
            return None

        def get_nodeport_ip(service_name: str) -> str:
            if settings.NODEPORT_USE_POD_NODE_IP:
                node_name = get_node_for_service(service_name)
                if node_name and node_name in node_ip_cache:
                    return node_ip_cache[node_name]
                if node_name:
                    node_ip = get_node_external_ip(node_name)
                    if node_ip:
                        return node_ip
            return cluster_ip

        # Ingress data
        ingress_entries: List[Dict[str, Any]] = []
        ingress_by_service: Dict[str, List[Dict[str, Any]]] = {}
        ingress_access_entries: List[Dict[str, Any]] = []
        try:
            if stack_name:
                ingress_selector = f"managed-by=labondemand,stack-name={stack_name}"
            else:
                ingress_selector = f"managed-by=labondemand,app={name}"
            ingress_list = networking_v1.list_namespaced_ingress(
                namespace, label_selector=ingress_selector
            )
        except Exception:
            ingress_list = client.V1IngressList(items=[])

        for ingress in getattr(ingress_list, "items", []) or []:
            ingress_meta = getattr(ingress, "metadata", None)
            ingress_spec = getattr(ingress, "spec", None)
            ingress_class = (
                getattr(ingress_spec, "ingress_class_name", None)
                if ingress_spec
                else None
            )
            tls_hosts = set()
            if ingress_spec and getattr(ingress_spec, "tls", None):
                for tls_block in ingress_spec.tls:
                    for host in getattr(tls_block, "hosts", []) or []:
                        if host:
                            tls_hosts.add(host)

            for rule in getattr(ingress_spec, "rules", []) or []:
                host = getattr(rule, "host", None)
                http_block = getattr(rule, "http", None)
                if not host or not http_block:
                    continue
                for path in getattr(http_block, "paths", []) or []:
                    backend = getattr(path, "backend", None)
                    service_ref = getattr(backend, "service", None) if backend else None
                    service_name = (
                        getattr(service_ref, "name", None) if service_ref else None
                    )
                    if not service_name:
                        continue
                    service_port_ref = (
                        getattr(service_ref, "port", None) if service_ref else None
                    )
                    service_port = (
                        getattr(service_port_ref, "number", None)
                        if service_port_ref
                        else None
                    )
                    if service_port is None:
                        service_port = getattr(service_port_ref, "name", None)
                    path_value = (
                        getattr(path, "path", None) or settings.INGRESS_DEFAULT_PATH
                    )
                    tls_enabled = host in tls_hosts or bool(settings.INGRESS_TLS_SECRET)
                    scheme = "https" if tls_enabled else "http"
                    entry = {
                        "ingress": getattr(ingress_meta, "name", None),
                        "host": host,
                        "path": path_value,
                        "service": service_name,
                        "service_port": service_port,
                        "class": ingress_class,
                        "tls": tls_enabled,
                        "annotations": dict(
                            getattr(ingress_meta, "annotations", {}) or {}
                        ),
                        "url": f"{scheme}://{host}{path_value}",
                    }
                    ingress_entries.append(entry)
                    ingress_by_service.setdefault(service_name, []).append(entry)
                    ingress_access_entries.append(
                        {
                            "url": entry["url"],
                            "service": service_name,
                            "ingress": entry["ingress"],
                            "host": host,
                            "protocol": scheme,
                            "secure": tls_enabled,
                            "path": path_value,
                        }
                    )

        # Build access URLs
        access_urls = []
        service_data = []

        for svc in services.items:
            service_name = svc.metadata.name
            service_info = {
                "name": svc.metadata.name,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "ports": [],
                "ingresses": ingress_by_service.get(service_name, []),
            }

            for port in svc.spec.ports or []:
                port_info = {
                    "name": port.name,
                    "port": port.port,
                    "target_port": str(port.target_port)
                    if port.target_port
                    else str(port.port),
                    "protocol": port.protocol,
                }

                if port.node_port:
                    port_info["node_port"] = port.node_port
                    if svc.spec.type == "NodePort":
                        label = ""
                        try:
                            lbls = svc.metadata.labels or {}
                            comp = lbls.get("component", "")
                            app_type = lbls.get("app-type", "")
                            if app_type == "lamp":
                                if comp == "web":
                                    label = "Web (Apache/PHP)"
                                elif comp == "phpmyadmin":
                                    label = "phpMyAdmin"
                        except Exception:
                            pass
                        scheme = "http"
                        nodeport_ip = get_nodeport_ip(svc.metadata.name)
                        node_name_for_svc = get_node_for_service(svc.metadata.name)

                        access_urls.append(
                            {
                                "url": f"{scheme}://{nodeport_ip}:{port.node_port}",
                                "service": svc.metadata.name,
                                "node_port": port.node_port,
                                "node_ip": nodeport_ip,
                                "node_name": node_name_for_svc,
                                "cluster_ip": cluster_ip,
                                "label": label or None,
                                "protocol": scheme,
                                "secure": False,
                            }
                        )

                service_info["ports"].append(port_info)

            service_data.append(service_info)

        access_urls.extend(ingress_access_entries)

        return {
            "deployment": {
                "name": deployment.metadata.name,
                "namespace": deployment.metadata.namespace,
                "replicas": deployment.spec.replicas,
                "ready_replicas": deployment.status.ready_replicas or 0,
                "available_replicas": deployment.status.available_replicas or 0,
                "image": deployment.spec.template.spec.containers[0].image
                if deployment.spec.template.spec.containers
                else None,
                "labels": dict(deployment.metadata.labels)
                if deployment.metadata.labels
                else {},
                "state": lifecycle_summary.get("state"),
                "paused": lifecycle_summary.get("paused", False),
            },
            "lifecycle": {
                "state": lifecycle_summary.get("state"),
                "paused": lifecycle_summary.get("paused", False),
                "paused_at": lifecycle_summary.get("paused_at"),
                "paused_by": lifecycle_summary.get("paused_by"),
                "components": lifecycle_components,
            },
            "pods": [
                {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "node_name": pod.spec.node_name,
                }
                for pod in pods.items
            ],
            "services": service_data,
            "ingresses": ingress_entries,
            "access_urls": access_urls,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "api_deployment_details_error",
            extra={
                "extra_fields": {
                    "namespace": namespace,
                    "name": name,
                    "user_id": getattr(current_user, "id", None),
                    "error": str(e),
                }
            },
        )
        raise_k8s_http(e)


# ============= CREDENTIALS (SECRETS) =============


@router.get("/deployments/{namespace}/{name}/credentials")
async def get_deployment_credentials(
    namespace: str, name: str, current_user: User = Depends(get_current_user)
):
    """Récupère les identifiants (secrets) associés à un déploiement LabOnDemand."""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)

    try:
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()

        requested_name = name
        try:
            deployment = apps_v1.read_namespaced_deployment(name, namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                label_selector = f"managed-by=labondemand,user-id={current_user.id},stack-name={name}"
                lst = apps_v1.list_namespaced_deployment(
                    namespace, label_selector=label_selector
                )
                if not lst.items:
                    raise HTTPException(
                        status_code=404,
                        detail="Application introuvable pour récupérer les identifiants",
                    )
                wp = [
                    d
                    for d in lst.items
                    if (d.metadata.labels or {}).get("component") == "wordpress"
                ]
                deployment = wp[0] if wp else lst.items[0]
            else:
                raise
        labels = deployment.metadata.labels or {}
        owner_id = labels.get("user-id")
        app_type = labels.get("app-type", "custom")
        stack_name = (
            labels.get("stack-name") or requested_name or deployment.metadata.name
        )

        if current_user.role == UserRole.student and owner_id != str(current_user.id):
            raise HTTPException(
                status_code=403, detail="Accès refusé à ces identifiants"
            )

        selector = f"managed-by=labondemand,stack-name={stack_name}"
        secrets_list = core_v1.list_namespaced_secret(
            namespace, label_selector=selector
        )
        secret_obj = None
        if secrets_list.items:
            secret_obj = secrets_list.items[0]
        else:
            wp_secret = f"{stack_name}-secret"
            mysql_secret = f"{stack_name}-db-secret"
            try:
                if app_type == "mysql":
                    secret_obj = core_v1.read_namespaced_secret(mysql_secret, namespace)
                else:
                    secret_obj = core_v1.read_namespaced_secret(wp_secret, namespace)
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    raise HTTPException(
                        status_code=404,
                        detail="Aucun identifiant trouvé pour cette application",
                    )
                raise

        data = secret_obj.data or {}

        def dec(key: str) -> Optional[str]:
            val = data.get(key)
            if not val:
                return None
            try:
                return base64.b64decode(val).decode("utf-8")
            except Exception:
                return None

        if app_type == "wordpress":
            wp_url = None
            if deployment_service._should_attach_ingress("wordpress"):
                try:
                    host = deployment_service._build_ingress_host(
                        stack_name, current_user
                    )
                    scheme = "https" if settings.INGRESS_TLS_SECRET else "http"
                    wp_url = f"{scheme}://{host}{settings.INGRESS_DEFAULT_PATH}"
                except Exception:
                    pass
            response = {
                "type": "wordpress",
                "wordpress": {
                    "username": dec("WORDPRESS_USERNAME"),
                    "password": dec("WORDPRESS_PASSWORD"),
                    "email": dec("WORDPRESS_EMAIL"),
                },
                "database": {
                    "host": f"{stack_name}-mariadb-service",
                    "port": 3306,
                    "username": dec("MARIADB_USER") or dec("WORDPRESS_DATABASE_USER"),
                    "password": dec("MARIADB_PASSWORD")
                    or dec("WORDPRESS_DATABASE_PASSWORD"),
                    "database": dec("MARIADB_DATABASE")
                    or dec("WORDPRESS_DATABASE_NAME"),
                },
            }
            if wp_url:
                response["wordpress"]["url"] = wp_url
            return response

        if app_type == "mysql":
            pma_url_hint = "http://<NODE_IP>:<NODE_PORT>/"
            if deployment_service._should_attach_ingress("mysql"):
                try:
                    host = deployment_service._build_ingress_host(
                        stack_name, current_user, component="pma"
                    )
                    scheme = "https" if settings.INGRESS_TLS_SECRET else "http"
                    pma_url_hint = f"{scheme}://{host}{settings.INGRESS_DEFAULT_PATH}"
                except Exception:
                    pass
            return {
                "type": "mysql",
                "database": {
                    "host": f"{stack_name}-mysql-service",
                    "port": 3306,
                    "username": dec("MYSQL_USER"),
                    "password": dec("MYSQL_PASSWORD"),
                    "database": dec("MYSQL_DATABASE"),
                },
                "phpmyadmin": {"url_hint": pma_url_hint},
            }

        if app_type == "lamp":
            lamp_pma_hint = "http://<NODE_IP>:<NODE_PORT>/"
            lamp_web_url = None
            if deployment_service._should_attach_ingress("lamp"):
                try:
                    host_pma = deployment_service._build_ingress_host(
                        stack_name, current_user, component="pma"
                    )
                    host_web = deployment_service._build_ingress_host(
                        stack_name, current_user, component="web"
                    )
                    scheme = "https" if settings.INGRESS_TLS_SECRET else "http"
                    lamp_pma_hint = (
                        f"{scheme}://{host_pma}{settings.INGRESS_DEFAULT_PATH}"
                    )
                    lamp_web_url = (
                        f"{scheme}://{host_web}{settings.INGRESS_DEFAULT_PATH}"
                    )
                except Exception:
                    pass
            response = {
                "type": "lamp",
                "database": {
                    "host": f"{stack_name}-mysql-service",
                    "port": 3306,
                    "username": dec("MYSQL_USER"),
                    "password": dec("MYSQL_PASSWORD"),
                    "database": dec("MYSQL_DATABASE"),
                },
                "phpmyadmin": {"url_hint": lamp_pma_hint},
            }
            if lamp_web_url:
                response["web"] = {"url_hint": lamp_web_url}
            return response

        decoded = {k: dec(k) for k in data.keys()}
        return {"type": app_type, "secrets": decoded}

    except Exception as e:
        raise_k8s_http(e)


# ============= CRÉATION =============


@router.post("/pods")
@limiter.limit("10/5minute")
async def create_pod(
    request: Request,
    name: str,
    image: str,
    namespace: str = "default",
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
):
    """Créer un pod (admin uniquement)."""
    name = validate_k8s_name(name)
    namespace = validate_k8s_name(namespace)

    try:
        v1 = client.CoreV1Api()
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name},
            "spec": {
                "containers": [
                    {"name": name, "image": image, "ports": [{"containerPort": 80}]}
                ]
            },
        }
        v1.create_namespaced_pod(namespace, pod_manifest)
        return {"message": f"Pod {name} créé avec succès dans le namespace {namespace}"}
    except Exception as e:
        raise_k8s_http(e)


@router.post("/deployments")
@limiter.limit("10/5minute")
async def create_deployment(
    request: Request,
    name: str,
    image: str,
    replicas: int = 1,
    create_service: bool = False,
    service_port: int = 80,
    service_target_port: int = 80,
    service_type: str = "ClusterIP",
    deployment_type: str = "custom",
    cpu_request: str = "100m",
    cpu_limit: str = "500m",
    memory_request: str = "128Mi",
    memory_limit: str = "512Mi",
    additional_labels: Optional[Dict[str, str]] = None,
    existing_pvc_name: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """Créer un déploiement avec service optionnel."""
    logger.debug(
        "api_create_deployment_request",
        extra={
            "extra_fields": {
                "name": name,
                "image": image,
                "replicas": replicas,
                "deployment_type": deployment_type,
                "user_id": getattr(current_user, "id", None),
            }
        },
    )
    return await deployment_service.create_deployment(
        name=name,
        image=image,
        replicas=replicas,
        namespace=None,
        create_service=create_service,
        service_port=service_port,
        service_target_port=service_target_port,
        service_type=service_type,
        deployment_type=deployment_type,
        cpu_request=cpu_request,
        cpu_limit=cpu_limit,
        memory_request=memory_request,
        memory_limit=memory_limit,
        additional_labels=additional_labels,
        current_user=current_user,
        existing_pvc_name=existing_pvc_name,
    )


# ============= PAUSE / RESUME =============


@router.post("/deployments/{namespace}/{name}/pause")
async def pause_deployment(
    namespace: str,
    name: str,
    current_user: User = Depends(get_current_user),
):
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    try:
        return await deployment_service.pause_application(namespace, name, current_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise_k8s_http(exc)


@router.post("/deployments/{namespace}/{name}/resume")
async def resume_deployment(
    namespace: str,
    name: str,
    current_user: User = Depends(get_current_user),
):
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    try:
        return await deployment_service.resume_application(
            namespace, name, current_user
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_k8s_http(exc)


# ============= SUPPRESSION =============


@router.delete("/pods/{namespace}/{name}")
async def delete_pod(
    namespace: str,
    name: str,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
):
    """Supprimer un pod (admin uniquement)."""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)

    try:
        v1 = client.CoreV1Api()
        v1.delete_namespaced_pod(name, namespace)
        return {"message": f"Pod {name} supprimé du namespace {namespace}"}
    except Exception as e:
        raise_k8s_http(e)


@router.delete("/deployments/{namespace}/{name}")
async def delete_deployment(
    namespace: str,
    name: str,
    delete_service: bool = True,
    delete_persistent: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Supprimer un déploiement et son service."""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    logger.info(
        "api_delete_deployment_request",
        extra={
            "extra_fields": {
                "namespace": namespace,
                "name": name,
                "user_id": getattr(current_user, "id", None),
                "username": getattr(current_user, "username", None),
                "delete_service": delete_service,
                "delete_persistent": delete_persistent,
            }
        },
    )

    try:
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        networking_v1 = client.NetworkingV1Api()

        def delete_associated_ingress(service_name: str) -> None:
            if not service_name.endswith("-service"):
                return
            ingress_name = f"{service_name[:-8]}-ingress"
            try:
                networking_v1.delete_namespaced_ingress(ingress_name, namespace)
            except client.exceptions.ApiException as exc:
                if exc.status != 404:
                    raise
            except Exception:
                pass

        # Resolve deployment
        stack_mode = False
        try:
            dep = apps_v1.read_namespaced_deployment(name, namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                try:
                    if current_user.role == UserRole.student:
                        label_selector = f"managed-by=labondemand,user-id={current_user.id},stack-name={name}"
                    else:
                        label_selector = f"managed-by=labondemand,stack-name={name}"
                    lst = apps_v1.list_namespaced_deployment(
                        namespace, label_selector=label_selector
                    )
                except Exception:
                    lst = client.V1DeploymentList(items=[])
                if lst and lst.items:
                    wp = [
                        d
                        for d in lst.items
                        if (d.metadata.labels or {}).get("component") == "wordpress"
                    ]
                    dep = wp[0] if wp else lst.items[0]
                    stack_mode = True
                    name = dep.metadata.name
                else:
                    lst2 = apps_v1.list_namespaced_deployment(
                        namespace, label_selector=f"app={name}"
                    )
                    if lst2.items:
                        dep = lst2.items[0]
                        name = dep.metadata.name
                    else:
                        raise HTTPException(
                            status_code=404, detail="Déploiement non trouvé"
                        )
            else:
                raise

        labels = dep.metadata.labels or {}
        app_type = labels.get("app-type", "custom")

        if current_user.role == UserRole.student:
            owner_id = labels.get("user-id")
            managed = labels.get("managed-by")
            if owner_id != str(current_user.id) or managed != "labondemand":
                raise HTTPException(
                    status_code=403, detail="Accès refusé à ce déploiement"
                )

        deleted = []

        if app_type == "wordpress" or (
            stack_mode
            and (
                labels.get("app-type") == "wordpress"
                or labels.get("component") == "wordpress"
            )
        ):
            stack_name = labels.get("stack-name") or name
            wp_name = stack_name
            db_name = f"{stack_name}-mariadb"

            for dep_name in [wp_name, db_name]:
                try:
                    apps_v1.delete_namespaced_deployment(dep_name, namespace)
                    deleted.append(dep_name)
                except client.exceptions.ApiException as e:
                    if e.status != 404:
                        raise

            if delete_service:
                for svc_name in [f"{wp_name}-service", f"{db_name}-service"]:
                    try:
                        core_v1.delete_namespaced_service(svc_name, namespace)
                    except client.exceptions.ApiException as exc:
                        if exc.status != 404:
                            raise
                    delete_associated_ingress(svc_name)

            if delete_persistent:
                try:
                    core_v1.delete_namespaced_persistent_volume_claim(
                        f"{db_name}-pvc", namespace
                    )
                except client.exceptions.ApiException:
                    pass
                try:
                    core_v1.delete_namespaced_secret(f"{stack_name}-secret", namespace)
                except client.exceptions.ApiException:
                    pass

            audit_logger.info(
                "deployment_deleted",
                extra={
                    "extra_fields": {
                        "namespace": namespace,
                        "name": stack_name,
                        "user_id": getattr(current_user, "id", None),
                        "deployment_type": "wordpress",
                        "components_deleted": deleted,
                        "delete_service": delete_service,
                        "delete_persistent": delete_persistent,
                    }
                },
            )
            # Soft delete en base pour garder l'historique
            _soft_delete_deployment(db, current_user.id, stack_name)
            return {
                "message": f"Stack WordPress '{stack_name}' supprimée: {', '.join(deleted)}"
            }

        elif (
            app_type == "mysql"
            or stack_mode
            and (
                labels.get("app-type") == "mysql"
                or labels.get("component") in {"database", "phpmyadmin"}
            )
        ):
            stack_name = labels.get("stack-name") or name
            db_name = f"{stack_name}-mysql"
            pma_name = f"{stack_name}-phpmyadmin"

            for dep_name in [db_name, pma_name]:
                try:
                    apps_v1.delete_namespaced_deployment(dep_name, namespace)
                    deleted.append(dep_name)
                except client.exceptions.ApiException as e:
                    if e.status != 404:
                        raise

            if delete_service:
                for svc_name in [f"{db_name}-service", f"{pma_name}-service"]:
                    try:
                        core_v1.delete_namespaced_service(svc_name, namespace)
                    except client.exceptions.ApiException as exc:
                        if exc.status != 404:
                            raise
                    delete_associated_ingress(svc_name)

            if delete_persistent:
                try:
                    core_v1.delete_namespaced_persistent_volume_claim(
                        f"{db_name}-pvc", namespace
                    )
                except client.exceptions.ApiException:
                    pass
                try:
                    core_v1.delete_namespaced_secret(
                        f"{stack_name}-db-secret", namespace
                    )
                except client.exceptions.ApiException:
                    pass

            audit_logger.info(
                "deployment_deleted",
                extra={
                    "extra_fields": {
                        "namespace": namespace,
                        "name": stack_name,
                        "user_id": getattr(current_user, "id", None),
                        "deployment_type": "mysql",
                        "components_deleted": deleted,
                        "delete_service": delete_service,
                        "delete_persistent": delete_persistent,
                    }
                },
            )
            # Soft delete en base pour garder l'historique
            _soft_delete_deployment(db, current_user.id, stack_name)
            return {
                "message": f"Stack MySQL/phpMyAdmin '{stack_name}' supprimée: {', '.join(deleted)}"
            }

        elif app_type == "lamp" or stack_mode and labels.get("app-type") == "lamp":
            stack_name = labels.get("stack-name") or name
            web_name = f"{stack_name}-web"
            db_name = f"{stack_name}-mysql"
            pma_name = f"{stack_name}-phpmyadmin"

            for dep_name in [web_name, db_name, pma_name]:
                try:
                    apps_v1.delete_namespaced_deployment(dep_name, namespace)
                    deleted.append(dep_name)
                except client.exceptions.ApiException as e:
                    if e.status != 404:
                        raise

            if delete_service:
                for svc_name in [
                    f"{web_name}-service",
                    f"{db_name}-service",
                    f"{pma_name}-service",
                ]:
                    try:
                        core_v1.delete_namespaced_service(svc_name, namespace)
                    except client.exceptions.ApiException as exc:
                        if exc.status != 404:
                            raise
                    delete_associated_ingress(svc_name)

            if delete_persistent:
                try:
                    core_v1.delete_namespaced_persistent_volume_claim(
                        f"{db_name}-pvc", namespace
                    )
                except client.exceptions.ApiException:
                    pass
                try:
                    core_v1.delete_namespaced_secret(
                        f"{stack_name}-db-secret", namespace
                    )
                except client.exceptions.ApiException:
                    pass

            audit_logger.info(
                "deployment_deleted",
                extra={
                    "extra_fields": {
                        "namespace": namespace,
                        "name": stack_name,
                        "user_id": getattr(current_user, "id", None),
                        "deployment_type": "lamp",
                        "components_deleted": deleted,
                        "delete_service": delete_service,
                        "delete_persistent": delete_persistent,
                    }
                },
            )
            # Soft delete en base pour garder l'historique
            _soft_delete_deployment(db, current_user.id, stack_name)
            return {
                "message": f"Stack LAMP '{stack_name}' supprimée: {', '.join(deleted)}"
            }

        else:
            apps_v1.delete_namespaced_deployment(name, namespace)
            if delete_service:
                try:
                    core_v1.delete_namespaced_service(f"{name}-service", namespace)
                except client.exceptions.ApiException as exc:
                    if exc.status != 404:
                        raise
                delete_associated_ingress(f"{name}-service")
            audit_logger.info(
                "deployment_deleted",
                extra={
                    "extra_fields": {
                        "namespace": namespace,
                        "name": name,
                        "user_id": getattr(current_user, "id", None),
                        "deployment_type": labels.get("app-type", "custom"),
                        "delete_service": delete_service,
                        "delete_persistent": delete_persistent,
                    }
                },
            )
            # Soft delete en base pour garder l'historique
            _soft_delete_deployment(db, current_user.id, name)
            return {"message": f"Déploiement {name} supprimé du namespace {namespace}"}
    except Exception as e:
        raise_k8s_http(e)
