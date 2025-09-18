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
    max_resource
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
                # Fallback si DB inaccessible: limiter aux types historiques connus
                if deployment_type not in {"jupyter", "vscode"}:
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
        service_type: str
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
        await ensure_namespace_exists(effective_namespace)
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
                replicas,
                config["cpu_request"],
                config["cpu_limit"],
                config["memory_request"],
                config["memory_limit"],
                config["service_target_port"],
                labels,
            )

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
                    "cpu_request": config["cpu_request"],
                    "cpu_limit": config["cpu_limit"],
                    "memory_request": config["memory_request"],
                    "memory_limit": config["memory_limit"],
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

# Instance globale du service
deployment_service = DeploymentService()
