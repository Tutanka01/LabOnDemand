"""Tests for deployment lifecycle endpoints (K8s mocked)."""
import datetime
import pytest
from unittest.mock import MagicMock
import base64


async def test_list_deployments_empty(admin_client, mock_k8s):
    r = await admin_client.get("/api/v1/k8s/deployments/labondemand")
    assert r.status_code == 200
    body = r.json()
    assert "deployments" in body
    assert body["deployments"] == []


async def test_list_deployments_unauthenticated(client):
    r = await client.get("/api/v1/k8s/deployments/labondemand")
    # Returns empty list (k8s unavailable) or 401 — both acceptable
    assert r.status_code in (200, 401)


async def test_list_deployments_with_items(student_client, mock_k8s, student_user):
    """Deployments belonging to the current user appear in the list."""
    dep = MagicMock()
    dep.metadata.name = "mylab"
    dep.metadata.namespace = f"student-{student_user.id}"
    dep.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(student_user.id),
        "app-type": "custom",
    }
    dep.metadata.annotations = {}
    dep.metadata.creation_timestamp = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    dep.spec.replicas = 1
    dep.spec.template.spec.containers = [MagicMock(image="nginx:latest")]
    dep.status.ready_replicas = 1

    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(
        items=[dep]
    )
    r = await student_client.get("/api/v1/k8s/deployments/labondemand")
    assert r.status_code == 200
    body = r.json()
    assert len(body["deployments"]) == 1
    assert body["deployments"][0]["name"] == "mylab"


async def test_create_deployment_simple(admin_client, mock_k8s):
    r = await admin_client.post(
        "/api/v1/k8s/deployments",
        params={
            "name": "mylab",
            "image": "nginx:latest",
            "deployment_type": "custom",
        },
    )
    assert r.status_code in (200, 201)


async def test_create_deployment_invalid_name(admin_client, mock_k8s):
    """Names with uppercase letters should be rejected."""
    r = await admin_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "my lab with spaces!", "image": "nginx:latest", "deployment_type": "custom"},
    )
    assert r.status_code in (400, 422)


async def test_create_deployment_unauthenticated(client, mock_k8s):
    r = await client.post(
        "/api/v1/k8s/deployments",
        params={"name": "mylab", "image": "nginx:latest", "deployment_type": "custom"},
    )
    assert r.status_code == 401


async def test_create_deployment_student_allowed(student_client, mock_k8s, sample_runtime_config):
    """Students can create deployments of types allowed for them."""
    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "mylab", "deployment_type": "vscode"},
    )
    # Should succeed (200/201) or fail due to quota (403) — not 401
    assert r.status_code in (200, 201, 403, 422)


async def test_create_vscode_deployment_generates_password_secret(
    student_client, mock_k8s, sample_runtime_config
):
    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "mylab", "image": "ignored", "deployment_type": "vscode"},
    )

    assert r.status_code in (200, 201)
    secret_manifest = mock_k8s["core"].create_namespaced_secret.call_args.args[1]
    assert secret_manifest["metadata"]["name"] == "mylab-secret"
    assert secret_manifest["metadata"]["labels"]["app"] == "mylab"
    assert secret_manifest["metadata"]["labels"]["stack-name"] == "mylab"
    assert secret_manifest["stringData"]["CODE_SERVER_USERNAME"] == "coder"
    assert len(secret_manifest["stringData"]["PASSWORD"]) >= 20

    deployment_manifest = mock_k8s["apps"].create_namespaced_deployment.call_args.args[1]
    container = deployment_manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "codercom/code-server:4.121.0-39"
    assert {"secretRef": {"name": "mylab-secret"}} in container["envFrom"]

    body = r.json()
    assert body["credentials"]["vscode"]["username"] == "coder"
    assert body["credentials"]["vscode"]["password"] == secret_manifest["stringData"]["PASSWORD"]


async def test_create_jupyter_deployment_generates_token_secret(
    student_client, mock_k8s, db
):
    from backend.models import RuntimeConfig

    db.add(
        RuntimeConfig(
            key="jupyter",
            default_image="tutanka01/k8s:jupyter",
            target_port=8888,
            default_service_type="NodePort",
            allowed_for_students=True,
            active=True,
        )
    )
    db.commit()

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "notebook", "image": "ignored", "deployment_type": "jupyter"},
    )

    assert r.status_code in (200, 201)
    secret_manifest = mock_k8s["core"].create_namespaced_secret.call_args.args[1]
    assert secret_manifest["metadata"]["name"] == "notebook-secret"
    assert secret_manifest["metadata"]["labels"]["stack-name"] == "notebook"
    assert len(secret_manifest["stringData"]["JUPYTER_TOKEN"]) >= 30

    deployment_manifest = mock_k8s["apps"].create_namespaced_deployment.call_args.args[1]
    container = deployment_manifest["spec"]["template"]["spec"]["containers"][0]
    assert {"secretRef": {"name": "notebook-secret"}} in container["envFrom"]
    assert container["command"] == ["/bin/sh", "-lc"]
    assert "ServerApp.token" in container["args"][0]
    assert "JUPYTER_TOKEN" in container["args"][0]

    body = r.json()
    assert body["credentials"]["jupyter"]["token"] == secret_manifest["stringData"]["JUPYTER_TOKEN"]


async def test_create_netbeans_deployment_generates_vnc_secret(
    student_client, mock_k8s, db
):
    from backend.models import RuntimeConfig

    db.add(
        RuntimeConfig(
            key="netbeans",
            default_image="tutanka01/labondemand:netbeansjava",
            target_port=6901,
            default_service_type="NodePort",
            allowed_for_students=True,
            active=True,
        )
    )
    db.commit()

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "desktop", "image": "ignored", "deployment_type": "netbeans"},
    )

    assert r.status_code in (200, 201)
    secret_manifest = mock_k8s["core"].create_namespaced_secret.call_args.args[1]
    assert secret_manifest["metadata"]["name"] == "desktop-secret"
    assert secret_manifest["metadata"]["labels"]["stack-name"] == "desktop"
    assert secret_manifest["stringData"]["VNC_USERNAME"] == "kasm_user"
    assert len(secret_manifest["stringData"]["VNC_PW"]) >= 20
    assert len(secret_manifest["stringData"]["VNC_VIEW_ONLY_PW"]) >= 20

    deployment_manifest = mock_k8s["apps"].create_namespaced_deployment.call_args.args[1]
    container = deployment_manifest["spec"]["template"]["spec"]["containers"][0]
    assert {"secretRef": {"name": "desktop-secret"}} in container["envFrom"]
    env_names = {item["name"] for item in container["env"]}
    assert "VNC_PW" not in env_names
    assert "VNC_VIEW_ONLY_PW" not in env_names

    body = r.json()
    assert body["credentials"]["netbeans"]["username"] == "kasm_user"
    assert body["credentials"]["netbeans"]["password"] == secret_manifest["stringData"]["VNC_PW"]


async def test_create_netbeans_deployment_persists_home_volume(
    student_client, mock_k8s, db
):
    """Le bureau VNC monte son home sur un PVC et copie le profil par défaut."""
    from backend.config import settings
    from backend.models import RuntimeConfig

    db.add(
        RuntimeConfig(
            key="netbeans",
            default_image="tutanka01/labondemand:netbeansjava",
            target_port=6901,
            default_service_type="NodePort",
            allowed_for_students=True,
            active=True,
        )
    )
    db.commit()

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "desktop", "image": "ignored", "deployment_type": "netbeans"},
    )
    assert r.status_code in (200, 201)

    pvc_manifest = mock_k8s["core"].create_namespaced_persistent_volume_claim.call_args.args[1]
    assert pvc_manifest["metadata"]["name"] == "desktop-pvc"
    assert pvc_manifest["spec"]["resources"]["requests"]["storage"] == settings.LAB_PVC_SIZE

    pod_spec = mock_k8s["apps"].create_namespaced_deployment.call_args.args[1][
        "spec"
    ]["template"]["spec"]
    container = pod_spec["containers"][0]
    assert {"name": "data", "mountPath": "/home/lod-user"} in container["volumeMounts"]
    assert pod_spec["volumes"] == [
        {"name": "data", "persistentVolumeClaim": {"claimName": "desktop-pvc"}}
    ]
    assert pod_spec["securityContext"]["fsGroup"] == 1000

    seed = pod_spec["initContainers"][0]
    assert seed["name"] == "seed-home"
    assert seed["image"] == "tutanka01/labondemand:netbeansjava"
    assert {"name": "data", "mountPath": "/mnt/home"} in seed["volumeMounts"]
    assert "labondemand-seeded" in seed["args"][0]


async def test_create_eclipse_deployment_generates_vnc_secret(
    student_client, mock_k8s, db
):
    """Un bureau Eclipse se comporte comme un bureau VNC (secret + identifiants)."""
    from backend.models import RuntimeConfig

    db.add(
        RuntimeConfig(
            key="eclipse",
            default_image="tutanka01/labondemand:eclipsejava",
            target_port=6901,
            default_service_type="NodePort",
            allowed_for_students=True,
            active=True,
        )
    )
    db.commit()

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "eclipsebox", "image": "ignored", "deployment_type": "eclipse"},
    )

    assert r.status_code in (200, 201)
    secret_manifest = mock_k8s["core"].create_namespaced_secret.call_args.args[1]
    assert secret_manifest["metadata"]["name"] == "eclipsebox-secret"
    assert secret_manifest["stringData"]["VNC_USERNAME"] == "kasm_user"
    assert len(secret_manifest["stringData"]["VNC_PW"]) >= 20
    assert len(secret_manifest["stringData"]["VNC_VIEW_ONLY_PW"]) >= 20

    pod_spec = mock_k8s["apps"].create_namespaced_deployment.call_args.args[1][
        "spec"
    ]["template"]["spec"]
    container = pod_spec["containers"][0]
    assert {"secretRef": {"name": "eclipsebox-secret"}} in container["envFrom"]
    assert {"name": "data", "mountPath": "/home/lod-user"} in container["volumeMounts"]
    assert any(
        p.get("name") == "tomcat" and p.get("containerPort") == 8080
        for p in container["ports"]
    )
    assert pod_spec["initContainers"][0]["name"] == "seed-home"
    assert pod_spec["initContainers"][0]["image"] == "tutanka01/labondemand:eclipsejava"

    # Tomcat est exposé par le service pour tester l'application web déployée.
    service_manifest = mock_k8s["core"].create_namespaced_service.call_args.args[1]
    tomcat_port = next(
        p for p in service_manifest["spec"]["ports"] if p.get("name") == "tomcat"
    )
    assert tomcat_port["port"] == 8080
    assert tomcat_port["targetPort"] == 8080

    body = r.json()
    assert body["credentials"]["eclipse"]["username"] == "kasm_user"
    assert body["credentials"]["eclipse"]["password"] == secret_manifest["stringData"]["VNC_PW"]
    assert body["connection_hints"]["tomcat"]["target_port"] == 8080


async def test_eclipse_runtime_minimum_survives_role_clamp(student_client, mock_k8s, db):
    """Le plancher de la RuntimeConfig (2Gi mini) doit primer sur le plafond de rôle.

    Régression OOMKilled (exit 137) : le plafond étudiant (1Gi) re-plafonnait le
    minimum Eclipse après application, ce qui lançait le bureau avec 1Gi -> le JVM
    et Firefox se faisaient tuer par le noyau.
    """
    from backend.models import RuntimeConfig

    db.add(
        RuntimeConfig(
            key="eclipse",
            default_image="tutanka01/labondemand:eclipsejava",
            target_port=6901,
            default_service_type="NodePort",
            allowed_for_students=True,
            min_cpu_request="500m",
            min_memory_request="1Gi",
            min_cpu_limit="1000m",
            min_memory_limit="2Gi",
            active=True,
        )
    )
    db.commit()

    # Preset "Faible" : très en dessous des planchers du runtime Eclipse.
    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={
            "name": "eclipsebox",
            "image": "ignored",
            "deployment_type": "eclipse",
            "cpu_request": "100m",
            "cpu_limit": "200m",
            "memory_request": "256Mi",
            "memory_limit": "512Mi",
        },
    )

    assert r.status_code in (200, 201)
    container = mock_k8s["apps"].create_namespaced_deployment.call_args.args[1][
        "spec"
    ]["template"]["spec"]["containers"][0]
    resources = container["resources"]
    # La limite mémoire réellement envoyée au cluster est bien celle du runtime (2Gi),
    # et non le plafond étudiant (1Gi).
    assert resources["limits"]["memory"] == "2Gi"
    assert resources["requests"]["memory"] == "1Gi"
    assert resources["limits"]["cpu"] == "1000m"
    assert resources["requests"]["cpu"] == "500m"


async def test_eclipse_clamp_still_applies_without_runtime_minimum(
    student_client, mock_k8s, db
):
    """Sans plancher déclaré, le plafond de rôle reste la seule borne (pas de contournement)."""
    from backend.models import RuntimeConfig

    db.add(
        RuntimeConfig(
            key="eclipse",
            default_image="tutanka01/labondemand:eclipsejava",
            target_port=6901,
            default_service_type="NodePort",
            allowed_for_students=True,
            active=True,
        )
    )
    db.commit()

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={
            "name": "eclipsebox",
            "image": "ignored",
            "deployment_type": "eclipse",
            "cpu_request": "2000m",
            "cpu_limit": "4000m",
            "memory_request": "4Gi",
            "memory_limit": "8Gi",
        },
    )

    assert r.status_code in (200, 201)
    container = mock_k8s["apps"].create_namespaced_deployment.call_args.args[1][
        "spec"
    ]["template"]["spec"]["containers"][0]
    resources = container["resources"]
    # Plafonds étudiant : 500m / 1000m / 512Mi / 1Gi
    assert resources["requests"]["cpu"] == "500m"
    assert resources["limits"]["cpu"] == "1000m"
    assert resources["requests"]["memory"] == "512Mi"
    assert resources["limits"]["memory"] == "1Gi"


async def test_get_eclipse_credentials_returns_vnc_passwords(
    student_client, mock_k8s, student_user
):
    dep = MagicMock()
    dep.metadata.name = "eclipsebox"
    dep.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(student_user.id),
        "user-role": "student",
        "app-type": "eclipse",
        "app": "eclipsebox",
    }
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep

    secret = MagicMock()
    secret.data = {
        "VNC_USERNAME": base64.b64encode(b"kasm_user").decode("ascii"),
        "VNC_PW": base64.b64encode(b"EclipsePass123").decode("ascii"),
        "VNC_VIEW_ONLY_PW": base64.b64encode(b"ViewOnlyPass123").decode("ascii"),
    }
    mock_k8s["core"].list_namespaced_secret.return_value = MagicMock(items=[secret])

    namespace = f"labondemand-user-{student_user.id}"
    r = await student_client.get(
        f"/api/v1/k8s/deployments/{namespace}/eclipsebox/credentials"
    )

    assert r.status_code == 200
    assert r.json() == {
        "type": "eclipse",
        "eclipse": {
            "username": "kasm_user",
            "password": "EclipsePass123",
            "view_only_password": "ViewOnlyPass123",
        },
    }


async def test_create_netbeans_deployment_reuses_existing_pvc(
    student_client, mock_k8s, db, student_user
):
    """Relancer un bureau avec un volume existant réutilise le PVC (travail conservé)."""
    from backend.models import RuntimeConfig

    db.add(
        RuntimeConfig(
            key="netbeans",
            default_image="tutanka01/labondemand:netbeansjava",
            target_port=6901,
            default_service_type="NodePort",
            allowed_for_students=True,
            active=True,
        )
    )
    db.commit()

    pvc = MagicMock()
    pvc.metadata.name = "mon-bureau"
    pvc.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(student_user.id),
    }
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = pvc

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={
            "name": "desktop2",
            "image": "ignored",
            "deployment_type": "netbeans",
            "existing_pvc_name": "mon-bureau",
        },
    )
    assert r.status_code in (200, 201)
    mock_k8s["core"].create_namespaced_persistent_volume_claim.assert_not_called()

    pod_spec = mock_k8s["apps"].create_namespaced_deployment.call_args.args[1][
        "spec"
    ]["template"]["spec"]
    assert pod_spec["volumes"] == [
        {"name": "data", "persistentVolumeClaim": {"claimName": "mon-bureau"}}
    ]
    assert {"name": "data", "mountPath": "/home/lod-user"} in pod_spec["containers"][
        0
    ]["volumeMounts"]


async def test_get_vscode_credentials_returns_code_server_password(
    student_client, mock_k8s, student_user
):
    dep = MagicMock()
    dep.metadata.name = "mylab"
    dep.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(student_user.id),
        "user-role": "student",
        "app-type": "vscode",
        "app": "mylab",
    }
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep

    secret = MagicMock()
    secret.data = {
        "CODE_SERVER_USERNAME": base64.b64encode(b"coder").decode("ascii"),
        "PASSWORD": base64.b64encode(b"GeneratedPass123").decode("ascii"),
    }
    mock_k8s["core"].list_namespaced_secret.return_value = MagicMock(items=[secret])

    namespace = f"labondemand-user-{student_user.id}"
    r = await student_client.get(f"/api/v1/k8s/deployments/{namespace}/mylab/credentials")

    assert r.status_code == 200
    body = r.json()
    assert body == {
        "type": "vscode",
        "vscode": {"username": "coder", "password": "GeneratedPass123"},
    }


async def test_get_jupyter_credentials_returns_token(
    student_client, mock_k8s, student_user
):
    dep = MagicMock()
    dep.metadata.name = "notebook"
    dep.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(student_user.id),
        "user-role": "student",
        "app-type": "jupyter",
        "app": "notebook",
    }
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep

    secret = MagicMock()
    secret.data = {
        "JUPYTER_TOKEN": base64.b64encode(b"NotebookToken123").decode("ascii"),
    }
    mock_k8s["core"].list_namespaced_secret.return_value = MagicMock(items=[secret])

    namespace = f"labondemand-user-{student_user.id}"
    r = await student_client.get(f"/api/v1/k8s/deployments/{namespace}/notebook/credentials")

    assert r.status_code == 200
    assert r.json() == {"type": "jupyter", "jupyter": {"token": "NotebookToken123"}}


async def test_get_netbeans_credentials_returns_vnc_passwords(
    student_client, mock_k8s, student_user
):
    dep = MagicMock()
    dep.metadata.name = "desktop"
    dep.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(student_user.id),
        "user-role": "student",
        "app-type": "netbeans",
        "app": "desktop",
    }
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep

    secret = MagicMock()
    secret.data = {
        "VNC_USERNAME": base64.b64encode(b"kasm_user").decode("ascii"),
        "VNC_PW": base64.b64encode(b"DesktopPass123").decode("ascii"),
        "VNC_VIEW_ONLY_PW": base64.b64encode(b"ViewOnlyPass123").decode("ascii"),
    }
    mock_k8s["core"].list_namespaced_secret.return_value = MagicMock(items=[secret])

    namespace = f"labondemand-user-{student_user.id}"
    r = await student_client.get(f"/api/v1/k8s/deployments/{namespace}/desktop/credentials")

    assert r.status_code == 200
    assert r.json() == {
        "type": "netbeans",
        "netbeans": {
            "username": "kasm_user",
            "password": "DesktopPass123",
            "view_only_password": "ViewOnlyPass123",
        },
    }


async def test_pause_deployment(admin_client, mock_k8s, admin_user):
    dep = MagicMock()
    dep.spec.replicas = 1
    dep.metadata.name = "mylab"
    dep.metadata.annotations = {}
    dep.metadata.labels = {"managed-by": "labondemand", "user-id": str(admin_user.id)}
    dep.status.ready_replicas = 1
    dep.status.available_replicas = 1
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep
    mock_k8s["apps"].patch_namespaced_deployment.return_value = dep

    namespace = f"labondemand-user-{admin_user.id}"
    r = await admin_client.post(f"/api/v1/k8s/deployments/{namespace}/mylab/pause")
    assert r.status_code in (200, 404)


async def test_resume_deployment(admin_client, mock_k8s, admin_user):
    dep = MagicMock()
    dep.spec.replicas = 0
    dep.metadata.name = "mylab"
    dep.metadata.annotations = {"labondemand/paused-replicas": "1"}
    dep.metadata.labels = {"managed-by": "labondemand", "user-id": str(admin_user.id)}
    dep.status.ready_replicas = 0
    dep.status.available_replicas = 0
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep
    mock_k8s["apps"].patch_namespaced_deployment.return_value = dep

    namespace = f"labondemand-user-{admin_user.id}"
    r = await admin_client.post(f"/api/v1/k8s/deployments/{namespace}/mylab/resume")
    assert r.status_code in (200, 404)


async def test_delete_deployment(admin_client, mock_k8s):
    mock_k8s["apps"].delete_namespaced_deployment.return_value = MagicMock()
    mock_k8s["core"].list_namespaced_service.return_value = MagicMock(items=[])
    mock_k8s["core"].list_namespaced_secret.return_value = MagicMock(items=[])
    mock_k8s["core"].list_namespaced_persistent_volume_claim.return_value = MagicMock(items=[])
    mock_k8s["networking"].list_namespaced_ingress.return_value = MagicMock(items=[])

    r = await admin_client.delete(
        "/api/v1/k8s/deployments/labondemand-admin/mylab",
        params={"delete_pvcs": "false"},
    )
    assert r.status_code in (200, 404)


async def test_delete_deployment_soft_delete_does_not_break_logging(
    admin_client, db, mock_k8s, admin_user
):
    from backend.models import Deployment

    db.add(
        Deployment(
            user_id=admin_user.id,
            name="juju",
            deployment_type="jupyter",
            namespace=f"labondemand-user-{admin_user.id}",
            status="active",
        )
    )
    db.commit()

    dep = MagicMock()
    dep.metadata.name = "juju"
    dep.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(admin_user.id),
        "app-type": "jupyter",
    }
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep
    mock_k8s["apps"].delete_namespaced_deployment.return_value = MagicMock()

    r = await admin_client.delete(
        f"/api/v1/k8s/deployments/labondemand-user-{admin_user.id}/juju",
        params={"delete_service": "true"},
    )

    assert r.status_code == 200
    deployment = db.query(Deployment).filter_by(name="juju").one()
    assert deployment.status == "deleted"
    assert deployment.deleted_at is not None


async def test_delete_deployment_student_forbidden_other(
    student_client, admin_user, mock_k8s
):
    """A student cannot delete a deployment in a namespace that is not theirs."""
    r = await student_client.delete(
        f"/api/v1/k8s/deployments/labondemand-user-{admin_user.id}/some-lab",
        params={"delete_pvcs": "false"},
    )
    # Namespace doesn't match student's own namespace → 403
    assert r.status_code in (403, 500)


async def test_pods_listing(admin_client, mock_k8s):
    r = await admin_client.get(
        "/api/v1/k8s/deployments/labondemand-admin/mylab/pods"
    )
    assert r.status_code in (200, 404)


async def test_deployment_details_not_found(admin_client, mock_k8s):
    from kubernetes import client as k8s_client
    mock_k8s["apps"].read_namespaced_deployment.side_effect = (
        k8s_client.exceptions.ApiException(status=404)
    )
    mock_k8s["apps"].list_namespaced_deployment.return_value = MagicMock(items=[])

    r = await admin_client.get(
        "/api/v1/k8s/deployments/labondemand-admin/nonexistent/details"
    )
    assert r.status_code == 404


async def test_deployment_details_exposes_novnc_endpoint(
    student_client, mock_k8s, student_user
):
    """Le port de service nommé "novnc" est exposé comme novnc_endpoint."""
    dep = MagicMock()
    dep.metadata.name = "desktop"
    dep.metadata.namespace = f"labondemand-user-{student_user.id}"
    dep.metadata.labels = {
        "managed-by": "labondemand",
        "user-id": str(student_user.id),
        "user-role": "student",
        "app-type": "netbeans",
        "app": "desktop",
    }
    dep.metadata.annotations = {}
    dep.spec.replicas = 1
    dep_container = MagicMock()
    dep_container.image = "tutanka01/labondemand:netbeansjava"
    dep.spec.template.spec.containers = [dep_container]
    dep.status.ready_replicas = 1
    dep.status.available_replicas = 1
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep

    port = MagicMock()
    port.name = "novnc"
    port.port = 6901
    port.target_port = 6901
    port.protocol = "TCP"
    port.node_port = 31001
    service = MagicMock()
    service.metadata.name = "desktop-service"
    service.metadata.labels = {"app": "desktop"}
    service.spec.type = "NodePort"
    service.spec.cluster_ip = "10.0.0.10"
    service.spec.ports = [port]
    service.spec.selector = {"app": "desktop"}
    mock_k8s["core"].list_namespaced_service.return_value = MagicMock(items=[service])

    namespace = f"labondemand-user-{student_user.id}"
    r = await student_client.get(
        f"/api/v1/k8s/deployments/{namespace}/desktop/details"
    )

    assert r.status_code == 200
    assert r.json()["novnc_endpoint"].endswith(":31001")
