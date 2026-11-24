"""
Kubernetes deployment service: creation, lifecycle (pause/resume) and deletion
of LabOnDemand labs. Every method is blocking (Kubernetes + DB calls): call it
from a plain ``def`` route handler or through ``asyncio.to_thread``.
Multi-component stacks (WordPress, MySQL, LAMP) live in ``backend/services/``.
"""

import base64
import binascii
import datetime
import logging
import re
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Dict, Any, Iterator, Optional, List, Tuple
from fastapi import HTTPException
from kubernetes import client

from .models import User, UserRole, RuntimeConfig, Deployment as DeploymentRecord
from .config import settings
from .database import read_session
from .error_handlers import (
    K8S_TRANSPORT_ERRORS,
    db_unavailable,
    k8s_unavailable,
)
from .lab_locks import user_lab_lock
from .k8s_utils import (
    validate_k8s_name,
    validate_resource_format,
    create_labondemand_labels,
    ensure_namespace_exists,
    build_user_namespace,
    ensure_namespace_baseline,
    max_resource,
    clamp_resources_for_role,
    parse_cpu_to_millicores,
    parse_memory_to_mi,
    get_role_limits,
)
from .templates import DeploymentConfig, VNC_DESKTOP_TYPES
from .services.wordpress_deploy import WordPressDeployMixin
from .services.mysql_deploy import MySQLDeployMixin
from .services.lamp_deploy import LAMPDeployMixin
from .services.stacks import STACK_SPECS, ResourcePlan, StackSpec, plan_resources

logger = logging.getLogger("labondemand.deployment")
audit_logger = logging.getLogger("labondemand.audit")

PAUSE_FLAG_ANNOTATION = "labondemand.io/paused"
PAUSE_REPLICAS_ANNOTATION = "labondemand.io/paused-replicas"
PAUSE_BY_ANNOTATION = "labondemand.io/paused-by"
PAUSE_AT_ANNOTATION = "labondemand.io/paused-at"

# Work directory kept on a PVC (emptyDir fallback) per runtime.
PERSISTENT_HOME_MOUNTS: Dict[str, str] = {
    "vscode": "/home/coder/project",
    "jupyter": "/home/jovyan/work",
    # VNC desktop: the whole user home (projects, XFCE config…)
    "netbeans": "/home/lod-user",
    "eclipse": "/home/lod-user",
}


@dataclass
class _RuntimeExtras:
    """Runtime-specific additions to a single-deployment lab."""

    main_port_name: Optional[str] = None
    extra_container_ports: Optional[List[Dict[str, Any]]] = None
    additional_service_ports: Optional[List[Dict[str, Any]]] = None
    env: Optional[List[Dict[str, Any]]] = None
    env_from: Optional[List[Dict[str, Any]]] = None
    command: Optional[List[str]] = None
    args: Optional[List[str]] = None
    secret_name: Optional[str] = None
    secret_data: Optional[Dict[str, str]] = None
    credentials: Optional[Dict[str, Dict[str, str]]] = None


def _format_port(detail: Dict[str, Any]) -> str:
    base = f"{detail.get('port')}->{detail.get('target_port')}"
    if detail.get("node_port"):
        base += f" (NodePort {detail['node_port']})"
    return f"{detail['name']}:{base}" if detail.get("name") else base


def _find_node_port(
    ports_details: List[Dict[str, Any]], target_name: str, fallback_port: int
) -> Optional[int]:
    for detail in ports_details:
        if detail.get("name") == target_name:
            return detail.get("node_port")
        if detail.get("target_port") == fallback_port:
            return detail.get("node_port")
    return None


def _vnc_connection_hints(
    deployment_type: str,
    ports_details: List[Dict[str, Any]],
    target_port: int,
    credentials: Optional[Dict[str, Dict[str, str]]],
) -> Dict[str, Any]:
    password = credentials[deployment_type]["password"] if credentials else None
    hints: Dict[str, Any] = {
        "novnc": {
            "description": "Bureau distant via navigateur (NoVNC)",
            "url_template": "http://<IP_DU_NOEUD>:<NODE_PORT>",
            "target_port": target_port,
            "node_port": _find_node_port(ports_details, "novnc", target_port),
            "protocol": "http",
            "secure": False,
            "username": "kasm_user",
            "password": password,
        },
        "vnc": {
            "description": "Client VNC classique (optionnel)",
            "target_port": 5901,
            "node_port": _find_node_port(ports_details, "vnc", 5901),
            "username": "kasm_user",
            "password": password,
        },
        "audio": {
            "description": "Flux audio (Websocket Kasm)",
            "target_port": 4901,
            "node_port": _find_node_port(ports_details, "audio", 4901),
        },
    }
    # Eclipse Java EE: public URL of the Tomcat application.
    if deployment_type == "eclipse":
        hints["tomcat"] = {
            "description": (
                "Application web Java EE déployée sur Tomcat "
                "(doit être démarrée dans Eclipse via « Run on Server »)"
            ),
            "url_template": "http://<IP_DU_NOEUD>:<NODE_PORT>",
            "target_port": 8080,
            "node_port": _find_node_port(ports_details, "tomcat", 8080),
            "protocol": "http",
            "secure": False,
        }
    return hints


class DeploymentService(WordPressDeployMixin, MySQLDeployMixin, LAMPDeployMixin):
    """
    Service responsable de la création et gestion des déploiements.
    Les méthodes de création de stacks (WordPress, MySQL, LAMP) sont
    extraites dans des mixins sous backend/services/.
    """

    def __init__(self):
        self.apps_v1 = client.AppsV1Api()
        self.core_v1 = client.CoreV1Api()
        self.networking_v1 = client.NetworkingV1Api()

    @staticmethod
    def _ingress_supported() -> bool:
        """Retourne True si la configuration Ingress est utilisable."""
        if not settings.INGRESS_ENABLED:
            return False
        if not settings.INGRESS_BASE_DOMAIN:
            logger.debug("ingress_disabled_missing_domain")
            return False
        return True

    @staticmethod
    def _should_attach_ingress(deployment_type: str) -> bool:
        if not DeploymentService._ingress_supported():
            return False
        d_type = (deployment_type or "").lower()
        if d_type in settings.INGRESS_EXCLUDED_TYPES:
            return False
        if settings.INGRESS_AUTO_TYPES and d_type not in settings.INGRESS_AUTO_TYPES:
            return False
        return True

    @staticmethod
    def _dns_label(value: str, fallback: str = "app") -> str:
        slug = re.sub(r"[^a-z0-9-]", "-", value.lower()).strip("-")
        slug = re.sub(r"-+", "-", slug)
        if not slug:
            slug = fallback
        if len(slug) > 62:
            slug = slug[:62].rstrip("-")
            if not slug:
                slug = fallback
        return slug

    def _build_ingress_host(
        self, base_name: str, current_user: User, component: Optional[str] = None
    ) -> str:
        label_parts = [self._dns_label(base_name)]
        if component:
            label_parts.append(self._dns_label(component))
        label_parts.append(self._dns_label(f"u{current_user.id}", fallback="u"))
        label = "-".join([part for part in label_parts if part])
        if len(label) > 62:
            label = label[:62].rstrip("-")
            if not label:
                label = "app"
        return f"{label}.{settings.INGRESS_BASE_DOMAIN}"

    def _base_ingress_annotations(self) -> Dict[str, str]:
        annotations = dict(settings.INGRESS_EXTRA_ANNOTATIONS)
        controller_hint = (settings.INGRESS_CLASS_NAME or "").lower()
        if controller_hint.startswith("traefik"):
            entrypoints = "websecure,web" if settings.INGRESS_TLS_SECRET else "web"
            annotations.setdefault(
                "traefik.ingress.kubernetes.io/router.entrypoints", entrypoints
            )
        elif (
            controller_hint.startswith("nginx")
            and settings.INGRESS_TLS_SECRET
            and settings.INGRESS_FORCE_TLS_REDIRECT
        ):
            annotations.setdefault(
                "nginx.ingress.kubernetes.io/force-ssl-redirect", "true"
            )
        return annotations

    def create_ingress_manifest(
        self,
        ingress_name: str,
        host: str,
        service_name: str,
        service_port: int,
        labels: Dict[str, str],
    ) -> Dict[str, Any]:
        app_label = labels.get("app")
        if not app_label and service_name.endswith("-service"):
            app_label = service_name[:-8]
        if not app_label:
            app_label = service_name
        metadata: Dict[str, Any] = {
            "name": ingress_name,
            "labels": {
                "app": app_label,
                **labels,
            },
        }
        annotations = self._base_ingress_annotations()
        if annotations:
            metadata["annotations"] = annotations

        spec: Dict[str, Any] = {
            "ingressClassName": settings.INGRESS_CLASS_NAME,
            "rules": [
                {
                    "host": host,
                    "http": {
                        "paths": [
                            {
                                "path": settings.INGRESS_DEFAULT_PATH,
                                "pathType": settings.INGRESS_PATH_TYPE,
                                "backend": {
                                    "service": {
                                        "name": service_name,
                                        "port": {"number": service_port},
                                    }
                                },
                            }
                        ]
                    },
                }
            ],
        }

        if settings.INGRESS_TLS_SECRET:
            spec["tls"] = [
                {
                    "hosts": [host],
                    "secretName": settings.INGRESS_TLS_SECRET,
                }
            ]

        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": metadata,
            "spec": spec,
        }

    def _apply_ingress(
        self,
        namespace: str,
        ingress_manifest: Dict[str, Any],
    ) -> Tuple[Optional[client.V1Ingress], bool]:
        """Crée ou met à jour un Ingress. Retourne (objet, created)."""
        try:
            created_ingress = self.networking_v1.create_namespaced_ingress(
                namespace, ingress_manifest
            )
            return created_ingress, True
        except client.exceptions.ApiException as exc:
            if exc.status == 409:
                # Ressource existante: effectuer un patch pour mettre à jour labels/spec
                name = ingress_manifest["metadata"]["name"]
                body = {
                    "metadata": {
                        "labels": ingress_manifest["metadata"].get("labels", {}),
                        "annotations": ingress_manifest["metadata"].get(
                            "annotations", {}
                        ),
                    },
                    "spec": ingress_manifest["spec"],
                }
                updated = self.networking_v1.patch_namespaced_ingress(
                    name=name, namespace=namespace, body=body
                )
                return updated, False
            raise

    def validate_permissions(self, user: User, deployment_type: str):
        """Valide les permissions selon le rôle utilisateur.

        Fails closed: when the runtime configuration cannot be read, the
        request fails with HTTP 503 (an admin may have disabled this type).
        """
        if user.role != UserRole.student:
            return
        try:
            with read_session(user) as db:
                rc = (
                    db.query(RuntimeConfig)
                    .filter(
                        RuntimeConfig.key == deployment_type,
                        RuntimeConfig.active == True,  # noqa: E712
                    )
                    .first()
                )
                allowed = bool(rc and rc.allowed_for_students)
        except Exception as exc:
            logger.error(
                "deployment_permission_db_unavailable",
                extra={"extra_fields": {"deployment_type": deployment_type, "error": str(exc)}},
            )
            raise db_unavailable()
        if not allowed:
            logger.warning(
                "deployment_permission_denied",
                extra={
                    "extra_fields": {
                        "user_id": getattr(user, "id", None),
                        "deployment_type": deployment_type,
                        "role": getattr(getattr(user, "role", None), "value", None),
                    }
                },
            )
            raise HTTPException(
                status_code=403,
                detail="Type non autorisé pour les étudiants",
            )

    def apply_deployment_config(
        self,
        deployment_type: str,
        image: str,
        cpu_request: str,
        cpu_limit: str,
        memory_request: str,
        memory_limit: str,
        service_target_port: int,
        create_service: bool,
        service_type: str,
        session_owner: Any = None,
    ) -> Dict[str, Any]:
        """
        Applique la configuration selon le type de déploiement.

        The ``RuntimeConfig`` is read through the session ``session_owner``
        (the current user) is attached to, if any. Fails closed: a DB failure
        raises HTTP 503 instead of silently using the static configuration
        (the DB row may hold stricter or admin-tuned values).
        """
        # 1) Chercher une RuntimeConfig en base
        try:
            with read_session(session_owner) as db:
                config_db = (
                    db.query(RuntimeConfig)
                    .filter(
                        RuntimeConfig.key == deployment_type,
                        RuntimeConfig.active == True,  # noqa: E712
                    )
                    .first()
                )
        except Exception as exc:
            logger.error(
                "runtime_config_lookup_failed",
                extra={"extra_fields": {"deployment_type": deployment_type, "error": str(exc)}},
            )
            raise db_unavailable()

        # 2) Fallback statique si pas de config DB
        # Planchers réellement déclarés par la config (jamais la valeur demandée) :
        # ils doivent survivre au clamp de rôle, cf. create_deployment().
        config = {}
        floors: Dict[str, Any] = {}
        if config_db:
            config = {
                "image": config_db.default_image,
                "target_port": config_db.target_port,
                "service_type": config_db.default_service_type or service_type,
                "min_cpu_request": config_db.min_cpu_request or cpu_request,
                "min_memory_request": config_db.min_memory_request or memory_request,
                "min_cpu_limit": config_db.min_cpu_limit or cpu_limit,
                "min_memory_limit": config_db.min_memory_limit or memory_limit,
            }
            floors = {
                "cpu_request": config_db.min_cpu_request,
                "cpu_limit": config_db.min_cpu_limit,
                "memory_request": config_db.min_memory_request,
                "memory_limit": config_db.min_memory_limit,
            }
        else:
            config = DeploymentConfig.get_config(deployment_type)
            floors = {
                res_key: config.get(f"min_{res_key}")
                for res_key in (
                    "cpu_request",
                    "cpu_limit",
                    "memory_request",
                    "memory_limit",
                )
            }

        if config:
            # Appliquer les valeurs par défaut
            image = config.get("image", image)
            service_target_port = config.get("target_port", service_target_port)
            create_service = True
            service_type = config.get("service_type", service_type)

            # Appliquer les minimums de ressources
            cpu_request = max_resource(
                cpu_request, config.get("min_cpu_request", cpu_request)
            )
            memory_request = max_resource(
                memory_request, config.get("min_memory_request", memory_request)
            )
            cpu_limit = max_resource(cpu_limit, config.get("min_cpu_limit", cpu_limit))
            memory_limit = max_resource(
                memory_limit, config.get("min_memory_limit", memory_limit)
            )

        return {
            "image": image,
            "cpu_request": cpu_request,
            "cpu_limit": cpu_limit,
            "memory_request": memory_request,
            "memory_limit": memory_limit,
            "service_target_port": service_target_port,
            "create_service": create_service,
            "service_type": service_type,
            "has_runtime_config": bool(config_db),
            "floors": floors,
        }

    def _get_user_usage(self, user: User) -> Dict[str, Any]:
        """Calcule l'utilisation actuelle (logique) dans le namespace de l'utilisateur.
        Retourne: {apps_used, pods_used, cpu_m_used, mem_mi_used}
        """
        ns = build_user_namespace(user)
        apps = client.AppsV1Api()
        cpu_m_total = 0.0
        mem_mi_total = 0.0
        pods_used = 0
        app_keys = set()
        try:
            dep_list = apps.list_namespaced_deployment(
                ns, label_selector="managed-by=labondemand"
            )
        except Exception as e:
            # Never forward the raw error: it may contain the API server address.
            logger.warning(
                "user_usage_unavailable",
                extra={"extra_fields": {"namespace": ns, "error": f"{type(e).__name__}: {e}"}},
            )
            raise HTTPException(
                status_code=503,
                detail="Mesure d'usage indisponible : Kubernetes ne répond pas. Réessayez dans un instant.",
            )

        for dep in getattr(dep_list, "items", []) or []:
            status_obj = getattr(dep, "status", None)
            if getattr(dep.metadata, "deletion_timestamp", None):
                remaining = max(
                    getattr(status_obj, "ready_replicas", 0) or 0,
                    getattr(status_obj, "available_replicas", 0) or 0,
                    getattr(status_obj, "updated_replicas", 0) or 0,
                    getattr(status_obj, "replicas", 0) or 0,
                )
                if remaining <= 0:
                    continue

            labels = getattr(dep.metadata, "labels", {}) or {}
            if labels.get("user-id") != str(user.id):
                continue

            replicas_spec = getattr(getattr(dep, "spec", None), "replicas", 0)
            if replicas_spec is None:
                replicas_spec = 0
            replicas_status = max(
                getattr(status_obj, "ready_replicas", 0) or 0,
                getattr(status_obj, "available_replicas", 0) or 0,
                getattr(status_obj, "updated_replicas", 0) or 0,
                getattr(status_obj, "replicas", 0) or 0,
            )
            replicas = max(replicas_spec, replicas_status)
            if replicas <= 0:
                continue
            pods_used += replicas

            # Clé logique d'application: stack-name si présent, sinon label app puis nom
            gkey = labels.get("stack-name") or labels.get("app") or dep.metadata.name
            app_keys.add(gkey)

            tmpl_spec = getattr(
                getattr(getattr(dep, "spec", None), "template", None), "spec", None
            )
            containers = []
            if isinstance(tmpl_spec, dict):
                containers = tmpl_spec.get("containers") or []
            elif tmpl_spec and hasattr(tmpl_spec, "containers"):
                containers = getattr(tmpl_spec, "containers") or []

            for c in containers:
                resources = getattr(c, "resources", None)
                req = getattr(resources, "requests", None) if resources else None
                # Compat dict
                cpu_s = None
                mem_s = None
                if isinstance(req, dict):
                    cpu_s = req.get("cpu")
                    mem_s = req.get("memory")
                else:
                    cpu_s = getattr(req, "get", lambda x: None)("cpu") if req else None
                    mem_s = (
                        getattr(req, "get", lambda x: None)("memory") if req else None
                    )
                if cpu_s:
                    cpu_m_total += parse_cpu_to_millicores(str(cpu_s)) * replicas
                if mem_s:
                    mem_mi_total += parse_memory_to_mi(str(mem_s)) * replicas

        return {
            "apps_used": len(app_keys),
            "pods_used": pods_used,
            "cpu_m_used": int(cpu_m_total),
            "mem_mi_used": int(mem_mi_total),
        }

    def _assert_user_quota(
        self,
        current_user: User,
        planned_apps: int,
        planned_pods: int,
        planned_cpu_request_m: int,
        planned_memory_request_mi: int,
    ) -> None:
        """Vérifie que l'ajout planifié ne dépasse pas les plafonds applicatifs.
        Lève HTTPException 403/400 en cas de dépassement.
        """
        role_val = getattr(current_user.role, "value", str(current_user.role))
        with read_session(current_user) as db:
            limits = get_role_limits(str(role_val), getattr(current_user, "id", None), db=db)
        usage = self._get_user_usage(current_user)

        apps_total = usage["apps_used"] + planned_apps
        pods_total = usage["pods_used"] + planned_pods
        cpu_total = usage["cpu_m_used"] + planned_cpu_request_m
        mem_total = usage["mem_mi_used"] + planned_memory_request_mi

        violations = []
        if apps_total > limits["max_apps"]:
            violations.append(f"apps: {apps_total}/{limits['max_apps']}")
        if pods_total > limits["max_pods"]:
            violations.append(f"pods: {pods_total}/{limits['max_pods']}")
        if cpu_total > limits["max_requests_cpu_m"]:
            violations.append(f"cpu(m): {cpu_total}/{limits['max_requests_cpu_m']}")
        if mem_total > limits["max_requests_mem_mi"]:
            violations.append(f"mem(Mi): {mem_total}/{limits['max_requests_mem_mi']}")

        if violations:
            raise HTTPException(
                status_code=403,
                detail="Quota dépassé: " + ", ".join(violations),
            )

    def _preflight_k8s_quota(
        self,
        namespace: str,
        planned_requests_cpu_m: int,
        planned_limits_cpu_m: int,
        planned_requests_mem_mi: int,
        planned_limits_mem_mi: int,
        planned_pods: int,
        planned_deployments: int,
    ) -> None:
        """Vérifie les ResourceQuota Kubernetes du namespace et lève 403 si l'ajout planned dépasse.
        On examine toutes les ResourceQuota présentes et on s'assure que pour chaque ressource définie,
        used + planned <= hard. En cas de dépassement, on liste les violations.
        """
        try:
            core = client.CoreV1Api()
            rqs = core.list_namespaced_resource_quota(namespace)
        except Exception as e:
            # RBAC may forbid reading quotas: do not block here, Kubernetes
            # itself rejects what exceeds a ResourceQuota.
            logger.warning(
                "k8s_quota_preflight_skipped",
                extra={"extra_fields": {"namespace": namespace, "error": str(e)}},
            )
            return

        if not getattr(rqs, "items", None):
            return

        def parse_cpu(s: str) -> int:
            try:
                return int(parse_cpu_to_millicores(str(s)))
            except Exception:
                return 0

        def parse_mem(s: str) -> int:
            try:
                return int(parse_memory_to_mi(str(s)))
            except Exception:
                return 0

        def parse_int(s: str) -> int:
            try:
                return int(str(s))
            except Exception:
                return 0

        violations: list[str] = []

        # Agréger contre chaque quota; si un seul quota est violé, on refuse.
        for rq in rqs.items:
            hard = getattr(getattr(rq, "status", None), "hard", None) or {}
            used = getattr(getattr(rq, "status", None), "used", None) or {}

            def chk(
                key: str, used_val: int, hard_val: int, add_val: int, unit: str
            ) -> None:
                if hard_val > 0 and (used_val + add_val) > hard_val:
                    violations.append(
                        f"{key}: {used_val}+{add_val}>{hard_val} {unit} (quota='{rq.metadata.name}')"
                    )

            if "requests.cpu" in hard:
                chk(
                    "requests.cpu(m)",
                    parse_cpu(used.get("requests.cpu", "0")),
                    parse_cpu(hard.get("requests.cpu", "0")),
                    planned_requests_cpu_m,
                    "m",
                )
            if "limits.cpu" in hard:
                chk(
                    "limits.cpu(m)",
                    parse_cpu(used.get("limits.cpu", "0")),
                    parse_cpu(hard.get("limits.cpu", "0")),
                    planned_limits_cpu_m,
                    "m",
                )
            if "requests.memory" in hard:
                chk(
                    "requests.memory(Mi)",
                    parse_mem(used.get("requests.memory", "0Mi")),
                    parse_mem(hard.get("requests.memory", "0Mi")),
                    planned_requests_mem_mi,
                    "Mi",
                )
            if "limits.memory" in hard:
                chk(
                    "limits.memory(Mi)",
                    parse_mem(used.get("limits.memory", "0Mi")),
                    parse_mem(hard.get("limits.memory", "0Mi")),
                    planned_limits_mem_mi,
                    "Mi",
                )
            if "pods" in hard:
                chk(
                    "pods",
                    parse_int(used.get("pods", "0")),
                    parse_int(hard.get("pods", "0")),
                    planned_pods,
                    "",
                )
            if "count/deployments.apps" in hard:
                chk(
                    "count/deployments.apps",
                    parse_int(used.get("count/deployments.apps", "0")),
                    parse_int(hard.get("count/deployments.apps", "0")),
                    planned_deployments,
                    "",
                )

        if violations:
            raise HTTPException(
                status_code=403,
                detail="Quota Kubernetes dépassé: " + "; ".join(violations),
            )

    @staticmethod
    def _assert_namespace_allowed(namespace: str, current_user: User) -> None:
        """Empêche un étudiant de manipuler un namespace qui n'est pas le sien."""
        if current_user.role != UserRole.student:
            return
        expected = build_user_namespace(current_user)
        if namespace != expected:
            audit_logger.warning(
                "namespace_access_denied",
                extra={
                    "extra_fields": {
                        "namespace": namespace,
                        "expected_namespace": expected,
                        "user_id": getattr(current_user, "id", None),
                    }
                },
            )
            raise HTTPException(
                status_code=403, detail="Namespace non autorisé pour cet utilisateur"
            )

    @staticmethod
    def _can_control_foreign_deployments(user: User) -> bool:
        role = getattr(user, "role", None)
        return role == UserRole.admin

    def _assert_deployment_access(
        self,
        labels: Dict[str, str],
        current_user: User,
        namespace: str,
        deployment_name: str,
    ) -> None:
        managed = labels.get("managed-by")
        owner_id = labels.get("user-id")
        if managed != "labondemand":
            audit_logger.warning(
                "deployment_access_blocked_non_managed",
                extra={
                    "extra_fields": {
                        "deployment": deployment_name,
                        "namespace": namespace,
                        "user_id": getattr(current_user, "id", None),
                        "managed": managed,
                    }
                },
            )
            raise HTTPException(
                status_code=403, detail="Déploiement hors périmètre LabOnDemand"
            )

        if not owner_id:
            audit_logger.warning(
                "deployment_access_blocked_no_owner",
                extra={
                    "extra_fields": {
                        "deployment": deployment_name,
                        "namespace": namespace,
                        "user_id": getattr(current_user, "id", None),
                    }
                },
            )
            raise HTTPException(
                status_code=403, detail="Déploiement sans propriétaire identifié"
            )

        if owner_id == str(getattr(current_user, "id", "")):
            return

        if self._can_control_foreign_deployments(current_user):
            return

        audit_logger.warning(
            "deployment_access_blocked_foreign_owner",
            extra={
                "extra_fields": {
                    "deployment": deployment_name,
                    "namespace": namespace,
                    "user_id": getattr(current_user, "id", None),
                    "target_owner": owner_id,
                }
            },
        )
        raise HTTPException(status_code=403, detail="Accès refusé à ce déploiement")

    def _stack_label_selector(self, stack_name: str, current_user: User) -> str:
        selector = f"managed-by=labondemand,stack-name={stack_name}"
        if not self._can_control_foreign_deployments(current_user):
            selector += f",user-id={current_user.id}"
        return selector

    def _resolve_target_deployments(
        self,
        namespace: str,
        name: str,
        current_user: User,
    ) -> Dict[str, Any]:
        namespace = validate_k8s_name(namespace)
        name = validate_k8s_name(name)
        self._assert_namespace_allowed(namespace, current_user)

        deployments: List[client.V1Deployment] = []
        stack_name: Optional[str] = None
        stack_mode = False

        try:
            deployment = self.apps_v1.read_namespaced_deployment(name, namespace)
            deployments = [deployment]
            labels = deployment.metadata.labels or {}
            stack_name = labels.get("stack-name")
            if stack_name:
                stack_mode = True
                deployments = (
                    self.apps_v1.list_namespaced_deployment(
                        namespace,
                        label_selector=self._stack_label_selector(
                            stack_name, current_user
                        ),
                    ).items
                    or []
                )
        except client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise

        if not deployments:
            stack_selector = self._stack_label_selector(name, current_user)
            stack_candidates = self.apps_v1.list_namespaced_deployment(
                namespace, label_selector=stack_selector
            )
            if stack_candidates.items:
                deployments = stack_candidates.items
                stack_name = name
                stack_mode = True
            else:
                app_selector = f"app={name}"
                app_candidates = self.apps_v1.list_namespaced_deployment(
                    namespace, label_selector=app_selector
                )
                if app_candidates.items:
                    deployments = app_candidates.items
                else:
                    raise HTTPException(
                        status_code=404, detail="Déploiement non trouvé"
                    )

        filtered: List[client.V1Deployment] = []
        for dep in deployments:
            labels = dep.metadata.labels or {}
            self._assert_deployment_access(
                labels, current_user, namespace, dep.metadata.name
            )
            filtered.append(dep)

        deployments = filtered
        if not deployments:
            raise HTTPException(status_code=404, detail="Déploiement introuvable")

        base_labels = deployments[0].metadata.labels or {}
        app_type = base_labels.get("app-type", "custom")
        display_name = (
            stack_name or base_labels.get("stack-name") or deployments[0].metadata.name
        )

        return {
            "deployments": deployments,
            "stack_mode": stack_mode,
            "stack_name": stack_name,
            "display_name": display_name,
            "namespace": namespace,
            "app_type": app_type,
        }

    @staticmethod
    def _record_lifecycle_status(
        user: User,
        name: str,
        namespace: str,
        status: str,
        mark_seen: bool = False,
        deleted: bool = False,
    ) -> None:
        try:
            # Own short session (not the caller's): a fresh transaction sees
            # rows committed by concurrent requests.
            from .database import SessionLocal

            with SessionLocal() as db:
                query = db.query(DeploymentRecord).filter(
                    DeploymentRecord.name == name,
                    DeploymentRecord.namespace == namespace,
                    DeploymentRecord.deleted_at.is_(None),
                )
                if user.role != UserRole.admin:
                    query = query.filter(DeploymentRecord.user_id == user.id)
                # Every live row: duplicates left by older versions are healed too.
                records = query.all()
                if not records:
                    return
                now = datetime.datetime.now(datetime.timezone.utc)
                for rec in records:
                    rec.status = status
                    if mark_seen:
                        rec.last_seen_at = now
                    if deleted:
                        rec.deleted_at = now
                db.commit()
        except Exception as exc:
            logger.warning(
                "deployment_db_status_update_failed",
                extra={
                    "extra_fields": {
                        "name": name,
                        "namespace": namespace,
                        "status": status,
                        "error": str(exc),
                    }
                },
            )

    def delete_labondemand_resources(
        self,
        namespace: str,
        name: str,
        current_user: User,
        delete_services: bool = True,
        delete_persistent: bool = False,
    ) -> Dict[str, Any]:
        """Supprime une application LabOnDemand entière via labels, après contrôle d'accès.

        The Kubernetes deletion and the DB soft delete run under the owner's
        lab lock, so a concurrent lab list cannot re-create the row in between.
        """
        resolved = self._resolve_target_deployments(namespace, name, current_user)
        with user_lab_lock(self._lab_owner_id(resolved["deployments"], current_user)):
            return self._delete_resolved(
                resolved, current_user, delete_services, delete_persistent
            )

    @staticmethod
    def _lab_owner_id(
        deployments: List[client.V1Deployment], current_user: User
    ) -> int:
        """Owner of a resolved lab (``user-id`` label), the caller by default."""
        for dep in deployments:
            owner = ((dep.metadata.labels or {}) if dep.metadata else {}).get("user-id")
            try:
                return int(owner)
            except (TypeError, ValueError):
                continue
        return int(current_user.id)

    def _delete_resolved(
        self,
        resolved: Dict[str, Any],
        current_user: User,
        delete_services: bool,
        delete_persistent: bool,
    ) -> Dict[str, Any]:
        display_name = resolved["display_name"]
        stack_name = resolved["stack_name"]
        selector_name = stack_name or display_name
        label_selector = (
            f"managed-by=labondemand,stack-name={selector_name}"
            if stack_name
            else f"managed-by=labondemand,app={display_name}"
        )
        if not self._can_control_foreign_deployments(current_user):
            label_selector += f",user-id={current_user.id}"

        deleted: Dict[str, List[str]] = {
            "deployments": [],
            "services": [],
            "ingresses": [],
            "pvcs": [],
            "secrets": [],
        }

        def ignore_404(call, resource_name: str, bucket: str) -> None:
            try:
                call()
                deleted[bucket].append(resource_name)
            except client.exceptions.ApiException as exc:
                if exc.status != 404:
                    raise

        for dep in resolved["deployments"]:
            dep_name = dep.metadata.name
            ignore_404(
                lambda dep_name=dep_name: self.apps_v1.delete_namespaced_deployment(
                    dep_name, resolved["namespace"]
                ),
                dep_name,
                "deployments",
            )

        if delete_services:
            services = self.core_v1.list_namespaced_service(
                resolved["namespace"], label_selector=label_selector
            )
            for svc in services.items or []:
                svc_name = svc.metadata.name
                ignore_404(
                    lambda svc_name=svc_name: self.core_v1.delete_namespaced_service(
                        svc_name, resolved["namespace"]
                    ),
                    svc_name,
                    "services",
                )

            ingresses = self.networking_v1.list_namespaced_ingress(
                resolved["namespace"], label_selector=label_selector
            )
            for ing in ingresses.items or []:
                ing_name = ing.metadata.name
                ignore_404(
                    lambda ing_name=ing_name: self.networking_v1.delete_namespaced_ingress(
                        ing_name, resolved["namespace"]
                    ),
                    ing_name,
                    "ingresses",
                )

        if resolved["app_type"] in {"vscode", "jupyter"} | VNC_DESKTOP_TYPES:
            secrets = self.core_v1.list_namespaced_secret(
                resolved["namespace"], label_selector=label_selector
            )
            for secret in secrets.items or []:
                secret_name = secret.metadata.name
                ignore_404(
                    lambda secret_name=secret_name: self.core_v1.delete_namespaced_secret(
                        secret_name, resolved["namespace"]
                    ),
                    secret_name,
                    "secrets",
                )

        if delete_persistent:
            pvcs = self.core_v1.list_namespaced_persistent_volume_claim(
                resolved["namespace"], label_selector=label_selector
            )
            for pvc in pvcs.items or []:
                pvc_name = pvc.metadata.name
                ignore_404(
                    lambda pvc_name=pvc_name: self.core_v1.delete_namespaced_persistent_volume_claim(
                        pvc_name, resolved["namespace"]
                    ),
                    pvc_name,
                    "pvcs",
                )

            secrets = self.core_v1.list_namespaced_secret(
                resolved["namespace"], label_selector=label_selector
            )
            for secret in secrets.items or []:
                secret_name = secret.metadata.name
                ignore_404(
                    lambda secret_name=secret_name: self.core_v1.delete_namespaced_secret(
                        secret_name, resolved["namespace"]
                    ),
                    secret_name,
                    "secrets",
                )

        self._record_lifecycle_status(
            current_user,
            display_name,
            resolved["namespace"],
            "deleted",
            deleted=True,
        )
        return {
            "name": display_name,
            "namespace": resolved["namespace"],
            "deployment_type": resolved["app_type"],
            "deleted": deleted,
        }

    def _rollback_created_objects(
        self, namespace: str, created: List[Tuple[str, str]]
    ) -> None:
        for kind, resource_name in reversed(created):
            try:
                if kind == "ingress":
                    self.networking_v1.delete_namespaced_ingress(resource_name, namespace)
                elif kind == "deployment":
                    self.apps_v1.delete_namespaced_deployment(resource_name, namespace)
                elif kind == "service":
                    self.core_v1.delete_namespaced_service(resource_name, namespace)
                elif kind == "pvc":
                    self.core_v1.delete_namespaced_persistent_volume_claim(
                        resource_name, namespace
                    )
                elif kind == "secret":
                    self.core_v1.delete_namespaced_secret(resource_name, namespace)
            except Exception as exc:
                if isinstance(exc, client.exceptions.ApiException) and exc.status == 404:
                    continue  # already gone
                logger.warning(
                    "deployment_create_rollback_item_failed",
                    extra={
                        "extra_fields": {
                            "namespace": namespace,
                            "kind": kind,
                            "name": resource_name,
                            "error": str(exc),
                        }
                    },
                )

    def describe_component_lifecycle(
        self, deployment: client.V1Deployment
    ) -> Dict[str, Any]:
        annotations = dict(getattr(deployment.metadata, "annotations", {}) or {})
        requested = int(getattr(getattr(deployment, "spec", None), "replicas", 0) or 0)
        ready = int(
            getattr(getattr(deployment, "status", None), "ready_replicas", 0) or 0
        )
        available = int(
            getattr(getattr(deployment, "status", None), "available_replicas", 0)
            or ready
        )
        paused_flag = annotations.get(PAUSE_FLAG_ANNOTATION) == "true"
        state = "running"
        if paused_flag or requested == 0:
            state = "paused"
        elif available > 0 and ready >= available:
            state = "running"
        else:
            state = "starting"

        stored_replicas = annotations.get(PAUSE_REPLICAS_ANNOTATION)
        resume_replicas: Optional[int] = None
        if stored_replicas:
            try:
                resume_replicas = max(int(stored_replicas), 1)
            except (TypeError, ValueError):
                resume_replicas = None

        return {
            "name": deployment.metadata.name,
            "state": state,
            "paused": state == "paused",
            "requested_replicas": requested,
            "ready_replicas": ready,
            "available_replicas": available,
            "paused_at": annotations.get(PAUSE_AT_ANNOTATION),
            "paused_by": annotations.get(PAUSE_BY_ANNOTATION),
            "resume_replicas": resume_replicas or max(requested, 1) or 1,
        }

    def summarize_lifecycle(self, components: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not components:
            return {
                "state": "unknown",
                "paused": False,
                "paused_components": 0,
                "total_components": 0,
            }

        total = len(components)
        paused_count = sum(1 for comp in components if comp.get("state") == "paused")
        running_count = sum(1 for comp in components if comp.get("state") == "running")

        if paused_count == total:
            state = "paused"
        elif running_count == total:
            state = "running"
        else:
            state = "mixed"

        paused_at_values = [
            comp.get("paused_at") for comp in components if comp.get("paused_at")
        ]
        paused_by_values = [
            comp.get("paused_by") for comp in components if comp.get("paused_by")
        ]

        return {
            "state": state,
            "paused": paused_count == total and total > 0,
            "paused_components": paused_count,
            "total_components": total,
            "paused_at": max(paused_at_values) if paused_at_values else None,
            "paused_by": paused_by_values[0] if paused_by_values else None,
        }

    def pause_application(
        self, namespace: str, name: str, current_user: User
    ) -> Dict[str, Any]:
        """Scale every component to 0 and remember the replica count (blocking)."""
        resolved = self._resolve_target_deployments(namespace, name, current_user)
        components_payload: List[Dict[str, Any]] = []
        iso_now = (
            datetime.datetime.now(datetime.timezone.utc)
            .replace(tzinfo=None)
            .isoformat()
            + "Z"
        )
        paused_by = getattr(
            current_user, "username", str(getattr(current_user, "id", "unknown"))
        )

        for deployment in resolved["deployments"]:
            lifecycle_before = self.describe_component_lifecycle(deployment)
            if lifecycle_before["state"] == "paused":
                components_payload.append(
                    {
                        "name": deployment.metadata.name,
                        "already_paused": True,
                        "lifecycle": lifecycle_before,
                    }
                )
                continue

            previous_replicas = max(lifecycle_before.get("requested_replicas", 0), 1)
            patch_body = {
                "metadata": {
                    "annotations": {
                        PAUSE_FLAG_ANNOTATION: "true",
                        PAUSE_REPLICAS_ANNOTATION: str(previous_replicas),
                        PAUSE_BY_ANNOTATION: paused_by,
                        PAUSE_AT_ANNOTATION: iso_now,
                    }
                },
                "spec": {"replicas": 0},
            }
            updated = self.apps_v1.patch_namespaced_deployment(
                name=deployment.metadata.name,
                namespace=resolved["namespace"],
                body=patch_body,
            )
            components_payload.append(
                {
                    "name": deployment.metadata.name,
                    "previous_replicas": previous_replicas,
                    "lifecycle": self.describe_component_lifecycle(updated),
                }
            )

        lifecycle_summary = self.summarize_lifecycle(
            [c["lifecycle"] for c in components_payload]
        )

        audit_logger.info(
            "deployment_paused",
            extra={
                "extra_fields": {
                    "namespace": resolved["namespace"],
                    "display_name": resolved["display_name"],
                    "user_id": getattr(current_user, "id", None),
                    "stack_mode": resolved["stack_mode"],
                    "components": [c["name"] for c in components_payload],
                }
            },
        )

        self._record_lifecycle_status(
            current_user,
            resolved["display_name"],
            resolved["namespace"],
            "paused",
            mark_seen=True,
        )

        return {
            "action": "paused",
            "name": resolved["display_name"],
            "namespace": resolved["namespace"],
            "stack": resolved["stack_name"],
            "components": components_payload,
            "lifecycle": lifecycle_summary,
            "message": "Application mise en pause. Les pods seront libérés dans quelques secondes.",
        }

    def _resume_plan(self, deployments: List[client.V1Deployment]) -> ResourcePlan:
        """Resources the paused components will request once scaled back up."""
        totals = {"req_cpu": 0.0, "req_mem": 0.0, "lim_cpu": 0.0, "lim_mem": 0.0}
        pods = 0
        for deployment in deployments:
            replicas = self.describe_component_lifecycle(deployment).get("resume_replicas") or 1
            pods += replicas
            tmpl_spec = getattr(getattr(deployment.spec, "template", None), "spec", None)
            for container in (getattr(tmpl_spec, "containers", None) or []) if tmpl_spec else []:
                resources = getattr(container, "resources", None)
                for prefix, values in (
                    ("req", getattr(resources, "requests", None) if resources else None),
                    ("lim", getattr(resources, "limits", None) if resources else None),
                ):
                    if not isinstance(values, dict):
                        continue
                    if values.get("cpu"):
                        totals[f"{prefix}_cpu"] += parse_cpu_to_millicores(str(values["cpu"])) * replicas
                    if values.get("memory"):
                        totals[f"{prefix}_mem"] += parse_memory_to_mi(str(values["memory"])) * replicas
        return ResourcePlan(
            requests_cpu_m=int(totals["req_cpu"]),
            # Containers without limits count their requests against limits quotas.
            limits_cpu_m=int(totals["lim_cpu"] or totals["req_cpu"]),
            requests_mem_mi=int(totals["req_mem"]),
            limits_mem_mi=int(totals["lim_mem"] or totals["req_mem"]),
            pods=pods,
            deployments=len(deployments),
        )

    def resume_application(
        self, namespace: str, name: str, current_user: User
    ) -> Dict[str, Any]:
        """Scale paused components back up after the quota checks (blocking).

        Quota check and scale-up run under the caller's lab lock (the quota
        being checked is the caller's), like lab creation.
        """
        resolved = self._resolve_target_deployments(namespace, name, current_user)
        with user_lab_lock(current_user.id):
            return self._resume_resolved(resolved, current_user)

    def _resume_resolved(
        self, resolved: Dict[str, Any], current_user: User
    ) -> Dict[str, Any]:
        self._enforce_quotas(
            current_user, resolved["namespace"], self._resume_plan(resolved["deployments"])
        )

        components_payload: List[Dict[str, Any]] = []
        for deployment in resolved["deployments"]:
            lifecycle_before = self.describe_component_lifecycle(deployment)
            target_replicas = lifecycle_before.get("resume_replicas") or 1
            patch_body = {
                "metadata": {
                    "annotations": {
                        PAUSE_FLAG_ANNOTATION: None,
                        PAUSE_REPLICAS_ANNOTATION: None,
                        PAUSE_BY_ANNOTATION: None,
                        PAUSE_AT_ANNOTATION: None,
                    }
                },
                "spec": {"replicas": target_replicas},
            }
            updated = self.apps_v1.patch_namespaced_deployment(
                name=deployment.metadata.name,
                namespace=resolved["namespace"],
                body=patch_body,
            )
            components_payload.append(
                {
                    "name": deployment.metadata.name,
                    "target_replicas": target_replicas,
                    "lifecycle": self.describe_component_lifecycle(updated),
                }
            )

        lifecycle_summary = self.summarize_lifecycle(
            [c["lifecycle"] for c in components_payload]
        )

        audit_logger.info(
            "deployment_resumed",
            extra={
                "extra_fields": {
                    "namespace": resolved["namespace"],
                    "display_name": resolved["display_name"],
                    "user_id": getattr(current_user, "id", None),
                    "stack_mode": resolved["stack_mode"],
                    "components": [c["name"] for c in components_payload],
                }
            },
        )

        self._record_lifecycle_status(
            current_user,
            resolved["display_name"],
            resolved["namespace"],
            "active",
            mark_seen=True,
        )

        return {
            "action": "resumed",
            "name": resolved["display_name"],
            "namespace": resolved["namespace"],
            "stack": resolved["stack_name"],
            "components": components_payload,
            "lifecycle": lifecycle_summary,
            "message": "Application redémarrée. Les pods seront recréés sous peu.",
        }

    def _validate_existing_pvc(
        self,
        namespace: str,
        pvc_name: str,
        current_user: User,
    ) -> client.V1PersistentVolumeClaim:
        """S'assure qu'un PVC existe et appartient bien à l'utilisateur courant."""
        pvc_name = validate_k8s_name(pvc_name)
        try:
            pvc = self.core_v1.read_namespaced_persistent_volume_claim(
                pvc_name, namespace
            )
        except client.exceptions.ApiException as e:
            if e.status == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Volume persistant '{pvc_name}' introuvable",
                )
            raise

        labels = pvc.metadata.labels or {}
        if current_user.role == UserRole.student:
            if labels.get("managed-by") != "labondemand" or labels.get(
                "user-id"
            ) != str(current_user.id):
                raise HTTPException(status_code=403, detail="Accès refusé à ce volume")

        return pvc

    def get_user_quota_summary(self, user: User) -> Dict[str, Any]:
        """Retourne un résumé des quotas: role, usage courant, limites et restants."""
        role_val = getattr(user.role, "value", str(user.role))
        with read_session(user) as db:
            limits = get_role_limits(str(role_val), getattr(user, "id", None), db=db)
        usage = self._get_user_usage(user)
        remaining = {
            "apps": max(limits["max_apps"] - usage["apps_used"], 0),
            "pods": max(limits["max_pods"] - usage["pods_used"], 0),
            "cpu_m": max(limits["max_requests_cpu_m"] - usage["cpu_m_used"], 0),
            "mem_mi": max(limits["max_requests_mem_mi"] - usage["mem_mi_used"], 0),
        }
        return {
            "role": str(role_val),
            "limits": limits,
            "usage": usage,
            "remaining": remaining,
        }

    def _track_deployment_in_db(
        self,
        user: User,
        name: str,
        deployment_type: str,
        namespace: str,
        stack_name: Optional[str] = None,
        cpu_requested: Optional[str] = None,
        mem_requested: Optional[str] = None,
    ) -> Optional[int]:
        """Crée ou met à jour l'enregistrement Deployment en base avec expires_at calculé selon le rôle.

        Called under the user's lab lock (see ``create_deployment``), in its
        own short session so the existence check sees committed rows.
        Returns the row id, or ``None`` when the DB could not be written (the
        lab list re-creates the row later).
        """
        try:
            from .database import SessionLocal
            from .tasks.cleanup import compute_expires_at

            role_val = getattr(user.role, "value", str(user.role))
            expires_at = compute_expires_at(role_val)

            with SessionLocal() as db:
                # Upsert : si un enregistrement actif existe déjà pour ce nom, on le met à jour
                existing = (
                    db.query(DeploymentRecord)
                    .filter(
                        DeploymentRecord.user_id == user.id,
                        DeploymentRecord.name == name,
                        DeploymentRecord.deleted_at.is_(None),
                    )
                    .first()
                )
                if existing:
                    record = existing
                    existing.status = "active"
                    existing.namespace = namespace
                    existing.deployment_type = deployment_type
                    existing.stack_name = stack_name
                    existing.expires_at = expires_at
                    if cpu_requested:
                        existing.cpu_requested = cpu_requested
                    if mem_requested:
                        existing.mem_requested = mem_requested
                else:
                    record = DeploymentRecord(
                        user_id=user.id,
                        name=name,
                        deployment_type=deployment_type,
                        namespace=namespace,
                        stack_name=stack_name,
                        status="active",
                        expires_at=expires_at,
                        cpu_requested=cpu_requested,
                        mem_requested=mem_requested,
                    )
                    db.add(record)
                db.commit()
                return int(record.id)
        except Exception as exc:
            logger.warning(
                "deployment_db_track_failed",
                extra={"extra_fields": {"name": name, "error": str(exc)}},
            )
            return None

    def create_deployment_manifest(
        self,
        name: str,
        image: str,
        replicas: int,
        cpu_request: str,
        cpu_limit: str,
        memory_request: str,
        memory_limit: str,
        service_target_port: int,
        labels: Dict[str, str],
        main_port_name: Optional[str] = None,
        extra_container_ports: Optional[List[Dict[str, Any]]] = None,
        env_vars: Optional[List[Dict[str, Any]]] = None,
        env_from: Optional[List[Dict[str, Any]]] = None,
        command: Optional[List[str]] = None,
        args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Crée le manifeste du déploiement"""
        ports: List[Dict[str, Any]] = []
        if service_target_port is not None:
            port_entry: Dict[str, Any] = {"containerPort": service_target_port}
            if main_port_name:
                port_entry["name"] = main_port_name
            ports.append(port_entry)
        if extra_container_ports:
            ports.extend(extra_container_ports)

        container_spec: Dict[str, Any] = {
            "name": name,
            "image": image,
            "resources": {
                "requests": {
                    "cpu": cpu_request,
                    "memory": memory_request,
                },
                "limits": {
                    "cpu": cpu_limit,
                    "memory": memory_limit,
                },
            },
        }
        if ports:
            container_spec["ports"] = ports
        if env_vars:
            container_spec["env"] = env_vars
        if env_from:
            container_spec["envFrom"] = env_from
        if command:
            container_spec["command"] = command
        if args:
            container_spec["args"] = args

        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": name,
                "labels": {"app": name, **labels},
            },
            "spec": {
                "replicas": replicas,
                "selector": {
                    "matchLabels": {"app": name},
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": name,
                            **labels,
                        }
                    },
                    "spec": {
                        "containers": [container_spec],
                    },
                },
            },
        }

    def create_service_manifest(
        self,
        name: str,
        service_port: int,
        service_target_port: int,
        service_type: str,
        labels: Dict[str, str],
        port_name: Optional[str] = None,
        additional_ports: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Crée le manifeste du service"""
        ports: List[Dict[str, Any]] = []

        if service_port is not None and service_target_port is not None:
            port_spec: Dict[str, Any] = {
                "port": service_port,
                "targetPort": service_target_port,
                "protocol": "TCP",
            }
            if port_name:
                port_spec["name"] = port_name
            ports.append(port_spec)

        if additional_ports:
            ports.extend(additional_ports)

        # Pour NodePort, ne pas spécifier nodePort pour laisser Kubernetes l'assigner automatiquement

        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": f"{name}-service", "labels": {"app": name, **labels}},
            "spec": {"selector": {"app": name}, "type": service_type, "ports": ports},
        }

    # ------------------------------------------------------------------
    # Creation helpers shared by single deployments and stacks
    # ------------------------------------------------------------------

    @staticmethod
    def _role_value(user: User) -> str:
        return str(getattr(user.role, "value", str(user.role)))

    @staticmethod
    def ingress_url(host: str) -> str:
        scheme = "https" if settings.INGRESS_TLS_SECRET else "http"
        return f"{scheme}://{host}{settings.INGRESS_DEFAULT_PATH}"

    @contextmanager
    def _rollback_on_failure(
        self,
        namespace: str,
        created: List[Tuple[str, str]],
        api_error_prefix: str,
        unexpected_error_prefix: str,
        **log_fields: Any,
    ) -> Iterator[None]:
        """Delete what the block created if it fails, and map the error to HTTP."""
        try:
            yield
        except HTTPException:
            self._rollback_created_objects(namespace, created)
            raise
        except client.exceptions.ApiException as exc:
            self._rollback_created_objects(namespace, created)
            logger.exception(
                "deployment_k8s_error",
                extra={
                    "extra_fields": {
                        **log_fields,
                        "namespace": namespace,
                        "status": getattr(exc, "status", None),
                        "reason": getattr(exc, "reason", None),
                    }
                },
            )
            status = exc.status or 0
            # A 401 means the platform's cluster credentials were rejected
            # (forwarding it would make the browser think the user session
            # expired); 503 / status 0 are transport-level failures.
            if status in (401, 503) or not 100 <= status <= 599:
                raise k8s_unavailable()
            raise HTTPException(
                status_code=status,
                detail=f"{api_error_prefix}: {exc.reason} - {exc.body}",
            )
        except K8S_TRANSPORT_ERRORS as exc:
            # Cluster unreachable: roll back what can be, answer 503 without
            # the raw error (it names the API server host).
            self._rollback_created_objects(namespace, created)
            logger.error(
                "deployment_k8s_unreachable",
                extra={
                    "extra_fields": {
                        **log_fields,
                        "namespace": namespace,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                },
            )
            raise k8s_unavailable()
        except Exception:
            self._rollback_created_objects(namespace, created)
            logger.exception(
                "deployment_unexpected_error",
                extra={"extra_fields": {**log_fields, "namespace": namespace}},
            )
            raise HTTPException(
                status_code=500,
                detail=f"{unexpected_error_prefix} (erreur interne, consultez les logs)",
            )

    @staticmethod
    def _decode_secret_data(data: Optional[Dict[str, str]]) -> Dict[str, str]:
        """Decode a Secret's base64 ``data`` (undecodable values are skipped)."""
        decoded: Dict[str, str] = {}
        for key, value in (data or {}).items():
            try:
                decoded[key] = base64.b64decode(value).decode("utf-8")
            except (binascii.Error, ValueError, TypeError, UnicodeDecodeError):
                continue
        return decoded

    def _create_or_relabel_secret(
        self,
        namespace: str,
        manifest: Dict[str, Any],
        created: List[Tuple[str, str]],
    ) -> Dict[str, str]:
        """Create a stack secret, or reuse the existing one of the same owner.

        Returns the values the pods will actually read: the manifest's
        ``stringData`` for a new secret, the existing secret's data otherwise
        (a stack re-created under the same name after a delete that kept its
        persistent data keeps its old credentials). An existing secret that is
        not managed by LabOnDemand for the same user is a conflict (HTTP 409).
        """
        name = manifest["metadata"]["name"]
        wanted_labels = manifest["metadata"].get("labels", {}) or {}
        try:
            self.core_v1.create_namespaced_secret(namespace, manifest)
            created.append(("secret", name))
            return dict(manifest.get("stringData") or {})
        except client.exceptions.ApiException as exc:
            if exc.status != 409:
                raise
        existing = self.core_v1.read_namespaced_secret(name, namespace)
        existing_labels = (getattr(existing, "metadata", None) and existing.metadata.labels) or {}
        if existing_labels.get("managed-by") != "labondemand" or existing_labels.get(
            "user-id"
        ) != wanted_labels.get("user-id"):
            audit_logger.warning(
                "stack_secret_conflict_foreign_owner",
                extra={
                    "extra_fields": {
                        "namespace": namespace,
                        "secret": name,
                        "user_id": wanted_labels.get("user-id"),
                        "existing_owner": existing_labels.get("user-id"),
                    }
                },
            )
            raise HTTPException(
                status_code=409,
                detail=f"Un secret '{name}' existe déjà et n'appartient pas à ce lab",
            )
        values = self._decode_secret_data(getattr(existing, "data", None))
        try:
            self.core_v1.patch_namespaced_secret(
                name=name,
                namespace=namespace,
                body={"metadata": {"labels": manifest["metadata"].get("labels", {})}},
            )
        except Exception as exc:
            logger.warning(
                "stack_secret_relabel_failed",
                extra={
                    "extra_fields": {
                        "namespace": namespace,
                        "secret": name,
                        "error": str(exc),
                    }
                },
            )
        logger.info(
            "stack_secret_reused",
            extra={"extra_fields": {"namespace": namespace, "secret": name}},
        )
        return values

    def _create_pvc_or_fallback(
        self,
        namespace: str,
        manifest: Dict[str, Any],
        created: List[Tuple[str, str]],
    ) -> bool:
        """Create a PVC. Returns False when the cluster cannot provide storage
        (the caller then mounts an emptyDir); other errors, 409 included, raise."""
        name = manifest["metadata"]["name"]
        try:
            self.core_v1.create_namespaced_persistent_volume_claim(namespace, manifest)
        except client.exceptions.ApiException as exc:
            msg = (getattr(exc, "body", "") or "").lower()
            storage_unavailable = (
                exc.status in (403, 422)
                or "no persistent volumes" in msg
                or "storageclass" in msg
                or "forbidden" in msg
            )
            if exc.status == 409 or not storage_unavailable:
                raise
            logger.warning(
                "deployment_pvc_fallback_empty_dir",
                extra={
                    "extra_fields": {
                        "pvc_name": name,
                        "namespace": namespace,
                        "status": exc.status,
                        "reason": getattr(exc, "reason", None),
                    }
                },
            )
            return False
        created.append(("pvc", name))
        return True

    def _expose_via_ingress(
        self,
        namespace: str,
        ingress_name: str,
        host: str,
        service_name: str,
        service_port: int,
        labels: Dict[str, str],
        created: List[Tuple[str, str]],
    ) -> Dict[str, Any]:
        """Create (or update) the Ingress of a service; returns its public details."""
        manifest = self.create_ingress_manifest(
            ingress_name, host, service_name, service_port, labels
        )
        ingress_obj, created_flag = self._apply_ingress(namespace, manifest)
        if created_flag:
            created.append(("ingress", ingress_name))
        return {
            "name": getattr(getattr(ingress_obj, "metadata", None), "name", ingress_name),
            "host": host,
            "url": self.ingress_url(host),
            "class": settings.INGRESS_CLASS_NAME,
            "tls": bool(settings.INGRESS_TLS_SECRET),
            "created": created_flag,
        }

    def _enforce_quotas(
        self, current_user: User, namespace: str, plan: ResourcePlan
    ) -> None:
        """Application quotas (per role/override), then namespace ResourceQuotas."""
        self._assert_user_quota(
            current_user,
            planned_apps=1,
            planned_pods=plan.pods,
            planned_cpu_request_m=plan.requests_cpu_m,
            planned_memory_request_mi=plan.requests_mem_mi,
        )
        self._preflight_k8s_quota(
            namespace,
            planned_requests_cpu_m=plan.requests_cpu_m,
            planned_limits_cpu_m=plan.limits_cpu_m,
            planned_requests_mem_mi=plan.requests_mem_mi,
            planned_limits_mem_mi=plan.limits_mem_mi,
            planned_pods=plan.pods,
            planned_deployments=plan.deployments,
        )

    def _prepare_user_namespace(self, current_user: User, deployment_name: str) -> str:
        """The user's own namespace, created if needed, with baseline guard-rails."""
        namespace = build_user_namespace(current_user)
        if not ensure_namespace_exists(namespace):
            logger.error(
                "namespace_unavailable",
                extra={
                    "extra_fields": {
                        "namespace": namespace,
                        "user_id": getattr(current_user, "id", None),
                        "deployment_name": deployment_name,
                    }
                },
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Impossible d'assurer le namespace '{namespace}'. "
                    f"Vérifiez les droits RBAC et la configuration Kubernetes."
                ),
            )
        # Best-effort: logs and returns False on failure.
        ensure_namespace_baseline(namespace, self._role_value(current_user))
        return namespace

    @staticmethod
    def _validate_service_and_resources(
        service_type: str,
        cpu_request: str,
        cpu_limit: str,
        memory_request: str,
        memory_limit: str,
    ) -> None:
        valid_service_types = ["ClusterIP", "NodePort", "LoadBalancer"]
        if service_type not in valid_service_types:
            raise HTTPException(
                status_code=400,
                detail=f"Type de service invalide. Types valides: {', '.join(valid_service_types)}",
            )
        try:
            validate_resource_format(cpu_request, cpu_limit, memory_request, memory_limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ------------------------------------------------------------------
    # Creation entry point
    # ------------------------------------------------------------------

    def create_deployment(
        self,
        name: str,
        image: str,
        replicas: int,
        namespace: Optional[str],  # ignored: every lab goes to the user's namespace
        create_service: bool,
        service_port: int,
        service_target_port: int,
        service_type: str,
        deployment_type: str,
        cpu_request: str,
        cpu_limit: str,
        memory_request: str,
        memory_limit: str,
        additional_labels: Optional[Dict[str, str]],
        current_user: User,
        existing_pvc_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a lab (single deployment or multi-component stack).

        Blocking (Kubernetes + DB calls): call it from a plain ``def`` route or
        through ``asyncio.to_thread``.
        """
        name = validate_k8s_name(name)
        logger.info(
            "deployment_request_received",
            extra={
                "extra_fields": {
                    "deployment_name": name,
                    "deployment_type": deployment_type,
                    "user_id": getattr(current_user, "id", None),
                    "username": getattr(current_user, "username", None),
                    "role": getattr(getattr(current_user, "role", None), "value", None),
                    "replicas": replicas,
                    "create_service": create_service,
                }
            },
        )
        effective_namespace = self._prepare_user_namespace(current_user, name)
        self.validate_permissions(current_user, deployment_type)
        self._validate_service_and_resources(
            service_type, cpu_request, cpu_limit, memory_request, memory_limit
        )

        # From the quota check to the DB row, nothing else may change this
        # user's labs: concurrent creations (double click, class-wide spawn,
        # resume) would all pass the check against the same old usage, and a
        # concurrent lab list would insert a second row for the new lab.
        with user_lab_lock(current_user.id):
            return self._create_locked(
                name=name,
                image=image,
                replicas=replicas,
                create_service=create_service,
                service_port=service_port,
                service_target_port=service_target_port,
                service_type=service_type,
                deployment_type=deployment_type,
                cpu_request=cpu_request,
                cpu_limit=cpu_limit,
                memory_request=memory_request,
                memory_limit=memory_limit,
                additional_labels=additional_labels or {},
                current_user=current_user,
                namespace=effective_namespace,
                existing_pvc_name=existing_pvc_name,
            )

    def _create_locked(
        self,
        *,
        name: str,
        image: str,
        replicas: int,
        create_service: bool,
        service_port: int,
        service_target_port: int,
        service_type: str,
        deployment_type: str,
        cpu_request: str,
        cpu_limit: str,
        memory_request: str,
        memory_limit: str,
        additional_labels: Dict[str, str],
        current_user: User,
        namespace: str,
        existing_pvc_name: Optional[str],
    ) -> Dict[str, Any]:
        """Quota checks, Kubernetes objects and DB row (caller holds the lab lock)."""
        stack = STACK_SPECS.get(deployment_type)
        if stack is not None:
            return self._create_stack(
                stack,
                name=name,
                namespace=namespace,
                service_type=service_type,
                service_port=service_port,
                current_user=current_user,
                additional_labels=additional_labels,
            )

        return self._create_single_deployment(
            name=name,
            image=image,
            replicas=replicas,
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
            namespace=namespace,
            existing_pvc_name=existing_pvc_name,
        )

    def _create_stack(
        self,
        spec: StackSpec,
        *,
        name: str,
        namespace: str,
        service_type: str,
        service_port: Optional[int],
        current_user: User,
        additional_labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """Quota checks, stack builder, audit log and DB tracking of a stack."""
        role = self._role_value(current_user)
        plan = plan_resources(
            [component.clamp(role) for component in spec.components],
            replicas=1,
            deployments=len(spec.components),
        )
        self._enforce_quotas(current_user, namespace, plan)

        builder = getattr(self, spec.builder)
        result = builder(
            name=name,
            effective_namespace=namespace,
            service_type=service_type,
            service_port=service_port or 8080,
            current_user=current_user,
            additional_labels=additional_labels,
        )
        audit_logger.info(
            "deployment_created",
            extra={
                "extra_fields": {
                    "deployment_name": name,
                    "deployment_type": spec.deployment_type,
                    "namespace": namespace,
                    "user_id": getattr(current_user, "id", None),
                    "username": getattr(current_user, "username", None),
                    "resource_summary": list((result.get("created_objects") or {}).keys()),
                    "service_type": result.get("service_info", {}).get("type"),
                }
            },
        )
        result["deployment_db_id"] = self._track_deployment_in_db(
            user=current_user,
            name=name,
            deployment_type=spec.deployment_type,
            namespace=namespace,
            stack_name=name,
        )
        return result

    # ------------------------------------------------------------------
    # Single-deployment path
    # ------------------------------------------------------------------

    def _clamp_with_runtime_floors(
        self,
        role: str,
        config: Dict[str, Any],
        replicas: int,
        deployment_type: str,
    ) -> Dict[str, Any]:
        """Cap resources by role, then let the runtime's declared floors win.

        A lab that starts OOMKilled is worse than a pod above the role ceiling
        (e.g. Eclipse needs 2Gi); namespace ResourceQuota and the preflight
        stay the hard limits. Finally keep request <= limit so a badly tuned
        floor never yields a manifest the API server rejects.
        """
        clamped = clamp_resources_for_role(
            role,
            config["cpu_request"],
            config["cpu_limit"],
            config["memory_request"],
            config["memory_limit"],
            replicas,
        )
        for res_key, floor in (config.get("floors") or {}).items():
            if not floor:
                continue
            to_units = (
                parse_memory_to_mi if res_key.startswith("memory") else parse_cpu_to_millicores
            )
            if to_units(clamped[res_key]) >= to_units(floor):
                continue
            audit_logger.warning(
                "resource_floor_over_role_ceiling",
                extra={
                    "extra_fields": {
                        "resource": res_key,
                        "role_ceiling": clamped[res_key],
                        "runtime_floor": floor,
                        "deployment_type": deployment_type,
                        "role": role,
                    }
                },
            )
            clamped[res_key] = floor

        for req_key, lim_key in (
            ("cpu_request", "cpu_limit"),
            ("memory_request", "memory_limit"),
        ):
            clamped[lim_key] = max_resource(clamped[lim_key], clamped[req_key])
        return clamped

    @staticmethod
    def _runtime_extras(deployment_type: str, name: str) -> _RuntimeExtras:
        """Ports, environment and generated credentials specific to a runtime."""
        secret_name = f"{name}-secret"
        if deployment_type in VNC_DESKTOP_TYPES:
            vnc_password = secrets.token_urlsafe(18)
            view_only_password = secrets.token_urlsafe(18)
            extra_container_ports = [
                {"containerPort": 5901, "name": "vnc"},
                {"containerPort": 4901, "name": "audio"},
            ]
            additional_service_ports = [
                {"name": "vnc", "port": 5901, "targetPort": 5901, "protocol": "TCP"},
                {"name": "audio", "port": 4901, "targetPort": 4901, "protocol": "TCP"},
            ]
            # Eclipse Java EE: expose Tomcat (8080) to test the web app
            # deployed from Eclipse (WTP) from any browser.
            if deployment_type == "eclipse":
                extra_container_ports.append({"containerPort": 8080, "name": "tomcat"})
                additional_service_ports.append(
                    {"name": "tomcat", "port": 8080, "targetPort": 8080, "protocol": "TCP"}
                )
            return _RuntimeExtras(
                main_port_name="novnc",
                extra_container_ports=extra_container_ports,
                additional_service_ports=additional_service_ports,
                env=[
                    {"name": "SECURE_CONNECTION", "value": "false"},
                    {"name": "KASM_ENABLE_SSL", "value": "false"},
                    {"name": "KASM_NO_VNC_SSL", "value": "1"},
                    {"name": "KASM_REQUIRE_SSL", "value": "false"},
                ],
                env_from=[{"secretRef": {"name": secret_name}}],
                secret_name=secret_name,
                secret_data={
                    "VNC_USERNAME": "kasm_user",
                    "VNC_PW": vnc_password,
                    "VNC_VIEW_ONLY_PW": view_only_password,
                },
                credentials={
                    deployment_type: {
                        "username": "kasm_user",
                        "password": vnc_password,
                        "view_only_password": view_only_password,
                    }
                },
            )
        if deployment_type == "jupyter":
            jupyter_token = secrets.token_urlsafe(24)
            return _RuntimeExtras(
                env=[{"name": "JUPYTER_ENABLE_LAB", "value": "yes"}],
                env_from=[{"secretRef": {"name": secret_name}}],
                command=["/bin/sh", "-lc"],
                args=[
                    (
                        "exec start-notebook.sh "
                        "--ServerApp.token=\"${JUPYTER_TOKEN}\" "
                        "--ServerApp.password='' "
                        "--NotebookApp.token=\"${JUPYTER_TOKEN}\" "
                        "--NotebookApp.password=''"
                    )
                ],
                secret_name=secret_name,
                secret_data={"JUPYTER_TOKEN": jupyter_token},
                credentials={"jupyter": {"token": jupyter_token}},
            )
        if deployment_type == "vscode":
            password = secrets.token_urlsafe(18)
            return _RuntimeExtras(
                env_from=[{"secretRef": {"name": secret_name}}],
                secret_name=secret_name,
                secret_data={"CODE_SERVER_USERNAME": "coder", "PASSWORD": password},
                credentials={"vscode": {"username": "coder", "password": password}},
            )
        return _RuntimeExtras()

    def _create_credentials_secret(
        self,
        namespace: str,
        name: str,
        labels: Dict[str, str],
        extras: _RuntimeExtras,
        created: List[Tuple[str, str]],
    ) -> None:
        secret_labels = {**labels, "app": name, "stack-name": name, "component": "credentials"}
        self.core_v1.create_namespaced_secret(
            namespace,
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": extras.secret_name, "labels": secret_labels},
                "type": "Opaque",
                "stringData": extras.secret_data,
            },
        )
        created.append(("secret", extras.secret_name))

    def _relabel_reused_pvc(
        self,
        namespace: str,
        pvc: client.V1PersistentVolumeClaim,
        deployment_type: str,
        app_name: str,
        current_user: User,
    ) -> None:
        """Point a reused PVC at the new app (best-effort)."""
        merged_labels = dict(pvc.metadata.labels or {})
        merged_labels.update(
            {
                "managed-by": "labondemand",
                "user-id": str(current_user.id),
                "user-role": current_user.role.value,
                "app-type": deployment_type,
                "labondemand/last-bound-app": app_name,
            }
        )
        try:
            self.core_v1.patch_namespaced_persistent_volume_claim(
                pvc.metadata.name, namespace, {"metadata": {"labels": merged_labels}}
            )
        except Exception as exc:
            logger.warning(
                "deployment_pvc_label_update_failed",
                extra={
                    "extra_fields": {
                        "pvc_name": pvc.metadata.name,
                        "namespace": namespace,
                        "deployment": app_name,
                        "error": str(exc),
                    }
                },
            )

    def _attach_persistent_home(
        self,
        manifest: Dict[str, Any],
        *,
        deployment_type: str,
        name: str,
        labels: Dict[str, str],
        image: str,
        namespace: str,
        current_user: User,
        existing_pvc_name: Optional[str],
        created: List[Tuple[str, str]],
    ) -> None:
        """Mount the runtime's work directory on a PVC (emptyDir fallback)."""
        mount_path = PERSISTENT_HOME_MOUNTS.get(deployment_type)
        if not mount_path:
            return

        pvc_name = f"{name}-pvc"
        use_pvc = True
        reused_pvc: Optional[client.V1PersistentVolumeClaim] = None
        if existing_pvc_name:
            reused_pvc = self._validate_existing_pvc(namespace, existing_pvc_name, current_user)
        else:
            pvc_manifest = {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {
                    "name": pvc_name,
                    "labels": {**labels, "labondemand/last-bound-app": name},
                },
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": settings.LAB_PVC_SIZE}},
                },
            }
            try:
                use_pvc = self._create_pvc_or_fallback(namespace, pvc_manifest, created)
            except client.exceptions.ApiException as exc:
                if exc.status != 409:
                    raise
                # Name collision: reuse the existing PVC once ownership is checked.
                reused_pvc = self._validate_existing_pvc(namespace, pvc_name, current_user)

        if reused_pvc is not None:
            pvc_name = reused_pvc.metadata.name
            self._relabel_reused_pvc(namespace, reused_pvc, deployment_type, name, current_user)

        pod_spec = manifest["spec"]["template"]["spec"]
        pod_spec["securityContext"] = {
            **(pod_spec.get("securityContext") or {}),
            "fsGroup": 1000,
            "seccompProfile": {"type": "RuntimeDefault"},
        }
        container = pod_spec["containers"][0]
        container.setdefault("volumeMounts", []).append({"name": "data", "mountPath": mount_path})
        pod_spec["volumes"] = (
            [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_name}}]
            if use_pvc
            else [{"name": "data", "emptyDir": {}}]
        )
        # VNC desktop: the home lives on the volume. Copy the image's default
        # profile (XFCE config, wallpaper, shortcuts) on first start without
        # overwriting the student's files.
        if deployment_type in VNC_DESKTOP_TYPES:
            pod_spec["initContainers"] = [
                {
                    "name": "seed-home",
                    "image": image,
                    "command": ["/bin/sh", "-c"],
                    "args": [
                        "test -f /mnt/home/.labondemand-seeded || "
                        "(cp -R /home/lod-user/. /mnt/home/ && "
                        "touch /mnt/home/.labondemand-seeded) || true"
                    ],
                    "resources": container.get("resources", {}),
                    "volumeMounts": [{"name": "data", "mountPath": "/mnt/home"}],
                }
            ]

    def _create_service_and_ingress(
        self,
        *,
        name: str,
        deployment_type: str,
        config: Dict[str, Any],
        service_port: Optional[int],
        labels: Dict[str, str],
        extras: _RuntimeExtras,
        use_ingress: bool,
        current_user: User,
        namespace: str,
        created: List[Tuple[str, str]],
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], str]:
        """Create the lab's Service (+ Ingress). Returns (service_info,
        connection_hints, message suffix)."""
        if not config["create_service"]:
            service_info = {
                "created": False,
                "type": None,
                "port": None,
                "node_port": None,
                "ports_detail": [],
                "ingress": None,
            }
            return service_info, None, ""

        service_type = config["service_type"]
        created_service = self.core_v1.create_namespaced_service(
            namespace,
            self.create_service_manifest(
                name,
                service_port,
                config["service_target_port"],
                service_type,
                labels,
                port_name=extras.main_port_name,
                additional_ports=extras.additional_service_ports,
            ),
        )
        created.append(("service", f"{name}-service"))

        ports_details = [
            {
                "name": getattr(svc_port, "name", None),
                "protocol": getattr(svc_port, "protocol", None),
                "port": getattr(svc_port, "port", None),
                "target_port": getattr(svc_port, "target_port", None),
                "node_port": getattr(svc_port, "node_port", None),
            }
            for svc_port in (getattr(getattr(created_service, "spec", None), "ports", []) or [])
        ]

        node_port = None
        if service_type in ["NodePort", "LoadBalancer"]:
            # First NodePort, kept for backward compatibility.
            node_port = next(
                (d["node_port"] for d in ports_details if d.get("node_port")), None
            )
            ports_desc = ", ".join(_format_port(d) for d in ports_details)
            message = (
                f". Service {name}-service créé (type: {service_type}, ports: {ports_desc})"
            )
        else:
            message = f". Service {name}-service créé (type: {service_type}, port: {service_port})"

        ingress_details: Optional[Dict[str, Any]] = None
        if use_ingress:
            ingress_details = self._expose_via_ingress(
                namespace,
                f"{name}-ingress",
                self._build_ingress_host(name, current_user),
                f"{name}-service",
                service_port,
                labels,
                created,
            )
            message += f" Ingress disponible sur {ingress_details['url']}"

        if deployment_type == "vscode" and service_type == "NodePort" and node_port:
            message += (
                f" VS Code Online sera accessible à l'adresse "
                f"http://<IP_DU_NOEUD>:{node_port}/"
            )

        connection_hints = None
        if deployment_type in VNC_DESKTOP_TYPES:
            connection_hints = _vnc_connection_hints(
                deployment_type,
                ports_details,
                config["service_target_port"],
                extras.credentials,
            )

        service_info = {
            "created": True,
            "type": service_type,
            "port": service_port,
            "node_port": node_port,
            "ports_detail": ports_details,
            "ingress": ingress_details,
        }
        return service_info, connection_hints, message

    def _create_single_deployment(
        self,
        *,
        name: str,
        image: str,
        replicas: int,
        create_service: bool,
        service_port: Optional[int],
        service_target_port: int,
        service_type: str,
        deployment_type: str,
        cpu_request: str,
        cpu_limit: str,
        memory_request: str,
        memory_limit: str,
        additional_labels: Dict[str, str],
        current_user: User,
        namespace: str,
        existing_pvc_name: Optional[str],
    ) -> Dict[str, Any]:
        config = self.apply_deployment_config(
            deployment_type,
            image,
            cpu_request,
            cpu_limit,
            memory_request,
            memory_limit,
            service_target_port,
            create_service,
            service_type,
            session_owner=current_user,
        )

        use_ingress = self._should_attach_ingress(deployment_type)
        if use_ingress and config["create_service"]:
            if config["service_type"] in ["NodePort", "LoadBalancer"]:
                config["service_type"] = "ClusterIP"
            if service_port is None:
                service_port = config.get("service_target_port") or 80

        # Runtimes configured in DB or known ones expose their target port as is.
        if config.get("has_runtime_config") or deployment_type in {
            "vscode",
            "jupyter",
            *VNC_DESKTOP_TYPES,
        }:
            service_port = config["service_target_port"]

        role = self._role_value(current_user)
        clamped = self._clamp_with_runtime_floors(role, config, replicas, deployment_type)
        self._enforce_quotas(
            current_user,
            namespace,
            plan_resources([clamped], replicas=int(clamped["replicas"]), deployments=1),
        )

        labels = create_labondemand_labels(
            deployment_type,
            str(current_user.id),
            current_user.role.value,
            additional_labels,
        )
        extras = self._runtime_extras(deployment_type, name)

        created: List[Tuple[str, str]] = []
        with self._rollback_on_failure(
            namespace,
            created,
            "Erreur lors de la création",
            "Erreur lors de la création",
            deployment_name=name,
            deployment_type=deployment_type,
        ):
            if extras.secret_name and extras.secret_data:
                self._create_credentials_secret(namespace, name, labels, extras, created)

            deployment_manifest = self.create_deployment_manifest(
                name,
                config["image"],
                clamped["replicas"],
                clamped["cpu_request"],
                clamped["cpu_limit"],
                clamped["memory_request"],
                clamped["memory_limit"],
                config["service_target_port"],
                labels,
                main_port_name=extras.main_port_name,
                extra_container_ports=extras.extra_container_ports,
                env_vars=extras.env,
                env_from=extras.env_from,
                command=extras.command,
                args=extras.args,
            )
            self._attach_persistent_home(
                deployment_manifest,
                deployment_type=deployment_type,
                name=name,
                labels=labels,
                image=config["image"],
                namespace=namespace,
                current_user=current_user,
                existing_pvc_name=existing_pvc_name,
                created=created,
            )
            self.apps_v1.create_namespaced_deployment(namespace, deployment_manifest)
            created.append(("deployment", name))

            service_info, connection_hints, service_message = self._create_service_and_ingress(
                name=name,
                deployment_type=deployment_type,
                config=config,
                service_port=service_port,
                labels=labels,
                extras=extras,
                use_ingress=use_ingress,
                current_user=current_user,
                namespace=namespace,
                created=created,
            )

            result: Dict[str, Any] = {
                "message": (
                    f"Deployment {name} créé dans le namespace {namespace} "
                    f"avec l'image {config['image']} "
                    f"(CPU: {config['cpu_request']}-{config['cpu_limit']}, "
                    f"RAM: {config['memory_request']}-{config['memory_limit']})"
                    + service_message
                ),
                "deployment_type": deployment_type,
                "namespace": namespace,
                "resources": {
                    "cpu_request": clamped["cpu_request"],
                    "cpu_limit": clamped["cpu_limit"],
                    "memory_request": clamped["memory_request"],
                    "memory_limit": clamped["memory_limit"],
                },
                "service_info": service_info,
                "connection_hints": connection_hints,
            }
            if extras.credentials:
                result["credentials"] = extras.credentials

            audit_logger.info(
                "deployment_created",
                extra={
                    "extra_fields": {
                        "deployment_name": name,
                        "deployment_type": deployment_type,
                        "namespace": namespace,
                        "user_id": getattr(current_user, "id", None),
                        "username": getattr(current_user, "username", None),
                        "service_type": service_info["type"],
                        "node_port": service_info["node_port"],
                        "replicas": clamped["replicas"],
                    }
                },
            )
            result["deployment_db_id"] = self._track_deployment_in_db(
                user=current_user,
                name=name,
                deployment_type=deployment_type,
                namespace=namespace,
                cpu_requested=clamped["cpu_request"],
                mem_requested=clamped["memory_request"],
            )
            return result

    def cleanup_user_namespace(self, user_id: int) -> Dict[str, Any]:
        """Supprime le namespace Kubernetes d'un utilisateur et toutes ses ressources.

        Appelé automatiquement lors de la suppression d'un compte (``DELETE /users/{id}``).
        Les erreurs K8s non critiques (namespace introuvable, etc.) sont journalisées
        mais n'interrompent pas la suppression de l'utilisateur en base.

        Returns:
            Dict avec ``deleted`` (bool), ``namespace`` (str) et ``error`` (str ou None).
        """
        from .k8s_utils import build_user_namespace

        namespace = build_user_namespace(user_id)
        try:
            core_v1 = client.CoreV1Api()
            core_v1.delete_namespace(namespace)
            logger.info(
                "user_namespace_deleted",
                extra={"extra_fields": {"user_id": user_id, "namespace": namespace}},
            )
            audit_logger.info(
                "user_namespace_cleanup",
                extra={
                    "extra_fields": {
                        "user_id": user_id,
                        "namespace": namespace,
                        "status": "deleted",
                    }
                },
            )
            return {"deleted": True, "namespace": namespace, "error": None}
        except client.exceptions.ApiException as e:
            if e.status == 404:
                logger.info(
                    "user_namespace_not_found",
                    extra={
                        "extra_fields": {"user_id": user_id, "namespace": namespace}
                    },
                )
                return {
                    "deleted": False,
                    "namespace": namespace,
                    "error": "namespace_not_found",
                }
            logger.warning(
                "user_namespace_delete_failed",
                extra={
                    "extra_fields": {
                        "user_id": user_id,
                        "namespace": namespace,
                        "error": str(e),
                    }
                },
            )
            return {"deleted": False, "namespace": namespace, "error": str(e)}
        except Exception as exc:
            logger.warning(
                "user_namespace_delete_error",
                extra={
                    "extra_fields": {
                        "user_id": user_id,
                        "namespace": namespace,
                        "error": str(exc),
                    }
                },
            )
            return {"deleted": False, "namespace": namespace, "error": str(exc)}


# Instance globale du service
deployment_service = DeploymentService()
