"""Grader fairness (one active run per user and assignment), queue-aware stuck
run reconciliation, and prompt shutdown of the grader workers."""

import datetime
import threading
import time

from backend import database, grader_service
from backend.models import GradingRun, User, UserRole
from backend.security import get_password_hash
from tests.test_grading import (
    BASE,
    _assignment,
    _classroom,
    _deployment,
    _enroll,
    _link_lab,
    _run,
    _spec,
)

WAIT = 10


def _setup_lab(db, teacher_user, student_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)
    _spec(db, asgn.id)
    dep = _deployment(db, student_user.id)
    _link_lab(db, asgn.id, student_user.id, dep.id)
    return cls, asgn, dep


# ---------------------------------------------------------------- one active run


async def test_student_cannot_queue_a_second_run_while_one_is_active(
    student_client, db, teacher_user, student_user, scheduled_gradings
):
    _, asgn, dep = _setup_lab(db, teacher_user, student_user)

    first = await student_client.post(f"{BASE}/student/assignments/{asgn.id}/run-tests")
    second = await student_client.post(f"{BASE}/student/assignments/{asgn.id}/run-tests")

    assert first.status_code == 200
    assert second.status_code == 409
    assert "déjà en cours" in second.json()["detail"]
    assert scheduled_gradings == [first.json()["id"]]
    assert db.query(GradingRun).filter(GradingRun.assignment_id == asgn.id).count() == 1


async def test_student_can_rerun_once_the_previous_run_finished(
    student_client, db, teacher_user, student_user, scheduled_gradings
):
    _, asgn, dep = _setup_lab(db, teacher_user, student_user)
    _run(db, asgn.id, student_user.id, status="done", trigger="student_self", deployment_id=dep.id)
    _run(db, asgn.id, student_user.id, status="error", trigger="student_self", deployment_id=dep.id)

    r = await student_client.post(f"{BASE}/student/assignments/{asgn.id}/run-tests")
    assert r.status_code == 200


async def test_teacher_test_now_refuses_a_second_active_run(
    teacher_client, db, teacher_user, scheduled_gradings
):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _spec(db, asgn.id)
    dep = _deployment(db, teacher_user.id, name="demo")
    _link_lab(db, asgn.id, teacher_user.id, dep.id)
    _run(db, asgn.id, teacher_user.id, status="running", trigger="teacher", deployment_id=dep.id)

    r = await teacher_client.post(f"{BASE}/classrooms/{cls.id}/assignments/{asgn.id}/test-now")
    assert r.status_code == 409
    assert scheduled_gradings == []


async def test_run_tests_all_skips_students_with_an_active_run(
    teacher_client, db, teacher_user, student_user, scheduled_gradings
):
    cls, asgn, dep = _setup_lab(db, teacher_user, student_user)
    other = User(
        username="stud2", email="stud2@test.lab", hashed_password=get_password_hash("Pass@12345678!"),
        role=UserRole.student, is_active=True, auth_provider="local",
    )
    db.add(other)
    db.commit()
    db.refresh(other)
    _enroll(db, cls.id, other.id)
    other_dep = _deployment(db, other.id, name="tp-test-u2", ns=f"labondemand-user-{other.id}")
    _link_lab(db, asgn.id, other.id, other_dep.id)
    busy = _run(db, asgn.id, student_user.id, status="queued", trigger="student_self", deployment_id=dep.id)

    r = await teacher_client.post(f"{BASE}/classrooms/{cls.id}/assignments/{asgn.id}/run-tests-all")

    assert r.status_code == 200
    assert r.json() == {"queued": 1, "skipped": 1}
    assert len(scheduled_gradings) == 1
    queued = db.get(GradingRun, scheduled_gradings[0])
    assert queued.user_id == other.id and busy.id not in scheduled_gradings


def test_enqueue_run_is_serialised_per_user_and_assignment(
    db, teacher_user, student_user, monkeypatch
):
    """Two simultaneous "run tests" clicks: both threads must not pass the check."""
    _, asgn, dep = _setup_lab(db, teacher_user, student_user)
    aid, uid, dep_id = asgn.id, student_user.id, dep.id
    both_checked = threading.Barrier(2, timeout=1)
    original = grader_service.has_active_run

    def has_active_run(*args, **kwargs):
        active = original(*args, **kwargs)
        try:
            both_checked.wait()  # only reachable by both threads without the lock
        except threading.BrokenBarrierError:
            pass
        return active

    monkeypatch.setattr(grader_service, "has_active_run", has_active_run)
    created: list = []

    def click() -> None:
        session = database.SessionLocal()
        try:
            run = grader_service.enqueue_run(
                session, assignment_id=aid, user_id=uid, deployment_id=dep_id, trigger="student_self"
            )
            created.append(run.id if run else None)
        finally:
            session.close()

    threads = [threading.Thread(target=click) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)

    assert len(created) == 2 and created.count(None) == 1
    db.expire_all()
    assert db.query(GradingRun).filter(GradingRun.assignment_id == aid).count() == 1


# ---------------------------------------------------------------- stuck runs


def test_cleanup_gives_queued_runs_time_to_reach_a_worker(db, teacher_user, student_user):
    from backend.tasks.cleanup import (
        GRADING_RUN_QUEUED_MAX_MINUTES,
        GRADING_RUN_STUCK_MINUTES,
        _reconcile_stuck_grading_runs,
    )

    _, asgn, dep = _setup_lab(db, teacher_user, student_user)
    now = datetime.datetime.now(datetime.timezone.utc)
    ago = lambda minutes: now - datetime.timedelta(minutes=minutes)  # noqa: E731
    waiting = _run(db, asgn.id, student_user.id, status="queued", created_at=ago(GRADING_RUN_STUCK_MINUTES * 2))
    abandoned = _run(db, asgn.id, student_user.id, status="queued", created_at=ago(GRADING_RUN_QUEUED_MAX_MINUTES + 1))
    # Queued for long, picked up recently: its clock starts at started_at.
    fresh_running = _run(
        db, asgn.id, student_user.id, status="running",
        created_at=ago(GRADING_RUN_STUCK_MINUTES * 4), started_at=ago(1),
    )
    stuck_running = _run(
        db, asgn.id, student_user.id, status="running",
        created_at=ago(GRADING_RUN_STUCK_MINUTES * 3), started_at=ago(GRADING_RUN_STUCK_MINUTES + 1),
    )

    _reconcile_stuck_grading_runs(db, now)

    db.expire_all()
    status = {run.id: db.get(GradingRun, run.id).status for run in (waiting, abandoned, fresh_running, stuck_running)}
    assert status == {
        waiting.id: "queued",
        abandoned.id: "error",
        fresh_running.id: "running",
        stuck_running.id: "error",
    }


def test_worker_never_starts_a_run_reconciled_while_queued(db, teacher_user, student_user, monkeypatch):
    _, asgn, dep = _setup_lab(db, teacher_user, student_user)
    run = _run(db, asgn.id, student_user.id, status="queued", deployment_id=dep.id)
    created_jobs: list = []
    monkeypatch.setattr(grader_service, "ensure_grader_infra", lambda: None)
    monkeypatch.setattr(grader_service, "_create_job", created_jobs.append)
    monkeypatch.setattr(grader_service, "_delete_job", lambda name: None)
    # The cleanup loop flips it between the worker's read and its claim.
    original_resolve = grader_service.resolve_target

    def resolve_then_reconcile(run_obj, session):
        target = original_resolve(run_obj, session)
        with database.SessionLocal() as other:
            other.get(GradingRun, run_obj.id).status = "error"
            other.commit()
        return target

    monkeypatch.setattr(grader_service, "resolve_target", resolve_then_reconcile)

    grader_service.run_grading(run.id)

    db.expire_all()
    assert db.get(GradingRun, run.id).status == "error"
    assert created_jobs == []


def test_startup_reconciles_runs_left_by_the_previous_process(db, teacher_user, student_user):
    _, asgn, dep = _setup_lab(db, teacher_user, student_user)
    queued = _run(db, asgn.id, student_user.id, status="queued")
    running = _run(db, asgn.id, student_user.id, status="running")
    done = _run(db, asgn.id, student_user.id, status="done")

    assert grader_service.reconcile_orphaned_runs(db) == 2

    db.expire_all()
    assert db.get(GradingRun, queued.id).status == "error"
    assert db.get(GradingRun, running.id).error == grader_service.INTERRUPTED_BY_RESTART
    assert db.get(GradingRun, done.id).status == "done"


# ---------------------------------------------------------------- shutdown


def test_shutdown_stops_a_watching_worker_promptly(db, teacher_user, student_user, monkeypatch):
    _, asgn, dep = _setup_lab(db, teacher_user, student_user)
    run = _run(db, asgn.id, student_user.id, status="queued", trigger="student_self", deployment_id=dep.id)
    run_id = run.id
    watching = threading.Event()
    deleted_jobs: list = []

    def job_status(job_name, namespace):
        watching.set()
        return type("S", (), {"succeeded": 0, "failed": 0})()  # never finishes

    monkeypatch.setattr(grader_service, "ensure_grader_infra", lambda: None)
    monkeypatch.setattr(grader_service, "_create_job", lambda manifest: None)
    monkeypatch.setattr(grader_service, "_delete_job", deleted_jobs.append)
    monkeypatch.setattr(grader_service, "_read_job_status", job_status)
    monkeypatch.setattr(grader_service.settings, "GRADER_POLL_INTERVAL_SECONDS", 1)

    executor, stop = grader_service._executor()
    executor.submit(grader_service._run_grading_logged, run_id, stop)
    assert watching.wait(WAIT)

    started = time.monotonic()
    grader_service.shutdown()
    for thread in list(executor._threads):
        thread.join(WAIT)
    elapsed = time.monotonic() - started

    assert elapsed < 3, f"workers kept polling for {elapsed:.1f}s after shutdown"
    assert not any(thread.is_alive() for thread in executor._threads)
    db.expire_all()
    stored = db.get(GradingRun, run_id)
    assert stored.status == "error"
    assert stored.error == grader_service.INTERRUPTED_BY_SHUTDOWN
    assert deleted_jobs == []  # no Kubernetes call on the way out
