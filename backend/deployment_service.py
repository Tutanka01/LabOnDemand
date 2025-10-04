"""
Service de déploiement Kubernetes
Principe KISS : une classe focalisée sur la création de déploiements
"""
import datetime
from typing import Dict, Any, Optional
from fastapi import HTTPException
from kubernetes import client
from sqlalchemy.orm import Session

from .models import User, UserRole, RuntimeConfig
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

class DeploymentService:
    """
    Service responsable de la création et gestion des déploiements
    """
    
    def __init__(self):
        self.apps_v1 = client.AppsV1Api()
        self.core_v1 = client.CoreV1Api()
    
    def validate_permissions(self, user: User, deployment_type: str):
        """Valide les permissions selon le rôle utilisateur"""
        if user.role == UserRole.student:
            try:
                from .database import SessionLocal
                with SessionLocal() as db:
                    rc = db.query(RuntimeConfig).filter(RuntimeConfig.key == deployment_type, RuntimeConfig.active == True).first()
                    if not rc or not rc.allowed_for_students:
                        raise HTTPException(
                            status_code=403,
                            detail="Type non autorisé pour les étudiants"
                        )
            except HTTPException:
                raise
            except Exception:
                # Fallback si DB inaccessible: limiter à un set sûr côté étudiant
                if deployment_type not in {"jupyter", "vscode", "wordpress", "mysql"}:
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
            labels = getattr(dep.metadata, "labels", {}) or {}
            if labels.get("user-id") != str(user.id):
                continue
            replicas = getattr(dep.spec, "replicas", 1) or 1
            pods_used += replicas

            # Clé logique d'application: stack-name si présent, sinon label app puis nom
            gkey = labels.get("stack-name") or labels.get("app") or dep.metadata.name
            app_keys.add(gkey)

            containers = (getattr(getattr(dep.spec, "template", None), "spec", None) or {}).get("containers") if isinstance(getattr(getattr(dep.spec, "template", None), "spec", None), dict) else None
            # Certaines versions du client retournent des objets; gérons les deux cas
            tmpl_spec = getattr(getattr(dep.spec, "template", None), "spec", None)
            if hasattr(tmpl_spec, "containers"):
                containers = tmpl_spec.containers
            if not containers:
                containers = []
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

    def get_user_quota_summary(self, current_user: User) -> Dict[str, Any]:
        role_val = getattr(current_user.role, "value", str(current_user.role))
        limits = get_role_limits(str(role_val))
        usage = self._get_user_usage(current_user)
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
        labels: Dict[str, str]
    ) -> Dict[str, Any]:
        """Crée le manifeste du déploiement"""
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": name,
                "labels": labels
            },
            "spec": {
                "replicas": replicas,
                "selector": {
                    "matchLabels": {"app": name}
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": name,
                            **labels
                        }
                    },
                    "spec": {
                        "containers": [{
                            "name": name,
                            "image": image,
                            "ports": [{"containerPort": service_target_port}],
                            "resources": {
                                "requests": {
                                    "cpu": cpu_request,
                                    "memory": memory_request
                                },
                                "limits": {
                                    "cpu": cpu_limit,
                                    "memory": memory_limit
                                }
                            },
                            "livenessProbe": {
                                "httpGet": {
                                    "path": "/",
                                    "port": service_target_port
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": 10,
                                "timeoutSeconds": 5
                            },
                            "readinessProbe": {
                                "httpGet": {
                                    "path": "/",
                                    "port": service_target_port
                                },
                                "initialDelaySeconds": 5,
                                "periodSeconds": 5
                            }
                        }]
                    }
                }
            }
        }
    
    def create_service_manifest(
        self,
        name: str,
        service_port: int,
        service_target_port: int,
        service_type: str,
        labels: Dict[str, str]
    ) -> Dict[str, Any]:
        """Crée le manifeste du service"""
        port_spec = {
            "port": service_port,
            "targetPort": service_target_port,
            "protocol": "TCP"
        }
        
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
                "ports": [port_spec]
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
        current_user: User
    ) -> Dict[str, Any]:
        """
        Méthode principale pour créer un déploiement
        """
        # Validation et formatage
        name = validate_k8s_name(name)
        # Politique d'isolation: namespace par utilisateur, aucun choix client
        effective_namespace = build_user_namespace(current_user)

        # S'assurer que le namespace existe (idempotent)
        ns_ok = await ensure_namespace_exists(effective_namespace)
        if not ns_ok:
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
            return await self._create_wordpress_stack(
                name=name,
                effective_namespace=effective_namespace,
                service_type=service_type,
                service_port=service_port or 8080,
                current_user=current_user,
                additional_labels=additional_labels or {},
            )

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

            return await self._create_mysql_pma_stack(
                name=name,
                effective_namespace=effective_namespace,
                service_type=service_type,
                service_port=service_port or 8080,
                current_user=current_user,
                additional_labels=additional_labels or {},
            )

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

            return await self._create_lamp_stack(
                name=name,
                effective_namespace=effective_namespace,
                service_type=service_type,
                service_port=service_port or 8080,
                current_user=current_user,
                additional_labels=additional_labels or {},
            )

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

        # Auto-détermination des ports pour les runtimes configurés (DB) ou connus (fallback):
        # - Si has_runtime_config est vrai OU runtime est vscode/jupyter, alors service_port = target_port
        if config.get("has_runtime_config") or deployment_type in {"vscode", "jupyter"}:
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
            )

            # Persistance best-effort pour VSCode/Jupyter
            if deployment_type in {"vscode", "jupyter"}:
                pvc_name = f"{name}-pvc"
                pvc_manifest = {
                    "apiVersion": "v1",
                    "kind": "PersistentVolumeClaim",
                    "metadata": {"name": pvc_name, "labels": labels},
                    "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "2Gi"}}},
                }
                use_pvc = True
                try:
                    self.core_v1.create_namespaced_persistent_volume_claim(effective_namespace, pvc_manifest)
                except client.exceptions.ApiException as e:
                    msg = (getattr(e, "body", "") or "").lower()
                    if e.status in (403, 422) or "no persistent volumes" in msg or "storageclass" in msg or "forbidden" in msg:
                        use_pvc = False
                    else:
                        raise

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
            if config["create_service"]:
                service_manifest = self.create_service_manifest(
                    name,
                    service_port,
                    config["service_target_port"],
                    config["service_type"],
                    labels,
                )

                created_service = self.core_v1.create_namespaced_service(
                    effective_namespace, service_manifest
                )

                if config["service_type"] in ["NodePort", "LoadBalancer"]:
                    node_port = created_service.spec.ports[0].node_port
                    result_message += (
                        f". Service {name}-service créé (type: {config['service_type']}, "
                        f"port: {service_port}, NodePort: {node_port})"
                    )
                else:
                    result_message += (
                        f". Service {name}-service créé (type: {config['service_type']}, "
                        f"port: {service_port})"
                    )

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

            return {
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
                },
            }

        except client.exceptions.ApiException as e:
            raise HTTPException(
                status_code=e.status,
                detail=f"Erreur lors de la création: {e.reason} - {e.body}",
            )

    async def _create_wordpress_stack(
        self,
        name: str,
        effective_namespace: str,
        service_type: str,
        service_port: int,
        current_user: User,
        additional_labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """Crée une stack WordPress + MariaDB isolée pour l'utilisateur.
        Composants:
          - Secret (mots de passe générés)
          - PVC pour DB
          - Service + Deployment MariaDB
          - Service + Deployment WordPress (bitnami)
        """
        import secrets
        import base64

        # Noms dérivés
        wp_name = name
        db_name = f"{name}-mariadb"
        svc_wp = f"{wp_name}-service"
        svc_db = f"{db_name}-service"
        pvc_db = f"{db_name}-pvc"
        secret_name = f"{name}-secret"

        # Labels communs + regroupement par stack
        labels_base = create_labondemand_labels(
            "wordpress", str(current_user.id), current_user.role.value, additional_labels
        )
        labels_wp = {**labels_base, "stack-name": name, "component": "wordpress"}
        labels_db = {**labels_base, "stack-name": name, "component": "database"}

        # Générer des mots de passe/identifiants
        db_user = "wp_user"
        db_pass = secrets.token_urlsafe(16)
        db_root = secrets.token_urlsafe(18)
        wp_admin_user = "admin"
        wp_admin_pass = secrets.token_urlsafe(18)

        # Secret (stringData pour lisibilité)
        secret_manifest = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": secret_name, "labels": labels_wp},
            "type": "Opaque",
            "stringData": {
                "MARIADB_ROOT_PASSWORD": db_root,
                "MARIADB_USER": db_user,
                "MARIADB_PASSWORD": db_pass,
                "MARIADB_DATABASE": "wordpress",
                "WORDPRESS_DATABASE_USER": db_user,
                "WORDPRESS_DATABASE_PASSWORD": db_pass,
                "WORDPRESS_DATABASE_NAME": "wordpress",
                "WORDPRESS_USERNAME": wp_admin_user,
                "WORDPRESS_PASSWORD": wp_admin_pass,
                "WORDPRESS_EMAIL": "admin@example.local",
            },
        }

        # PVC pour la DB (peut échouer si pas de StorageClass par défaut)
        pvc_manifest = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": pvc_db, "labels": labels_db},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "1Gi"}},
            },
        }

        # Service DB
        svc_db_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": svc_db, "labels": {"app": db_name, **labels_db}},
            "spec": {
                "type": "ClusterIP",
                "ports": [{"port": 3306, "targetPort": 3306}],
                "selector": {"app": db_name},
            },
        }

        # Déterminer les ressources selon rôle
        role_val = getattr(current_user.role, "value", str(current_user.role))
        db_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
        wp_res = clamp_resources_for_role(str(role_val), "250m", "1000m", "512Mi", "1Gi", 1)

        # Deployment DB (Bitnami MariaDB)
        dep_db_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": db_name, "labels": labels_db},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": db_name}},
                "template": {
                    "metadata": {"labels": {"app": db_name, **labels_db}},
                    "spec": {
                        "securityContext": {
                            "fsGroup": 1001,
                            "seccompProfile": {"type": "RuntimeDefault"}
                        },
                        "containers": [
                            {
                                "name": "mariadb",
                                "image": "bitnamilegacy/mariadb:12.0.2-debian-12-r0",
                                "envFrom": [{"secretRef": {"name": secret_name}}],
                                "ports": [{"containerPort": 3306}],
                                "resources": {
                                    "requests": {"cpu": db_res["cpu_request"], "memory": db_res["memory_request"]},
                                    "limits": {"cpu": db_res["cpu_limit"], "memory": db_res["memory_limit"]},
                                },
                                "securityContext": {
                                    "runAsUser": 1001,
                                    "runAsNonRoot": True,
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]}
                                },
                                "livenessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 30, "periodSeconds": 10},
                                "readinessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 10, "periodSeconds": 5},
                                "volumeMounts": [
                                    {"name": "data", "mountPath": "/bitnami/mariadb"}
                                ],
                            }
                        ],
                        "volumes": [  # par défaut: PVC; pourra être remplacé par emptyDir si pas de StorageClass
                            {"name": "data", "persistentVolumeClaim": {"claimName": pvc_db}}
                        ],
                    },
                },
            },
        }

        # Service WordPress
        svc_wp_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": svc_wp, "labels": {"app": wp_name, **labels_wp}},
            "spec": {
                "type": service_type,
                "ports": [{"port": service_port, "targetPort": 8080}],
                "selector": {"app": wp_name},
            },
        }

        # Deployment WordPress (Bitnami WordPress, listen 8080)
        dep_wp_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": wp_name, "labels": labels_wp},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": wp_name}},
                "template": {
                    "metadata": {"labels": {"app": wp_name, **labels_wp}},
                    "spec": {
                        "securityContext": {
                            "fsGroup": 1001,
                            "seccompProfile": {"type": "RuntimeDefault"}
                        },
                        "containers": [
                            {
                                "name": "wordpress",
                                "image": "bitnamilegacy/wordpress:6.8.2-debian-12-r5",
                                "env": [
                                    {"name": "WORDPRESS_ENABLE_HTTPS", "value": "no"},
                                    {"name": "APACHE_HTTP_PORT_NUMBER", "value": "8080"},
                                    {"name": "WORDPRESS_DATABASE_HOST", "value": svc_db},
                                    {"name": "WORDPRESS_DATABASE_PORT_NUMBER", "value": "3306"}
                                ],
                                "envFrom": [
                                    {"secretRef": {"name": secret_name}}
                                ],
                                "ports": [{"containerPort": 8080}],
                                "resources": {
                                    "requests": {"cpu": wp_res["cpu_request"], "memory": wp_res["memory_request"]},
                                    "limits": {"cpu": wp_res["cpu_limit"], "memory": wp_res["memory_limit"]},
                                },
                                "securityContext": {
                                    "runAsUser": 1001,
                                    "runAsNonRoot": True,
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]}
                                },
                                "readinessProbe": {
                                    "httpGet": {"path": "/", "port": 8080},
                                    "initialDelaySeconds": 10,
                                    "periodSeconds": 5,
                                },
                                "livenessProbe": {
                                    "httpGet": {"path": "/", "port": 8080},
                                    "initialDelaySeconds": 30,
                                    "periodSeconds": 10,
                                },
                                "volumeMounts": [
                                    {"name": "wp-content", "mountPath": "/bitnami/wordpress"}
                                ],
                            }
                        ],
                        "volumes": [
                            {"name": "wp-content", "emptyDir": {}}
                        ],
                    },
                },
            },
        }

        try:
            # Créer les ressources dans un ordre logique
            # Secret: rendre idempotent. Si déjà existant (409), ne pas écraser les données (pour rester cohérent avec un PVC existant),
            # mais patcher les labels afin qu'il soit bien rattaché à la stack et découvrable.
            try:
                self.core_v1.create_namespaced_secret(effective_namespace, secret_manifest)
            except client.exceptions.ApiException as e:
                if e.status == 409:  # AlreadyExists
                    try:
                        self.core_v1.patch_namespaced_secret(
                            name=secret_manifest["metadata"]["name"],
                            namespace=effective_namespace,
                            body={"metadata": {"labels": secret_manifest["metadata"].get("labels", {})}},
                        )
                    except Exception:
                        # En dernier recours, ignorer; on utilisera le secret existant tel quel
                        pass
                else:
                    raise

            # Essayer de créer le PVC; fallback emptyDir si impossible (ex: pas de StorageClass par défaut, RBAC restreint)
            use_pvc = True
            try:
                self.core_v1.create_namespaced_persistent_volume_claim(effective_namespace, pvc_manifest)
            except client.exceptions.ApiException as e:
                msg = (getattr(e, "body", "") or "").lower()
                if e.status in (403, 422) or "no persistent volumes" in msg or "storageclass" in msg or "forbidden" in msg:
                    # Fallback sans persistance
                    use_pvc = False
                else:
                    raise

            self.core_v1.create_namespaced_service(effective_namespace, svc_db_manifest)

            # Adapter le volume de la DB si pas de PVC disponible
            if not use_pvc:
                dep_db_manifest["spec"]["template"]["spec"]["volumes"] = [
                    {"name": "data", "emptyDir": {}}
                ]

            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_db_manifest)
            created_wp_svc = self.core_v1.create_namespaced_service(effective_namespace, svc_wp_manifest)
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_wp_manifest)

            # Vérification rapide: s'assurer que les Deployments existent bien
            try:
                apps_v1 = client.AppsV1Api()
                lbl = f"managed-by=labondemand,stack-name={name},user-id={current_user.id}"
                _lst = apps_v1.list_namespaced_deployment(effective_namespace, label_selector=lbl)
                if not (_lst.items or []):
                    raise HTTPException(status_code=500, detail="Stack WordPress créée partiellement: aucun Deployment trouvé juste après la création")
            except HTTPException:
                raise
            except Exception:
                # Non bloquant: si lister échoue, on continue mais on retournera les noms créés
                pass

            node_port = None
            if service_type in ["NodePort", "LoadBalancer"]:
                node_port = created_wp_svc.spec.ports[0].node_port

            msg = (
                f"Stack WordPress créée: DB={db_name}, WP={wp_name} dans {effective_namespace}. "
                f"Admin: {wp_admin_user}/{wp_admin_pass}. DB user: {db_user}/{db_pass}."
            )

            return {
                "message": msg,
                "deployment_type": "wordpress",
                "namespace": effective_namespace,
                "service_info": {
                    "created": True,
                    "type": service_type,
                    "port": service_port,
                    "node_port": node_port,
                },
                "created_objects": {
                    "secret": secret_name,
                    "pvc": pvc_db,
                    "services": [svc_db, svc_wp],
                    "deployments": [db_name, wp_name],
                },
                "credentials": {
                    "wordpress": {"username": wp_admin_user, "password": wp_admin_pass},
                    "database": {
                        "host": svc_db,
                        "port": 3306,
                        "username": db_user,
                        "password": db_pass,
                        "database": "wordpress",
                    },
                },
            }
        except client.exceptions.ApiException as e:
            raise HTTPException(status_code=e.status or 500, detail=f"Erreur WordPress: {e.reason} - {e.body}")
        except Exception as e:
            # Garde-fou générique pour éviter un 200 silencieux
            raise HTTPException(status_code=500, detail=f"Erreur WordPress inattendue: {e}")

    async def _create_mysql_pma_stack(
        self,
        name: str,
        effective_namespace: str,
        service_type: str,
        service_port: int,
        current_user: User,
        additional_labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """Crée une stack MySQL + phpMyAdmin:
          - Secret (mots de passe/identifiants)
          - PVC pour MySQL
          - Service + Deployment MySQL (ClusterIP)
          - Service + Deployment phpMyAdmin (exposé)
        """
        import secrets

        db_name = f"{name}-mysql"
        pma_name = f"{name}-phpmyadmin"
        svc_db = f"{db_name}-service"
        svc_pma = f"{pma_name}-service"
        pvc_db = f"{db_name}-pvc"
        secret_name = f"{name}-db-secret"

        # Labels et stack-name
        labels_base = create_labondemand_labels(
            "mysql", str(current_user.id), current_user.role.value, additional_labels
        )
        labels_db = {**labels_base, "stack-name": name, "component": "database"}
        labels_pma = {**labels_base, "stack-name": name, "component": "phpmyadmin"}

        # Credentials
        db_user = "student"
        db_pass = secrets.token_urlsafe(16)
        db_root = secrets.token_urlsafe(18)
        db_default = "studentdb"

        secret_manifest = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": secret_name, "labels": labels_db},
            "type": "Opaque",
            "stringData": {
                "MYSQL_ROOT_PASSWORD": db_root,
                "MYSQL_USER": db_user,
                "MYSQL_PASSWORD": db_pass,
                "MYSQL_DATABASE": db_default,
            },
        }

        pvc_manifest = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": pvc_db, "labels": labels_db},
            "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}},
        }

        svc_db_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": svc_db, "labels": {"app": db_name, **labels_db}},
            "spec": {"type": "ClusterIP", "ports": [{"port": 3306, "targetPort": 3306}], "selector": {"app": db_name}},
        }

        # Ressources
        role_val = getattr(current_user.role, "value", str(current_user.role))
        db_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
        pma_res = clamp_resources_for_role(str(role_val), "150m", "300m", "128Mi", "256Mi", 1)

        dep_db_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": db_name, "labels": labels_db},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": db_name}},
                "template": {
                    "metadata": {"labels": {"app": db_name, **labels_db}},
                    "spec": {
                        "securityContext": {"fsGroup": 999, "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [
                            {
                                "name": "mysql",
                                "image": "mysql:9",
                                "envFrom": [{"secretRef": {"name": secret_name}}],
                                "ports": [{"containerPort": 3306}],
                                "resources": {
                                    "requests": {"cpu": db_res["cpu_request"], "memory": db_res["memory_request"]},
                                    "limits": {"cpu": db_res["cpu_limit"], "memory": db_res["memory_limit"]},
                                },
                                "securityContext": {
                                    "runAsUser": 999,
                                    "runAsNonRoot": True,
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"]},
                                },
                                "livenessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 30, "periodSeconds": 10},
                                "readinessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 10, "periodSeconds": 5},
                                "volumeMounts": [{"name": "data", "mountPath": "/var/lib/mysql"}],
                            }
                        ],
                        "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_db}}],
                    },
                },
            },
        }

        # phpMyAdmin écoute sur 80
        svc_pma_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": svc_pma, "labels": {"app": pma_name, **labels_pma}},
            "spec": {
                "type": service_type,
                "ports": [{"port": service_port, "targetPort": 80}],
                "selector": {"app": pma_name},
            },
        }

        dep_pma_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": pma_name, "labels": labels_pma},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": pma_name}},
                "template": {
                    "metadata": {"labels": {"app": pma_name, **labels_pma}},
                    "spec": {
                        "containers": [
                            {
                                "name": "phpmyadmin",
                                "image": "phpmyadmin:latest",
                                "env": [
                                    {"name": "PMA_HOST", "value": svc_db},
                                    {"name": "PMA_USER", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_USER"}}},
                                    {"name": "PMA_PASSWORD", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_PASSWORD"}}},
                                ],
                                "ports": [{"containerPort": 80}],
                                "resources": {
                                    "requests": {"cpu": pma_res["cpu_request"], "memory": pma_res["memory_request"]},
                                    "limits": {"cpu": pma_res["cpu_limit"], "memory": pma_res["memory_limit"]},
                                },
                                "readinessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 10, "periodSeconds": 5},
                                "livenessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 30, "periodSeconds": 10},
                            }
                        ],
                    },
                },
            },
        }

        try:
            # Secret MySQL: idem, idempotent
            try:
                self.core_v1.create_namespaced_secret(effective_namespace, secret_manifest)
            except client.exceptions.ApiException as e:
                if e.status == 409:
                    try:
                        self.core_v1.patch_namespaced_secret(
                            name=secret_manifest["metadata"]["name"],
                            namespace=effective_namespace,
                            body={"metadata": {"labels": secret_manifest["metadata"].get("labels", {})}},
                        )
                    except Exception:
                        pass
                else:
                    raise
            use_pvc = True
            try:
                self.core_v1.create_namespaced_persistent_volume_claim(effective_namespace, pvc_manifest)
            except client.exceptions.ApiException as e:
                msg = (getattr(e, "body", "") or "").lower()
                if e.status in (403, 422) or "no persistent volumes" in msg or "storageclass" in msg or "forbidden" in msg:
                    use_pvc = False
                else:
                    raise

            self.core_v1.create_namespaced_service(effective_namespace, svc_db_manifest)
            if not use_pvc:
                dep_db_manifest["spec"]["template"]["spec"]["volumes"] = [{"name": "data", "emptyDir": {}}]
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_db_manifest)

            created_pma_svc = self.core_v1.create_namespaced_service(effective_namespace, svc_pma_manifest)
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_pma_manifest)

            node_port = None
            if service_type in ["NodePort", "LoadBalancer"]:
                node_port = created_pma_svc.spec.ports[0].node_port

            msg = (
                f"Stack MySQL+phpMyAdmin créée dans {effective_namespace}. "
                f"phpMyAdmin exposé sur port {service_port} (NodePort={node_port}). "
                f"DB user={db_user}, database={db_default}."
            )

            return {
                "message": msg,
                "deployment_type": "mysql",
                "namespace": effective_namespace,
                "service_info": {"created": True, "type": service_type, "port": service_port, "node_port": node_port},
                "created_objects": {
                    "secret": secret_name,
                    "pvc": pvc_db,
                    "services": [svc_db, svc_pma],
                    "deployments": [db_name, pma_name],
                },
                "credentials": {
                    "database": {"host": svc_db, "port": 3306, "username": db_user, "password": db_pass, "database": db_default},
                    "phpmyadmin": {"url_hint": "http://<NODE_IP>:<NODE_PORT>/"},
                },
            }
        except client.exceptions.ApiException as e:
            raise HTTPException(status_code=e.status or 500, detail=f"Erreur MySQL/phpMyAdmin: {e.reason} - {e.body}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur MySQL/phpMyAdmin inattendue: {e}")

    async def _create_lamp_stack(
        self,
        name: str,
        effective_namespace: str,
        service_type: str,
        service_port: int,
        current_user: User,
        additional_labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """Crée une stack LAMP complète (Apache+PHP, MySQL, phpMyAdmin).
        Composants:
          - Secret (mots de passe MySQL)
          - PVC pour MySQL
          - Service + Deployment MySQL (ClusterIP)
          - Service + Deployment phpMyAdmin (exposé port 80 via NodePort/LoadBalancer)
          - Service + Deployment Web (Apache+PHP) exposé en NodePort (8080 -> 80)
        """
        import secrets

        web_name = f"{name}-web"
        db_name = f"{name}-mysql"
        pma_name = f"{name}-phpmyadmin"
        svc_web = f"{web_name}-service"
        svc_db = f"{db_name}-service"
        svc_pma = f"{pma_name}-service"
        pvc_db = f"{db_name}-pvc"
        secret_name = f"{name}-db-secret"

        # Labels et stack-name
        labels_base = create_labondemand_labels("lamp", str(current_user.id), current_user.role.value, additional_labels)
        labels_web = {**labels_base, "stack-name": name, "component": "web"}
        labels_db = {**labels_base, "stack-name": name, "component": "database"}
        labels_pma = {**labels_base, "stack-name": name, "component": "phpmyadmin"}

        # Credentials MySQL
        db_user = "appuser"
        db_pass = secrets.token_urlsafe(16)
        db_root = secrets.token_urlsafe(18)
        db_default = "appdb"

        secret_manifest = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": secret_name, "labels": labels_db},
            "type": "Opaque",
            "stringData": {
                "MYSQL_ROOT_PASSWORD": db_root,
                "MYSQL_USER": db_user,
                "MYSQL_PASSWORD": db_pass,
                "MYSQL_DATABASE": db_default,
            },
        }

        pvc_manifest = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": pvc_db, "labels": labels_db},
            "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}},
        }

        # Services
        svc_db_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": svc_db, "labels": {"app": db_name, **labels_db}},
            "spec": {"type": "ClusterIP", "ports": [{"port": 3306, "targetPort": 3306}], "selector": {"app": db_name}},
        }

        svc_web_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": svc_web, "labels": {"app": web_name, **labels_web}},
            "spec": {"type": service_type, "ports": [{"port": service_port, "targetPort": 80}], "selector": {"app": web_name}},
        }

        svc_pma_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": svc_pma, "labels": {"app": pma_name, **labels_pma}},
            "spec": {"type": service_type, "ports": [{"port": 8081, "targetPort": 80}], "selector": {"app": pma_name}},
        }

        # Ressources par rôle
        role_val = getattr(current_user.role, "value", str(current_user.role))
        web_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
        db_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
        pma_res = clamp_resources_for_role(str(role_val), "150m", "300m", "128Mi", "256Mi", 1)

        # Déploiements
        dep_db_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": db_name, "labels": labels_db},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": db_name}},
                "template": {
                    "metadata": {"labels": {"app": db_name, **labels_db}},
                    "spec": {
                        "securityContext": {"fsGroup": 999, "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [
                            {
                                "name": "mysql",
                                "image": "mysql:9",
                                "envFrom": [{"secretRef": {"name": secret_name}}],
                                "ports": [{"containerPort": 3306}],
                                "resources": {
                                    "requests": {"cpu": db_res["cpu_request"], "memory": db_res["memory_request"]},
                                    "limits": {"cpu": db_res["cpu_limit"], "memory": db_res["memory_limit"]},
                                },
                                "securityContext": {"runAsUser": 999, "runAsNonRoot": True, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                                "livenessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 30, "periodSeconds": 10},
                                "readinessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 10, "periodSeconds": 5},
                                "volumeMounts": [{"name": "data", "mountPath": "/var/lib/mysql"}],
                            }
                        ],
                        "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_db}}],
                    },
                },
            },
        }

        dep_web_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": web_name, "labels": labels_web},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": web_name}},
                "template": {
                    "metadata": {"labels": {"app": web_name, **labels_web}},
                    "spec": {
                        # Init container: prépare un index.php minimal pour éviter 403 et valider les probes
                        "initContainers": [
                            {
                                "name": "init-www",
                                "image": "busybox:1.36",
                                "command": [
                                    "sh",
                                    "-c",
                                                                        '''cat > /workdir/index.php << 'PHP'
<?php
header('Content-Type: text/html; charset=utf-8');
echo '<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>LAMP – UPPA LabOnDemand</title>
    </head>
<body style="background:#0b1220;color:#e6edf3;font-family:Arial,Helvetica,sans-serif;padding:32px">

    <div style="background:#111827;border:1px solid #243244;border-radius:12px;
                            padding:24px;max-width:820px;box-shadow:0 2px 8px rgba(0,0,0,0.3)">

        <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px">
            <img src="https://upload.wikimedia.org/wikipedia/fr/4/41/Logo_UPPA.svg" 
                     alt="UPPA Logo" style="height:64px;background:#fff;padding:6px;border-radius:8px">
            <h2 style="margin:0;color:#A6BE0B"> Ça marche ! – Stack LAMP</h2>
        </div>

        <p style="opacity:.85;font-size:15px">
            Page par défaut générée automatiquement pour <b>Université de Pau et des Pays de l’Adour</b>.
        </p>

        <p style="margin-top:12px;font-size:14px;line-height:1.5">
            Remplacez <code>/var/www/html/index.php</code> par votre application.
        </p>

        <hr style="margin:24px 0;border:0;border-top:1px solid #243244">

        <footer style="font-size:13px;color:#9ca3af">
            UPPA – Université de Pau et des Pays de l’Adour - by makhal
        </footer>

    </div>
</body>
</html>';
?>
PHP
chmod 644 /workdir/index.php
'''
                                ],
                                "volumeMounts": [{"name": "www", "mountPath": "/workdir"}]
                            }
                        ],
                        "containers": [
                            {
                                "name": "apache",
                                "image": "php:8.2-apache",
                                "env": [
                                    {"name": "DB_HOST", "value": svc_db},
                                    {"name": "DB_NAME", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_DATABASE"}}},
                                    {"name": "DB_USER", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_USER"}}},
                                    {"name": "DB_PASSWORD", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_PASSWORD"}}}
                                ],
                                "ports": [{"containerPort": 80}],
                                "resources": {
                                    "requests": {"cpu": web_res["cpu_request"], "memory": web_res["memory_request"]},
                                    "limits": {"cpu": web_res["cpu_limit"], "memory": web_res["memory_limit"]},
                                },
                                "securityContext": {
                                    "runAsUser": 33,
                                    "runAsGroup": 33,
                                    "runAsNonRoot": True,
                                    "allowPrivilegeEscalation": False,
                                    "capabilities": {"drop": ["ALL"], "add": ["NET_BIND_SERVICE"]},
                                    "seccompProfile": {"type": "RuntimeDefault"}
                                },
                                "readinessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 10, "periodSeconds": 5},
                                "livenessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 30, "periodSeconds": 10},
                                "volumeMounts": [{"name": "www", "mountPath": "/var/www/html"}],
                            }
                        ],
                        "volumes": [{"name": "www", "persistentVolumeClaim": {"claimName": f"{web_name}-pvc"}}],
                    },
                },
            },
        }

        dep_pma_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": pma_name, "labels": labels_pma},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": pma_name}},
                "template": {
                    "metadata": {"labels": {"app": pma_name, **labels_pma}},
                    "spec": {
                        "containers": [
                            {
                                "name": "phpmyadmin",
                                "image": "phpmyadmin:latest",
                                "env": [
                                    {"name": "PMA_HOST", "value": svc_db},
                                    {"name": "PMA_USER", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_USER"}}},
                                    {"name": "PMA_PASSWORD", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_PASSWORD"}}},
                                ],
                                "ports": [{"containerPort": 80}],
                                "resources": {
                                    "requests": {"cpu": pma_res["cpu_request"], "memory": pma_res["memory_request"]},
                                    "limits": {"cpu": pma_res["cpu_limit"], "memory": pma_res["memory_limit"]},
                                },
                                "readinessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 10, "periodSeconds": 5},
                                "livenessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 30, "periodSeconds": 10},
                            }
                        ],
                    },
                },
            },
        }

        try:
            # Secret idempotent
            try:
                self.core_v1.create_namespaced_secret(effective_namespace, secret_manifest)
            except client.exceptions.ApiException as e:
                if e.status == 409:
                    try:
                        self.core_v1.patch_namespaced_secret(
                            name=secret_manifest["metadata"]["name"],
                            namespace=effective_namespace,
                            body={"metadata": {"labels": secret_manifest["metadata"].get("labels", {})}},
                        )
                    except Exception:
                        pass
                else:
                    raise

            # PVC best-effort
            use_pvc = True
            try:
                self.core_v1.create_namespaced_persistent_volume_claim(effective_namespace, pvc_manifest)
            except client.exceptions.ApiException as e:
                msg = (getattr(e, "body", "") or "").lower()
                if e.status in (403, 422) or "no persistent volumes" in msg or "storageclass" in msg or "forbidden" in msg:
                    use_pvc = False
                else:
                    raise

            # Services
            self.core_v1.create_namespaced_service(effective_namespace, svc_db_manifest)
            created_web_svc = self.core_v1.create_namespaced_service(effective_namespace, svc_web_manifest)
            created_pma_svc = self.core_v1.create_namespaced_service(effective_namespace, svc_pma_manifest)

            # Volumes DB
            if not use_pvc:
                dep_db_manifest["spec"]["template"]["spec"]["volumes"] = [{"name": "data", "emptyDir": {}}]

            # Déploiements
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_db_manifest)
            # PVC best-effort pour le web LAMP
            pvc_web = f"{web_name}-pvc"
            pvc_web_manifest = {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": pvc_web, "labels": labels_web},
                "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}},
            }
            use_web_pvc = True
            try:
                self.core_v1.create_namespaced_persistent_volume_claim(effective_namespace, pvc_web_manifest)
            except client.exceptions.ApiException as e:
                msg = (getattr(e, "body", "") or "").lower()
                if e.status in (403, 422) or "no persistent volumes" in msg or "storageclass" in msg or "forbidden" in msg:
                    use_web_pvc = False
                else:
                    raise
            if not use_web_pvc:
                dep_web_manifest["spec"]["template"]["spec"]["volumes"] = [{"name": "www", "emptyDir": {}}]
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_web_manifest)
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_pma_manifest)

            node_port_web = None
            node_port_pma = None
            if service_type in ["NodePort", "LoadBalancer"]:
                try:
                    node_port_web = created_web_svc.spec.ports[0].node_port
                except Exception:
                    node_port_web = None
                try:
                    node_port_pma = created_pma_svc.spec.ports[0].node_port
                except Exception:
                    node_port_pma = None

            msg = (
                f"Stack LAMP créée: WEB={web_name} (NodePort={node_port_web}), DB={db_name}, PMA={pma_name} (NodePort={node_port_pma}) dans {effective_namespace}. "
                f"DB user: {db_user}/{db_pass}, database: {db_default}."
            )

            return {
                "message": msg,
                "deployment_type": "lamp",
                "namespace": effective_namespace,
                "service_info": {
                    "created": True,
                    "type": service_type,
                    "web": {"port": service_port, "node_port": node_port_web, "service": svc_web},
                    "phpmyadmin": {"port": 8081, "node_port": node_port_pma, "service": svc_pma},
                },
                "created_objects": {
                    "secret": secret_name,
                    "pvc": pvc_db,
                    "services": [svc_db, svc_web, svc_pma],
                    "deployments": [db_name, web_name, pma_name],
                },
                "credentials": {
                    "database": {"host": svc_db, "port": 3306, "username": db_user, "password": db_pass, "database": db_default},
                },
            }
        except client.exceptions.ApiException as e:
            raise HTTPException(status_code=e.status or 500, detail=f"Erreur LAMP: {e.reason} - {e.body}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur LAMP inattendue: {e}")

# Instance globale du service
deployment_service = DeploymentService()
