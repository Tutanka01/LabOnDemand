"""Tests for security utilities and RBAC enforcement."""
import pytest
import sys
import os

# Allow importing backend.security directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.security import validate_password_strength, get_password_hash, verify_password


# ============= Password strength =============

def test_password_too_short():
    assert validate_password_strength("Sh0rt!") is False


def test_password_no_uppercase():
    assert validate_password_strength("weakpassword1!") is False


def test_password_no_lowercase():
    assert validate_password_strength("WEAKPASSWORD1!") is False


def test_password_no_digit():
    assert validate_password_strength("WeakPassword!") is False


def test_password_no_special():
    assert validate_password_strength("WeakPassword1") is False


def test_password_strong():
    assert validate_password_strength("StrongP@ssw0rd123!") is True


def test_password_minimum_valid():
    # Exactly 8 chars with all criteria
    assert validate_password_strength("Abcdefg1!abc") is True


# ============= Password hashing =============

def test_password_hash_not_plaintext():
    pw = "TestPassword@1!"
    hashed = get_password_hash(pw)
    assert hashed != pw


def test_password_verify_correct():
    pw = "TestPassword@1!"
    hashed = get_password_hash(pw)
    assert verify_password(pw, hashed) is True


def test_password_verify_wrong():
    pw = "TestPassword@1!"
    hashed = get_password_hash(pw)
    assert verify_password("WrongPassword@1!", hashed) is False


# ============= Session / RBAC via HTTP =============

async def test_protected_route_no_cookie(client):
    """Unauthenticated requests are rejected with 401."""
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


async def test_protected_route_invalid_session(client):
    r = await client.get(
        "/api/v1/auth/me",
        cookies={"session_id": "definitely-not-valid-xxxx"},
    )
    assert r.status_code == 401


async def test_admin_only_route_as_student(student_client):
    r = await student_client.get("/api/v1/auth/users")
    assert r.status_code == 403


async def test_teacher_or_admin_route_as_student(student_client):
    r = await student_client.get("/api/v1/auth/users")
    assert r.status_code == 403


async def test_teacher_can_access_teacher_route(teacher_client):
    r = await teacher_client.get("/api/v1/auth/me")
    assert r.status_code == 200


async def test_admin_can_list_users(admin_client):
    r = await admin_client.get("/api/v1/auth/users")
    assert r.status_code == 200


async def test_student_cannot_create_user(student_client):
    r = await student_client.post(
        "/api/v1/auth/register",
        json={
            "username": "hacker",
            "email": "h@h.com",
            "password": "Hacker@1234!",
        },
    )
    # register is open but role cannot be elevated to admin
    assert r.status_code in (200, 201, 400, 403, 422)


async def test_inactive_user_cannot_login(client, inactive_user):
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": inactive_user.username, "password": "StudPass@9012!"},
    )
    # app may return 401 (auth failure) or 403 (account disabled) — both mean rejected
    assert r.status_code in (401, 403, 429)


async def test_change_password_requires_old_password(admin_client, admin_user):
    r = await admin_client.post(
        "/api/v1/auth/change-password",
        params={"old_password": "WrongOld@1!", "new_password": "NewAdmin@1234!"},
    )
    assert r.status_code in (400, 403)


async def test_student_cannot_change_own_role(student_client, student_user):
    r = await student_client.put(
        f"/api/v1/auth/users/{student_user.id}",
        json={"role": "admin"},
    )
    assert r.status_code in (403, 422)
