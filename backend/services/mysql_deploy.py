"""Mixin pour la création de stacks MySQL + phpMyAdmin."""
import secrets
from typing import Dict, Any, Optional

from fastapi import HTTPException
from kubernetes import client

from ..models import User
from ..config import settings
from ..k8s_utils import create_labondemand_labels, clamp_resources_for_role


class MySQLDeployMixin:
    """Fournit _create_mysql_pma_stack() pour DeploymentService."""

    async def _create_mysql_pma_stack(
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
        db_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
        pma_res = clamp_resources_for_role(str(role_val), "150m", "300m", "128Mi", "256Mi", 1)

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

        try:
            try:
                self.core_v1.create_namespaced_secret(effective_namespace, secret_manifest)
            except client.exceptions.ApiException as e:
                if e.status == 409:
                    try:
                        self.core_v1.patch_namespaced_secret(name=secret_manifest["metadata"]["name"], namespace=effective_namespace, body={"metadata": {"labels": secret_manifest["metadata"].get("labels", {})}})
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
            ingress_details: Optional[Dict[str, Any]] = None
            if service_type in ["NodePort", "LoadBalancer"]:
                node_port = created_pma_svc.spec.ports[0].node_port

            result_msg = (
                f"Stack MySQL+phpMyAdmin créée dans {effective_namespace}. "
                f"phpMyAdmin exposé sur port {service_port} (NodePort={node_port}). "
                f"DB user={db_user}, database={db_default}."
            )

            if use_ingress:
                ingress_name = f"{pma_name}-ingress"
                host = self._build_ingress_host(name, current_user, component="pma")
                ingress_manifest = self.create_ingress_manifest(ingress_name, host, svc_pma, service_port, labels_pma)
                ingress_obj, created_flag = self._apply_ingress(effective_namespace, ingress_manifest)
                scheme = "https" if settings.INGRESS_TLS_SECRET else "http"
                ingress_details = {
                    "name": getattr(getattr(ingress_obj, "metadata", None), "name", ingress_name),
                    "host": host, "url": f"{scheme}://{host}{settings.INGRESS_DEFAULT_PATH}",
                    "class": settings.INGRESS_CLASS_NAME, "tls": bool(settings.INGRESS_TLS_SECRET), "created": created_flag,
                }
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
        except client.exceptions.ApiException as e:
            raise HTTPException(status_code=e.status or 500, detail=f"Erreur MySQL/phpMyAdmin: {e.reason} - {e.body}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur MySQL/phpMyAdmin inattendue: {e}")
