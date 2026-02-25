"""Mixin pour la création de stacks WordPress + MariaDB."""
import base64
import secrets
from typing import Dict, Any, Optional

from fastapi import HTTPException
from kubernetes import client

from ..models import User
from ..config import settings
from ..k8s_utils import create_labondemand_labels, clamp_resources_for_role


class WordPressDeployMixin:
    """Fournit _create_wordpress_stack() pour DeploymentService."""

    async def _create_wordpress_stack(
        self,
        name: str,
        effective_namespace: str,
        service_type: str,
        service_port: int,
        current_user: User,
        additional_labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """Crée une stack WordPress + MariaDB isolée pour l'utilisateur."""
        wp_name = name
        db_name = f"{name}-mariadb"
        svc_wp = f"{wp_name}-service"
        svc_db = f"{db_name}-service"
        pvc_db = f"{db_name}-pvc"
        secret_name = f"{name}-secret"

        labels_base = create_labondemand_labels(
            "wordpress", str(current_user.id), current_user.role.value, additional_labels
        )
        labels_wp = {**labels_base, "stack-name": name, "component": "wordpress"}
        labels_db = {**labels_base, "stack-name": name, "component": "database"}

        use_ingress = self._should_attach_ingress("wordpress")
        if use_ingress and service_type in ["NodePort", "LoadBalancer"]:
            service_type = "ClusterIP"

        db_user = "wp_user"
        db_pass = secrets.token_urlsafe(16)
        db_root = secrets.token_urlsafe(18)
        wp_admin_user = "admin"
        wp_admin_pass = secrets.token_urlsafe(18)

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

        pvc_manifest = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": pvc_db, "labels": labels_db},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "1Gi"}},
            },
        }

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

        role_val = getattr(current_user.role, "value", str(current_user.role))
        db_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
        wp_res = clamp_resources_for_role(str(role_val), "250m", "1000m", "512Mi", "1Gi", 1)

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
                        "securityContext": {"fsGroup": 1001, "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [{
                            "name": "mariadb",
                            "image": "bitnamilegacy/mariadb:12.0.2-debian-12-r0",
                            "envFrom": [{"secretRef": {"name": secret_name}}],
                            "ports": [{"containerPort": 3306}],
                            "resources": {
                                "requests": {"cpu": db_res["cpu_request"], "memory": db_res["memory_request"]},
                                "limits": {"cpu": db_res["cpu_limit"], "memory": db_res["memory_limit"]},
                            },
                            "securityContext": {"runAsUser": 1001, "runAsNonRoot": True, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                            "livenessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 30, "periodSeconds": 10},
                            "readinessProbe": {"tcpSocket": {"port": 3306}, "initialDelaySeconds": 10, "periodSeconds": 5},
                            "volumeMounts": [{"name": "data", "mountPath": "/bitnami/mariadb"}],
                        }],
                        "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_db}}],
                    },
                },
            },
        }

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
                        "securityContext": {"fsGroup": 1001, "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [{
                            "name": "wordpress",
                            "image": "bitnamilegacy/wordpress:6.8.2-debian-12-r5",
                            "env": [
                                {"name": "WORDPRESS_ENABLE_HTTPS", "value": "no"},
                                {"name": "APACHE_HTTP_PORT_NUMBER", "value": "8080"},
                                {"name": "WORDPRESS_DATABASE_HOST", "value": svc_db},
                                {"name": "WORDPRESS_DATABASE_PORT_NUMBER", "value": "3306"},
                            ],
                            "envFrom": [{"secretRef": {"name": secret_name}}],
                            "ports": [{"containerPort": 8080}],
                            "resources": {
                                "requests": {"cpu": wp_res["cpu_request"], "memory": wp_res["memory_request"]},
                                "limits": {"cpu": wp_res["cpu_limit"], "memory": wp_res["memory_limit"]},
                            },
                            "securityContext": {"runAsUser": 1001, "runAsNonRoot": True, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                            "readinessProbe": {"httpGet": {"path": "/", "port": 8080}, "initialDelaySeconds": 10, "periodSeconds": 5},
                            "livenessProbe": {"httpGet": {"path": "/", "port": 8080}, "initialDelaySeconds": 30, "periodSeconds": 10},
                            "volumeMounts": [{"name": "wp-content", "mountPath": "/bitnami/wordpress"}],
                        }],
                        "volumes": [{"name": "wp-content", "emptyDir": {}}],
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
            created_wp_svc = self.core_v1.create_namespaced_service(effective_namespace, svc_wp_manifest)
            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_wp_manifest)

            try:
                apps_v1 = client.AppsV1Api()
                lbl = f"managed-by=labondemand,stack-name={name},user-id={current_user.id}"
                _lst = apps_v1.list_namespaced_deployment(effective_namespace, label_selector=lbl)
                if not (_lst.items or []):
                    raise HTTPException(status_code=500, detail="Stack WordPress créée partiellement: aucun Deployment trouvé juste après la création")
            except HTTPException:
                raise
            except Exception:
                pass

            node_port = None
            ingress_details: Optional[Dict[str, Any]] = None
            if service_type in ["NodePort", "LoadBalancer"]:
                node_port = created_wp_svc.spec.ports[0].node_port

            result_msg = (
                f"Stack WordPress créée: DB={db_name}, WP={wp_name} dans {effective_namespace}. "
                f"Admin: {wp_admin_user}/{wp_admin_pass}. DB user: {db_user}/{db_pass}."
            )

            if use_ingress:
                ingress_name = f"{wp_name}-ingress"
                host = self._build_ingress_host(wp_name, current_user)
                ingress_manifest = self.create_ingress_manifest(ingress_name, host, svc_wp, service_port, labels_wp)
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
                result_msg += f" Accès web: {ingress_details['url']}"

            return {
                "message": result_msg,
                "deployment_type": "wordpress",
                "namespace": effective_namespace,
                "service_info": {"created": True, "type": service_type, "port": service_port, "node_port": node_port, "ingress": ingress_details},
                "created_objects": {"secret": secret_name, "pvc": pvc_db, "services": [svc_db, svc_wp], "deployments": [db_name, wp_name]},
                "credentials": {
                    "wordpress": {"username": wp_admin_user, "password": wp_admin_pass},
                    "database": {"host": svc_db, "port": 3306, "username": db_user, "password": db_pass, "database": "wordpress"},
                },
            }
        except client.exceptions.ApiException as e:
            raise HTTPException(status_code=e.status or 500, detail=f"Erreur WordPress: {e.reason} - {e.body}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur WordPress inattendue: {e}")
