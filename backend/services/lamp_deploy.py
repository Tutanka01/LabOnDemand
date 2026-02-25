"""Mixin pour la création de stacks LAMP (Apache+PHP, MySQL, phpMyAdmin)."""
import secrets
from typing import Dict, Any, Optional

from fastapi import HTTPException
from kubernetes import client

from ..models import User
from ..config import settings
from ..k8s_utils import create_labondemand_labels, clamp_resources_for_role


# Page index.php par défaut pour le init-container
_DEFAULT_INDEX_PHP = r'''cat > /workdir/index.php << 'PHP'
<?php
header('Content-Type: text/html; charset=utf-8');
echo '<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>LAMP – LabOnDemand</title>
    </head>
<body style="background:#0b1220;color:#e6edf3;font-family:Arial,Helvetica,sans-serif;padding:32px">

    <div style="background:#111827;border:1px solid #243244;border-radius:12px;
                            padding:24px;max-width:820px;box-shadow:0 2px 8px rgba(0,0,0,0.3)">

        <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px">
            <div style="width:64px;height:64px;border-radius:8px;background:#0ea5e9;display:flex;align-items:center;justify-content:center;color:#0b1220;font-weight:700;font-size:18px;">
                LOD
            </div>
            <h2 style="margin:0;color:#A6BE0B"> Ça marche ! – Stack LAMP</h2>
        </div>

        <p style="opacity:.85;font-size:15px">
            Page par défaut générée automatiquement pour <b>LabOnDemand</b> (by makhal).
        </p>

        <p style="margin-top:12px;font-size:14px;line-height:1.5">
            Remplacez <code>/var/www/html/index.php</code> par votre application.
        </p>

        <hr style="margin:24px 0;border:0;border-top:1px solid #243244">

        <footer style="font-size:13px;color:#9ca3af">
            LabOnDemand - by makhal
        </footer>

    </div>
</body>
</html>';
?>
PHP
chmod 644 /workdir/index.php
'''


class LAMPDeployMixin:
    """Fournit _create_lamp_stack() pour DeploymentService."""

    async def _create_lamp_stack(
        self,
        name: str,
        effective_namespace: str,
        service_type: str,
        service_port: int,
        current_user: User,
        additional_labels: Dict[str, str],
    ) -> Dict[str, Any]:
        """Crée une stack LAMP complète (Apache+PHP, MySQL, phpMyAdmin)."""
        web_name = f"{name}-web"
        db_name = f"{name}-mysql"
        pma_name = f"{name}-phpmyadmin"
        svc_web = f"{web_name}-service"
        svc_db = f"{db_name}-service"
        svc_pma = f"{pma_name}-service"
        pvc_db = f"{db_name}-pvc"
        secret_name = f"{name}-db-secret"

        labels_base = create_labondemand_labels("lamp", str(current_user.id), current_user.role.value, additional_labels)
        labels_web = {**labels_base, "stack-name": name, "component": "web"}
        labels_db = {**labels_base, "stack-name": name, "component": "database"}
        labels_pma = {**labels_base, "stack-name": name, "component": "phpmyadmin"}

        use_ingress = self._should_attach_ingress("lamp")
        if use_ingress and service_type in ["NodePort", "LoadBalancer"]:
            service_type = "ClusterIP"

        db_user = "appuser"
        db_pass = secrets.token_urlsafe(16)
        db_root = secrets.token_urlsafe(18)
        db_default = "appdb"

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
        svc_web_manifest = {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": svc_web, "labels": {"app": web_name, **labels_web}},
            "spec": {"type": service_type, "ports": [{"port": service_port, "targetPort": 80}], "selector": {"app": web_name}},
        }
        svc_pma_manifest = {
            "apiVersion": "v1", "kind": "Service",
            "metadata": {"name": svc_pma, "labels": {"app": pma_name, **labels_pma}},
            "spec": {"type": service_type, "ports": [{"port": 8081, "targetPort": 80}], "selector": {"app": pma_name}},
        }

        role_val = getattr(current_user.role, "value", str(current_user.role))
        web_res = clamp_resources_for_role(str(role_val), "250m", "500m", "256Mi", "512Mi", 1)
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

        dep_web_manifest = {
            "apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": web_name, "labels": labels_web},
            "spec": {
                "replicas": 1, "selector": {"matchLabels": {"app": web_name}},
                "template": {
                    "metadata": {"labels": {"app": web_name, **labels_web}},
                    "spec": {
                        "initContainers": [{
                            "name": "init-www", "image": "busybox:1.36",
                            "command": ["sh", "-c", _DEFAULT_INDEX_PHP],
                            "volumeMounts": [{"name": "www", "mountPath": "/workdir"}],
                        }],
                        "containers": [{
                            "name": "apache", "image": "php:8.2-apache",
                            "env": [
                                {"name": "DB_HOST", "value": svc_db},
                                {"name": "DB_NAME", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_DATABASE"}}},
                                {"name": "DB_USER", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_USER"}}},
                                {"name": "DB_PASSWORD", "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "MYSQL_PASSWORD"}}},
                            ],
                            "ports": [{"containerPort": 80}],
                            "resources": {"requests": {"cpu": web_res["cpu_request"], "memory": web_res["memory_request"]}, "limits": {"cpu": web_res["cpu_limit"], "memory": web_res["memory_limit"]}},
                            "securityContext": {"runAsUser": 33, "runAsGroup": 33, "runAsNonRoot": True, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"], "add": ["NET_BIND_SERVICE"]}, "seccompProfile": {"type": "RuntimeDefault"}},
                            "readinessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 10, "periodSeconds": 5},
                            "livenessProbe": {"httpGet": {"path": "/", "port": 80}, "initialDelaySeconds": 30, "periodSeconds": 10},
                            "volumeMounts": [{"name": "www", "mountPath": "/var/www/html"}],
                        }],
                        "volumes": [{"name": "www", "persistentVolumeClaim": {"claimName": f"{web_name}-pvc"}}],
                    },
                },
            },
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
            # Secret idempotent
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
            created_web_svc = self.core_v1.create_namespaced_service(effective_namespace, svc_web_manifest)
            created_pma_svc = self.core_v1.create_namespaced_service(effective_namespace, svc_pma_manifest)

            if not use_pvc:
                dep_db_manifest["spec"]["template"]["spec"]["volumes"] = [{"name": "data", "emptyDir": {}}]

            self.apps_v1.create_namespaced_deployment(effective_namespace, dep_db_manifest)

            # PVC web LAMP
            pvc_web = f"{web_name}-pvc"
            pvc_web_manifest = {
                "apiVersion": "v1", "kind": "PersistentVolumeClaim",
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
            ingress_details: Dict[str, Optional[Dict[str, Any]]] = {"web": None, "phpmyadmin": None}
            if service_type in ["NodePort", "LoadBalancer"]:
                try:
                    node_port_web = created_web_svc.spec.ports[0].node_port
                except Exception:
                    node_port_web = None
                try:
                    node_port_pma = created_pma_svc.spec.ports[0].node_port
                except Exception:
                    node_port_pma = None

            result_msg = (
                f"Stack LAMP créée: WEB={web_name}, DB={db_name}, PMA={pma_name} dans {effective_namespace}. "
                f"DB user: {db_user}/{db_pass}, database: {db_default}."
            )

            if use_ingress:
                scheme = "https" if settings.INGRESS_TLS_SECRET else "http"

                ingress_web_name = f"{web_name}-ingress"
                host_web = self._build_ingress_host(name, current_user, component="web")
                ingress_web_manifest = self.create_ingress_manifest(ingress_web_name, host_web, svc_web, service_port, labels_web)
                ingress_web_obj, created_web = self._apply_ingress(effective_namespace, ingress_web_manifest)
                ingress_details["web"] = {
                    "name": getattr(getattr(ingress_web_obj, "metadata", None), "name", ingress_web_name),
                    "host": host_web, "url": f"{scheme}://{host_web}{settings.INGRESS_DEFAULT_PATH}",
                    "class": settings.INGRESS_CLASS_NAME, "tls": bool(settings.INGRESS_TLS_SECRET), "created": created_web,
                }

                ingress_pma_name = f"{pma_name}-ingress"
                host_pma = self._build_ingress_host(name, current_user, component="pma")
                ingress_pma_manifest = self.create_ingress_manifest(ingress_pma_name, host_pma, svc_pma, 8081, labels_pma)
                ingress_pma_obj, created_pma = self._apply_ingress(effective_namespace, ingress_pma_manifest)
                ingress_details["phpmyadmin"] = {
                    "name": getattr(getattr(ingress_pma_obj, "metadata", None), "name", ingress_pma_name),
                    "host": host_pma, "url": f"{scheme}://{host_pma}{settings.INGRESS_DEFAULT_PATH}",
                    "class": settings.INGRESS_CLASS_NAME, "tls": bool(settings.INGRESS_TLS_SECRET), "created": created_pma,
                }

                result_msg += f" Web: {ingress_details['web']['url']} – phpMyAdmin: {ingress_details['phpmyadmin']['url']}."
            else:
                result_msg += f" NodePorts: web={node_port_web}, phpMyAdmin={node_port_pma}."

            return {
                "message": result_msg, "deployment_type": "lamp", "namespace": effective_namespace,
                "service_info": {
                    "created": True, "type": service_type,
                    "web": {"port": service_port, "node_port": node_port_web, "service": svc_web},
                    "phpmyadmin": {"port": 8081, "node_port": node_port_pma, "service": svc_pma},
                    "ingress": ingress_details,
                },
                "created_objects": {"secret": secret_name, "pvc": pvc_db, "services": [svc_db, svc_web, svc_pma], "deployments": [db_name, web_name, pma_name]},
                "credentials": {"database": {"host": svc_db, "port": 3306, "username": db_user, "password": db_pass, "database": db_default}},
            }
        except client.exceptions.ApiException as e:
            raise HTTPException(status_code=e.status or 500, detail=f"Erreur LAMP: {e.reason} - {e.body}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur LAMP inattendue: {e}")
