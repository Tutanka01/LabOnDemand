"""Régressions : le jeton de session ne doit jamais être lisible par JavaScript.

Le jeton ``session_id`` ne doit transiter que via le cookie HttpOnly posé par
le serveur. Il ne doit apparaître ni dans un corps de réponse (JSON ou HTML),
ni dans un en-tête autre que ``Set-Cookie`` (anciennement un en-tête
``session_id`` était renvoyé au login), ni dans l'URL de redirection du SSO.
"""
from unittest.mock import patch

from backend.models import User

BASE = "/api/v1/auth"
STATE = "state-token-exposure"


def _session_cookie_header(response) -> str:
    """Retourne l'en-tête Set-Cookie qui pose ``session_id``."""
    cookies = [c for c in response.headers.get_list("set-cookie") if c.startswith("session_id=")]
    assert len(cookies) == 1, cookies
    return cookies[0]


def _assert_token_not_leaked(response, token: str) -> None:
    """Le jeton ne doit figurer ni dans le corps ni dans un en-tête non-cookie."""
    assert token
    assert token not in response.text
    for name, value in response.headers.multi_items():
        if name.lower() == "set-cookie":
            continue
        assert token not in value, f"jeton exposé dans l'en-tête {name!r}"
        assert name.lower() != "session_id", "en-tête session_id renvoyé au client"


async def test_login_does_not_expose_session_token(client, admin_user):
    r = await client.post(
        f"{BASE}/login",
        json={"username": "testadmin", "password": "TestAdmin@1234!"},
    )
    assert r.status_code == 200
    token = r.cookies.get("session_id")
    _assert_token_not_leaked(r, token)
    assert set(r.json().keys()) == {"user"}


async def test_login_session_cookie_is_httponly(client, admin_user):
    r = await client.post(
        f"{BASE}/login",
        json={"username": "testadmin", "password": "TestAdmin@1234!"},
    )
    assert r.status_code == 200
    header = _session_cookie_header(r).lower()
    assert "httponly" in header
    assert "path=/" in header
    assert "samesite=lax" in header


async def test_authenticated_responses_do_not_echo_session_token(admin_client, admin_token):
    r = await admin_client.get(f"{BASE}/me")
    assert r.status_code == 200
    _assert_token_not_leaked(r, admin_token)

    r = await admin_client.post(f"{BASE}/logout")
    assert r.status_code == 200
    _assert_token_not_leaked(r, admin_token)


async def test_sso_callback_does_not_expose_session_token(client, db):
    from backend import auth_router
    from backend.config import settings

    claims = {
        "sub": "leak001",
        "email": "leak001@sso.test",
        "preferred_username": "leak001",
        "name": "Leak Test",
        "eduPersonAffiliation": "etudiant",
    }
    with (
        patch.object(settings, "SSO_ENABLED", True),
        patch.object(settings, "FRONTEND_BASE_URL", "https://lab.example.test/app"),
        patch.object(auth_router, "exchange_code", return_value={"access_token": "fake"}),
        patch.object(auth_router, "get_userinfo", return_value=claims),
    ):
        r = await client.get(
            f"{BASE}/sso/callback",
            params={"code": "auth-code", "state": STATE},
            cookies={"oidc_state": STATE},
            follow_redirects=False,
        )

    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://lab.example.test/app"
    token = r.cookies.get("session_id")
    _assert_token_not_leaked(r, token)
    assert "httponly" in _session_cookie_header(r).lower()
    assert db.query(User).filter(User.external_id == "leak001").first() is not None


def test_login_response_schema_has_no_session_field():
    from backend.schemas import LoginResponse

    assert "session_id" not in LoginResponse.model_fields
