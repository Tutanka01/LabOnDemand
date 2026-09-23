"""Régressions : le jeton de session ne doit jamais être lisible par JavaScript.

Le jeton ``session_id`` ne doit transiter que via le cookie HttpOnly posé par
le serveur. Il ne doit apparaître ni dans un corps de réponse (JSON ou HTML),
ni dans un en-tête autre que ``Set-Cookie`` (anciennement un en-tête
``session_id`` était renvoyé au login), ni dans l'URL de redirection du SSO.

Couvre aussi la configuration centralisée des cookies (``settings``) et le
garde-fou de démarrage ``COOKIE_DOMAIN`` / ``INGRESS_BASE_DOMAIN``.
"""
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from starlette.responses import Response

from backend.config import settings
from backend.models import User
from backend.session import (
    clear_session_cookie,
    cookie_domain_covers,
    set_session_cookie,
    validate_cookie_settings,
)

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


# ============================================================
# Configuration des cookies : source unique + garde-fous au démarrage
# ============================================================

@pytest.mark.parametrize(
    "cookie_domain, host, expected",
    [
        ("labs.example.com", "labs.example.com", True),
        (".labs.example.com", "labs.example.com", True),
        ("example.com", "labs.example.com", True),
        ("EXAMPLE.COM.", "x.labs.example.com", True),
        ("app.example.com", "labs.example.com", False),
        ("ample.com", "example.com", False),
        ("labs.example.com", "example.com", False),
        (None, "labs.example.com", False),
        ("example.com", None, False),
        ("", "", False),
    ],
)
def test_cookie_domain_covers(cookie_domain, host, expected):
    assert cookie_domain_covers(cookie_domain, host) is expected


@pytest.mark.parametrize("cookie_domain", [".example.com", "example.com", "labs.example.com"])
def test_startup_refuses_cookie_domain_covering_lab_domain(cookie_domain):
    with (
        patch.object(settings, "COOKIE_DOMAIN", cookie_domain),
        patch.object(settings, "INGRESS_BASE_DOMAIN", "labs.example.com"),
    ):
        with pytest.raises(RuntimeError, match="COOKIE_DOMAIN"):
            validate_cookie_settings()


@pytest.mark.parametrize("cookie_domain", [None, "app.example.com"])
def test_startup_accepts_cookie_domain_disjoint_from_lab_domain(cookie_domain):
    with (
        patch.object(settings, "COOKIE_DOMAIN", cookie_domain),
        patch.object(settings, "INGRESS_BASE_DOMAIN", "labs.example.com"),
    ):
        validate_cookie_settings()


def test_startup_rejects_invalid_samesite():
    with patch.object(settings, "SESSION_SAMESITE", "sometimes"):
        with pytest.raises(RuntimeError, match="SESSION_SAMESITE"):
            validate_cookie_settings()


def test_startup_rejects_samesite_none_without_secure():
    with (
        patch.object(settings, "SESSION_SAMESITE", "none"),
        patch.object(settings, "SECURE_COOKIES", False),
    ):
        with pytest.raises(RuntimeError, match="SECURE_COOKIES"):
            validate_cookie_settings()
    with (
        patch.object(settings, "SESSION_SAMESITE", "none"),
        patch.object(settings, "SECURE_COOKIES", True),
    ):
        validate_cookie_settings()


def test_startup_check_reads_environment():
    """Bout en bout : variables d'environnement → Settings → refus explicite."""
    env = dict(
        os.environ,
        COOKIE_DOMAIN=".Example.com",
        INGRESS_BASE_DOMAIN="Labs.Example.com",
    )
    code = (
        "from backend.session import validate_cookie_settings\n"
        "validate_cookie_settings()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode != 0
    assert "COOKIE_DOMAIN" in proc.stderr and "INGRESS_BASE_DOMAIN" in proc.stderr


def test_default_samesite_is_lax():
    assert settings.SESSION_SAMESITE == "lax"


def test_session_cookie_follows_central_settings():
    with (
        patch.object(settings, "COOKIE_DOMAIN", "app.example.com"),
        patch.object(settings, "SECURE_COOKIES", True),
        patch.object(settings, "SESSION_SAMESITE", "strict"),
        patch.object(settings, "SESSION_EXPIRY_HOURS", 2),
    ):
        resp = Response()
        set_session_cookie(resp, "tok")
        header = resp.headers["set-cookie"].lower()
        assert "domain=app.example.com" in header
        assert "secure" in header
        assert "samesite=strict" in header
        assert "max-age=7200" in header
        assert "httponly" in header

        resp = Response()
        clear_session_cookie(resp)
        header = resp.headers["set-cookie"].lower()
        assert "max-age=0" in header
        assert "domain=app.example.com" in header
