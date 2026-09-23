"""Tests de la protection CSRF (backend/csrf.py).

Deux contrôles cumulatifs sur toute requête mutante sous /api/ :
en-tête ``X-Requested-With: XMLHttpRequest`` obligatoire, puis ``Origin``
(ou, à défaut, ``Referer``) de confiance.
"""
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend import csrf
from backend.config import settings
from backend.database import get_db
from backend.main import app
from backend.models import User

from .conftest import ADMIN_PASSWORD, CSRF_HEADERS, _db_override

AUTH = "/api/v1/auth"
XRW = CSRF_HEADERS


@pytest.fixture()
async def bare_client(db, admin_token):
    """Client authentifié (admin) qui n'envoie PAS l'en-tête anti-CSRF."""
    app.dependency_overrides[get_db] = _db_override(db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session_id": admin_token},
    ) as c:
        yield c
    app.dependency_overrides.clear()


def _assert_csrf_rejected(response) -> None:
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["error"] == "csrf_failed"
    assert body["detail"]


# ============================================================
# En-tête personnalisé obligatoire
# ============================================================

@pytest.mark.parametrize(
    "method, path",
    [
        ("POST", f"{AUTH}/logout"),
        ("PUT", f"{AUTH}/me"),
        ("DELETE", f"{AUTH}/users/1"),
        ("PATCH", f"{AUTH}/me"),
        ("POST", "/api/v1/k8s/deployments"),
        ("DELETE", "/api/v1/k8s/pvcs/some-pvc"),
    ],
)
async def test_unsafe_request_without_custom_header_is_rejected(bare_client, method, path):
    r = await bare_client.request(method, path, json={})
    _assert_csrf_rejected(r)


async def test_rejected_request_has_no_side_effect(bare_client, admin_token):
    from backend.session_store import session_store

    r = await bare_client.post(f"{AUTH}/logout")
    _assert_csrf_rejected(r)
    # La session n'a pas été détruite : la requête n'a jamais atteint la route.
    assert session_store.get(admin_token) is not None
    r = await bare_client.get(f"{AUTH}/me")
    assert r.status_code == 200


@pytest.mark.parametrize("value", ["", "fetch", "com.android.browser", "XMLHttpRequest2"])
async def test_wrong_custom_header_value_is_rejected(bare_client, value):
    r = await bare_client.post(f"{AUTH}/logout", headers={"X-Requested-With": value})
    _assert_csrf_rejected(r)


async def test_custom_header_value_is_case_insensitive(bare_client):
    r = await bare_client.post(f"{AUTH}/logout", headers={"x-requested-with": "xmlhttprequest"})
    assert r.status_code == 200


async def test_safe_methods_are_not_checked(bare_client):
    headers = {"Origin": "https://evil.example"}
    assert (await bare_client.get(f"{AUTH}/me", headers=headers)).status_code == 200
    assert (await bare_client.head(f"{AUTH}/me", headers=headers)).status_code != 403


async def test_non_api_paths_are_out_of_scope(bare_client):
    # Aucune route mutante hors /api/ : le routeur répond 405, pas le CSRF.
    r = await bare_client.post("/")
    assert r.status_code == 405


@pytest.mark.parametrize("path", ["//api/v1/auth/logout", "/api//v1/auth/logout", "///api/x"])
def test_repeated_slashes_do_not_bypass(path):
    scope = {"type": "http", "method": "POST", "path": path, "headers": [], "scheme": "http"}
    assert csrf.csrf_rejection_reason(scope) == "missing_custom_header"


async def test_multipart_user_import_is_rejected(bare_client, db):
    csv = b"username,email,password,role\nmallory,mallory@evil.test,Mallory@12345!,admin\n"
    r = await bare_client.post(
        f"{AUTH}/users/import",
        files={"file": ("users.csv", csv, "text/csv")},
    )
    _assert_csrf_rejected(r)
    assert db.query(User).filter(User.username == "mallory").first() is None


# ============================================================
# Login CSRF : la connexion est protégée comme le reste
# ============================================================

async def test_login_without_custom_header_is_rejected(bare_client, admin_user):
    r = await bare_client.post(
        f"{AUTH}/login", json={"username": "testadmin", "password": ADMIN_PASSWORD}
    )
    _assert_csrf_rejected(r)
    assert "session_id" not in r.cookies


async def test_login_from_untrusted_origin_is_rejected(client, admin_user):
    r = await client.post(
        f"{AUTH}/login",
        json={"username": "testadmin", "password": ADMIN_PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    _assert_csrf_rejected(r)
    assert "session_id" not in r.cookies


async def test_login_from_trusted_origin_succeeds(client, admin_user):
    r = await client.post(
        f"{AUTH}/login",
        json={"username": "testadmin", "password": ADMIN_PASSWORD},
        headers={"Origin": "http://localhost"},
    )
    assert r.status_code == 200
    assert "session_id" in r.cookies


# ============================================================
# Vérification de l'origine
# ============================================================

@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example",
        "null",
        "http://localhost.evil.example",
        "http://localhost:8081",  # port différent = autre origine
        "https://localhost",  # schéma différent = autre origine
        "http://localhost/path",  # un en-tête Origin n'a jamais de chemin
        "http://user@localhost",
        "javascript:alert(1)",
        "garbage",
    ],
)
async def test_untrusted_origin_is_rejected(admin_client, origin):
    r = await admin_client.post(f"{AUTH}/logout", headers={"Origin": origin})
    _assert_csrf_rejected(r)


@pytest.mark.parametrize(
    "origin",
    ["http://localhost", "http://LOCALHOST:80", "http://127.0.0.1:8000", "http://localhost:8000"],
)
async def test_origin_from_cors_origins_is_accepted(admin_client, origin):
    r = await admin_client.post(f"{AUTH}/logout", headers={"Origin": origin})
    assert r.status_code == 200


async def test_frontend_base_url_origin_is_accepted(admin_client):
    with patch.object(settings, "FRONTEND_BASE_URL", "https://labondemand.example.org/app/"):
        r = await admin_client.post(
            f"{AUTH}/logout", headers={"Origin": "https://labondemand.example.org"}
        )
    assert r.status_code == 200


async def test_sibling_lab_subdomain_is_rejected(admin_client):
    """Un lab étudiant sur un sous-domaine frère n'est jamais de confiance."""
    with patch.object(settings, "FRONTEND_BASE_URL", "https://labondemand.example.org"):
        r = await admin_client.post(
            f"{AUTH}/logout",
            headers={"Origin": "https://vscode-12-u7.labs.example.org"},
        )
    _assert_csrf_rejected(r)


async def test_wildcard_cors_origin_never_trusts_everyone(admin_client):
    with patch.object(settings, "CORS_ORIGINS", ["*"]):
        r = await admin_client.post(f"{AUTH}/logout", headers={"Origin": "https://evil.example"})
    _assert_csrf_rejected(r)


async def test_same_origin_from_host_header_with_port(admin_client):
    host = "labondemand.local:8080"
    ok = await admin_client.post(
        f"{AUTH}/me", headers={"Host": host, "Origin": f"http://{host}"}
    )
    # La requête franchit le CSRF (405 : POST /me n'existe pas).
    assert ok.status_code == 405
    ko = await admin_client.post(
        f"{AUTH}/logout", headers={"Host": host, "Origin": "http://labondemand.local:9090"}
    )
    _assert_csrf_rejected(ko)


async def test_same_origin_uses_effective_scheme(db, admin_token):
    """Derrière nginx TLS, uvicorn fixe le schéma à https (X-Forwarded-Proto)."""
    app.dependency_overrides[get_db] = _db_override(db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://lab.example.org",
        headers=XRW,
        cookies={"session_id": admin_token},
    ) as c:
        ko = await c.post(f"{AUTH}/logout", headers={"Origin": "http://lab.example.org"})
        ok = await c.post(f"{AUTH}/logout", headers={"Origin": "https://lab.example.org"})
    app.dependency_overrides.clear()
    _assert_csrf_rejected(ko)
    assert ok.status_code == 200


async def test_trusted_referer_is_accepted_when_origin_absent(admin_client):
    r = await admin_client.post(
        f"{AUTH}/logout", headers={"Referer": "http://localhost/dashboard?tab=labs"}
    )
    assert r.status_code == 200


@pytest.mark.parametrize(
    "referer",
    ["https://evil.example/page", "https://vscode-1-u2.labs.example.org/", "not a url"],
)
async def test_untrusted_referer_is_rejected_when_origin_absent(admin_client, referer):
    r = await admin_client.post(f"{AUTH}/logout", headers={"Referer": referer})
    _assert_csrf_rejected(r)


async def test_origin_takes_precedence_over_referer(admin_client):
    r = await admin_client.post(
        f"{AUTH}/logout",
        headers={"Origin": "https://evil.example", "Referer": "http://localhost/"},
    )
    _assert_csrf_rejected(r)


async def test_no_origin_and_no_referer_is_accepted_with_header(admin_client):
    # Clients non navigateurs (curl, scripts) : l'en-tête suffit.
    r = await admin_client.post(f"{AUTH}/logout")
    assert r.status_code == 200


# ============================================================
# Interaction avec CORS, i18n et journalisation
# ============================================================

async def test_cors_preflight_still_allowed_for_trusted_origin(client):
    r = await client.options(
        f"{AUTH}/logout",
        headers={
            "Origin": "http://localhost:8000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-requested-with, content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:8000"


async def test_cors_preflight_refused_for_untrusted_origin(client):
    r = await client.options(
        f"{AUTH}/logout",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-requested-with",
        },
    )
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


async def test_rejection_carries_cors_headers_for_trusted_origin(bare_client):
    r = await bare_client.post(f"{AUTH}/logout", headers={"Origin": "http://localhost:8000"})
    _assert_csrf_rejected(r)
    assert r.headers["access-control-allow-origin"] == "http://localhost:8000"


async def test_rejection_message_is_localized(bare_client):
    fr = await bare_client.post(f"{AUTH}/logout")
    en = await bare_client.post(f"{AUTH}/logout", headers={"Accept-Language": "en-US,en;q=0.9"})
    _assert_csrf_rejected(fr)
    _assert_csrf_rejected(en)
    assert "Requête refusée" in fr.json()["detail"]
    assert "Request rejected" in en.json()["detail"]


async def test_rejection_is_logged_without_cookies(bare_client, admin_token):
    with patch.object(csrf, "audit_logger") as audit:
        r = await bare_client.post(
            f"{AUTH}/logout",
            headers={"Origin": "https://evil.example", "Referer": "https://evil.example/p?secret=1"},
        )
    _assert_csrf_rejected(r)
    audit.warning.assert_called_once()
    event, = audit.warning.call_args.args
    fields = audit.warning.call_args.kwargs["extra"]["extra_fields"]
    assert event == "csrf_rejected"
    assert fields["reason"] == "missing_custom_header"
    assert fields["method"] == "POST"
    assert fields["path"] == f"{AUTH}/logout"
    assert fields["origin"] == "https://evil.example"
    assert fields["referer_origin"] == "https://evil.example"
    logged = repr(audit.warning.call_args)
    assert admin_token not in logged
    assert "secret=1" not in logged
    assert "cookie" not in {k.lower() for k in fields}


# ============================================================
# Normalisation des origines (unitaire)
# ============================================================

@pytest.mark.parametrize(
    "value, strict, expected",
    [
        ("http://Example.COM", True, "http://example.com"),
        ("https://example.com:443", True, "https://example.com"),
        ("http://example.com:80/", True, "http://example.com"),
        ("http://example.com:8080", True, "http://example.com:8080"),
        ("http://[::1]:8000", True, "http://[::1]:8000"),
        ("http://example.com/path", True, None),
        ("http://example.com/path?q=1", False, "http://example.com"),
        ("http://example.com?", True, None),
        ("ftp://example.com", True, None),
        ("http://a:b@example.com", False, None),
        ("http://example.com:99999", True, None),
        ("null", True, None),
        ("", True, None),
        (None, True, None),
    ],
)
def test_normalize_origin(value, strict, expected):
    assert csrf.normalize_origin(value, strict=strict) == expected


def test_no_machine_to_machine_exemptions():
    """Toute exemption doit être délibérée et documentée dans csrf.py."""
    assert csrf.CSRF_EXEMPT_PATHS == frozenset()
