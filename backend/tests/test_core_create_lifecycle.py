"""create_deployment refactor (stacks as data), resume quotas and cleanup cycle."""

import asyncio
import datetime
import threading
from unittest.mock import MagicMock

import pytest
from kubernetes import client as k8s_client

from backend.deployment_service import deployment_service
from backend.models import Deployment, RuntimeConfig, UserQuotaOverride
from backend.services.stacks import STACK_SPECS, plan_resources
from backend.k8s_utils import clamp_resources_for_role


def _allow_for_students(db, key):
    db.add(
        RuntimeConfig(
            key=key,
            default_image="unused",
            target_port=80,
            default_service_type="NodePort",
            allowed_for_students=True,
            active=True,
        )
    )
    db.commit()


@pytest.mark.parametrize(
    "stack_type,deployments,services",
    [
        ("wordpress", ["s-mariadb", "s"], ["s-mariadb-service", "s-service"]),
        ("mysql", ["s-mysql", "s-phpmyadmin"], ["s-mysql-service", "s-phpmyadmin-service"]),
        (
            "lamp",
            ["s-mysql", "s-web", "s-phpmyadmin"],
            ["s-mysql-service", "s-web-service", "s-phpmyadmin-service"],
        ),
    ],
)
async def test_create_stack_creates_components_and_tracks_record(
    student_client, mock_k8s, student_user, db, stack_type, deployments, services
):
    _allow_for_students(db, stack_type)
    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "s", "image": "ignored", "deployment_type": stack_type, "service_type": "NodePort"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deployment_type"] == stack_type
    assert body["namespace"] == f"labondemand-user-{student_user.id}"
    assert body["created_objects"]["deployments"] == deployments

    created_deps = [c.args[1] for c in mock_k8s["apps"].create_namespaced_deployment.call_args_list]
    assert [m["metadata"]["name"] for m in created_deps] == deployments
    for manifest in created_deps:
        labels = manifest["metadata"]["labels"]
        assert labels["stack-name"] == "s"
        assert labels["user-id"] == str(student_user.id)
        assert labels["app-type"] == stack_type
    created_svcs = [c.args[1]["metadata"]["name"] for c in mock_k8s["core"].create_namespaced_service.call_args_list]
    assert sorted(created_svcs) == sorted(services)

    record = db.query(Deployment).filter_by(user_id=student_user.id, name="s").one()
    assert record.stack_name == "s"
    assert record.deployment_type == stack_type


def test_stack_plan_matches_component_resources():
    spec = STACK_SPECS["lamp"]
    plan = plan_resources([c.clamp("student") for c in spec.components], 1, 3)
    # web 250m + db 250m + pma 150m ; 256 + 256 + 128 Mi
    assert (plan.requests_cpu_m, plan.requests_mem_mi) == (650, 640)
    assert (plan.limits_cpu_m, plan.limits_mem_mi) == (1300, 1280)
    assert (plan.pods, plan.deployments) == (3, 3)


def test_single_plan_multiplies_by_replicas():
    clamped = clamp_resources_for_role("teacher", "300m", "600m", "256Mi", "512Mi", 2)
    plan = plan_resources([clamped], replicas=clamped["replicas"], deployments=1)
    assert (plan.requests_cpu_m, plan.limits_cpu_m) == (600, 1200)
    assert (plan.requests_mem_mi, plan.limits_mem_mi) == (512, 1024)
    assert (plan.pods, plan.deployments) == (2, 1)


async def test_stack_over_quota_is_refused_before_any_creation(
    student_client, mock_k8s, student_user, db
):
    _allow_for_students(db, "mysql")
    db.add(UserQuotaOverride(user_id=student_user.id, max_apps=0))
    db.commit()

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "s", "image": "ignored", "deployment_type": "mysql"},
    )
    assert r.status_code == 403
    assert "Quota" in r.json()["detail"]
    mock_k8s["apps"].create_namespaced_deployment.assert_not_called()
    mock_k8s["core"].create_namespaced_secret.assert_not_called()


async def test_foreign_existing_pvc_keeps_403_and_rolls_back(
    student_client, mock_k8s, student_user, db, sample_runtime_config
):
    """An HTTPException raised while creating is no longer turned into a 500."""
    pvc = MagicMock()
    pvc.metadata.name = "not-mine"
    pvc.metadata.labels = {"managed-by": "labondemand", "user-id": "999999"}
    mock_k8s["core"].read_namespaced_persistent_volume_claim.return_value = pvc

    r = await student_client.post(
        "/api/v1/k8s/deployments",
        params={
            "name": "code",
            "image": "ignored",
            "deployment_type": "vscode",
            "existing_pvc_name": "not-mine",
        },
    )
    assert r.status_code == 403
    mock_k8s["apps"].create_namespaced_deployment.assert_not_called()
    # The credentials secret created first is rolled back.
    mock_k8s["core"].delete_namespaced_secret.assert_called_once()


async def test_k8s_error_during_creation_rolls_back_and_keeps_status(
    admin_client, mock_k8s
):
    mock_k8s["apps"].create_namespaced_deployment.side_effect = (
        k8s_client.exceptions.ApiException(status=409, reason="Conflict")
    )
    r = await admin_client.post(
        "/api/v1/k8s/deployments",
        params={"name": "web", "image": "nginx:1", "deployment_type": "custom", "create_service": "true"},
    )
    assert r.status_code == 409
    assert r.json()["detail"].startswith("Erreur lors de la création: Conflict")
    mock_k8s["core"].create_namespaced_service.assert_not_called()


async def test_resume_over_quota_is_refused(student_client, mock_k8s, student_user, db):
    db.add(UserQuotaOverride(user_id=student_user.id, max_cpu_m=100))
    db.commit()
    dep = MagicMock()
    dep.metadata.name = "lab"
    dep.metadata.annotations = {"labondemand.io/paused": "true", "labondemand.io/paused-replicas": "1"}
    dep.metadata.labels = {"managed-by": "labondemand", "user-id": str(student_user.id)}
    dep.spec.replicas = 0
    container = MagicMock()
    container.resources.requests = {"cpu": "250m", "memory": "256Mi"}
    container.resources.limits = {"cpu": "500m", "memory": "512Mi"}
    dep.spec.template.spec.containers = [container]
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep

    ns = f"labondemand-user-{student_user.id}"
    r = await student_client.post(f"/api/v1/k8s/deployments/{ns}/lab/resume")
    assert r.status_code == 403
    assert "cpu(m): 250/100" in r.json()["detail"]
    mock_k8s["apps"].patch_namespaced_deployment.assert_not_called()


def test_pause_application_is_synchronous(mock_k8s, admin_user):
    dep = MagicMock()
    dep.spec.replicas = 1
    dep.metadata.name = "lab"
    dep.metadata.annotations = {}
    dep.metadata.labels = {"managed-by": "labondemand", "user-id": str(admin_user.id)}
    dep.status.ready_replicas = 1
    dep.status.available_replicas = 1
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep
    mock_k8s["apps"].patch_namespaced_deployment.return_value = dep

    result = deployment_service.pause_application(
        f"labondemand-user-{admin_user.id}", "lab", admin_user
    )
    assert result["action"] == "paused"
    body = mock_k8s["apps"].patch_namespaced_deployment.call_args.kwargs["body"]
    assert body["spec"]["replicas"] == 0
    assert body["metadata"]["annotations"]["labondemand.io/paused-at"].endswith("Z")


# ---------------------------------------------------------------- cleanup


def test_cleanup_step_failure_does_not_abort_the_cycle(monkeypatch, db, student_user):
    from backend.tasks import cleanup

    db.add(
        Deployment(
            user_id=student_user.id,
            name="old",
            deployment_type="custom",
            namespace="ns",
            status="active",
        )
    )
    db.commit()

    def boom(_db, _now):
        raise RuntimeError("cluster down")

    monkeypatch.setattr(
        cleanup,
        "_CLEANUP_STEPS",
        (("boom", boom), ("backfill", cleanup._backfill_missing_expires_at)),
    )
    cleanup.run_cleanup_cycle()

    db.expire_all()
    assert db.query(Deployment).filter_by(name="old").one().expires_at is not None


def test_cleanup_pauses_expired_labs(mock_k8s, db, student_user):
    from backend.tasks.cleanup import run_cleanup_cycle

    db.add(
        Deployment(
            user_id=student_user.id,
            name="lab",
            deployment_type="custom",
            namespace=f"labondemand-user-{student_user.id}",
            status="active",
            expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
        )
    )
    db.commit()
    dep = MagicMock()
    dep.spec.replicas = 1
    dep.metadata.name = "lab"
    dep.metadata.annotations = {}
    dep.metadata.labels = {"managed-by": "labondemand", "user-id": str(student_user.id)}
    mock_k8s["apps"].read_namespaced_deployment.return_value = dep
    mock_k8s["apps"].patch_namespaced_deployment.return_value = dep

    run_cleanup_cycle()

    db.expire_all()
    assert db.query(Deployment).filter_by(name="lab").one().status == "paused"
    mock_k8s["apps"].patch_namespaced_deployment.assert_called_once()


async def test_cleanup_loop_runs_cycle_off_the_event_loop(monkeypatch):
    from backend.tasks import cleanup

    loop_thread = threading.get_ident()
    seen = []
    monkeypatch.setattr(cleanup, "run_cleanup_cycle", lambda: seen.append(threading.get_ident()))

    async def stop(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(cleanup.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        await cleanup.run_cleanup_loop()
    assert seen and seen[0] != loop_thread
