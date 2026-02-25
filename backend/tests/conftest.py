"""
Test configuration for LabOnDemand.

All external patches (Redis, Kubernetes, database) are applied at MODULE LEVEL,
before any backend package is imported, so the backends's own module-level code
(settings.init_kubernetes(), Base.metadata.create_all(), session_store creation)
uses our test doubles.

Import order matters:
  1. Env vars
  2. Redis mock (required by session_store.py at import time)
  3. Kubernetes config mock (required by main.py at import time)
  4. SQLite engine replaces the MySQL engine in backend.database
  5. backend.main imported (uses all the patched objects above)
  6. pytest fixtures defined
"""
import os
from typing import Dict, Generator, Optional

# ============================================================
# 1. Environment variables — read by config.py at import time
# ============================================================
os.environ.setdefault("REDIS_URL", "redis://fake-redis:6379/0")
os.environ.setdefault("ADMIN_DEFAULT_PASSWORD", "TestAdmin@1234!")
os.environ.setdefault("DEBUG_MODE", "false")
os.environ.setdefault("SESSION_EXPIRY_HOURS", "24")
os.environ.setdefault("INGRESS_ENABLED", "false")
os.environ.setdefault("SSO_ENABLED", "false")

# ============================================================
# 2. Mock Redis — session_store.py calls redis.from_url() at module level
# ============================================================
_test_sessions: Dict[str, str] = {}


class _FakeRedis:
    """In-memory Redis substitute — same interface as redis.Redis."""

    def ping(self) -> bool:
        return True

    def setex(self, key: str, ttl: int, value: str) -> None:
        _test_sessions[key] = value

    def get(self, key: str) -> Optional[str]:
        return _test_sessions.get(key)

    def delete(self, key: str) -> int:
        existed = key in _test_sessions
        _test_sessions.pop(key, None)
        return 1 if existed else 0


import redis as _redis_mod  # noqa: E402 (must come after os.environ setup)
_redis_mod.from_url = lambda url, **kw: _FakeRedis()

# ============================================================
# 3. Mock Kubernetes config — main.py calls settings.init_kubernetes()
#    at module level, which calls config.load_kube_config()
# ============================================================
import kubernetes.config as _k8s_cfg  # noqa: E402
_k8s_cfg.load_kube_config = lambda **kw: None
_k8s_cfg.load_incluster_config = lambda **kw: None

# ============================================================
# 4. Replace MySQL engine with SQLite in-memory BEFORE main.py
#    imports `from .database import engine` (a local binding)
# ============================================================
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

_TEST_DB_URL = "sqlite:///:memory:"
_test_engine = create_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

# Patch the module's attributes BEFORE main.py does `from .database import engine`
import backend.database as _db_mod  # noqa: E402
_db_mod.engine = _test_engine
_db_mod.SessionLocal = _TestSession

# ============================================================
# 5. Import backend — all patches are in place
# ============================================================
from backend.database import Base, get_db  # noqa: E402
from backend.main import app  # noqa: E402  ← triggers init_kubernetes() + create_all()
from backend.models import User, UserRole, Template, RuntimeConfig  # noqa: E402
from backend.security import get_password_hash, create_session  # noqa: E402

# Ensure schema exists (idempotent)
Base.metadata.create_all(bind=_test_engine)

# ============================================================
# 6. pytest fixtures
# ============================================================
import pytest  # noqa: E402
from httpx import AsyncClient, ASGITransport  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

# ---------- Passwords used in fixtures ----------
ADMIN_PASSWORD = "TestAdmin@1234!"
TEACHER_PASSWORD = "TeachPass@5678!"
STUDENT_PASSWORD = "StudPass@9012!"


# ---------- Isolation: wipe tables + sessions before every test ----------

@pytest.fixture(autouse=True)
def _isolate():
    """Truncate every table and clear the session store before each test."""
    with _test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    _test_sessions.clear()


# ---------- Database session ----------

@pytest.fixture()
def db():
    """Open SQLAlchemy session; closed after the test."""
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


# ---------- User fixtures ----------

def _make_user(db, username, email, password, role, is_active=True) -> User:
    u = User(
        username=username,
        email=email,
        hashed_password=get_password_hash(password),
        role=role,
        is_active=is_active,
        auth_provider="local",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture()
def admin_user(db) -> User:
    return _make_user(db, "testadmin", "admin@test.lab", ADMIN_PASSWORD, UserRole.admin)


@pytest.fixture()
def teacher_user(db) -> User:
    return _make_user(db, "testteacher", "teacher@test.lab", TEACHER_PASSWORD, UserRole.teacher)


@pytest.fixture()
def student_user(db) -> User:
    return _make_user(db, "teststudent", "student@test.lab", STUDENT_PASSWORD, UserRole.student)


@pytest.fixture()
def inactive_user(db) -> User:
    return _make_user(db, "inactive", "inactive@test.lab", STUDENT_PASSWORD, UserRole.student, is_active=False)


@pytest.fixture()
def oidc_user(db) -> User:
    u = User(
        username="ssouser",
        email="sso@test.lab",
        hashed_password="",
        role=UserRole.student,
        is_active=True,
        auth_provider="oidc",
        external_id="sso-ext-001",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------- Session tokens ----------

@pytest.fixture()
def admin_token(admin_user) -> str:
    return create_session(admin_user.id, admin_user.username, admin_user.role)


@pytest.fixture()
def teacher_token(teacher_user) -> str:
    return create_session(teacher_user.id, teacher_user.username, teacher_user.role)


@pytest.fixture()
def student_token(student_user) -> str:
    return create_session(student_user.id, student_user.username, student_user.role)


# ---------- HTTP client helpers ----------

def _db_override(session):
    """Return a FastAPI dependency override that yields the given session."""
    def _override() -> Generator:
        yield session
    return _override


@pytest.fixture()
async def client(db) -> AsyncClient:
    """Unauthenticated HTTP client backed by the test DB."""
    app.dependency_overrides[get_db] = _db_override(db)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
async def admin_client(db, admin_token) -> AsyncClient:
    """HTTP client authenticated as admin."""
    app.dependency_overrides[get_db] = _db_override(db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session_id": admin_token},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
async def teacher_client(db, teacher_token) -> AsyncClient:
    """HTTP client authenticated as teacher."""
    app.dependency_overrides[get_db] = _db_override(db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session_id": teacher_token},
    ) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
async def student_client(db, student_token) -> AsyncClient:
    """HTTP client authenticated as student."""
    app.dependency_overrides[get_db] = _db_override(db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={"session_id": student_token},
    ) as c:
        yield c
    app.dependency_overrides.clear()


# ---------- Kubernetes mock ----------

@pytest.fixture()
def mock_k8s():
    """
    Patch kubernetes.client.{AppsV1Api,CoreV1Api,NetworkingV1Api} globally so
    that every inline `client.AppsV1Api()` call inside routers and
    deployment_service returns our controlled mock.

    Also patches the three attributes on the singleton deployment_service
    instance (used by the mixin stack methods).
    """
    from kubernetes import client as k8s_client

    apps = MagicMock(name="AppsV1Api-instance")
    core = MagicMock(name="CoreV1Api-instance")
    net = MagicMock(name="NetworkingV1Api-instance")

    # List operations → empty by default
    _empty = MagicMock(items=[])
    apps.list_deployment_for_all_namespaces.return_value = _empty
    apps.list_namespaced_deployment.return_value = _empty
    core.list_namespaced_service.return_value = _empty
    core.list_namespaced_secret.return_value = _empty
    core.list_namespaced_persistent_volume_claim.return_value = _empty
    core.list_persistent_volume_claim_for_all_namespaces.return_value = _empty
    net.list_namespaced_ingress.return_value = _empty
    net.list_ingress_for_all_namespaces.return_value = _empty

    # Namespace: 404 → causes ensure_namespace_exists to create it
    core.read_namespace.side_effect = k8s_client.exceptions.ApiException(status=404)
    core.create_namespace.return_value = MagicMock()

    # ResourceQuota / LimitRange: 409 = already exists — handled silently
    def _already_exists(*a, **kw):
        raise k8s_client.exceptions.ApiException(status=409)

    core.create_namespaced_resource_quota.side_effect = _already_exists
    core.create_namespaced_limit_range.side_effect = _already_exists

    # Service creation → returns a mock with a NodePort
    _svc = MagicMock()
    _svc.spec.ports = [MagicMock(node_port=30080)]
    core.create_namespaced_service.return_value = _svc

    # Deployment / Secret / PVC creation
    apps.create_namespaced_deployment.return_value = MagicMock()
    core.create_namespaced_secret.return_value = MagicMock()
    core.create_namespaced_persistent_volume_claim.return_value = MagicMock()

    # Pod listing
    core.list_namespaced_pod.return_value = _empty

    with (
        patch("kubernetes.client.AppsV1Api", return_value=apps),
        patch("kubernetes.client.CoreV1Api", return_value=core),
        patch("kubernetes.client.NetworkingV1Api", return_value=net),
    ):
        # Also replace on the singleton DeploymentService instance
        from backend.deployment_service import deployment_service as _ds
        _orig = (_ds.apps_v1, _ds.core_v1, _ds.networking_v1)
        _ds.apps_v1, _ds.core_v1, _ds.networking_v1 = apps, core, net
        yield {"apps": apps, "core": core, "networking": net}
        _ds.apps_v1, _ds.core_v1, _ds.networking_v1 = _orig


# ---------- Data fixtures ----------

@pytest.fixture()
def sample_template(db) -> Template:
    t = Template(
        key="vscode-test",
        name="VS Code Test",
        deployment_type="vscode",
        default_port=8080,
        default_service_type="NodePort",
        active=True,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture()
def inactive_template(db) -> Template:
    t = Template(
        key="hidden-tpl",
        name="Hidden Template",
        deployment_type="custom",
        default_port=80,
        default_service_type="NodePort",
        active=False,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@pytest.fixture()
def sample_runtime_config(db) -> RuntimeConfig:
    rc = RuntimeConfig(
        key="vscode",
        default_image="codercom/code-server:latest",
        target_port=8080,
        default_service_type="NodePort",
        allowed_for_students=True,
        active=True,
    )
    db.add(rc)
    db.commit()
    db.refresh(rc)
    return rc
