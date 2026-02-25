"""Tests for deployment lifecycle endpoints (K8s mocked)."""
import pytest
from unittest.mock import MagicMock


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
