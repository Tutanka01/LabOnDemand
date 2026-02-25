"""Tests for runtime config CRUD endpoints (admin-only)."""
import pytest

BASE = "/api/v1/k8s"


async def test_list_runtime_configs_admin(admin_client, sample_runtime_config):
    r = await admin_client.get(f"{BASE}/runtime-configs")
    assert r.status_code == 200
    keys = [rc["key"] for rc in r.json()]
    assert "vscode" in keys


async def test_list_runtime_configs_student_forbidden(student_client):
    r = await student_client.get(f"{BASE}/runtime-configs")
    assert r.status_code == 403


async def test_list_runtime_configs_unauthenticated(client):
    r = await client.get(f"{BASE}/runtime-configs")
    assert r.status_code == 401


async def test_create_runtime_config(admin_client):
    payload = {
        "key": "jupyter-rc",
        "default_image": "jupyter/base-notebook:latest",
        "target_port": 8888,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
        "active": True,
    }
    r = await admin_client.post(f"{BASE}/runtime-configs", json=payload)
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["key"] == "jupyter-rc"
    assert "id" in body


async def test_create_runtime_config_duplicate_key(admin_client, sample_runtime_config):
    payload = {
        "key": "vscode",  # already exists
        "default_image": "other:latest",
        "target_port": 8080,
        "default_service_type": "NodePort",
        "allowed_for_students": True,
        "active": True,
    }
    r = await admin_client.post(f"{BASE}/runtime-configs", json=payload)
    assert r.status_code == 400


async def test_create_runtime_config_student_forbidden(student_client):
    payload = {"key": "evil", "default_service_type": "NodePort", "active": True,
               "allowed_for_students": True}
    r = await student_client.post(f"{BASE}/runtime-configs", json=payload)
    assert r.status_code == 403


async def test_update_runtime_config(admin_client, sample_runtime_config):
    r = await admin_client.put(
        f"{BASE}/runtime-configs/{sample_runtime_config.id}",
        json={"allowed_for_students": False, "active": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["allowed_for_students"] is False
    assert body["active"] is False


async def test_update_nonexistent_runtime_config(admin_client):
    r = await admin_client.put(f"{BASE}/runtime-configs/99999", json={"active": False})
    assert r.status_code == 404


async def test_delete_runtime_config(admin_client, sample_runtime_config):
    r = await admin_client.delete(f"{BASE}/runtime-configs/{sample_runtime_config.id}")
    assert r.status_code == 200


async def test_delete_nonexistent_runtime_config(admin_client):
    r = await admin_client.delete(f"{BASE}/runtime-configs/99999")
    assert r.status_code == 404


async def test_delete_runtime_config_student_forbidden(student_client, sample_runtime_config):
    r = await student_client.delete(f"{BASE}/runtime-configs/{sample_runtime_config.id}")
    assert r.status_code == 403
