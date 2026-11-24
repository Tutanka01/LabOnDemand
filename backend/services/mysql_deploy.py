"""Mixin pour la création de stacks MySQL + phpMyAdmin."""
import secrets
from typing import Any, Dict, List, Optional, Tuple

from ..models import User
from ..k8s_utils import create_labondemand_labels
from .stacks import DATABASE_RESOURCES, PHPMYADMIN_RESOURCES


class MySQLDeployMixin:
    """Fournit _create_mysql_pma_stack() pour DeploymentService."""

    def _create_mysql_pma_stack(
        self,
        name: str,
        effective_namespace: str,
        service_type: str,
        service_port: int,
        current_user: User,
        additional_labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """Crée une stack MySQL + phpMyAdmin."""
        db_name = f"{name}-mysql"
        pma_name = f"{name}-phpmyadmin"
        svc_db = f"{db_name}-service"
        svc_pma = f"{pma_name}-service"
        pvc_db = f"{db_name}-pvc"
        secret_name = f"{name}-db-secret"

        labels_base = create_labondemand_labels("mysql", str(current_user.id), current_user.role.value, additional_labels)
        labels_db = {**labels_base, "stack-name": name, "component": "database"}
        labels_pma = {**labels_base, "stack-name": name, "component": "phpmyadmin"}

        use_ingress = self._should_attach_ingress("mysql")
        if use_ingress and service_type in ["NodePort", "LoadBalancer"]:
            service_type = "ClusterIP"

        db_user = "student"
        db_pass = secrets.token_urlsafe(16)
        db_root = secrets.token_urlsafe(18)
        db_default = "studentdb"

        secret_manifest = {
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": secret_name, "labels": labels_db},
            "type": "Opaque",
            "stringData": {"MYSQL_ROOT_PASSWORD": db_root, "MYSQL_USER": db_user, "MYSQL_PASSWORD": db_pass, "MYSQL_DATABASE": db_default},
        }

        pvc_manifest = {
            "apiVersion": "v1", "kind": "PersistentVolumeClaim",
            "metadata": {"name": pvc_db, "labels": labels_db},
            "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}}},
        }

        svc_db_manifest = {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": svc_db, "labels": {"app": db_name, **labels_db}},
            "spec": {"type": "ClusterIP", "ports": [{"port": 3306, "targetPort": 3306}], "selector": {"app": db_name}},
        }

        role_val = getattr(current_user.role, "value", str(current_user.role))
        db_res = DATABASE_RESOURCES.clamp(str(role_val))
        pma_res = PHPMYADMIN_RESOURCES.clamp(str(role_val))

        dep_db_manifest = {
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": db_name, "labels": labels_db},
            "spec": {
                "replicas": 1, "selector": {"matchLabels": {"app": db_name}},
                "template": {
                    "metadata": {"labels": {"app": db_name, **labels_db}},
                    "spec": {
                        "securityContext": {"fsGroup": 999, "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [{
                            "name": "mysql", "image": "mysql:9",
                            "envFrom": [{"secretRef": {"name": secret_name}}],
                            "ports": [{"containerPort": 3306}],
                            "resources": {"requests": {"cpu": db_res["cpu_request"], "memory": db_res["memory_request"]}, "limits": {"cpu": db_res["cpu_limit"], "memory": db_res["memory_limit"]}},
                            "securityContext": {"runAsUser": 999, "runAsNonRoot": True, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                            "livenessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 30, "periodSeconds": 10},
                            "readinessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 10, "periodSeconds": 5},
                            "volumeMounts": [{"name": "data", "mountPath": "/var/lib/mysql"}],
                        }],
                        "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_db}}],
                    },
                },
            },
        }

        svc_pma_manifest = {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": svc_pma, "labels": {"app": pma_name, **labels_pma}},
            "spec": {"type": service_type, "ports": [{"port": service_port, "targetPort": 80}], "selector": {"app": pma_name}},
        }

        dep_pma_manifest = {
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": pma_name, "labels": labels_pma},
            "spec": {
                "replicas": 1, "selector": {"matchLabels": {"app": pma_name}},
                "template": {
                    "metadata": {"labels": {"app": pma_name, **labels_pma}},
                    "spec": {
                        "containers": [{
                            "name": "phpmyadmin", "image": "phpmyadmin:latest",
                            "env": [
                                {"name": "PMA_HOST", "value": svc_db},
                                {"name": "PMA_USER", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_USER"}}},
                                {"name": "PMA_PASSWORD", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_PASSWORD"}}},
                            ],
                            "ports": [{"containerPort": 80}],
                            "resources": {"requests": {"cpu": pma_res["cpu_request"], "memory": pma_res["memory_request"]}, "limits": {"cpu": pma_res["cpu_limit"], "memory": pma_res["memory_limit"]}},
                            "readinessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 10, "periodSeconds": 5},
                            "livenessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 30, "periodSeconds": 10},
                        }],
                    },
                },
            },
        }

        created_objects: List[Tuple[str, str]] = []
        with self._rollback_on_failure(
            effective_namespace,
            created_objects,
            "Erreur MySQL/phpMyAdmin",
            "Erreur MySQL/phpMyAdmin inattendue",
        ):
            # Credentials the pods really use (an existing secret is kept).
            secret_values = self._create_or_relabel_secret(
                effective_namespace, secret_manifest, created_objects
            )
            db_user = secret_values.get("MYSQL_USER")
            db_pass = secret_values.get("MYSQL_PASSWORD")
            db_default = secret_values.get("MYSQL_DATABASE")
            use_pvc = self._create_pvc_or_fallback(effective_namespace, pvc_manifest, created_objects)

            self.core_v1.create_namespaced_service(effective_namespace, svc_db_manifest)
            created_objects.append(("service", svc_db))
            if not use_pvc:
                dep_db_manifest["spec"]["template"]["spec"]["volumes"] = [{"name": "data", "emptyDir": {}}]
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_db_manifest)
            created_objects.append(("deployment", db_name))

            created_pma_svc = self.core_v1.create_namespaced_service(effective_namespace, svc_pma_manifest)
            created_objects.append(("service", svc_pma))
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_pma_manifest)
            created_objects.append(("deployment", pma_name))

            node_port = None
            ingress_details: Optional[Dict[str, Any]] = None
            if service_type in ["NodePort", "LoadBalancer"]:
                node_port = created_pma_svc.spec.ports[0].node_port

            result_msg = (
                f"Stack MySQL+phpMyAdmin créée dans {effective_namespace}. "
                f"phpMyAdmin exposé sur port {service_port} (NodePort={node_port}). "
                f"DB user={db_user}, database={db_default}."
            )

            if use_ingress:
                ingress_details = self._expose_via_ingress(
                    effective_namespace,
                    f"{pma_name}-ingress",
                    self._build_ingress_host(name, current_user, component="pma"),
                    svc_pma,
                    service_port,
                    labels_pma,
                    created_objects,
                )
                result_msg = (
                    f"Stack MySQL+phpMyAdmin créée dans {effective_namespace}. "
                    f"phpMyAdmin accessible via {ingress_details['url']}. "
                    f"DB user={db_user}, database={db_default}."
                )

            return {
                "message": result_msg, "deployment_type": "mysql", "namespace": effective_namespace,
                "service_info": {"created": True, "type": service_type, "port": service_port, "node_port": node_port, "ingress": ingress_details},
                "created_objects": {"secret": secret_name, "pvc": pvc_db, "services": [svc_db, svc_pma], "deployments": [db_name, pma_name]},
                "credentials": {"database": {"host": svc_db, "port": 3306, "username": db_user, "password": db_pass, "database": db_default}, "phpmyadmin": {"url_hint": "http://<NODE_IP>:<NODE_PORT>/"}},
            }
