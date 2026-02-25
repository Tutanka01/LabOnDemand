"""Tests for authentication endpoints: login, logout, me, SSO status, password change."""
import pytest

BASE = "/api/v1/auth"


# ============================================================
# Login
# ============================================================

async def test_login_success(client, admin_user):
    r = await client.post(f"{BASE}/login", json={"username": "testadmin", "password": "TestAdmin@1234!"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "testadmin"
    assert body["user"]["role"] == "admin"
    assert "session_id" in body
    assert "session_id" in r.cookies


async def test_login_wrong_password(client, admin_user):
    r = await client.post(f"{BASE}/login", json={"username": "testadmin", "password": "WrongPassword!"})
    assert r.status_code == 401


async def test_login_unknown_user(client):
    r = await client.post(f"{BASE}/login", json={"username": "ghost", "password": "DoesNotMatter1!"})
    assert r.status_code == 401


async def test_login_inactive_user(client, inactive_user):
    r = await client.post(f"{BASE}/login", json={"username": "inactive", "password": "StudPass@9012!"})
    assert r.status_code == 401


async def test_login_oidc_user_cannot_use_local_login(client, oidc_user):
    """SSO-only accounts must not be accessible via the local login form."""
    r = await client.post(f"{BASE}/login", json={"username": "ssouser", "password": "anything"})
    assert r.status_code == 401


# ============================================================
# Logout
# ============================================================

async def test_logout(admin_client):
    r = await admin_client.post(f"{BASE}/logout")
    assert r.status_code == 200


async def test_logout_clears_session(client, admin_user, admin_token):
    """After logout, the session token must no longer authenticate."""
    r = await client.post(f"{BASE}/logout", cookies={"session_id": admin_token})
    assert r.status_code == 200
    r2 = await client.get(f"{BASE}/me", cookies={"session_id": admin_token})
    assert r2.status_code == 401


async def test_logout_no_session(client):
    r = await client.post(f"{BASE}/logout")
    assert r.status_code != 500


# ============================================================
# GET /me
# ============================================================

async def test_get_me_authenticated(admin_client, admin_user):
    r = await admin_client.get(f"{BASE}/me")
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "testadmin"
    assert body["role"] == "admin"
    assert "hashed_password" not in body


async def test_get_me_unauthenticated(client):
    r = await client.get(f"{BASE}/me")
    assert r.status_code == 401


async def test_get_me_student(student_client, student_user):
    r = await student_client.get(f"{BASE}/me")
    assert r.status_code == 200
    assert r.json()["role"] == "student"


# ============================================================
# SSO status
# ============================================================

async def test_sso_status_disabled(client):
    r = await client.get(f"{BASE}/sso/status")
    assert r.status_code == 200
    assert r.json()["sso_enabled"] is False


# ============================================================
# Check-role
# ============================================================

async def test_check_role_admin(admin_client):
    r = await admin_client.get(f"{BASE}/check-role")
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


async def test_check_role_student(student_client):
    r = await student_client.get(f"{BASE}/check-role")
    assert r.status_code == 200
    assert r.json()["role"] == "student"


async def test_check_role_unauthenticated(client):
    r = await client.get(f"{BASE}/check-role")
    assert r.status_code == 401


# ============================================================
# Update own profile
# ============================================================

async def test_update_own_profile(student_client):
    r = await student_client.put(f"{BASE}/me", json={"full_name": "Test Student"})
    assert r.status_code == 200
    assert r.json()["full_name"] == "Test Student"


async def test_update_own_profile_unauthenticated(client):
    r = await client.put(f"{BASE}/me", json={"full_name": "Ghost"})
    assert r.status_code == 401


# ============================================================
# Change password
# ============================================================

async def test_change_password_success(admin_client):
    r = await admin_client.post(
        f"{BASE}/change-password",
        params={"old_password": "TestAdmin@1234!", "new_password": "NewAdmin@5678!"},
    )
    assert r.status_code == 200


async def test_change_password_wrong_current(admin_client):
    r = await admin_client.post(
        f"{BASE}/change-password",
        params={"old_password": "WrongPass!", "new_password": "NewAdmin@5678!"},
    )
    assert r.status_code in (400, 401, 403)


async def test_change_password_weak_new(admin_client):
    r = await admin_client.post(
        f"{BASE}/change-password",
        params={"old_password": "TestAdmin@1234!", "new_password": "weak"},
    )
    assert r.status_code in (400, 422)


async def test_change_password_unauthenticated(client):
    r = await client.post(
        f"{BASE}/change-password",
        params={"old_password": "TestAdmin@1234!", "new_password": "NewAdmin@5678!"},
    )
    assert r.status_code == 401
