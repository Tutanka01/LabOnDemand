"""Per-user serialisation of lab operations (quota race, phantom/duplicate rows).

Route handlers run concurrently in the threadpool, so these tests use real
threads and events: they fail when the user's lab lock is missing.
"""

import datetime
import threading
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from kubernetes import client as k8s_client

from backend import database
from backend.deployment_service import deployment_service
from backend.lab_locks import KeyedLocks, LabLockTimeout, user_lab_lock
from backend.models import Deployment, UserQuotaOverride
from backend.services.lab_listing import reconcile_lab_records

WAIT = 10  # seconds: generous upper bound for every event wait


class _SerializedSession:
    """A real session whose ``with`` blocks are serialised (the test DB is one
    shared in-memory SQLite connection that tolerates no concurrent use)."""

    def __init__(self, factory, lock: threading.RLock) -> None:
        self._session = factory()
        self._lock = lock

    def __enter__(self):
        self._lock.acquire()
        return self._session.__enter__()

    def __exit__(self, *exc_info):
        try:
            return self._session.__exit__(*exc_info)
        finally:
            self._lock.release()


@pytest.fixture()
def serialized_sessions(monkeypatch):
    factory = database.SessionLocal
    lock = threading.RLock()
    monkeypatch.setattr(database, "SessionLocal", lambda: _SerializedSession(factory, lock))


def _detached(db, user):
    """A detached copy of ``user`` that worker threads can read safely."""
    db.refresh(user)
    db.expunge(user)
    return user


def _k8s_deployment(name: str, user_id: int, replicas: int, paused: bool = False) -> Any:
    annotations = (
        {"labondemand.io/paused": "true", "labondemand.io/paused-replicas": "1"} if paused else {}
    )
    container = SimpleNamespace(
        image="img",
        resources=SimpleNamespace(
            requests={"cpu": "100m", "memory": "128Mi"},
            limits={"cpu": "200m", "memory": "256Mi"},
        ),
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            namespace=f"labondemand-user-{user_id}",
            labels={
                "managed-by": "labondemand",
                "user-id": str(user_id),
                "app": name,
                "app-type": "custom",
            },
            annotations=annotations,
            deletion_timestamp=None,
            creation_timestamp=None,
        ),
        spec=SimpleNamespace(
            replicas=replicas, template=SimpleNamespace(spec=SimpleNamespace(containers=[container]))
        ),
        status=SimpleNamespace(
            ready_replicas=0, available_replicas=0, updated_replicas=0, replicas=0
        ),
    )


def _run_in_thread(results: Dict[str, Any], key: str, fn, *args, **kwargs) -> threading.Thread:
    def target() -> None:
        try:
            fn(*args, **kwargs)
            results[key] = "ok"
        except HTTPException as exc:
            results[key] = exc.status_code
        except Exception as exc:  # surfaced by the assertions
            results[key] = repr(exc)

    thread = threading.Thread(target=target, name=f"test-{key}")
    thread.start()
    return thread


# ---------------------------------------------------------------- KeyedLocks


def test_keyed_locks_are_reentrant_and_released():
    locks = KeyedLocks()
    with locks.hold(1, timeout=1):
        with locks.hold(1, timeout=1):  # same thread: no deadlock
            pass
    assert len(locks) == 0  # unused entries are dropped


def test_user_lab_lock_times_out_with_409_instead_of_blocking_forever():
    held, done = threading.Event(), threading.Event()

    def holder() -> None:
        with user_lab_lock(4242):
            held.set()
            done.wait(WAIT)

    thread = threading.Thread(target=holder)
    thread.start()
    assert held.wait(WAIT)
    try:
        with pytest.raises(LabLockTimeout) as exc_info:
            with user_lab_lock(4242, timeout=0.2):
                pass
        assert exc_info.value.status_code == 409
    finally:
        done.set()
        thread.join(WAIT)


# ---------------------------------------------------------------- finding 1: quotas


def test_concurrent_creations_cannot_both_pass_the_quota_check(
    mock_k8s, db, teacher_user, serialized_sessions
):
    """Two creations of the same user at once with max_apps=1: one must be refused."""
    db.add(UserQuotaOverride(user_id=teacher_user.id, max_apps=1))
    db.commit()
    user = _detached(db, teacher_user)

    created: List[Any] = []
    first_create_entered, release_first = threading.Event(), threading.Event()

    def list_namespaced_deployment(namespace, label_selector=None, **_):
        return SimpleNamespace(items=list(created))

    def create_namespaced_deployment(namespace, manifest, **_):
        if not first_create_entered.is_set():
            first_create_entered.set()
            assert release_first.wait(WAIT)
        created.append(_k8s_deployment(manifest["metadata"]["name"], user.id, replicas=1))
        return MagicMock()

    mock_k8s["apps"].list_namespaced_deployment.side_effect = list_namespaced_deployment
    mock_k8s["apps"].create_namespaced_deployment.side_effect = create_namespaced_deployment

    def create(name: str) -> None:
        deployment_service.create_deployment(
            name=name,
            image="nginx:1",
            replicas=1,
            namespace=None,
            create_service=False,
            service_port=80,
            service_target_port=80,
            service_type="ClusterIP",
            deployment_type="custom",
            cpu_request="100m",
            cpu_limit="200m",
            memory_request="128Mi",
            memory_limit="256Mi",
            additional_labels=None,
            current_user=user,
        )

    results: Dict[str, Any] = {}
    first = _run_in_thread(results, "a", create, "lab-a")
    assert first_create_entered.wait(WAIT)  # A passed its quota check, creation in flight
    second = _run_in_thread(results, "b", create, "lab-b")
    second.join(1.0)  # without the lock, B passes the check against the old usage here
    release_first.set()
    first.join(WAIT)
    second.join(WAIT)

    assert results == {"a": "ok", "b": 403}
    assert [dep.metadata.name for dep in created] == ["lab-a"]
    rows = db.query(Deployment).filter_by(user_id=user.id).all()
    assert [row.name for row in rows] == ["lab-a"]


def test_concurrent_resumes_cannot_both_pass_the_quota_check(
    mock_k8s, db, teacher_user, serialized_sessions
):
    db.add(UserQuotaOverride(user_id=teacher_user.id, max_apps=1))
    db.commit()
    user = _detached(db, teacher_user)
    labs = {name: _k8s_deployment(name, user.id, replicas=0, paused=True) for name in ("l1", "l2")}
    first_patch_entered, release_first = threading.Event(), threading.Event()
    patched: List[str] = []

    def read_namespaced_deployment(name, namespace, **_):
        return labs[name]

    def list_namespaced_deployment(namespace, label_selector=None, **_):
        return SimpleNamespace(items=list(labs.values()))

    def patch_namespaced_deployment(name, namespace, body, **_):
        if not first_patch_entered.is_set():
            first_patch_entered.set()
            assert release_first.wait(WAIT)
        labs[name].spec.replicas = body["spec"]["replicas"]
        labs[name].metadata.annotations = {}
        patched.append(name)
        return labs[name]

    apps = mock_k8s["apps"]
    apps.read_namespaced_deployment.side_effect = read_namespaced_deployment
    apps.list_namespaced_deployment.side_effect = list_namespaced_deployment
    apps.patch_namespaced_deployment.side_effect = patch_namespaced_deployment

    namespace = f"labondemand-user-{user.id}"
    results: Dict[str, Any] = {}
    first = _run_in_thread(results, "l1", deployment_service.resume_application, namespace, "l1", user)
    assert first_patch_entered.wait(WAIT)
    second = _run_in_thread(results, "l2", deployment_service.resume_application, namespace, "l2", user)
    second.join(1.0)
    release_first.set()
    first.join(WAIT)
    second.join(WAIT)

    assert results == {"l1": "ok", "l2": 403}
    assert patched == ["l1"]


# ---------------------------------------------------------------- finding 2: rows


def _lab(name: str, user_id: int) -> Dict[str, Any]:
    return {
        "name": name,
        "type": "custom",
        "namespace": f"labondemand-user-{user_id}",
        "labels": {},
        "_k8s_created_at": None,
    }


def _live_rows(db, user_id: int) -> List[Deployment]:
    db.expire_all()
    return db.query(Deployment).filter(
        Deployment.user_id == user_id, Deployment.deleted_at.is_(None)
    ).all()


def test_list_does_not_resurrect_a_lab_deleted_after_its_snapshot(mock_k8s, db, student_user):
    """Snapshot taken before a DELETE that soft-deleted the row since."""
    uid = student_user.id
    db.add(
        Deployment(
            user_id=uid,
            name="lab",
            deployment_type="custom",
            namespace=f"labondemand-user-{uid}",
            status="deleted",
            deleted_at=datetime.datetime.now(datetime.timezone.utc),
        )
    )
    db.commit()
    terminating = _k8s_deployment("lab", uid, replicas=1)
    terminating.metadata.deletion_timestamp = datetime.datetime.now(datetime.timezone.utc)
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = SimpleNamespace(
        items=[terminating]
    )

    records = reconcile_lab_records(db, student_user, [_lab("lab", uid)])

    assert records == {}
    assert _live_rows(db, uid) == []


def test_list_waits_for_an_in_flight_creation_and_inserts_no_duplicate(
    mock_k8s, db, student_user, monkeypatch
):
    """List between create_namespaced_deployment and the creation's DB row."""
    from backend.services import lab_listing

    uid = student_user.id
    user = _detached(db, student_user)
    mock_k8s["apps"].list_deployment_for_all_namespaces.return_value = SimpleNamespace(
        items=[_k8s_deployment("lab", uid, replicas=1)]
    )
    # Without the lock, the list reads "no row", then inserts after the
    # creation tracked its own row: pause it right before its insert.
    at_insert, tracked = threading.Event(), threading.Event()
    original_expires_at_for = lab_listing._expires_at_for

    def expires_at_for(*args):
        at_insert.set()
        tracked.wait(2)
        return original_expires_at_for(*args)

    monkeypatch.setattr(lab_listing, "_expires_at_for", expires_at_for)

    results: Dict[str, Any] = {}
    list_session = database.SessionLocal()
    with user_lab_lock(uid):  # the creation is between its Kubernetes calls and its row
        lister = _run_in_thread(
            results, "list", reconcile_lab_records, list_session, user, [_lab("lab", uid)]
        )
        at_insert.wait(0.5)
        deployment_service._track_deployment_in_db(
            user=user, name="lab", deployment_type="custom", namespace=f"labondemand-user-{uid}"
        )
        tracked.set()
    lister.join(WAIT)
    list_session.close()

    assert results == {"list": "ok"}
    assert [row.name for row in _live_rows(db, uid)] == ["lab"]


def test_delete_cannot_interleave_with_list_reconciliation(mock_k8s, db, student_user):
    """A DELETE landing between the list's re-check and its insert must win."""
    uid = student_user.id
    user = _detached(db, student_user)
    namespace = f"labondemand-user-{uid}"
    lab_dep = _k8s_deployment("lab", uid, replicas=1)
    rechecking, go = threading.Event(), threading.Event()

    def list_all(label_selector=None, **_):
        rechecking.set()
        go.wait(2)
        return SimpleNamespace(items=[lab_dep])  # the lab still exists at the re-check

    mock_k8s["apps"].list_deployment_for_all_namespaces.side_effect = list_all
    mock_k8s["apps"].read_namespaced_deployment.return_value = lab_dep

    results: Dict[str, Any] = {}
    list_session = database.SessionLocal()
    lister = _run_in_thread(results, "list", reconcile_lab_records, list_session, user, [_lab("lab", uid)])
    assert rechecking.wait(WAIT)
    deleter = _run_in_thread(
        results, "delete", deployment_service.delete_labondemand_resources, namespace, "lab", user
    )
    deleter.join(0.5)  # without the lock, the deletion completes here
    go.set()
    lister.join(WAIT)
    deleter.join(WAIT)
    list_session.close()

    assert results == {"list": "ok", "delete": "ok"}
    mock_k8s["apps"].delete_namespaced_deployment.assert_called_once()
    assert _live_rows(db, uid) == []


def test_list_skips_reconciliation_when_kubernetes_cannot_confirm(mock_k8s, db, student_user):
    uid = student_user.id
    mock_k8s["apps"].list_deployment_for_all_namespaces.side_effect = (
        k8s_client.exceptions.ApiException(status=503)
    )
    assert reconcile_lab_records(db, student_user, [_lab("lab", uid)]) == {}
    assert _live_rows(db, uid) == []


# ---------------------------------------------------------------- cleanup healing


def _expired_row(db, user_id: int, status: str = "active") -> Deployment:
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)
    row = Deployment(
        user_id=user_id,
        name="gone",
        deployment_type="custom",
        namespace=f"labondemand-user-{user_id}",
        status=status,
        expires_at=past,
        last_seen_at=past,
    )
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("status", ["active", "paused"])
def test_cleanup_marks_rows_of_vanished_labs_deleted(mock_k8s, db, student_user, status):
    from backend.tasks.cleanup import run_cleanup_cycle

    _expired_row(db, student_user.id, status)
    mock_k8s["apps"].read_namespaced_deployment.side_effect = k8s_client.exceptions.ApiException(
        status=404
    )

    run_cleanup_cycle()
    run_cleanup_cycle()

    db.expire_all()
    row = db.query(Deployment).filter_by(name="gone").one()
    assert row.status == "deleted"
    assert row.deleted_at is not None
    # Healed on the first cycle: the second one no longer asks Kubernetes.
    assert mock_k8s["apps"].read_namespaced_deployment.call_count == 1


def test_cleanup_does_not_heal_a_row_on_transport_errors(mock_k8s, db, student_user):
    import urllib3

    from backend.tasks.cleanup import run_cleanup_cycle

    _expired_row(db, student_user.id)
    mock_k8s["apps"].read_namespaced_deployment.side_effect = urllib3.exceptions.MaxRetryError(
        None, "/apis", reason="refused"
    )
    run_cleanup_cycle()
    db.expire_all()
    assert db.query(Deployment).filter_by(name="gone").one().status == "active"
