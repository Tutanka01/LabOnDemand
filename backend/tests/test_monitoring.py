"""Tests for monitoring / cluster-stats endpoints."""
import pytest
from unittest.mock import MagicMock


async def test_ping_authenticated(admin_client, mock_k8s):
    r = await admin_client.get("/api/v1/k8s/ping")
    assert r.status_code == 200


async def test_ping_unauthenticated(client, mock_k8s):
    r = await client.get("/api/v1/k8s/ping")
    assert r.status_code == 401


async def test_cluster_stats_admin(admin_client, mock_k8s):
    # Set up minimal node/pod/deployment lists
    _empty = MagicMock(items=[])
    mock_k8s["core"].list_node.return_value = _empty
    mock_k8s["core"].list_pod_for_all_namespaces.return_value = _empty
    mock_k8s["core"].list_namespace.return_value = _empty
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = _empty

    r = await admin_client.get("/api/v1/k8s/stats/cluster")
    assert r.status_code == 200
    body = r.json()
    assert "deployments_count" in body or "nodes" in body or "k8s_available" in body


async def test_cluster_stats_teacher_forbidden(teacher_client, mock_k8s):
    r = await teacher_client.get("/api/v1/k8s/stats/cluster")
    assert r.status_code == 403


async def test_cluster_stats_student_forbidden(student_client, mock_k8s):
    r = await student_client.get("/api/v1/k8s/stats/cluster")
    assert r.status_code == 403


async def test_cluster_stats_unauthenticated(client, mock_k8s):
    r = await client.get("/api/v1/k8s/stats/cluster")
    assert r.status_code == 401


async def test_namespaces_teacher(teacher_client, mock_k8s):
    r = await teacher_client.get("/api/v1/k8s/namespaces")
    assert r.status_code == 200


async def test_namespaces_admin(admin_client, mock_k8s):
    r = await admin_client.get("/api/v1/k8s/namespaces")
    assert r.status_code == 200


async def test_namespaces_student_forbidden(student_client, mock_k8s):
    r = await student_client.get("/api/v1/k8s/namespaces")
    assert r.status_code == 403


async def test_usage_authenticated(student_client, mock_k8s):
    r = await student_client.get("/api/v1/k8s/usage")
    assert r.status_code in (200, 404)


# ── Kubernetes unavailable → 503 (never an empty 200) ─────────────────────


def _unreachable():
    import urllib3

    return urllib3.exceptions.MaxRetryError(None, "/api/v1/nodes", reason="connection refused")


async def test_cluster_stats_unreachable_returns_503(admin_client, mock_k8s):
    mock_k8s["core"].list_node.side_effect = _unreachable()
    r = await admin_client.get("/api/v1/k8s/stats/cluster")
    assert r.status_code == 503
    assert r.json()["detail"]
    assert "connection refused" not in r.text


async def test_namespaces_unreachable_returns_503(teacher_client, mock_k8s):
    mock_k8s["core"].list_namespace.side_effect = _unreachable()
    r = await teacher_client.get("/api/v1/k8s/namespaces")
    assert r.status_code == 503


async def test_pods_unreachable_returns_503(admin_client, mock_k8s):
    mock_k8s["core"].list_pod_for_all_namespaces.side_effect = _unreachable()
    r = await admin_client.get("/api/v1/k8s/pods")
    assert r.status_code == 503


async def test_my_apps_usage_unreachable_returns_503(student_client, mock_k8s):
    mock_k8s["core"].list_pod_for_all_namespaces.side_effect = _unreachable()
    r = await student_client.get("/api/v1/k8s/usage/my-apps")
    assert r.status_code == 503


async def test_ping_reports_false_with_200_when_unreachable(admin_client, mock_k8s):
    mock_k8s["core"].list_namespace.side_effect = _unreachable()
    r = await admin_client.get("/api/v1/k8s/ping")
    assert r.status_code == 200
    assert r.json() == {"k8s": False}


async def test_ping_is_cached(admin_client, mock_k8s):
    for _ in range(3):
        r = await admin_client.get("/api/v1/k8s/ping")
        assert r.json() == {"k8s": True}
    assert mock_k8s["core"].list_namespace.call_count == 1


async def test_cluster_stats_are_cached(admin_client, mock_k8s):
    _empty = MagicMock(items=[])
    mock_k8s["core"].list_node.return_value = _empty
    mock_k8s["core"].list_pod_for_all_namespaces.return_value = _empty
    mock_k8s["core"].list_namespace.return_value = _empty
    for _ in range(2):
        r = await admin_client.get("/api/v1/k8s/stats/cluster")
        assert r.status_code == 200
    assert mock_k8s["core"].list_node.call_count == 1


async def test_my_apps_usage_falls_back_to_requests_without_metrics(student_client, mock_k8s, student_user):
    pod = MagicMock()
    pod.metadata.name = "lab-abc"
    pod.metadata.namespace = f"labondemand-user-{student_user.id}"
    pod.metadata.labels = {"app": "lab", "app-type": "vscode"}
    container = MagicMock()
    container.resources.requests = {"cpu": "250m", "memory": "512Mi"}
    pod.spec.containers = [container]
    mock_k8s["core"].list_pod_for_all_namespaces.return_value = MagicMock(items=[pod])

    from kubernetes import client as k8s_client
    from unittest.mock import patch

    custom = MagicMock()
    custom.list_namespaced_custom_object.side_effect = k8s_client.exceptions.ApiException(status=404)
    with patch("kubernetes.client.CustomObjectsApi", return_value=custom):
        r = await student_client.get("/api/v1/k8s/usage/my-apps")

    assert r.status_code == 200
    body = r.json()
    assert body["metrics"] is False
    assert body["items"] == [
        {"name": "lab", "namespace": pod.metadata.namespace, "app_type": "vscode",
         "cpu_m": 250.0, "mem_mi": 512.0, "pods": 1, "source": "requests"}
    ]
