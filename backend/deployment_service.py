"""
Service de déploiement Kubernetes
Principe KISS : une classe focalisée sur la création de déploiements
"""
import datetime
import logging
import re
from typing import Dict, Any, Optional, List, Tuple
from fastapi import HTTPException
from kubernetes import client
from sqlalchemy.orm import Session

from .models import User, UserRole, RuntimeConfig
from .config import settings
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
from .templates import DeploymentConfig

logger = logging.getLogger("labondemand.deployment")
audit_logger = logging.getLogger("labondemand.audit")

PAUSE_FLAG_ANNOTATION = "labondemand.io/paused"
PAUSE_REPLICAS_ANNOTATION = "labondemand.io/paused-replicas"
PAUSE_BY_ANNOTATION = "labondemand.io/paused-by"
PAUSE_AT_ANNOTATION = "labondemand.io/paused-at"

from .services.wordpress_deploy import WordPressDeployMixin
from .services.mysql_deploy import MySQLDeployMixin
from .services.lamp_deploy import LAMPDeployMixin


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

    def _build_ingress_host(self, base_name: str, current_user: User, component: Optional[str] = None) -> str:
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
            annotations.setdefault("traefik.ingress.kubernetes.io/router.entrypoints", entrypoints)
        elif controller_hint.startswith("nginx") and settings.INGRESS_TLS_SECRET and settings.INGRESS_FORCE_TLS_REDIRECT:
            annotations.setdefault("nginx.ingress.kubernetes.io/force-ssl-redirect", "true")
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
            created_ingress = self.networking_v1.create_namespaced_ingress(namespace, ingress_manifest)
            return created_ingress, True
        except client.exceptions.ApiException as exc:
            if exc.status == 409:
                # Ressource existante: effectuer un patch pour mettre à jour labels/spec
                name = ingress_manifest["metadata"]["name"]
                body = {
                    "metadata": {
                        "labels": ingress_manifest["metadata"].get("labels", {}),
                        "annotations": ingress_manifest["metadata"].get("annotations", {}),
                    },
                    "spec": ingress_manifest["spec"],
                }
                updated = self.networking_v1.patch_namespaced_ingress(name=name, namespace=namespace, body=body)
                return updated, False
            raise
    def validate_permissions(self, user: User, deployment_type: str):
        """Valide les permissions selon le rôle utilisateur"""
        if user.role == UserRole.student:
            try:
                from .database import SessionLocal
                with SessionLocal() as db:
                    rc = db.query(RuntimeConfig).filter(RuntimeConfig.key == deployment_type, RuntimeConfig.active == True).first()
                    if not rc or not rc.allowed_for_students:
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
                            detail="Type non autorisé pour les étudiants"
                        )
            except HTTPException:
                raise
            except Exception:
                # Fallback si DB inaccessible: limiter à un set sûr côté étudiant
                if deployment_type not in {"jupyter", "vscode", "wordpress", "mysql", "netbeans"}:
                    logger.warning(
                        "deployment_permission_denied_fallback",
                        extra={
                            "extra_fields": {
                                "user_id": getattr(user, "id", None),
                                "deployment_type": deployment_type,
                                "role": getattr(getattr(user, "role", None), "value", None),
                            }
                        },
                    )
                    raise HTTPException(status_code=403, detail="Type non autorisé pour les étudiants")
    
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
    ) -> Dict[str, Any]:
        """
        Applique la configuration selon le type de déploiement
        """
        # 1) Chercher une RuntimeConfig en base
        config_db = None
        try:
            # On ne possède pas de session ici; lecture best-effort via client Python K8s context
            # => Passer par une requête naïve SQL n'est pas souhaitable; on utilisera le fallback si indisponible
            # L'appelant (router) ne fournit pas de DB session ici. Pour garder KISS, on lit via ORM avec une Session locale si disponible.
            # On évite l’overengineering; on se contente d’un get via SQLAlchemy SessionLocal si importable.
            from .database import SessionLocal  # import local pour éviter cycle
            with SessionLocal() as db:
                config_db = db.query(RuntimeConfig).filter(RuntimeConfig.key == deployment_type, RuntimeConfig.active == True).first()
        except Exception:
            config_db = None

        # 2) Fallback statique si pas de config DB
        config = {}
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
        else:
            config = DeploymentConfig.get_config(deployment_type)
        
        if config:
            # Appliquer les valeurs par défaut
            image = config.get("image", image)
            service_target_port = config.get("target_port", service_target_port)
            create_service = True
            service_type = config.get("service_type", service_type)
            
            # Appliquer les minimums de ressources
            cpu_request = max_resource(cpu_request, config.get("min_cpu_request", cpu_request))
            memory_request = max_resource(memory_request, config.get("min_memory_request", memory_request))
            cpu_limit = max_resource(cpu_limit, config.get("min_cpu_limit", cpu_limit))
            memory_limit = max_resource(memory_limit, config.get("min_memory_limit", memory_limit))
        
        return {
            "image": image,
            "cpu_request": cpu_request,
            "cpu_limit": cpu_limit,
            "memory_request": memory_request,
            "memory_limit": memory_limit,
            "service_target_port": service_target_port,
            "create_service": create_service,
            "service_type": service_type,
            "has_runtime_config": bool(config_db)
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
            dep_list = apps.list_namespaced_deployment(ns, label_selector="managed-by=labondemand")
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Mesure d'usage indisponible (K8s: {e})")

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

            tmpl_spec = getattr(getattr(getattr(dep, "spec", None), "template", None), "spec", None)
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
                    mem_s = getattr(req, "get", lambda x: None)("memory") if req else None
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
        limits = get_role_limits(str(role_val))
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
            # Si on ne peut pas lire les quotas, on ne bloque pas ici (RBAC restreint) -> laisser K8s refuser plus tard si besoin
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
            hard = (getattr(getattr(rq, "status", None), "hard", None) or {})
            used = (getattr(getattr(rq, "status", None), "used", None) or {})

            def chk(key: str, used_val: int, hard_val: int, add_val: int, unit: str) -> None:
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
            raise HTTPException(status_code=403, detail="Namespace non autorisé pour cet utilisateur")

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
            raise HTTPException(status_code=403, detail="Déploiement hors périmètre LabOnDemand")

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
            raise HTTPException(status_code=403, detail="Déploiement sans propriétaire identifié")

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
        if current_user.role == UserRole.student:
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
                        namespace, label_selector=self._stack_label_selector(stack_name, current_user)
                    ).items
                    or []
                )
        except client.exceptions.ApiException as exc:
            if exc.status != 404:
                raise

        if not deployments:
            stack_selector = self._stack_label_selector(name, current_user)
            stack_candidates = self.apps_v1.list_namespaced_deployment(namespace, label_selector=stack_selector)
            if stack_candidates.items:
                deployments = stack_candidates.items
                stack_name = name
                stack_mode = True
            else:
                app_selector = f"app={name}"
                app_candidates = self.apps_v1.list_namespaced_deployment(namespace, label_selector=app_selector)
                if app_candidates.items:
                    deployments = app_candidates.items
                else:
                    raise HTTPException(status_code=404, detail="Déploiement non trouvé")

        filtered: List[client.V1Deployment] = []
        for dep in deployments:
            labels = dep.metadata.labels or {}
            self._assert_deployment_access(labels, current_user, namespace, dep.metadata.name)
            filtered.append(dep)

        deployments = filtered
        if not deployments:
            raise HTTPException(status_code=404, detail="Déploiement introuvable")

        base_labels = deployments[0].metadata.labels or {}
        app_type = base_labels.get("app-type", "custom")
        display_name = stack_name or base_labels.get("stack-name") or deployments[0].metadata.name

        return {
            "deployments": deployments,
            "stack_mode": stack_mode,
            "stack_name": stack_name,
            "display_name": display_name,
            "namespace": namespace,
            "app_type": app_type,
        }

    def describe_component_lifecycle(self, deployment: client.V1Deployment) -> Dict[str, Any]:
        annotations = dict(getattr(deployment.metadata, "annotations", {}) or {})
        requested = int(getattr(getattr(deployment, "spec", None), "replicas", 0) or 0)
        ready = int(getattr(getattr(deployment, "status", None), "ready_replicas", 0) or 0)
        available = int(getattr(getattr(deployment, "status", None), "available_replicas", 0) or ready)
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
            return {"state": "unknown", "paused": False, "paused_components": 0, "total_components": 0}

        total = len(components)
        paused_count = sum(1 for comp in components if comp.get("state") == "paused")
        running_count = sum(1 for comp in components if comp.get("state") == "running")

        if paused_count == total:
            state = "paused"
        elif running_count == total:
            state = "running"
        else:
            state = "mixed"

        paused_at_values = [comp.get("paused_at") for comp in components if comp.get("paused_at")]
        paused_by_values = [comp.get("paused_by") for comp in components if comp.get("paused_by")]

        return {
            "state": state,
            "paused": paused_count == total and total > 0,
            "paused_components": paused_count,
            "total_components": total,
            "paused_at": max(paused_at_values) if paused_at_values else None,
            "paused_by": paused_by_values[0] if paused_by_values else None,
        }

    async def pause_application(self, namespace: str, name: str, current_user: User) -> Dict[str, Any]:
        resolved = self._resolve_target_deployments(namespace, name, current_user)
        components_payload: List[Dict[str, Any]] = []
        iso_now = datetime.datetime.utcnow().isoformat() + "Z"
        paused_by = getattr(current_user, "username", str(getattr(current_user, "id", "unknown")))

        for deployment in resolved["deployments"]:
            lifecycle_before = self.describe_component_lifecycle(deployment)
            if lifecycle_before["state"] == "paused":
                components_payload.append({
                    "name": deployment.metadata.name,
                    "already_paused": True,
                    "lifecycle": lifecycle_before,
                })
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
            lifecycle_after = self.describe_component_lifecycle(updated)
            components_payload.append({
                "name": deployment.metadata.name,
                "previous_replicas": previous_replicas,
                "lifecycle": lifecycle_after,
            })

        lifecycle_summary = self.summarize_lifecycle([c["lifecycle"] for c in components_payload])

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

        return {
            "action": "paused",
            "name": resolved["display_name"],
            "namespace": resolved["namespace"],
            "stack": resolved["stack_name"],
            "components": components_payload,
            "lifecycle": lifecycle_summary,
            "message": "Application mise en pause. Les pods seront libérés dans quelques secondes.",
        }

    async def resume_application(self, namespace: str, name: str, current_user: User) -> Dict[str, Any]:
        resolved = self._resolve_target_deployments(namespace, name, current_user)
        components_payload: List[Dict[str, Any]] = []

        # Calculer l'impact quota avant de relancer les pods
        planned_pods = 0
        planned_cpu_m = 0
        planned_mem_mi = 0
        planned_limits_cpu_m = 0
        planned_limits_mem_mi = 0

        for deployment in resolved["deployments"]:
            lifecycle = self.describe_component_lifecycle(deployment)
            target_replicas = lifecycle.get("resume_replicas") or 1
            planned_pods += target_replicas

            tmpl_spec = getattr(getattr(deployment.spec, "template", None), "spec", None)
            containers = []
            if tmpl_spec and getattr(tmpl_spec, "containers", None):
                containers = tmpl_spec.containers
            for container in containers:
                resources = getattr(container, "resources", None)
                requests = getattr(resources, "requests", None) if resources else None
                limits = getattr(resources, "limits", None) if resources else None
                cpu_req = None
                mem_req = None
                cpu_lim = None
                mem_lim = None
                if isinstance(requests, dict):
                    cpu_req = requests.get("cpu")
                    mem_req = requests.get("memory")
                if isinstance(limits, dict):
                    cpu_lim = limits.get("cpu")
                    mem_lim = limits.get("memory")
                if cpu_req:
                    planned_cpu_m += parse_cpu_to_millicores(str(cpu_req)) * target_replicas
                if mem_req:
                    planned_mem_mi += parse_memory_to_mi(str(mem_req)) * target_replicas
                if cpu_lim:
                    planned_limits_cpu_m += parse_cpu_to_millicores(str(cpu_lim)) * target_replicas
                if mem_lim:
                    planned_limits_mem_mi += parse_memory_to_mi(str(mem_lim)) * target_replicas

        if planned_pods == 0:
            planned_pods = len(resolved["deployments"])

        self._assert_user_quota(
            current_user=current_user,
            planned_apps=1,
            planned_pods=planned_pods,
            planned_cpu_request_m=int(planned_cpu_m),
            planned_memory_request_mi=int(planned_mem_mi),
        )
        try:
            self._preflight_k8s_quota(
                resolved["namespace"],
                planned_requests_cpu_m=int(planned_cpu_m),
                planned_limits_cpu_m=int(planned_limits_cpu_m or planned_cpu_m),
                planned_requests_mem_mi=int(planned_mem_mi),
                planned_limits_mem_mi=int(planned_limits_mem_mi or planned_mem_mi),
                planned_pods=planned_pods,
                planned_deployments=len(resolved["deployments"]),
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning(
                "resume_quota_preflight_failed",
                extra={
                    "extra_fields": {
                        "namespace": resolved["namespace"],
                        "error": str(exc),
                    }
                },
            )

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
            lifecycle_after = self.describe_component_lifecycle(updated)
            components_payload.append({
                "name": deployment.metadata.name,
                "target_replicas": target_replicas,
                "lifecycle": lifecycle_after,
            })

        lifecycle_summary = self.summarize_lifecycle([c["lifecycle"] for c in components_payload])

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
            pvc = self.core_v1.read_namespaced_persistent_volume_claim(pvc_name, namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                raise HTTPException(status_code=404, detail=f"Volume persistant '{pvc_name}' introuvable")
            raise

        labels = pvc.metadata.labels or {}
        if current_user.role == UserRole.student:
            if labels.get("managed-by") != "labondemand" or labels.get("user-id") != str(current_user.id):
                raise HTTPException(status_code=403, detail="Accès refusé à ce volume")

        return pvc

    def get_user_quota_summary(self, user: User) -> Dict[str, Any]:
        """Retourne un résumé des quotas: role, usage courant, limites et restants."""
        role_val = getattr(user.role, "value", str(user.role))
        limits = get_role_limits(str(role_val))
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

        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": name,
                "labels": labels,
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
            "metadata": {
                "name": f"{name}-service",
                "labels": {
                    "app": name,
                    **labels
                }
            },
            "spec": {
                "selector": {"app": name},
                "type": service_type,
                "ports": ports
            }
        }
    
    async def create_deployment(
        self,
        name: str,
        image: str,
        replicas: int,
        namespace: Optional[str],  # ignoré volontairement, conservation pour compat
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
        storage_mode: str = "auto",
        existing_pvc_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Méthode principale pour créer un déploiement
        """
        # Validation et formatage
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
        # Politique d'isolation: namespace par utilisateur, aucun choix client
        effective_namespace = build_user_namespace(current_user)

        # S'assurer que le namespace existe (idempotent)
        ns_ok = await ensure_namespace_exists(effective_namespace)
        if not ns_ok:
            logger.error(
                "namespace_unavailable",
                extra={
                    "extra_fields": {
                        "namespace": effective_namespace,
                        "user_id": getattr(current_user, "id", None),
                        "deployment_name": name,
                    }
                },
            )
            # Échec explicite si on ne peut pas assurer le namespace
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Impossible d'assurer le namespace '{effective_namespace}'. "
                    f"Vérifiez les droits RBAC et la configuration Kubernetes."
                ),
            )
        # Appliquer des garde-fous de base (idempotent, best-effort)
        try:
            role_val = getattr(current_user.role, "value", str(current_user.role))
            ensure_namespace_baseline(effective_namespace, str(role_val))
        except Exception:
            pass

        # Valider les permissions
        self.validate_permissions(current_user, deployment_type)

    # Valider les types de service
        valid_service_types = ["ClusterIP", "NodePort", "LoadBalancer"]
        if service_type not in valid_service_types:
            raise HTTPException(
                status_code=400,
                detail=f"Type de service invalide. Types valides: {', '.join(valid_service_types)}"
            )

        # Valider les formats de ressources
        try:
            validate_resource_format(cpu_request, cpu_limit, memory_request, memory_limit)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Cas spécial: application multi-composants (WordPress)
        if deployment_type == "wordpress":
            # Estimation des ressources planifiées (2 pods: DB + WP)
            role_val = getattr(current_user.role, "value", str(current_user.role))
            db_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
            wp_res = clamp_resources_for_role(str(role_val), "250m", "1000m", "512Mi", "1Gi", 1)
            planned_cpu_m = int(parse_cpu_to_millicores(db_res["cpu_request"])) + int(parse_cpu_to_millicores(wp_res["cpu_request"]))
            planned_mem_mi = int(parse_memory_to_mi(db_res["memory_request"])) + int(parse_memory_to_mi(wp_res["memory_request"]))
            self._assert_user_quota(current_user, planned_apps=1, planned_pods=2, planned_cpu_request_m=planned_cpu_m, planned_memory_request_mi=planned_mem_mi)

            # Préflight contre ResourceQuota Kubernetes (requests+limits et pods/deployments)
            planned_limits_cpu_m = int(parse_cpu_to_millicores(db_res["cpu_limit"])) + int(parse_cpu_to_millicores(wp_res["cpu_limit"]))
            planned_limits_mem_mi = int(parse_memory_to_mi(db_res["memory_limit"])) + int(parse_memory_to_mi(wp_res["memory_limit"]))
            self._preflight_k8s_quota(
                effective_namespace,
                planned_requests_cpu_m=planned_cpu_m,
                planned_limits_cpu_m=planned_limits_cpu_m,
                planned_requests_mem_mi=planned_mem_mi,
                planned_limits_mem_mi=planned_limits_mem_mi,
                planned_pods=2,
                planned_deployments=2,
            )
            result = await self._create_wordpress_stack(
                name=name,
                effective_namespace=effective_namespace,
                service_type=service_type,
                service_port=service_port or 8080,
                current_user=current_user,
                additional_labels=additional_labels or {},
            )
            audit_logger.info(
                "deployment_created",
                extra={
                    "extra_fields": {
                        "deployment_name": name,
                        "deployment_type": "wordpress",
                        "namespace": effective_namespace,
                        "user_id": getattr(current_user, "id", None),
                        "username": getattr(current_user, "username", None),
                        "resource_summary": list((result.get("created_objects") or {}).keys()),
                        "service_type": result.get("service_info", {}).get("type"),
                    }
                },
            )
            return result

        # Cas spécial: stack MySQL + phpMyAdmin (DB interne + UI exposée)
        if deployment_type == "mysql":
            role_val = getattr(current_user.role, "value", str(current_user.role))
            # Estimation des ressources planifiées (2 pods: MySQL + phpMyAdmin)
            db_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
            pma_res = clamp_resources_for_role(str(role_val), "150m", "300m", "128Mi", "256Mi", 1)
            planned_cpu_m = int(parse_cpu_to_millicores(db_res["cpu_request"])) + int(parse_cpu_to_millicores(pma_res["cpu_request"]))
            planned_mem_mi = int(parse_memory_to_mi(db_res["memory_request"])) + int(parse_memory_to_mi(pma_res["memory_request"]))
            self._assert_user_quota(current_user, planned_apps=1, planned_pods=2, planned_cpu_request_m=planned_cpu_m, planned_memory_request_mi=planned_mem_mi)

            planned_limits_cpu_m = int(parse_cpu_to_millicores(db_res["cpu_limit"])) + int(parse_cpu_to_millicores(pma_res["cpu_limit"]))
            planned_limits_mem_mi = int(parse_memory_to_mi(db_res["memory_limit"])) + int(parse_memory_to_mi(pma_res["memory_limit"]))
            self._preflight_k8s_quota(
                effective_namespace,
                planned_requests_cpu_m=planned_cpu_m,
                planned_limits_cpu_m=planned_limits_cpu_m,
                planned_requests_mem_mi=planned_mem_mi,
                planned_limits_mem_mi=planned_limits_mem_mi,
                planned_pods=2,
                planned_deployments=2,
            )

            result = await self._create_mysql_pma_stack(
                name=name,
                effective_namespace=effective_namespace,
                service_type=service_type,
                service_port=service_port or 8080,
                current_user=current_user,
                additional_labels=additional_labels or {},
            )
            audit_logger.info(
                "deployment_created",
                extra={
                    "extra_fields": {
                        "deployment_name": name,
                        "deployment_type": "mysql",
                        "namespace": effective_namespace,
                        "user_id": getattr(current_user, "id", None),
                        "username": getattr(current_user, "username", None),
                        "resource_summary": list((result.get("created_objects") or {}).keys()),
                        "service_type": result.get("service_info", {}).get("type"),
                    }
                },
            )
            return result

        # Cas spécial: stack LAMP (Apache+PHP, MySQL, phpMyAdmin)
        if deployment_type == "lamp":
            role_val = getattr(current_user.role, "value", str(current_user.role))
            # 3 pods: web + db + pma
            web_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
            db_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
            pma_res = clamp_resources_for_role(str(role_val), "150m", "300m", "128Mi", "256Mi", 1)

            planned_cpu_m = int(parse_cpu_to_millicores(web_res["cpu_request"])) + int(parse_cpu_to_millicores(db_res["cpu_request"])) + int(parse_cpu_to_millicores(pma_res["cpu_request"]))
            planned_mem_mi = int(parse_memory_to_mi(web_res["memory_request"])) + int(parse_memory_to_mi(db_res["memory_request"])) + int(parse_memory_to_mi(pma_res["memory_request"]))
            self._assert_user_quota(current_user, planned_apps=1, planned_pods=3, planned_cpu_request_m=planned_cpu_m, planned_memory_request_mi=planned_mem_mi)

            planned_limits_cpu_m = int(parse_cpu_to_millicores(web_res["cpu_limit"])) + int(parse_cpu_to_millicores(db_res["cpu_limit"])) + int(parse_cpu_to_millicores(pma_res["cpu_limit"]))
            planned_limits_mem_mi = int(parse_memory_to_mi(web_res["memory_limit"])) + int(parse_memory_to_mi(db_res["memory_limit"])) + int(parse_memory_to_mi(pma_res["memory_limit"]))
            self._preflight_k8s_quota(
                effective_namespace,
                planned_requests_cpu_m=planned_cpu_m,
                planned_limits_cpu_m=planned_limits_cpu_m,
                planned_requests_mem_mi=planned_mem_mi,
                planned_limits_mem_mi=planned_limits_mem_mi,
                planned_pods=3,
                planned_deployments=3,
            )

            result = await self._create_lamp_stack(
                name=name,
                effective_namespace=effective_namespace,
                service_type=service_type,
                service_port=service_port or 8080,
                current_user=current_user,
                additional_labels=additional_labels or {},
            )
            audit_logger.info(
                "deployment_created",
                extra={
                    "extra_fields": {
                        "deployment_name": name,
                        "deployment_type": "lamp",
                        "namespace": effective_namespace,
                        "user_id": getattr(current_user, "id", None),
                        "username": getattr(current_user, "username", None),
                        "resource_summary": list((result.get("created_objects") or {}).keys()),
                        "service_type": result.get("service_info", {}).get("type"),
                    }
                },
            )
            return result

        # Appliquer la configuration du déploiement
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
        )

        use_ingress = self._should_attach_ingress(deployment_type)
        if use_ingress and config["create_service"]:
            if config["service_type"] in ["NodePort", "LoadBalancer"]:
                config["service_type"] = "ClusterIP"
            if service_port is None:
                service_port = config.get("service_target_port") or 80

        # Auto-détermination des ports pour les runtimes configurés (DB) ou connus (fallback):
        # - Si has_runtime_config est vrai OU runtime est vscode/jupyter, alors service_port = target_port
        if config.get("has_runtime_config") or deployment_type in {"vscode", "jupyter", "netbeans"}:
            service_port = config["service_target_port"]

        # Plafonner selon le rôle (sécurité)
        role_val = getattr(current_user.role, "value", str(current_user.role))
        clamped = clamp_resources_for_role(
            str(role_val),
            config["cpu_request"],
            config["cpu_limit"],
            config["memory_request"],
            config["memory_limit"],
            replicas,
        )

        # Vérification des quotas logiques (apps, CPU requests, RAM requests, pods) avant création
        planned_cpu_m = int(parse_cpu_to_millicores(clamped["cpu_request"]) * clamped["replicas"])
        planned_mem_mi = int(parse_memory_to_mi(clamped["memory_request"]) * clamped["replicas"])
        self._assert_user_quota(
            current_user,
            planned_apps=1,
            planned_pods=int(clamped["replicas"]),
            planned_cpu_request_m=planned_cpu_m,
            planned_memory_request_mi=planned_mem_mi,
        )

        # Vérifier aussi les ResourceQuota Kubernetes du namespace
        planned_limits_cpu_m = int(parse_cpu_to_millicores(clamped["cpu_limit"]) * clamped["replicas"])
        planned_limits_mem_mi = int(parse_memory_to_mi(clamped["memory_limit"]) * clamped["replicas"])
        self._preflight_k8s_quota(
            effective_namespace,
            planned_requests_cpu_m=planned_cpu_m,
            planned_limits_cpu_m=planned_limits_cpu_m,
            planned_requests_mem_mi=planned_mem_mi,
            planned_limits_mem_mi=planned_limits_mem_mi,
            planned_pods=int(clamped["replicas"]),
            planned_deployments=1,
        )

        # Créer les labels
        if additional_labels is None:
            additional_labels = {}

        labels = create_labondemand_labels(
            deployment_type,
            str(current_user.id),
            current_user.role.value,
            additional_labels,
        )

        main_port_name: Optional[str] = None
        extra_container_ports: Optional[List[Dict[str, Any]]] = None
        additional_service_ports: Optional[List[Dict[str, Any]]] = None
        container_env: Optional[List[Dict[str, Any]]] = None
        if deployment_type == "netbeans":
            main_port_name = "novnc"
            extra_container_ports = [
                {"containerPort": 5901, "name": "vnc"},
                {"containerPort": 4901, "name": "audio"},
            ]
            additional_service_ports = [
                {"name": "vnc", "port": 5901, "targetPort": 5901, "protocol": "TCP"},
                {"name": "audio", "port": 4901, "targetPort": 4901, "protocol": "TCP"},
            ]
            container_env = [
                {"name": "SECURE_CONNECTION", "value": "false"},
                {"name": "KASM_ENABLE_SSL", "value": "false"},
                {"name": "KASM_NO_VNC_SSL", "value": "1"},
                {"name": "KASM_REQUIRE_SSL", "value": "false"},
                {"name": "VNC_PW", "value": "password"},
                {"name": "VNC_VIEW_ONLY_PW", "value": "password"},
            ]

        try:
            # Créer le déploiement
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
                main_port_name=main_port_name,
                extra_container_ports=extra_container_ports,
                env_vars=container_env,
            )

            # Persistance best-effort pour VSCode/Jupyter
            if deployment_type in {"vscode", "jupyter"}:
                pvc_name = f"{name}-pvc"
                use_pvc = True
                pvc_obj: Optional[client.V1PersistentVolumeClaim] = None
                # Permettre la réutilisation d'un PVC existant lorsqu'un nom identique est fourni
                if existing_pvc_name:
                    pvc_obj = self._validate_existing_pvc(effective_namespace, existing_pvc_name, current_user)
                    pvc_name = pvc_obj.metadata.name
                else:
                    pvc_labels = dict(labels)
                    pvc_labels["labondemand/last-bound-app"] = name
                    pvc_manifest = {
                        "apiVersion": "v1",
                        "kind": "PersistentVolumeClaim",
                        "metadata": {"name": pvc_name, "labels": pvc_labels},
                        "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "2Gi"}}},
                    }
                    try:
                        self.core_v1.create_namespaced_persistent_volume_claim(effective_namespace, pvc_manifest)
                    except client.exceptions.ApiException as e:
                        msg = (getattr(e, "body", "") or "").lower()
                        if e.status == 409:
                            # Collision de nom: réutiliser le PVC existant après validation
                            pvc_obj = self._validate_existing_pvc(effective_namespace, pvc_name, current_user)
                            pvc_name = pvc_obj.metadata.name
                        elif e.status in (403, 422) or "no persistent volumes" in msg or "storageclass" in msg or "forbidden" in msg:
                            use_pvc = False
                        else:
                            raise

                if use_pvc:
                    if pvc_obj is None:
                        try:
                            pvc_obj = self.core_v1.read_namespaced_persistent_volume_claim(pvc_name, effective_namespace)
                        except Exception:
                            pvc_obj = None

                    if pvc_obj is not None:
                        merged_labels = dict(pvc_obj.metadata.labels or {})
                        merged_labels.update({
                            "managed-by": "labondemand",
                            "user-id": str(current_user.id),
                            "user-role": current_user.role.value,
                            "app-type": deployment_type,
                            "labondemand/last-bound-app": name,
                        })
                        try:
                            self.core_v1.patch_namespaced_persistent_volume_claim(
                                pvc_name,
                                effective_namespace,
                                {"metadata": {"labels": merged_labels}},
                            )
                        except Exception:
                            logger.warning(
                                "deployment_pvc_label_update_failed",
                                extra={
                                    "extra_fields": {
                                        "pvc_name": pvc_name,
                                        "namespace": effective_namespace,
                                        "deployment": name,
                                    }
                                },
                            )

                # Monter sur chemin de travail usuel
                mount_path = "/home/jovyan/work" if deployment_type == "jupyter" else "/home/coder/project"
                pod_spec = deployment_manifest["spec"]["template"]["spec"]
                # Pod security context pour permissions
                pod_spec["securityContext"] = {**(pod_spec.get("securityContext") or {}), "fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}}
                # VolumeMounts conteneur
                container = pod_spec["containers"][0]
                container.setdefault("volumeMounts", []).append({"name": "data", "mountPath": mount_path})
                # Volumes pod
                pod_spec["volumes"] = [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_name}}] if use_pvc else [{"name": "data", "emptyDir": {}}]

            self.apps_v1.create_namespaced_deployment(effective_namespace, deployment_manifest)

            result_message = (
                f"Deployment {name} créé dans le namespace {effective_namespace} "
                f"avec l'image {config['image']} "
                f"(CPU: {config['cpu_request']}-{config['cpu_limit']}, "
                f"RAM: {config['memory_request']}-{config['memory_limit']})"
            )

            # Créer le service si nécessaire
            node_port = None
            ports_details: List[Dict[str, Any]] = []
            connection_hints: Optional[Dict[str, Any]] = None
            ingress_details: Optional[Dict[str, Any]] = None
            if config["create_service"]:
                service_manifest = self.create_service_manifest(
                    name,
                    service_port,
                    config["service_target_port"],
                    config["service_type"],
                    labels,
                    port_name=main_port_name,
                    additional_ports=additional_service_ports,
                )

                created_service = self.core_v1.create_namespaced_service(
                    effective_namespace, service_manifest
                )

                svc_ports = list(getattr(getattr(created_service, "spec", None), "ports", []) or [])
                for svc_port in svc_ports:
                    ports_details.append({
                        "name": getattr(svc_port, "name", None),
                        "protocol": getattr(svc_port, "protocol", None),
                        "port": getattr(svc_port, "port", None),
                        "target_port": getattr(svc_port, "target_port", None),
                        "node_port": getattr(svc_port, "node_port", None),
                    })

                if config["service_type"] in ["NodePort", "LoadBalancer"]:
                    # Premier NodePort disponible pour compat rétro
                    for detail in ports_details:
                        if detail.get("node_port"):
                            node_port = detail["node_port"]
                            break

                    def _format_port(detail: Dict[str, Any]) -> str:
                        name = detail.get("name")
                        base = f"{detail.get('port')}->{detail.get('target_port')}"
                        if detail.get("node_port"):
                            base += f" (NodePort {detail['node_port']})"
                        return f"{name}:{base}" if name else base

                    ports_desc = ", ".join(_format_port(d) for d in ports_details)
                    result_message += (
                        f". Service {name}-service créé (type: {config['service_type']}, "
                        f"ports: {ports_desc})"
                    )
                else:
                    result_message += (
                        f". Service {name}-service créé (type: {config['service_type']}, "
                        f"port: {service_port})"
                    )

                if use_ingress:
                    ingress_name = f"{name}-ingress"
                    host = self._build_ingress_host(name, current_user)
                    ingress_manifest = self.create_ingress_manifest(
                        ingress_name,
                        host,
                        f"{name}-service",
                        service_port,
                        labels,
                    )
                    ingress_obj, created_flag = self._apply_ingress(effective_namespace, ingress_manifest)
                    scheme = "https" if settings.INGRESS_TLS_SECRET else "http"
                    ingress_details = {
                        "name": getattr(getattr(ingress_obj, "metadata", None), "name", ingress_name),
                        "host": host,
                        "url": f"{scheme}://{host}{settings.INGRESS_DEFAULT_PATH}",
                        "class": settings.INGRESS_CLASS_NAME,
                        "tls": bool(settings.INGRESS_TLS_SECRET),
                        "created": created_flag,
                    }
                    result_message += f" Ingress disponible sur {ingress_details['url']}"

                # Instructions d'accès spécifiques
                if (
                    deployment_type == "vscode"
                    and config["service_type"] == "NodePort"
                    and node_port
                ):
                    result_message += (
                        f" VS Code Online sera accessible à l'adresse "
                        f"http://<IP_DU_NOEUD>:{node_port}/ (mot de passe: labondemand)"
                    )

                if deployment_type == "netbeans":
                    def _find_node_port(target_name: str, fallback_port: int) -> Optional[int]:
                        for detail in ports_details:
                            if detail.get("name") == target_name:
                                return detail.get("node_port")
                            if detail.get("target_port") == fallback_port:
                                return detail.get("node_port")
                        return None

                    connection_hints = {
                        "novnc": {
                            "description": "Bureau distant via navigateur (NoVNC)",
                            "url_template": "http://<IP_DU_NOEUD>:<NODE_PORT>",
                            "target_port": config["service_target_port"],
                            "node_port": _find_node_port("novnc", config["service_target_port"]),
                            "protocol": "http",
                            "secure": False,
                            "username": "kasm_user",
                            "password": "password",
                        },
                        "vnc": {
                            "description": "Client VNC classique (optionnel)",
                            "target_port": 5901,
                            "node_port": _find_node_port("vnc", 5901),
                            "username": "kasm_user",
                            "password": "password",
                        },
                        "audio": {
                            "description": "Flux audio (Websocket Kasm)",
                            "target_port": 4901,
                            "node_port": _find_node_port("audio", 4901),
                        },
                    }

            result = {
                "message": result_message,
                "deployment_type": deployment_type,
                "namespace": effective_namespace,
                "resources": {
                    "cpu_request": clamped["cpu_request"],
                    "cpu_limit": clamped["cpu_limit"],
                    "memory_request": clamped["memory_request"],
                    "memory_limit": clamped["memory_limit"],
                },
                "service_info": {
                    "created": config["create_service"],
                    "type": config["service_type"] if config["create_service"] else None,
                    "port": service_port if config["create_service"] else None,
                    "node_port": node_port,
                    "ports_detail": ports_details if config["create_service"] else [],
                    "ingress": ingress_details,
                },
                "connection_hints": connection_hints,
            }

            audit_logger.info(
                "deployment_created",
                extra={
                    "extra_fields": {
                        "deployment_name": name,
                        "deployment_type": deployment_type,
                        "namespace": effective_namespace,
                        "user_id": getattr(current_user, "id", None),
                        "username": getattr(current_user, "username", None),
                        "service_type": result["service_info"]["type"],
                        "node_port": node_port,
                        "replicas": clamped["replicas"],
                    }
                },
            )

            return result

        except client.exceptions.ApiException as e:
            logger.exception(
                "deployment_k8s_error",
                extra={
                    "extra_fields": {
                        "deployment_name": name,
                        "deployment_type": deployment_type,
                        "namespace": effective_namespace,
                        "status": getattr(e, "status", None),
                        "reason": getattr(e, "reason", None),
                    }
                },
            )
            raise HTTPException(
                status_code=e.status,
                detail=f"Erreur lors de la création: {e.reason} - {e.body}",
            )
        except Exception as e:
            logger.exception(
                "deployment_unexpected_error",
                extra={
                    "extra_fields": {
                        "deployment_name": name,
                        "deployment_type": deployment_type,
                        "namespace": effective_namespace,
                    }
                },
            )
            raise HTTPException(status_code=500, detail=f"Erreur lors de la création: {str(e)}")

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
                extra={"extra_fields": {"user_id": user_id, "namespace": namespace, "status": "deleted"}},
            )
            return {"deleted": True, "namespace": namespace, "error": None}
        except client.exceptions.ApiException as e:
            if e.status == 404:
                logger.info(
                    "user_namespace_not_found",
                    extra={"extra_fields": {"user_id": user_id, "namespace": namespace}},
                )
                return {"deleted": False, "namespace": namespace, "error": "namespace_not_found"}
            logger.warning(
                "user_namespace_delete_failed",
                extra={"extra_fields": {"user_id": user_id, "namespace": namespace, "error": str(e)}},
            )
            return {"deleted": False, "namespace": namespace, "error": str(e)}
        except Exception as exc:
            logger.warning(
                "user_namespace_delete_error",
                extra={"extra_fields": {"user_id": user_id, "namespace": namespace, "error": str(exc)}},
            )
            return {"deleted": False, "namespace": namespace, "error": str(exc)}


# Instance globale du service
deployment_service = DeploymentService()
