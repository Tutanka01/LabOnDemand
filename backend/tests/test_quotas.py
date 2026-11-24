"""Tests for quota endpoints."""
import pytest
from unittest.mock import MagicMock, patch


async def test_quotas_student(student_client, mock_k8s, student_user):
    # Minimal mock so get_user_quota_summary() doesn't fail on K8s
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(items=[])
    mock_k8s["core"].list_namespaced_persistent_volume_claim.return_value = MagicMock(items=[])

    r = await student_client.get("/api/v1/quotas/me")
    assert r.status_code == 200
    body = r.json()
    assert "max_labs" in body or "deployments" in body or "quota" in body or isinstance(body, dict)


async def test_quotas_admin(admin_client, mock_k8s, admin_user):
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(items=[])
    mock_k8s["core"].list_namespaced_persistent_volume_claim.return_value = MagicMock(items=[])

    r = await admin_client.get("/api/v1/quotas/me")
    assert r.status_code == 200


async def test_quotas_teacher(teacher_client, mock_k8s):
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(items=[])
    mock_k8s["core"].list_namespaced_persistent_volume_claim.return_value = MagicMock(items=[])

    r = await teacher_client.get("/api/v1/quotas/me")
    assert r.status_code == 200


async def test_quotas_unauthenticated(client):
    r = await client.get("/api/v1/quotas/me")
    assert r.status_code == 401


async def test_quotas_response_shape(student_client, mock_k8s):
    """The quota summary must be a dict (not a list)."""
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = MagicMock(items=[])
    mock_k8s["core"].list_namespaced_persistent_volume_claim.return_value = MagicMock(items=[])

    r = await student_client.get("/api/v1/quotas/me")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


async def test_quotas_unreachable_cluster_returns_503(student_client, monkeypatch):
    import urllib3
    from backend.deployment_service import deployment_service

    def _boom(user):
        raise urllib3.exceptions.MaxRetryError(None, "/api", reason="refused")

    monkeypatch.setattr(deployment_service, "get_user_quota_summary", _boom)
    r = await student_client.get("/api/v1/quotas/me")
    assert r.status_code == 503
