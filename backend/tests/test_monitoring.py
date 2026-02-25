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
