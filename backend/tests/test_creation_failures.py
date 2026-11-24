"""Lab creation under failure: cluster outage (503, no leaked host), DB lookups
that fail closed, nested DB sessions, and reused stack secrets."""

import base64
from unittest.mock import MagicMock

import pytest
import urllib3
from fastapi import HTTPException
from kubernetes import client as k8s_client
from sqlalchemy.exc import OperationalError

from backend import database
from backend.deployment_service import deployment_service
from backend.error_handlers import K8S_UNAVAILABLE_DETAIL
from backend.k8s_utils import get_role_limits
from backend.models import Deployment, User, UserRole
from tests.test_core_create_lifecycle import _allow_for_students

API_HOST = "k8s-api.internal.example"


def _unreachable() -> urllib3.exceptions.MaxRetryError:
    pool = urllib3.HTTPSConnectionPool(API_HOST, port=6443)
    return urllib3.exceptions.MaxRetryError(
        pool, "/api/v1/namespaces", reason=urllib3.exceptions.NewConnectionError(pool, "refused")
    )


# ---------------------------------------------------------------- finding 4


async def test_create_answers_503_when_namespace_check_cannot_reach_cluster(admin_client, mock_k8s):
    mock_k8s["core"].read_namespace.side_effect = _unreachable()

    r = await admin_client.post(
        "/api/v1/k8s/deployments", params={"name": "web", "image": "nginx:1"}
    )

    assert r.status_code == 503
    assert r.json()["detail"] == K8S_UNAVAILABLE_DETAIL
    assert API_HOST not in r.text
    mock_k8s["core"].create_namespace.assert_not_called()


async def test_create_still_reports_a_refused_namespace_as_rbac_problem(admin_client, mock_k8s):
    mock_k8s["core"].read_namespace.side_effect = k8s_client.exceptions.ApiException(status=403)

    r = await admin_client.post(
        "/api/v1/k8s/deployments", params={"name": "web", "image": "nginx:1"}
    )

    assert r.status_code == 500
    assert "RBAC" in r.json()["detail"]


async def test_create_rolls_back_and_answers_503_on_transport_error(admin_client, mock_k8s):
    mock_k8s["apps"].create_namespaced_deployment.side_effect = _unreachable()

    r = await admin_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "code", "image": "ignored", "deployment_type": "vscode"},
    )

    assert r.status_code == 503
    assert r.json()["detail"] == K8S_UNAVAILABLE_DETAIL
    assert API_HOST not in r.text
    # The credentials secret created before the failure is rolled back.
    mock_k8s["core"].delete_namespaced_secret.assert_called_once()


async def test_create_unexpected_error_does_not_leak_its_text(admin_client, mock_k8s):
    mock_k8s["apps"].create_namespaced_deployment.side_effect = RuntimeError(
        f"boom while talking to {API_HOST}"
    )

    r = await admin_client.post(
        "/api/v1/k8s/deployments", params={"name": "web", "image": "nginx:1"}
    )

    assert r.status_code == 500
    assert API_HOST not in r.text


# ---------------------------------------------------------------- finding 5


def _db_down():
    raise OperationalError("SELECT 1", {}, Exception("QueuePool limit reached, timed out"))


def _transient_student() -> User:
    return User(id=987654, username="ghost", email="ghost@test.lab", role=UserRole.student)


def test_student_permission_check_fails_closed_when_db_unavailable(monkeypatch):
    monkeypatch.setattr(database, "SessionLocal", _db_down)
    with pytest.raises(HTTPException) as exc_info:
        # vscode used to be granted by the static fallback list.
        deployment_service.validate_permissions(_transient_student(), "vscode")
    assert exc_info.value.status_code == 503


def test_role_limits_fail_closed_when_overrides_cannot_be_read(monkeypatch):
    monkeypatch.setattr(database, "SessionLocal", _db_down)
    with pytest.raises(HTTPException) as exc_info:
        get_role_limits("student", 987654)
    assert exc_info.value.status_code == 503


def test_runtime_config_lookup_fails_closed_when_db_unavailable(monkeypatch):
    monkeypatch.setattr(database, "SessionLocal", _db_down)
    with pytest.raises(HTTPException) as exc_info:
        deployment_service.apply_deployment_config(
            "vscode", "img", "100m", "200m", "128Mi", "256Mi", 8080, True, "NodePort"
        )
    assert exc_info.value.status_code == 503


async def test_create_request_reuses_its_session_for_lookups(
    student_client, mock_k8s, student_user, sample_runtime_config, monkeypatch
):
    """Permission, runtime config and quota lookups use the request's session:
    only the DB row write opens a session of its own."""
    factory = database.SessionLocal
    opened: list = []

    def counting_factory():
        opened.append(1)
        return factory()

    monkeypatch.setattr(database, "SessionLocal", counting_factory)

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "code", "image": "ignored", "deployment_type": "vscode"},
    )

    assert r.status_code == 200, r.text
    assert len(opened) == 1
    assert r.json()["deployment_db_id"] is not None


# ---------------------------------------------------------------- reused stack secret


def _existing_secret(owner_id, values):
    secret = MagicMock()
    secret.metadata.labels = {"managed-by": "labondemand", "user-id": str(owner_id)}
    secret.data = {k: base64.b64encode(v.encode()).decode() for k, v in values.items()}
    return secret


async def test_recreated_stack_returns_the_credentials_of_the_kept_secret(
    student_client, mock_k8s, student_user, db
):
    _allow_for_students(db, "mysql")
    mock_k8s["core"].create_namespaced_secret.side_effect = k8s_client.exceptions.ApiException(
        status=409
    )
    mock_k8s["core"].read_namespaced_secret.return_value = _existing_secret(
        student_user.id,
        {
            "MYSQL_ROOT_PASSWORD": "old-root",
            "MYSQL_USER": "student",
            "MYSQL_PASSWORD": "old-pass",
            "MYSQL_DATABASE": "studentdb",
        },
    )

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "s", "image": "ignored", "deployment_type": "mysql"},
    )

    assert r.status_code == 200, r.text
    database_creds = r.json()["credentials"]["database"]
    assert database_creds["password"] == "old-pass"
    assert database_creds["username"] == "student"
    # The kept secret is not rolled back nor replaced.
    mock_k8s["core"].delete_namespaced_secret.assert_not_called()


async def test_existing_secret_of_another_owner_is_a_conflict(
    student_client, mock_k8s, student_user, db
):
    _allow_for_students(db, "mysql")
    mock_k8s["core"].create_namespaced_secret.side_effect = k8s_client.exceptions.ApiException(
        status=409
    )
    mock_k8s["core"].read_namespaced_secret.return_value = _existing_secret(
        999999, {"MYSQL_PASSWORD": "not-yours"}
    )

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "s", "image": "ignored", "deployment_type": "mysql"},
    )

    assert r.status_code == 409
    assert "not-yours" not in r.text
    mock_k8s["apps"].create_namespaced_deployment.assert_not_called()
    assert db.query(Deployment).count() == 0
