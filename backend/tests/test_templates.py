"""Tests for template CRUD endpoints and resource-presets."""
import pytest

BASE = "/api/v1/k8s"


# ============================================================
# List templates
# ============================================================

async def test_list_templates_returns_active(admin_client, sample_template, inactive_template):
    r = await admin_client.get(f"{BASE}/templates")
    assert r.status_code == 200
    body = r.json()
    items = body.get("templates", body) if isinstance(body, dict) else body
    ids = [t.get("id") or t.get("key") for t in items]
    assert "vscode-test" in ids
    # Inactive template is excluded from the default list (active-only view)
    assert "hidden-tpl" not in ids


async def test_list_all_templates_admin(admin_client, sample_template, inactive_template):
    """GET /templates/all must return ALL templates regardless of active flag."""
    r = await admin_client.get(f"{BASE}/templates/all")
    assert r.status_code == 200
    items = r.json()
    keys = [t["key"] for t in items]
    assert "vscode-test" in keys
    assert "hidden-tpl" in keys


async def test_list_all_templates_student_forbidden(student_client):
    r = await student_client.get(f"{BASE}/templates/all")
    assert r.status_code == 403


async def test_list_templates_unauthenticated(client):
    r = await client.get(f"{BASE}/templates")
    assert r.status_code == 401


# ============================================================
# Create template
# ============================================================

async def test_create_template_admin(admin_client):
    payload = {
        "key": "my-tpl",
        "name": "My Template",
        "deployment_type": "custom",
        "default_port": 8080,
        "default_service_type": "NodePort",
        "active": True,
    }
    r = await admin_client.post(f"{BASE}/templates", json=payload)
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["key"] == "my-tpl"
    assert "id" in body


async def test_create_template_duplicate_key(admin_client, sample_template):
    payload = {
        "key": "vscode-test",  # already exists
        "name": "Duplicate",
        "deployment_type": "custom",
        "default_service_type": "NodePort",
        "active": True,
    }
    r = await admin_client.post(f"{BASE}/templates", json=payload)
    assert r.status_code == 400


async def test_create_template_student_forbidden(student_client):
    payload = {"key": "evil-tpl", "name": "Evil", "deployment_type": "custom",
               "default_service_type": "NodePort", "active": True}
    r = await student_client.post(f"{BASE}/templates", json=payload)
    assert r.status_code == 403


async def test_create_template_invalid_key(admin_client):
    """deployment_type must match ^[a-z0-9][a-z0-9-]{1,49}$ - tested here as field validation."""
    payload = {"key": "good-key", "name": "Bad", "deployment_type": "INVALID TYPE",
               "default_service_type": "NodePort", "active": True}
    r = await admin_client.post(f"{BASE}/templates", json=payload)
    assert r.status_code == 422


# ============================================================
# Update template
# ============================================================

async def test_update_template(admin_client, sample_template):
    r = await admin_client.put(
        f"{BASE}/templates/{sample_template.id}",
        json={"name": "Updated Name", "active": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Updated Name"
    assert body["active"] is False


async def test_update_nonexistent_template(admin_client):
    r = await admin_client.put(f"{BASE}/templates/99999", json={"name": "Ghost"})
    assert r.status_code == 404


async def test_update_template_student_forbidden(student_client, sample_template):
    r = await student_client.put(f"{BASE}/templates/{sample_template.id}", json={"name": "Hack"})
    assert r.status_code == 403


# ============================================================
# Delete template
# ============================================================

async def test_delete_template(admin_client, sample_template):
    r = await admin_client.delete(f"{BASE}/templates/{sample_template.id}")
    assert r.status_code == 200


async def test_delete_nonexistent_template(admin_client):
    r = await admin_client.delete(f"{BASE}/templates/99999")
    assert r.status_code == 404


async def test_delete_template_student_forbidden(student_client, sample_template):
    r = await student_client.delete(f"{BASE}/templates/{sample_template.id}")
    assert r.status_code == 403


# ============================================================
# Resource presets
# ============================================================

async def test_resource_presets_student(student_client):
    r = await student_client.get(f"{BASE}/resource-presets")
    assert r.status_code == 200
    body = r.json()
    # Should contain at least CPU and memory fields
    assert any("cpu" in str(k).lower() for k in body)


async def test_resource_presets_admin(admin_client):
    r = await admin_client.get(f"{BASE}/resource-presets")
    assert r.status_code == 200


async def test_resource_presets_unauthenticated(client):
    r = await client.get(f"{BASE}/resource-presets")
    assert r.status_code == 401
