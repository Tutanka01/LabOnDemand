"""Limitation de débit : connexion (IP + nom d'utilisateur) et déploiements.

Couvre aussi l'égalisation du temps de réponse de ``authenticate_user`` :
un nom inconnu ne doit pas répondre plus vite qu'un mauvais mot de passe.
"""
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import redis
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from limits.storage import RedisStorage
from slowapi.errors import RateLimitExceeded
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend import rate_limit, security
from backend.config import settings
from backend.database import get_db
from backend.main import app
from backend.models import User, UserRole
from backend.rate_limit import (
    limiter,
    login_failure_throttle,
    normalize_username,
    rate_limit_exceeded_handler,
    user_or_ip_key,
    validate_rate_limit_settings,
)

from .conftest import ADMIN_PASSWORD, CSRF_HEADERS, _db_override

LOGIN = "/api/v1/auth/login"
DEPLOY = "/api/v1/k8s/deployments"
# IP fixe de nginx sur le réseau compose (FRONTEND_IPV4_ADDRESS).
TRUSTED_PROXY = "172.28.100.10"


@asynccontextmanager
async def _client_from(db, ip, *, asgi_app=app, cookies=None):
    """Client HTTP dont la connexion TCP semble venir de ``ip``."""
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=asgi_app, client=(ip, 40000)),
            base_url="http://test",
            headers=CSRF_HEADERS,
            cookies=cookies,
        ) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


async def _login(client, username, password="wrong-password", **kwargs):
    return await client.post(LOGIN, json={"username": username, "password": password}, **kwargs)


def _retry_after(response) -> int:
    value = int(response.headers["Retry-After"])
    assert value >= 1
    return value


# ============================================================
# Égalisation du temps de réponse (énumération des comptes)
# ============================================================

def test_unknown_user_still_runs_a_password_check(db):
    with patch("backend.security.verify_password", wraps=security.verify_password) as verify:
        assert security.authenticate_user(db, "nobody", "whatever") is False
    verify.assert_called_once_with("whatever", security._DUMMY_PASSWORD_HASH)


def test_sso_account_still_runs_a_password_check(db, oidc_user):
    with patch("backend.security.verify_password", wraps=security.verify_password) as verify:
        assert security.authenticate_user(db, "ssouser", "whatever") is False
    verify.assert_called_once_with("whatever", security._DUMMY_PASSWORD_HASH)


def test_wrong_password_checks_the_real_hash(db, admin_user):
    with patch("backend.security.verify_password", wraps=security.verify_password) as verify:
        assert security.authenticate_user(db, "testadmin", "wrong") is False
    verify.assert_called_once_with("wrong", admin_user.hashed_password)


def test_dummy_hash_has_the_same_cost_as_real_hashes():
    """Même coût bcrypt que les empreintes réelles : même durée de vérification."""
    dummy_prefix = security._DUMMY_PASSWORD_HASH.split("$")[1:3]
    real_prefix = security.get_password_hash("Some@Password123").split("$")[1:3]
    assert dummy_prefix == real_prefix


def test_dummy_hash_never_matches():
    for candidate in ("", "password", "admin", "changez-moi-en-dev"):
        assert not security.verify_password(candidate, security._DUMMY_PASSWORD_HASH)


# ============================================================
# Configuration et démarrage
# ============================================================

def test_default_limits():
    assert settings.RATE_LIMIT_LOGIN == "30/minute"
    assert settings.RATE_LIMIT_LOGIN_FAILURES == "10/15minute"
    assert settings.RATE_LIMIT_DEPLOY == "10/5minute"
    validate_rate_limit_settings()


@pytest.mark.parametrize("name", rate_limit.LIMIT_SETTING_NAMES)
@pytest.mark.parametrize("value", ["lots", "10 per fortnight", "0/minute"])
def test_invalid_limit_refuses_to_start(name, value):
    """slowapi ignorerait silencieusement une limite invalide : refus au démarrage."""
    with patch.object(settings, name, value):
        with pytest.raises(RuntimeError, match=name):
            validate_rate_limit_settings()


def test_multiple_limits_are_accepted():
    with patch.object(settings, "RATE_LIMIT_LOGIN", "30/minute;200/hour"):
        validate_rate_limit_settings()


def test_custom_429_handler_is_registered():
    assert app.exception_handlers[RateLimitExceeded] is rate_limit_exceeded_handler
    assert app.state.limiter is limiter
    # Compatibilité : les routeurs importent toujours le limiteur via security.
    assert security.limiter is limiter


# ============================================================
# Connexion : limite par IP
# ============================================================

@pytest.fixture()
def tight_login_limit():
    """Limite par IP de 2/minute ; identifiants toujours refusés (401)."""
    with patch.object(settings, "RATE_LIMIT_LOGIN", "2/minute"), patch(
        "backend.auth_router.authenticate_user", return_value=False
    ):
        yield


async def test_classroom_behind_one_nat_can_log_in(db):
    """30 étudiants derrière la même IP (NAT de salle de TP) se connectent."""
    db.add_all(
        User(
            username=f"student{i:02d}",
            email=f"student{i:02d}@test.lab",
            hashed_password="unused",
            role=UserRole.student,
            is_active=True,
            auth_provider="local",
        )
        for i in range(31)
    )
    db.commit()

    def fast_authenticate(session, username, password):
        # Seul le débit est testé ici : on évite 31 vérifications bcrypt.
        return session.query(User).filter(User.username == username).first()

    with patch("backend.auth_router.authenticate_user", side_effect=fast_authenticate):
        async with _client_from(db, "198.51.100.7") as c:
            for i in range(30):
                resp = await _login(c, f"student{i:02d}", "Student@Pass123")
                assert resp.status_code == 200, (i, resp.text)
            blocked = await _login(c, "student30", "Student@Pass123")

    assert blocked.status_code == 429
    assert _retry_after(blocked) <= 60


async def test_login_ip_limit_is_per_client_ip(db, tight_login_limit):
    async with _client_from(db, "198.51.100.1") as c:
        assert (await _login(c, "alice")).status_code == 401
        assert (await _login(c, "bob")).status_code == 401
        blocked = await _login(c, "carol")

    assert blocked.status_code == 429
    retry_after = _retry_after(blocked)
    assert retry_after <= 60
    body = blocked.json()
    assert body["error"] == "Rate limit exceeded: 2 per 1 minute"
    assert body["detail"].startswith("Trop de requêtes")
    assert str(retry_after) in body["detail"]

    async with _client_from(db, "198.51.100.2") as c:
        assert (await _login(c, "alice")).status_code == 401


async def test_rate_limit_message_is_localized(db, tight_login_limit):
    async with _client_from(db, "198.51.100.3") as c:
        for _ in range(2):
            await _login(c, "alice")
        blocked = await _login(c, "alice", headers={"Accept-Language": "en-US,en;q=0.8"})

    assert blocked.status_code == 429
    assert blocked.json()["detail"].startswith("Too many requests")


# ============================================================
# Connexion : échecs par nom d'utilisateur
# ============================================================

async def test_username_throttle_blocks_across_ips_before_bcrypt(db, admin_user):
    with patch.object(settings, "RATE_LIMIT_LOGIN_FAILURES", "3/15minute"):
        for i in range(3):
            async with _client_from(db, f"203.0.113.{i + 1}") as c:
                assert (await _login(c, "testadmin")).status_code == 401

        with patch(
            "backend.auth_router.authenticate_user", wraps=security.authenticate_user
        ) as auth:
            async with _client_from(db, "203.0.113.50") as c:
                resp = await _login(c, "testadmin", ADMIN_PASSWORD)
            auth.assert_not_called()

    assert resp.status_code == 429
    assert "session_id" not in resp.cookies
    assert 850 <= _retry_after(resp) <= 900
    assert resp.json()["detail"].startswith("Trop de tentatives de connexion")


async def test_username_throttle_counts_unknown_usernames(db):
    """Même traitement qu'un compte existant : pas d'oracle d'énumération."""
    with patch.object(settings, "RATE_LIMIT_LOGIN_FAILURES", "2/15minute"):
        async with _client_from(db, "203.0.113.9") as c:
            codes = [(await _login(c, "ghost")).status_code for _ in range(3)]
    assert codes == [401, 401, 429]


async def test_successful_login_resets_failure_counter(db, admin_user):
    with patch.object(settings, "RATE_LIMIT_LOGIN_FAILURES", "3/15minute"):
        async with _client_from(db, "203.0.113.10") as c:
            for _ in range(2):
                assert (await _login(c, "testadmin")).status_code == 401
            assert (await _login(c, "testadmin", ADMIN_PASSWORD)).status_code == 200
            for _ in range(3):
                assert (await _login(c, "testadmin")).status_code == 401
            assert (await _login(c, "testadmin", ADMIN_PASSWORD)).status_code == 429


async def test_username_throttle_is_per_username(db, admin_user):
    with patch.object(settings, "RATE_LIMIT_LOGIN_FAILURES", "2/15minute"):
        async with _client_from(db, "203.0.113.11") as c:
            codes = [(await _login(c, "victim")).status_code for _ in range(3)]
            assert codes == [401, 401, 429]
            assert (await _login(c, "testadmin", ADMIN_PASSWORD)).status_code == 200


async def test_username_throttle_ignores_spelling_variants(db, admin_user):
    """La collation MariaDB confond ces graphies : le compteur aussi."""
    with patch.object(settings, "RATE_LIMIT_LOGIN_FAILURES", "3/15minute"):
        async with _client_from(db, "203.0.113.12") as c:
            for variant in ("TestAdmin", "testadmin  ", "t\u00e9st\u200badmin"):
                assert (await _login(c, variant)).status_code == 401
            assert (await _login(c, "TESTADMIN", ADMIN_PASSWORD)).status_code == 429


@pytest.mark.parametrize(
    "variant",
    [
        "Admin",
        " admin ",
        "ADM\u0130N",  # I majuscule pointé (turc)
        "\u00e1dmin",  # á précomposé
        "a\u0301dmin",  # a + accent combinant
        "admin\u200b",  # espace sans chasse
        "\uff41\uff44\uff4d\uff49\uff4e",  # lettres pleine chasse
    ],
)
def test_normalize_username_folds_collation_equivalents(variant):
    assert normalize_username(variant) == "admin"


def test_normalize_username_keeps_distinct_names_apart():
    assert normalize_username("alice") != normalize_username("alicia")
    assert normalize_username("admin1") != normalize_username("admin")
    assert normalize_username("") == ""


async def test_login_throttle_stores_only_a_digest(db):
    async with _client_from(db, "203.0.113.13") as c:
        assert (await _login(c, "secret-user")).status_code == 401

    keys = [k.decode() for k in redis.from_url(settings.REDIS_URL).keys("*")]
    assert any("login_failures" in k for k in keys), keys
    assert not any("secret" in k for k in keys), keys


# ============================================================
# Création de déploiements : limite par utilisateur
# ============================================================

DEPLOY_PARAMS = {"name": "demo", "image": "nginx:latest"}


@pytest.fixture()
def fake_deploy():
    """Limite 2/minute ; le service de déploiement répond 418 (atteint)."""
    create = MagicMock(side_effect=HTTPException(status_code=418))
    with patch.object(settings, "RATE_LIMIT_DEPLOY", "2/minute"), patch(
        "backend.routers.k8s_deployments.deployment_service.create_deployment", create
    ):
        yield create


async def test_deploy_limit_is_keyed_by_user_not_ip(db, fake_deploy, student_token, teacher_token):
    async with _client_from(db, "198.51.100.20", cookies={"session_id": student_token}) as c:
        codes = [(await c.post(DEPLOY, params=DEPLOY_PARAMS)).status_code for _ in range(2)]
        blocked = await c.post(DEPLOY, params=DEPLOY_PARAMS)
    assert codes == [418, 418]
    assert blocked.status_code == 429
    assert _retry_after(blocked) <= 60

    # Même IP (NAT), autre utilisateur : quota intact.
    async with _client_from(db, "198.51.100.20", cookies={"session_id": teacher_token}) as c:
        assert (await c.post(DEPLOY, params=DEPLOY_PARAMS)).status_code == 418
    assert fake_deploy.call_count == 3


async def test_deploy_limit_follows_user_across_ips(db, fake_deploy, student_token):
    cookies = {"session_id": student_token}
    for ip in ("198.51.100.21", "198.51.100.22"):
        async with _client_from(db, ip, cookies=cookies) as c:
            assert (await c.post(DEPLOY, params=DEPLOY_PARAMS)).status_code == 418
    async with _client_from(db, "198.51.100.23", cookies=cookies) as c:
        assert (await c.post(DEPLOY, params=DEPLOY_PARAMS)).status_code == 429


def test_user_or_ip_key():
    def request(ip="192.0.2.1", **state):
        client = SimpleNamespace(host=ip) if ip else None
        return SimpleNamespace(client=client, state=SimpleNamespace(**state))

    assert user_or_ip_key(request(user_id=7)) == "user:7"
    assert user_or_ip_key(request(session=SimpleNamespace(user_id=9))) == "user:9"
    assert user_or_ip_key(request()) == "ip:192.0.2.1"
    assert user_or_ip_key(request(ip=None)) == "ip:unknown"


# ============================================================
# IP cliente derrière nginx (uvicorn --proxy-headers)
# ============================================================

@pytest.fixture()
def proxied_app():
    """L'API telle que servie par uvicorn : seul nginx est un proxy de confiance."""
    return ProxyHeadersMiddleware(app, trusted_hosts=TRUSTED_PROXY)


async def test_trusted_proxy_forwarded_ips_get_separate_buckets(db, proxied_app, tight_login_limit):
    first = {"X-Forwarded-For": "198.51.100.30"}
    second = {"X-Forwarded-For": "198.51.100.31"}
    async with _client_from(db, TRUSTED_PROXY, asgi_app=proxied_app) as c:
        codes = [(await _login(c, f"u{i}", headers=first)).status_code for i in range(3)]
        # Autre client derrière le même nginx : son propre quota.
        other = await _login(c, "u9", headers=second)
    assert codes == [401, 401, 429]
    assert other.status_code == 401


async def test_trusted_proxy_ignores_client_supplied_xff_prefix(db, proxied_app, tight_login_limit):
    """nginx ajoute l'IP réelle à droite : ce que le client a mis avant est ignoré."""
    async with _client_from(db, TRUSTED_PROXY, asgi_app=proxied_app) as c:
        codes = [
            (await _login(c, f"u{i}", headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.20"})).status_code
            for i in range(3)
        ]
    assert codes == [401, 401, 429]


async def test_untrusted_client_cannot_spoof_xff(db, proxied_app, tight_login_limit):
    """Connexion directe (hors nginx) : X-Forwarded-For forgé sans effet."""
    async with _client_from(db, "192.0.2.66", asgi_app=proxied_app) as c:
        codes = [
            (await _login(c, f"u{i}", headers={"X-Forwarded-For": f"198.51.100.{100 + i}"})).status_code
            for i in range(3)
        ]
    assert codes == [401, 401, 429]


# ============================================================
# Stockage Redis et pannes
# ============================================================

def test_limiter_uses_redis_storage_from_redis_url():
    assert settings.RATE_LIMIT_STORAGE_URI == settings.REDIS_URL
    assert isinstance(limiter._storage, RedisStorage)
    assert isinstance(login_failure_throttle._primary.storage, RedisStorage)


def _storage_uri_with_env(**env_vars: str) -> str:
    """Valeur de RATE_LIMIT_STORAGE_URI calculée dans un processus neuf."""
    env = {k: v for k, v in os.environ.items() if k not in ("REDIS_URL", "RATE_LIMIT_STORAGE_URI")}
    env.update(env_vars)
    result = subprocess.run(
        [sys.executable, "-c", "from backend.config import settings; print(settings.RATE_LIMIT_STORAGE_URI)"],
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return result.stdout.strip().splitlines()[-1]


def test_storage_uri_resolution_from_environment():
    assert _storage_uri_with_env(REDIS_URL="redis://r:6379/0") == "redis://r:6379/0"
    assert (
        _storage_uri_with_env(REDIS_URL="redis://r:6379/0", RATE_LIMIT_STORAGE_URI="redis://other:6379/3")
        == "redis://other:6379/3"
    )
    assert _storage_uri_with_env() == "memory://"


def test_redis_client_uses_short_timeouts():
    assert rate_limit._storage_options("redis://:pw@redis:6379/0") == {
        "socket_connect_timeout": 1.0,
        "socket_timeout": 1.0,
    }
    assert rate_limit._storage_options("memory://") == {}


async def test_limits_still_enforced_in_memory_when_redis_is_down(db, tight_login_limit):
    down = redis.exceptions.ConnectionError("redis down")
    with patch.object(limiter._storage, "incr", side_effect=down), patch.object(
        limiter._storage, "get", side_effect=down
    ), patch.object(limiter._storage, "check", return_value=False):
        async with _client_from(db, "198.51.100.40") as c:
            assert (await _login(c, "u1")).status_code == 401
            assert limiter._storage_dead is True
            assert (await _login(c, "u2")).status_code == 401
            assert (await _login(c, "u3")).status_code == 429


async def test_limiter_fails_open_when_every_storage_fails(db, tight_login_limit):
    """Dernier recours : jamais de 500 à cause du stockage des compteurs."""
    down = redis.exceptions.ConnectionError("redis down")
    with patch.object(limiter._storage, "incr", side_effect=down), patch.object(
        limiter._storage, "get", side_effect=down
    ), patch.object(limiter._storage, "check", return_value=False), patch.object(
        limiter._fallback_storage, "incr", side_effect=RuntimeError("memory broken")
    ):
        async with _client_from(db, "198.51.100.41") as c:
            codes = [(await _login(c, f"u{i}")).status_code for i in range(3)]
    assert codes == [401, 401, 401]


async def test_username_throttle_falls_back_to_memory_when_redis_down(db):
    storage = login_failure_throttle._primary.storage
    down = redis.exceptions.ConnectionError("redis down")
    with patch.object(settings, "RATE_LIMIT_LOGIN_FAILURES", "2/15minute"), patch.object(
        storage, "incr", side_effect=down
    ), patch.object(storage, "get", side_effect=down), patch.object(storage, "clear", side_effect=down):
        async with _client_from(db, "198.51.100.42") as c:
            codes = [(await _login(c, "victim")).status_code for _ in range(3)]
    assert codes == [401, 401, 429]
