"""Endpoints CRUD déploiements, pause/resume, pods, détails, credentials.

Every handler is a plain ``def``: FastAPI runs it in its threadpool, so the
blocking Kubernetes / SQLAlchemy calls never freeze the event loop.
"""

import base64
import logging
from typing import Dict, Optional

import urllib3
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from kubernetes import client
from sqlalchemy.orm import Session

from ..config import settings
from ..security import get_current_user, is_admin, limiter
from ..models import User, UserRole, Deployment as DeploymentModel
from ..database import get_db
from ..k8s_utils import validate_k8s_name
from ..deployment_service import deployment_service
from ..services.access_urls import build_endpoints, get_node_addresses
from ..services.lab_listing import list_user_labs, reconcile_lab_records, to_public_lab
from ..templates import VNC_DESKTOP_TYPES
from ._helpers import raise_k8s_http, audit_logger

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


# ============= LISTING DES DÉPLOIEMENTS LABONDEMAND =============


@router.get("/deployments/labondemand")
def get_labondemand_deployments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, object]:
    """Labs of the current user, each with its ``access_url`` (or ``null``).

    Kubernetes failures answer 503 instead of an empty list.
    """
    try:
        labs = list_user_labs(current_user, deployment_service)
    except HTTPException:
        raise
    except (client.exceptions.ApiException, urllib3.exceptions.HTTPError, OSError) as exc:
        logger.error(
            "api_list_deployments_k8s_unavailable",
            extra={
                "extra_fields": {
                    "user_id": current_user.id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Kubernetes est injoignable : impossible de lister vos labs pour le moment.",
        )

    records = reconcile_lab_records(db, current_user, labs)
    return {
        "deployments": [to_public_lab(lab, records.get(lab["name"])) for lab in labs],
    }


# ============= DÉTAILS D'UN DÉPLOIEMENT =============


@router.get("/deployments/{namespace}/{name}/details")
def get_deployment_details(
    namespace: str, name: str, current_user: User = Depends(get_current_user)
) -> Dict[str, object]:
    """Obtenir les détails d'un déploiement (polled by the UI)."""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)

    try:
        core_v1 = client.CoreV1Api()
        resolved = deployment_service._resolve_target_deployments(
            namespace, name, current_user
        )
        component_deployments = resolved["deployments"]
        preferred = [
            d
            for d in component_deployments
            if (d.metadata.labels or {}).get("component") in {"wordpress", "web"}
        ]
        deployment = preferred[0] if preferred else component_deployments[0]
        name = deployment.metadata.name
        dep_labels = deployment.metadata.labels or {}
        stack_name = resolved["stack_name"] or dep_labels.get("stack-name")
        owner_selector = (
            ""
            if current_user.role == UserRole.admin
            else f",user-id={dep_labels.get('user-id')}"
        )
        selector = (
            f"managed-by=labondemand,stack-name={stack_name}{owner_selector}"
            if stack_name
            else f"managed-by=labondemand,app={name}{owner_selector}"
        )

        lifecycle_components = [
            deployment_service.describe_component_lifecycle(dep)
            for dep in component_deployments
        ]
        lifecycle_summary = deployment_service.summarize_lifecycle(lifecycle_components)

        pods = core_v1.list_namespaced_pod(namespace, label_selector=selector)
        services = core_v1.list_namespaced_service(namespace, label_selector=selector)
        try:
            ingresses = client.NetworkingV1Api().list_namespaced_ingress(
                namespace, label_selector=selector
            ).items or []
        except Exception as exc:
            # Best-effort: NodePort URLs remain usable without the Ingress view.
            logger.warning(
                "ingress_list_failed",
                extra={"extra_fields": {"namespace": namespace, "error": str(exc)}},
            )
            ingresses = []

        pod_nodes = (
            [pod.spec.node_name for pod in pods.items or []]
            if settings.NODEPORT_USE_POD_NODE_IP
            else []
        )
        endpoints = build_endpoints(
            services.items or [], pods.items or [], ingresses, get_node_addresses(pod_nodes)
        )

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
                for pod in pods.items or []
            ],
            **endpoints,
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


def _ingress_url_for(
    app_type: str, stack_name: str, user: User, component: Optional[str] = None
) -> Optional[str]:
    """Public Ingress URL of a lab, when Ingress is used for this app type."""
    if not deployment_service._should_attach_ingress(app_type):
        return None
    host = deployment_service._build_ingress_host(stack_name, user, component=component)
    return deployment_service.ingress_url(host)


def _decode_secret_value(data: Dict[str, str], key: str) -> Optional[str]:
    value = data.get(key)
    if not value:
        return None
    try:
        return base64.b64decode(value).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


@router.get("/deployments/{namespace}/{name}/credentials")
def get_deployment_credentials(
    namespace: str, name: str, current_user: User = Depends(get_current_user)
) -> Dict[str, object]:
    """Récupère les identifiants (secrets) associés à un déploiement LabOnDemand."""
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)

    try:
        core_v1 = client.CoreV1Api()

        resolved = deployment_service._resolve_target_deployments(
            namespace, name, current_user
        )
        deployment = resolved["deployments"][0]
        labels = deployment.metadata.labels or {}
        app_type = labels.get("app-type", "custom")
        stack_name = (
            resolved["stack_name"]
            or labels.get("stack-name")
            or name
            or deployment.metadata.name
        )

        selector = f"managed-by=labondemand,stack-name={stack_name}"
        if current_user.role != UserRole.admin:
            selector += f",user-id={labels.get('user-id')}"
        secrets_list = core_v1.list_namespaced_secret(
            namespace, label_selector=selector
        )
        if secrets_list.items:
            secret_obj = secrets_list.items[0]
        else:
            legacy_name = (
                f"{stack_name}-db-secret" if app_type == "mysql" else f"{stack_name}-secret"
            )
            try:
                secret_obj = core_v1.read_namespaced_secret(legacy_name, namespace)
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    raise HTTPException(
                        status_code=404,
                        detail="Aucun identifiant trouvé pour cette application",
                    )
                raise

        data = secret_obj.data or {}

        def dec(key: str) -> Optional[str]:
            return _decode_secret_value(data, key)

        if app_type == "wordpress":
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
            wp_url = _ingress_url_for("wordpress", stack_name, current_user)
            if wp_url:
                response["wordpress"]["url"] = wp_url
            return response

        if app_type == "vscode":
            response = {
                "type": "vscode",
                "vscode": {
                    "username": dec("CODE_SERVER_USERNAME") or "coder",
                    "password": dec("PASSWORD"),
                },
            }
            vscode_url = _ingress_url_for("vscode", stack_name, current_user)
            if vscode_url:
                response["vscode"]["url"] = vscode_url
            return response

        if app_type == "jupyter":
            response = {
                "type": "jupyter",
                "jupyter": {"token": dec("JUPYTER_TOKEN")},
            }
            jupyter_url = _ingress_url_for("jupyter", stack_name, current_user)
            if jupyter_url:
                response["jupyter"]["url"] = jupyter_url
            return response

        if app_type in VNC_DESKTOP_TYPES:
            response = {
                "type": app_type,
                app_type: {
                    "username": dec("VNC_USERNAME") or "kasm_user",
                    "password": dec("VNC_PW"),
                    "view_only_password": dec("VNC_VIEW_ONLY_PW"),
                },
            }
            desktop_url = _ingress_url_for(app_type, stack_name, current_user)
            if desktop_url:
                response[app_type]["url"] = desktop_url
            return response

        node_port_hint = "http://<NODE_IP>:<NODE_PORT>/"
        database = {
            "host": f"{stack_name}-mysql-service",
            "port": 3306,
            "username": dec("MYSQL_USER"),
            "password": dec("MYSQL_PASSWORD"),
            "database": dec("MYSQL_DATABASE"),
        }
        if app_type == "mysql":
            pma_url = _ingress_url_for("mysql", stack_name, current_user, component="pma")
            return {
                "type": "mysql",
                "database": database,
                "phpmyadmin": {"url_hint": pma_url or node_port_hint},
            }

        if app_type == "lamp":
            pma_url = _ingress_url_for("lamp", stack_name, current_user, component="pma")
            web_url = _ingress_url_for("lamp", stack_name, current_user, component="web")
            response = {
                "type": "lamp",
                "database": database,
                "phpmyadmin": {"url_hint": pma_url or node_port_hint},
            }
            if web_url:
                response["web"] = {"url_hint": web_url}
            return response

        return {"type": app_type, "secrets": {k: dec(k) for k in data.keys()}}

    except Exception as e:
        raise_k8s_http(e)


# ============= CRÉATION =============


@router.post("/pods")
@limiter.limit("10/5minute")
def create_pod(
    request: Request,
    name: str,
    image: str,
    namespace: str = "default",
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
) -> Dict[str, str]:
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
def create_deployment(
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
) -> Dict[str, object]:
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
    return deployment_service.create_deployment(
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
def pause_deployment(
    namespace: str,
    name: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, object]:
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    try:
        return deployment_service.pause_application(namespace, name, current_user)
    except Exception as exc:
        raise_k8s_http(exc)


@router.post("/deployments/{namespace}/{name}/resume")
def resume_deployment(
    namespace: str,
    name: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, object]:
    namespace = validate_k8s_name(namespace)
    name = validate_k8s_name(name)
    try:
        return deployment_service.resume_application(namespace, name, current_user)
    except Exception as exc:
        raise_k8s_http(exc)


# ============= SUPPRESSION =============


@router.delete("/pods/{namespace}/{name}")
def delete_pod(
    namespace: str,
    name: str,
    current_user: User = Depends(get_current_user),
    _: bool = Depends(is_admin),
) -> Dict[str, str]:
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
def delete_deployment(
    namespace: str,
    name: str,
    delete_service: bool = True,
    delete_persistent: bool = False,
    current_user: User = Depends(get_current_user),
) -> Dict[str, object]:
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
        result = deployment_service.delete_labondemand_resources(
            namespace=namespace,
            name=name,
            current_user=current_user,
            delete_services=delete_service,
            delete_persistent=delete_persistent,
        )
    except Exception as e:
        raise_k8s_http(e)
    audit_logger.info(
        "deployment_deleted",
        extra={
            "extra_fields": {
                "namespace": namespace,
                "name": result["name"],
                "user_id": getattr(current_user, "id", None),
                "deployment_type": result["deployment_type"],
                "delete_service": delete_service,
                "delete_persistent": delete_persistent,
                "deleted": result["deleted"],
            }
        },
    )
    return {
        "message": f"Application '{result['name']}' supprimée du namespace {namespace}",
        "deleted": result["deleted"],
    }
