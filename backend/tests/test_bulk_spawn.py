"""Tests for "deploy assignment to all students" (bulk lab spawn).

The endpoint creates labs from a bounded worker pool, each worker with its own
DB sessions. These tests check that the work really runs in parallel, that no
session is shared between threads (nor with the request), that one failing
student is recorded without aborting the others, and that each successful lab
is linked to the assignment through ``AssignmentDeployment.deployment_id``.
"""
import threading

import pytest
from fastapi import HTTPException

from backend import database
from backend.deployment_service import deployment_service
from backend.models import (
    Assignment,
    AssignmentDeployment,
    Classroom,
    Deployment,
    Enrollment,
    User,
    UserRole,
)
from backend.security import get_password_hash

BASE = "/api/v1"


class _SerializedSession:
    """Context manager around a real session that serializes DB access.

    The test database is one in-memory SQLite connection shared by every
    session, which tolerates no concurrent use. Worker code only touches the
    DB inside ``with database.SessionLocal() as db:`` blocks, so holding a lock
    for the duration of each block keeps SQLite safe while the Kubernetes phase
    (outside those blocks) still runs concurrently.
    """

    def __init__(self, factory, lock: threading.RLock, log: list) -> None:
        self._session = factory()
        self._lock = lock
        log.append((self._session, threading.get_ident()))

    def __enter__(self):
        self._lock.acquire()
        return self._session.__enter__()

    def __exit__(self, *exc_info):
        try:
            return self._session.__exit__(*exc_info)
        finally:
            self._lock.release()


@pytest.fixture()
def worker_sessions(monkeypatch):
    """Record every session opened through ``database.SessionLocal``."""
    factory = database.SessionLocal
    lock = threading.RLock()
    log: list = []
    monkeypatch.setattr(database, "SessionLocal", lambda: _SerializedSession(factory, lock, log))
    return log


def _student(db, username: str) -> User:
    user = User(
        username=username,
        email=f"{username}@test.lab",
        hashed_password=get_password_hash("Student@12345!"),
        role=UserRole.student,
        is_active=True,
        auth_provider="local",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _class_with_assignment(db, teacher_id: int, students: list[User], title: str = "TP Web"):
    classroom = Classroom(name="Classe", owner_id=teacher_id)
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    for student in students:
        db.add(Enrollment(classroom_id=classroom.id, user_id=student.id))
    assignment = Assignment(classroom_id=classroom.id, title=title, instructions="x")
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return classroom.id, assignment.id


async def test_bulk_spawn_isolates_failures_and_sessions(
    teacher_client, db, teacher_user, monkeypatch, worker_sessions
):
    alice, bob, carol = (_student(db, name) for name in ("alice", "bob", "carol"))
    ids = {"alice": alice.id, "bob": bob.id, "carol": carol.id}
    cid, aid = _class_with_assignment(db, teacher_user.id, [alice, bob, carol])

    # alice and bob must both be inside create_deployment at the same time to
    # pass this barrier: it proves the labs are created concurrently.
    barrier = threading.Barrier(2, timeout=10)
    calls: list = []
    calls_lock = threading.Lock()

    def fake_create_deployment(**kwargs):
        user = kwargs["current_user"]
        with calls_lock:
            calls.append((user.id, threading.current_thread().name))
        if user.id == ids["carol"]:
            raise HTTPException(status_code=400, detail="Quota dépassé")
        barrier.wait()
        # Like the real service, record the lab in a session of its own.
        with database.SessionLocal() as session:
            session.add(
                Deployment(
                    user_id=user.id,
                    name=kwargs["name"],
                    namespace=f"labondemand-user-{user.id}",
                    deployment_type=kwargs["deployment_type"],
                    status="active",
                )
            )
            session.commit()
        return {"message": "created"}

    monkeypatch.setattr(deployment_service, "create_deployment", fake_create_deployment)

    r = await teacher_client.post(f"{BASE}/classrooms/{cid}/assignments/{aid}/deploy-all")

    assert r.status_code == 200
    body = r.json()
    assert (body["total"], body["ok"], body["errors"], body["skipped"]) == (3, 2, 1, 0)
    by_user = {row["user_id"]: row for row in body["results"]}
    assert by_user[ids["alice"]]["status"] == "ok"
    assert by_user[ids["bob"]]["status"] == "ok"
    assert by_user[ids["carol"]]["status"] == "error"
    assert by_user[ids["carol"]]["error"] == "Quota dépassé"
    assert [row["user_id"] for row in body["results"]] == [alice.id, bob.id, carol.id]

    # Labs were created from the worker pool, never from the request thread.
    assert len(calls) == 3
    assert all(name.startswith("bulk-spawn") for _, name in calls)

    # No session crosses threads, and none is the request's session.
    sessions = [session for session, _ in worker_sessions]
    assert worker_sessions, "workers must open their own sessions"
    assert db not in sessions
    threads_by_session: dict = {}
    for session, thread_id in worker_sessions:
        threads_by_session.setdefault(id(session), set()).add(thread_id)
    assert all(len(threads) == 1 for threads in threads_by_session.values())

    # Per-student bookkeeping: successes linked to their lab, the failure recorded.
    db.expire_all()
    links = {
        link.user_id: link
        for link in db.query(AssignmentDeployment).filter(AssignmentDeployment.assignment_id == aid)
    }
    assert set(links) == set(ids.values())
    for name in ("alice", "bob"):
        link = links[ids[name]]
        lab = db.query(Deployment).filter(Deployment.user_id == ids[name]).one()
        assert link.spawn_status == "ok"
        assert link.deployment_id == lab.id
    assert links[ids["carol"]].spawn_status == "error"
    assert links[ids["carol"]].deployment_id is None
    assert links[ids["carol"]].spawn_error == "Quota dépassé"


async def test_bulk_spawn_unexpected_error_does_not_abort_class(
    teacher_client, db, teacher_user, monkeypatch, worker_sessions
):
    alice, bob = _student(db, "alice"), _student(db, "bob")
    cid, aid = _class_with_assignment(db, teacher_user.id, [alice, bob])
    alice_id = alice.id

    def fake_create_deployment(**kwargs):
        if kwargs["current_user"].id == alice_id:
            raise RuntimeError("kaboom")
        return {}

    monkeypatch.setattr(deployment_service, "create_deployment", fake_create_deployment)

    r = await teacher_client.post(f"{BASE}/classrooms/{cid}/assignments/{aid}/deploy-all")

    assert r.status_code == 200
    body = r.json()
    assert (body["ok"], body["errors"]) == (1, 1)
    statuses = {row["user_id"]: row["status"] for row in body["results"]}
    assert statuses[alice_id] == "error"


async def test_bulk_spawn_skips_existing_lab_and_inactive_students(
    teacher_client, db, teacher_user, monkeypatch, worker_sessions
):
    alice, bob = _student(db, "alice"), _student(db, "bob")
    bob.is_active = False
    db.commit()
    cid, aid = _class_with_assignment(db, teacher_user.id, [alice, bob], title="TP Web")
    db.add(
        Deployment(
            user_id=alice.id,
            name=f"tp-web-u{alice.id}",
            namespace="ns",
            deployment_type="custom",
            status="paused",
        )
    )
    db.commit()

    called = []
    monkeypatch.setattr(
        deployment_service, "create_deployment", lambda **kwargs: called.append(kwargs) or {}
    )

    r = await teacher_client.post(f"{BASE}/classrooms/{cid}/assignments/{aid}/deploy-all")

    assert r.status_code == 200
    body = r.json()
    assert (body["total"], body["skipped"], body["ok"]) == (1, 1, 0)
    assert body["results"][0]["status"] == "skipped"
    assert called == []


async def test_bulk_spawn_requires_classroom_owner(student_client, db, teacher_user, student_user):
    cid, aid = _class_with_assignment(db, teacher_user.id, [student_user])
    r = await student_client.post(f"{BASE}/classrooms/{cid}/assignments/{aid}/deploy-all")
    assert r.status_code == 403
