"""Tests for basic API health endpoints (no auth required)."""
import urllib3


async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "LabOnDemand" in r.json()["message"]


async def test_status(client):
    r = await client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "version" in body


async def test_health_connected(client, mock_k8s):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok"
    assert body["redis"] == "ok"
    assert body["k8s"] == "ok"
    assert body["status"] == "healthy"
    assert "timestamp" in body


async def test_health_degraded_does_not_leak_error_text(client, mock_k8s):
    mock_k8s["core"].list_namespace.side_effect = urllib3.exceptions.MaxRetryError(
        None, "https://10.0.0.1:6443/api/v1/namespaces", reason="secret-host refused"
    )
    r = await client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["k8s"] == "error"
    assert body["db"] == "ok"
    assert "secret-host" not in r.text
    assert "10.0.0.1" not in r.text
