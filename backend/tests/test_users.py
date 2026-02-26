"""Tests for user management endpoints (admin-only CRUD)."""
import pytest

BASE = "/api/v1/auth"
STRONG_PASS = "ValidPass@9999!"


# ============================================================
# List users
# ============================================================

async def test_list_users_admin(admin_client, student_user, teacher_user):
    r = await admin_client.get(f"{BASE}/users")
    assert r.status_code in (200, 204)
    usernames = [u["username"] for u in r.json()]
    assert "teststudent" in usernames
    assert "testteacher" in usernames


async def test_list_users_student_forbidden(student_client):
    r = await student_client.get(f"{BASE}/users")
    assert r.status_code == 403


async def test_list_users_teacher_forbidden(teacher_client):
    r = await teacher_client.get(f"{BASE}/users")
    assert r.status_code == 403


async def test_list_users_unauthenticated(client):
    r = await client.get(f"{BASE}/users")
    assert r.status_code == 401


async def test_list_users_pagination(admin_client, db):
    """skip and limit query params must be honoured."""
    from backend.models import User, UserRole
    from backend.security import get_password_hash
    for i in range(5):
        db.add(User(
            username=f"paginuser{i}",
            email=f"paginuser{i}@test.lab",
            hashed_password=get_password_hash(STRONG_PASS),
            role=UserRole.student,
            is_active=True,
            auth_provider="local",
        ))
    db.commit()
    r = await admin_client.get(f"{BASE}/users?skip=0&limit=2")
    assert r.status_code in (200, 204)
    assert len(r.json()) <= 2


# ============================================================
# Create user
# ============================================================

async def test_create_user_admin(admin_client):
    payload = {
        "username": "newstudent",
        "email": "newstudent@test.lab",
        "password": STRONG_PASS,
        "role": "student",
    }
    r = await admin_client.post(f"{BASE}/register", json=payload)
    assert r.status_code in (200, 201)
    body = r.json()
    assert body["username"] == "newstudent"
    assert "hashed_password" not in body


async def test_create_user_duplicate_username(admin_client, admin_user):
    payload = {
        "username": "testadmin",
        "email": "other@test.lab",
        "password": STRONG_PASS,
        "role": "student",
    }
    r = await admin_client.post(f"{BASE}/register", json=payload)
    assert r.status_code == 400


async def test_create_user_duplicate_email(admin_client, admin_user):
    payload = {
        "username": "otheradmin",
        "email": "admin@test.lab",
        "password": STRONG_PASS,
        "role": "student",
    }
    r = await admin_client.post(f"{BASE}/register", json=payload)
    assert r.status_code == 400


async def test_create_user_weak_password(admin_client):
    payload = {
        "username": "weakpass",
        "email": "weakpass@test.lab",
        "password": "short",
        "role": "student",
    }
    r = await admin_client.post(f"{BASE}/register", json=payload)
    assert r.status_code in (400, 422)


async def test_create_user_as_student_forbidden(student_client):
    payload = {
        "username": "sneaky",
        "email": "sneaky@test.lab",
        "password": STRONG_PASS,
        "role": "admin",
    }
    r = await student_client.post(f"{BASE}/register", json=payload)
    assert r.status_code == 403


# ============================================================
# Get user by ID
# ============================================================

async def test_get_user_by_id(admin_client, student_user):
    r = await admin_client.get(f"{BASE}/users/{student_user.id}")
    assert r.status_code in (200, 204)
    assert r.json()["username"] == "teststudent"


async def test_get_nonexistent_user(admin_client):
    r = await admin_client.get(f"{BASE}/users/99999")
    assert r.status_code == 404


async def test_get_user_student_forbidden(student_client, admin_user):
    r = await student_client.get(f"{BASE}/users/{admin_user.id}")
    assert r.status_code == 403


# ============================================================
# Update user
# ============================================================

async def test_update_user_email(admin_client, student_user):
    r = await admin_client.put(
        f"{BASE}/users/{student_user.id}",
        json={"email": "updated@test.lab"},
    )
    assert r.status_code in (200, 204)
    assert r.json()["email"] == "updated@test.lab"


async def test_update_user_role(admin_client, student_user):
    r = await admin_client.put(
        f"{BASE}/users/{student_user.id}",
        json={"role": "teacher"},
    )
    assert r.status_code in (200, 204)
    assert r.json()["role"] == "teacher"


async def test_update_user_role_sets_override_flag(admin_client, student_user, db):
    """Changer le rôle via l'API admin doit positionner role_override=True en base."""
    r = await admin_client.put(
        f"{BASE}/users/{student_user.id}",
        json={"role": "teacher"},
    )
    assert r.status_code in (200, 204)
    db.refresh(student_user)
    assert student_user.role_override is True


async def test_update_user_without_role_does_not_set_override(admin_client, student_user, db):
    """Modifier un champ autre que le rôle ne doit pas activer role_override."""
    r = await admin_client.put(
        f"{BASE}/users/{student_user.id}",
        json={"full_name": "Just a name"},
    )
    assert r.status_code in (200, 204)
    db.refresh(student_user)
    assert student_user.role_override is False


async def test_update_user_deactivate(admin_client, student_user):
    r = await admin_client.put(
        f"{BASE}/users/{student_user.id}",
        json={"is_active": False},
    )
    assert r.status_code in (200, 204)
    assert r.json()["is_active"] is False


async def test_update_user_student_forbidden(student_client, admin_user):
    r = await student_client.put(
        f"{BASE}/users/{admin_user.id}",
        json={"email": "hack@test.lab"},
    )
    assert r.status_code == 403


# ============================================================
# Delete user
# ============================================================

async def test_delete_user(admin_client, student_user):
    r = await admin_client.delete(f"{BASE}/users/{student_user.id}")
    assert r.status_code in (200, 204)


async def test_delete_nonexistent_user(admin_client):
    r = await admin_client.delete(f"{BASE}/users/99999")
    assert r.status_code == 404


async def test_delete_user_student_forbidden(student_client, admin_user):
    r = await student_client.delete(f"{BASE}/users/{admin_user.id}")
    assert r.status_code == 403
