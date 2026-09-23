"""Tests for basic API health endpoints (no auth required)."""
import pytest


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
    assert body["status"] == "healthy"
    assert body["db"] == "ok"
    assert body["redis"] == "ok"
    assert body["k8s"] == "ok"
