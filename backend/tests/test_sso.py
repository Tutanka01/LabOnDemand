"""Tests pour le callback SSO OIDC, en particulier la logique role_override.

Scénarios couverts :
- Nouvel utilisateur SSO → rôle attribué depuis les claims IdP.
- Utilisateur existant sans override → rôle mis à jour depuis les claims IdP.
- Utilisateur existant avec role_override=True → rôle conservé malgré les claims.
- Utilisateur admin SSO → rôle jamais rétrogradé.
"""
import pytest
from unittest.mock import patch

from backend.models import User, UserRole
from backend.security import get_password_hash

BASE = "/api/v1/auth"
STATE = "test-csrf-state-xyz"


# ============================================================
# Helpers
# ============================================================

def _claims(sub: str = "sub001", affiliation: str | list | None = "etudiant") -> dict:
    """Construit un dict de claims OIDC minimaliste."""
    c = {
        "sub": sub,
        "email": f"{sub}@sso.test",
        "preferred_username": sub,
        "name": "Test SSO",
    }
    if affiliation is not None:
        c["eduPersonAffiliation"] = affiliation
    return c


def _oidc_user(db, sub: str, role: UserRole, role_override: bool = False) -> User:
    """Crée un utilisateur SSO directement en base (contourne le callback)."""
    u = User(
        username=sub,
        email=f"{sub}@sso.test",
        hashed_password=get_password_hash("irrelevant"),
        role=role,
        role_override=role_override,
        is_active=True,
        auth_provider="oidc",
        external_id=sub,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


async def _do_callback(client, claims: dict, state: str = STATE):
    """Simule un appel au callback SSO avec les claims IdP mockés."""
    from backend import auth_router
    from backend.config import settings

    with (
        patch.object(settings, "SSO_ENABLED", True),
        patch.object(settings, "FRONTEND_BASE_URL", ""),
        patch.object(auth_router, "exchange_code", return_value={"access_token": "fake-tok"}),
        patch.object(auth_router, "get_userinfo", return_value=claims),
    ):
        return await client.get(
            f"{BASE}/sso/callback",
            params={"code": "auth-code", "state": state},
            cookies={"oidc_state": state},
            follow_redirects=False,
        )


# ============================================================
# Création d'un nouvel utilisateur
# ============================================================

async def test_sso_callback_creates_new_user(client, db):
    """Un compte inconnu doit être créé avec le rôle issu des claims."""
    claims = _claims(sub="newuser001", affiliation="etudiant")
    r = await _do_callback(client, claims)
    # Le callback redirige vers FRONTEND_BASE_URL (ici "")
    assert r.status_code in (302, 307)

    user = db.query(User).filter(User.external_id == "newuser001").first()
    assert user is not None
    assert user.role == UserRole.student
    assert user.role_override is False


async def test_sso_callback_new_user_teacher_claim(client, db):
    """Un nouvel utilisateur avec un claim enseignant doit obtenir le rôle teacher."""
    claims = _claims(sub="newteacher001", affiliation="enseignant")
    r = await _do_callback(client, claims)
    assert r.status_code in (302, 307)

    user = db.query(User).filter(User.external_id == "newteacher001").first()
    assert user is not None
    assert user.role == UserRole.teacher


# ============================================================
# Utilisateur existant sans role_override
# ============================================================

async def test_sso_callback_updates_role_without_override(client, db):
    """Sans override, le rôle est mis à jour depuis les claims à chaque connexion."""
    _oidc_user(db, sub="dynrole", role=UserRole.student, role_override=False)

    # L'IdP dit maintenant que l'utilisateur est enseignant
    claims = _claims(sub="dynrole", affiliation="enseignant")
    r = await _do_callback(client, claims)
    assert r.status_code in (302, 307)

    user = db.query(User).filter(User.external_id == "dynrole").first()
    db.refresh(user)
    assert user.role == UserRole.teacher


# ============================================================
# Utilisateur existant avec role_override=True
# ============================================================

async def test_sso_callback_respects_role_override(client, db):
    """Avec role_override=True, les claims IdP ne doivent pas modifier le rôle."""
    _oidc_user(db, sub="overrideuser", role=UserRole.teacher, role_override=True)

    # L'IdP continue d'envoyer « etudiant » mais l'admin a promu l'utilisateur
    claims = _claims(sub="overrideuser", affiliation="etudiant")
    r = await _do_callback(client, claims)
    assert r.status_code in (302, 307)

    user = db.query(User).filter(User.external_id == "overrideuser").first()
    db.refresh(user)
    assert user.role == UserRole.teacher, (
        "Le rôle défini manuellement par l'admin doit être conservé"
    )


async def test_sso_callback_override_preserved_after_multiple_logins(client, db):
    """Plusieurs connexions SSO consécutives ne doivent pas effacer l'override."""
    _oidc_user(db, sub="multilogin", role=UserRole.teacher, role_override=True)
    claims = _claims(sub="multilogin", affiliation="etudiant")

    for _ in range(3):
        r = await _do_callback(client, claims)
        assert r.status_code in (302, 307)

    user = db.query(User).filter(User.external_id == "multilogin").first()
    db.refresh(user)
    assert user.role == UserRole.teacher
    assert user.role_override is True


# ============================================================
# Protection des admins
# ============================================================

async def test_sso_callback_never_downgrades_admin(client, db):
    """Un compte admin SSO ne doit jamais être rétrogradé, même sans override explicite."""
    _oidc_user(db, sub="ssoadmin", role=UserRole.admin, role_override=False)

    claims = _claims(sub="ssoadmin", affiliation="etudiant")
    r = await _do_callback(client, claims)
    assert r.status_code in (302, 307)

    user = db.query(User).filter(User.external_id == "ssoadmin").first()
    db.refresh(user)
    assert user.role == UserRole.admin


# ============================================================
# Sécurité CSRF
# ============================================================

async def test_sso_callback_rejects_invalid_state(client):
    """Un state CSRF invalide doit être rejeté avec 400."""
    from backend import auth_router
    from backend.config import settings

    with (
        patch.object(settings, "SSO_ENABLED", True),
        patch.object(auth_router, "exchange_code", return_value={"access_token": "tok"}),
        patch.object(auth_router, "get_userinfo", return_value=_claims()),
    ):
        r = await client.get(
            f"{BASE}/sso/callback",
            params={"code": "auth-code", "state": "wrong-state"},
            cookies={"oidc_state": "correct-state"},
            follow_redirects=False,
        )
    assert r.status_code == 400


async def test_sso_callback_rejects_idp_error(client):
    """Un paramètre 'error' renvoyé par l'IdP doit aboutir à un 401."""
    from backend.config import settings

    with patch.object(settings, "SSO_ENABLED", True):
        r = await client.get(
            f"{BASE}/sso/callback",
            params={"error": "access_denied", "state": STATE},
            cookies={"oidc_state": STATE},
            follow_redirects=False,
        )
    assert r.status_code == 401
