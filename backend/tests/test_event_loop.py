"""
Tests de non-blocage de la boucle asyncio et de bornage des appels K8s.

Sections :
  - délais par défaut du client REST Kubernetes (backend/k8s_timeouts.py) ;
  - dimensionnement du pool de threads AnyIO ;
  - services K8s synchrones (exécutés hors boucle par les appelants) ;
  - garde statique : endpoints/dépendances async limités à une liste blanche ;
  - déploiement en masse : concurrence bornée, sessions par thread, échecs partiels ;
  - Grading Runs : travail bloquant hors boucle, lots bornés, tâches référencées.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import threading
import time
from typing import Any, Dict
from unittest.mock import MagicMock

import anyio.to_thread
import pytest
import urllib3
from kubernetes import client as k8s_client
from kubernetes.client import rest

from backend import k8s_timeouts
from backend.config import settings


# ============================================================
# Délais par défaut du client REST Kubernetes
# ============================================================


@pytest.fixture()
def rest_client():
    """RESTClientObject réel dont le pool urllib3 est remplacé par un mock."""
    configuration = k8s_client.Configuration()
    configuration.host = "https://k8s.invalid:6443"
    rc = rest.RESTClientObject(configuration)
    response = MagicMock(status=200, reason="OK", data=b"{}", headers={})
    rc.pool_manager = MagicMock()
    rc.pool_manager.request.return_value = response
    return rc


@pytest.fixture()
def default_timeouts():
    """Installe des délais connus puis restaure la configuration applicative."""
    k8s_timeouts.install_default_request_timeout(5, 30)
    yield
    k8s_timeouts.install_default_request_timeout(
        settings.K8S_REQUEST_TIMEOUT_CONNECT, settings.K8S_REQUEST_TIMEOUT_READ
    )


def _sent_timeout(rc: rest.RESTClientObject) -> urllib3.Timeout:
    return rc.pool_manager.request.call_args.kwargs["timeout"]


def test_default_timeout_is_installed_at_startup():
    # init_kubernetes() (appelé à l'import de backend.main) installe l'enveloppe.
    assert getattr(rest.RESTClientObject.request, "__labondemand_default_timeout__", False)


def test_default_timeout_applied_when_caller_gives_none(rest_client, default_timeouts):
    rest_client.GET("https://k8s.invalid:6443/api/v1/namespaces")
    timeout = _sent_timeout(rest_client)
    assert isinstance(timeout, urllib3.Timeout)
    assert timeout.connect_timeout == 5
    assert timeout.read_timeout == 30


def test_default_timeout_applied_through_generated_api(default_timeouts):
    # Les API générées passent toujours _request_timeout=None explicitement.
    configuration = k8s_client.Configuration()
    configuration.host = "https://k8s.invalid:6443"
    api_client = k8s_client.ApiClient(configuration)
    response = MagicMock(status=200, reason="OK", data=b'{"items": []}', headers={})
    api_client.rest_client.pool_manager = MagicMock()
    api_client.rest_client.pool_manager.request.return_value = response
    k8s_client.CoreV1Api(api_client).list_namespace(limit=1)
    timeout = api_client.rest_client.pool_manager.request.call_args.kwargs["timeout"]
    assert (timeout.connect_timeout, timeout.read_timeout) == (5, 30)


def test_explicit_int_timeout_is_preserved(rest_client, default_timeouts):
    rest_client.GET("https://k8s.invalid:6443/api", _request_timeout=3)
    timeout = _sent_timeout(rest_client)
    assert timeout.total == 3


def test_explicit_tuple_timeout_is_preserved(rest_client, default_timeouts):
    rest_client.request("GET", "https://k8s.invalid:6443/api", _request_timeout=(1, 2))
    timeout = _sent_timeout(rest_client)
    assert (timeout.connect_timeout, timeout.read_timeout) == (1, 2)


def test_explicit_positional_timeout_is_preserved(rest_client, default_timeouts):
    # request(method, url, query_params, headers, body, post_params,
    #         _preload_content, _request_timeout)
    rest_client.request(
        "GET", "https://k8s.invalid:6443/api", None, None, None, None, True, 7
    )
    assert _sent_timeout(rest_client).total == 7


def test_opt_out_with_none_tuple(rest_client, default_timeouts):
    rest_client.GET("https://k8s.invalid:6443/api", _request_timeout=(None, None))
    timeout = _sent_timeout(rest_client)
    assert timeout.connect_timeout is None
    assert timeout.read_timeout is None


def test_streaming_call_gets_no_short_read_timeout(rest_client, default_timeouts):
    # watch / logs suivis : _preload_content=False → connexion bornée seulement.
    rest_client.GET("https://k8s.invalid:6443/api", _preload_content=False)
    timeout = _sent_timeout(rest_client)
    assert timeout.connect_timeout == 5
    assert timeout.read_timeout is None


def test_zero_disables_timeouts(rest_client):
    try:
        k8s_timeouts.install_default_request_timeout(0, 0)
        rest_client.GET("https://k8s.invalid:6443/api")
        # Aucun délai : comportement historique du client.
        assert _sent_timeout(rest_client) is None
    finally:
        k8s_timeouts.install_default_request_timeout(
            settings.K8S_REQUEST_TIMEOUT_CONNECT, settings.K8S_REQUEST_TIMEOUT_READ
        )


def test_install_is_idempotent(default_timeouts):
    original = k8s_timeouts._unwrap(rest.RESTClientObject.request)
    k8s_timeouts.install_default_request_timeout(1, 2)
    k8s_timeouts.install_default_request_timeout(3, 4)
    wrapper = rest.RESTClientObject.request
    assert wrapper.__wrapped__ is original


def test_resolve_request_timeout_rules():
    resolve = k8s_timeouts.resolve_request_timeout
    assert resolve(None, True, 5, 30) == (5, 30)
    assert resolve(None, False, 5, 30) == (5, None)
    assert resolve(9, True, 5, 30) == 9
    assert resolve((None, None), True, 5, 30) == (None, None)
    assert resolve(None, True, 0, 0) is None
    assert resolve(None, False, 0, 30) is None


def test_websocket_stream_path_is_untouched(default_timeouts):
    """kubernetes.stream.stream remplace ApiClient.request : REST jamais appelé."""
    from kubernetes.stream import stream as k8s_stream

    captured: Dict[str, Any] = {}

    def fake_websocket_call(configuration, *args, **kwargs):
        captured.update(kwargs)
        return "ws-result"

    configuration = k8s_client.Configuration()
    configuration.host = "https://k8s.invalid:6443"
    api_client = k8s_client.ApiClient(configuration)
    api_client.rest_client.pool_manager = MagicMock()
    core = k8s_client.CoreV1Api(api_client)

    # Même mécanique que kubernetes.stream.stream, avec un faux websocket_call.
    ws_request = functools.partial(k8s_stream.func, fake_websocket_call, None)
    ws_request(
        core.connect_get_namespaced_pod_exec,
        "pod",
        "ns",
        command=["ls"],
        stdout=True,
        _preload_content=False,
    )

    api_client.rest_client.pool_manager.request.assert_not_called()
    # Aucun délai injecté sur le chemin websocket (None = défaut du ws_client).
    assert captured.get("_request_timeout") is None
    assert captured.get("_preload_content") is False


# ============================================================
# Pool de threads AnyIO
# ============================================================


async def test_configure_threadpool_applies_setting(monkeypatch):
    from backend.config import Settings

    monkeypatch.setattr(Settings, "API_THREADPOOL_SIZE", 7)
    assert settings.configure_threadpool() == 7
    assert anyio.to_thread.current_default_thread_limiter().total_tokens == 7


async def test_threadpool_startup_hook_is_registered():
    from backend.main import app, configure_threadpool

    assert configure_threadpool in app.router.on_startup


# ============================================================
# Services K8s synchrones
# ============================================================


def test_blocking_services_are_plain_functions():
    from backend import k8s_utils
    from backend.deployment_service import deployment_service

    for func in (
        deployment_service.create_deployment,
        deployment_service.pause_application,
        deployment_service.resume_application,
        deployment_service._create_wordpress_stack,
        deployment_service._create_mysql_pma_stack,
        deployment_service._create_lamp_stack,
        k8s_utils.ensure_namespace_exists,
    ):
        assert not inspect.iscoroutinefunction(func), func.__name__


def test_ensure_namespace_exists_tolerates_concurrent_creation(mock_k8s):
    from backend.k8s_utils import ensure_namespace_exists

    mock_k8s["core"].create_namespace.side_effect = k8s_client.exceptions.ApiException(
        status=409
    )
    assert ensure_namespace_exists("labondemand-user-42") is True


def test_ensure_namespace_exists_reports_failure(mock_k8s):
    from backend.k8s_utils import ensure_namespace_exists

    mock_k8s["core"].create_namespace.side_effect = k8s_client.exceptions.ApiException(
        status=403
    )
    assert ensure_namespace_exists("labondemand-user-42") is False


# ============================================================
# Garde statique : endpoints et dépendances async
# ============================================================

# Seuls ces endpoints peuvent rester `async def` : ils attendent réellement
# quelque chose (WebSocket, orchestration concurrente, tâche de fond) et
# déportent chaque partie bloquante dans un thread. Tout autre endpoint doit
# être `def` pour que FastAPI l'exécute dans le pool de threads.
ASYNC_ENDPOINT_ALLOWLIST = {
    "backend.main.read_root",
    "backend.main.get_status",
    "backend.main.health_check",
    "backend.main.test_auth",
    "backend.routers.k8s_terminal.ws_pod_terminal",
    "backend.routers.classrooms.deploy_assignment_to_class",
    "backend.routers.classrooms.test_now",
    "backend.routers.classrooms.run_tests_all",
    "backend.routers.student.run_tests",
}


def _endpoint_id(func) -> str:
    func = inspect.unwrap(func)
    return f"{func.__module__}.{func.__qualname__}"


def _iter_dependency_calls(dependant):
    for dep in dependant.dependencies:
        if dep.call is not None:
            yield dep.call
        yield from _iter_dependency_calls(dep)


def test_async_endpoints_are_allowlisted():
    from backend.main import app

    offenders = sorted(
        _endpoint_id(route.endpoint)
        for route in app.routes
        if getattr(route, "endpoint", None) is not None
        and _endpoint_id(route.endpoint).startswith("backend.")
        and inspect.iscoroutinefunction(inspect.unwrap(route.endpoint))
        and _endpoint_id(route.endpoint) not in ASYNC_ENDPOINT_ALLOWLIST
    )
    assert offenders == [], f"endpoints async hors liste blanche : {offenders}"


def test_request_dependencies_are_sync():
    from backend.main import app

    offenders = set()
    for route in app.routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for call in _iter_dependency_calls(dependant):
            module = getattr(call, "__module__", "") or ""
            if module.startswith("backend.") and inspect.iscoroutinefunction(call):
                offenders.add(f"{module}.{getattr(call, '__qualname__', call)}")
    assert offenders == set(), f"dépendances async (bloquantes ?) : {sorted(offenders)}"


# ============================================================
# Outils : la boucle reste réactive pendant un appel lent
# ============================================================


async def _timed(awaitable, delay: float = 0.0):
    """Attend `delay`, exécute l'awaitable et renvoie (résultat, durée)."""
    if delay:
        await asyncio.sleep(delay)
    loop = asyncio.get_running_loop()
    start = loop.time()
    result = await awaitable
    return result, loop.time() - start


async def _assert_loop_responsive(client, slow_awaitable, slow_min: float = 0.4):
    """Lance une requête lente et, en parallèle, /api/v1/status qui doit finir vite."""
    (slow_resp, slow_elapsed), (fast_resp, fast_elapsed) = await asyncio.gather(
        _timed(slow_awaitable),
        _timed(client.get("/api/v1/status"), delay=0.05),
    )
    assert fast_resp.status_code == 200
    assert slow_elapsed >= slow_min, f"appel lent trop rapide ({slow_elapsed:.2f}s)"
    assert fast_elapsed < 0.25, f"/status bloqué {fast_elapsed:.2f}s derrière un appel lent"
    return slow_resp


# ============================================================
# Déploiement en masse
# ============================================================


@pytest.fixture()
def bulk_class(db, teacher_user):
    from backend.models import Assignment, Classroom, Enrollment, User, UserRole
    from backend.security import get_password_hash

    classroom = Classroom(name="Classe bulk", owner_id=teacher_user.id)
    db.add(classroom)
    db.commit()
    hashed = get_password_hash("BulkPass@1234!")
    students = []
    for index in range(6):
        user = User(
            username=f"bulk{index}",
            email=f"bulk{index}@test.lab",
            hashed_password=hashed,
            role=UserRole.student,
            is_active=True,
            auth_provider="local",
        )
        db.add(user)
        db.commit()
        db.add(Enrollment(classroom_id=classroom.id, user_id=user.id))
        students.append(user)
    assignment = Assignment(
        classroom_id=classroom.id,
        title="TP Réseau",
        cpu_preset="low",
        ram_preset="low",
        status="active",
    )
    db.add(assignment)
    db.commit()
    return classroom.id, assignment.id, [(u.id, u.username) for u in students]


async def test_bulk_spawn_bounded_threads_and_partial_failures(
    teacher_client, db, bulk_class, monkeypatch
):
    from sqlalchemy import inspect as sa_inspect

    from backend.config import Settings
    from backend.models import AssignmentDeployment, Deployment
    from backend.routers import classrooms as classrooms_mod

    cid, aid, students = bulk_class
    monkeypatch.setattr(Settings, "BULK_SPAWN_CONCURRENCY", 2)

    # Étudiant 0 : lab déjà actif → skipped. Étudiant 2 : échec K8s.
    skipped_id, failing_id = students[0][0], students[2][0]
    db.add(
        Deployment(
            user_id=skipped_id,
            name=f"tp-r-seau-u{skipped_id}",
            deployment_type="custom",
            namespace="labondemand-user-x",
            status="active",
        )
    )
    db.commit()

    lock = threading.Lock()
    state = {"active": 0, "max": 0}
    spawn_threads = set()
    users_detached = []
    loop_thread = threading.get_ident()

    def fake_create_deployment(**kwargs):
        user = kwargs["current_user"]
        users_detached.append(sa_inspect(user).detached)
        with lock:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            spawn_threads.add(threading.get_ident())
        try:
            time.sleep(0.2)
            if user.id == failing_id:
                raise RuntimeError("Quota Kubernetes dépassé")
            return {"message": "ok"}
        finally:
            with lock:
                state["active"] -= 1

    real_factory = classrooms_mod.SessionLocal
    sessions = []
    # SQLite de test (StaticPool) : une seule connexion partagée, non utilisable
    # en parallèle. On sérialise donc la durée de vie des sessions des workers
    # (en production, chaque session a sa propre connexion du pool). Effet de
    # bord utile : si une session restait ouverte pendant l'appel K8s, la
    # concurrence observée tomberait à 1.
    db_lock = threading.Lock()

    def tracking_session_local():
        db_lock.acquire()
        session = real_factory()
        sessions.append((threading.get_ident(), session))
        original_close = session.close
        released = False

        def close() -> None:
            nonlocal released
            try:
                original_close()
            finally:
                if not released:
                    released = True
                    db_lock.release()

        session.close = close
        return session

    monkeypatch.setattr(
        classrooms_mod.deployment_service, "create_deployment", fake_create_deployment
    )
    monkeypatch.setattr(classrooms_mod, "SessionLocal", tracking_session_local)

    resp = await _assert_loop_responsive(
        teacher_client,
        teacher_client.post(f"/api/v1/classrooms/{cid}/assignments/{aid}/deploy-all"),
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()

    # Forme du rapport et échecs partiels conservés, dans l'ordre des étudiants.
    assert (report["total"], report["ok"], report["skipped"], report["errors"]) == (6, 4, 1, 1)
    assert [r["user_id"] for r in report["results"]] == [sid for sid, _ in students]
    by_user = {r["user_id"]: r for r in report["results"]}
    assert by_user[skipped_id]["status"] == "skipped"
    assert by_user[failing_id]["status"] == "error"
    assert "Quota" in by_user[failing_id]["error"]

    # Concurrence bornée par BULK_SPAWN_CONCURRENCY, hors de la boucle.
    assert state["max"] == 2
    assert loop_thread not in spawn_threads
    # Sessions propres à chaque unité de travail, jamais ouvertes dans la boucle.
    assert sessions and all(tid != loop_thread for tid, _ in sessions)
    assert len({id(s) for _, s in sessions}) == len(sessions)
    # L'utilisateur transmis vient de la session du thread (détachée), pas de la requête.
    assert users_detached and all(users_detached)

    records = db.query(AssignmentDeployment).filter(AssignmentDeployment.assignment_id == aid).all()
    statuses = sorted(r.spawn_status for r in records)
    assert statuses == ["error", "ok", "ok", "ok", "ok"]
    error_record = next(r for r in records if r.spawn_status == "error")
    assert error_record.user_id == failing_id
    assert "Quota" in error_record.spawn_error


async def test_bulk_spawn_rejects_archived_assignment(teacher_client, db, bulk_class):
    from backend.models import Assignment

    cid, aid, _ = bulk_class
    db.query(Assignment).filter(Assignment.id == aid).update({"status": "archived"})
    db.commit()
    resp = await teacher_client.post(f"/api/v1/classrooms/{cid}/assignments/{aid}/deploy-all")
    assert resp.status_code == 400


# ============================================================
# Grading Runs
# ============================================================


async def test_run_grading_does_blocking_work_off_loop(client, db, teacher_user, student_user, monkeypatch):
    from backend import grader_service
    from backend.models import GradingRun
    from backend.tests.test_grading import _assignment, _classroom, _deployment, _run, _spec

    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _spec(db, asgn.id)
    dep = _deployment(db, student_user.id)
    run = _run(db, asgn.id, student_user.id, status="queued", trigger="student_self", deployment_id=dep.id)
    logs = (
        f"{grader_service.RESULT_BEGIN}\n"
        '{"checks": [{"id": "h1", "name": "H1", "status": "pass", "weight": 1, "visibility": "student"}]}'
        f"\n{grader_service.RESULT_END}\n"
    )

    threads: Dict[str, int] = {}

    def record(name: str, result: Any = None, delay: float = 0.0):
        def _fn(*_args, **_kwargs):
            threads[name] = threading.get_ident()
            if delay:
                time.sleep(delay)
            return result
        return _fn

    real_factory = grader_service.SessionLocal
    session_threads = []

    def tracking_session_local():
        session_threads.append(threading.get_ident())
        return real_factory()

    # Infra K8s lente (0.5 s) : la boucle doit continuer de servir /status.
    monkeypatch.setattr(grader_service, "ensure_grader_infra", record("infra", delay=0.5))
    monkeypatch.setattr(grader_service, "_create_job", record("create"))
    monkeypatch.setattr(grader_service, "_delete_job", record("delete"))
    monkeypatch.setattr(
        grader_service, "_read_job_status", record("status", type("S", (), {"succeeded": 1, "failed": 0})())
    )
    monkeypatch.setattr(grader_service, "_read_job_logs", record("logs", logs))
    monkeypatch.setattr(grader_service, "SessionLocal", tracking_session_local)
    monkeypatch.setattr(grader_service.settings, "GRADER_POLL_INTERVAL_SECONDS", 0)

    await _assert_loop_responsive(client, grader_service.run_grading(run.id))

    loop_thread = threading.get_ident()
    assert set(threads) == {"infra", "create", "delete", "status", "logs"}
    assert loop_thread not in threads.values()
    assert session_threads and loop_thread not in session_threads
    db.expire_all()
    assert db.query(GradingRun).filter(GradingRun.id == run.id).one().status == "done"


async def test_run_tests_all_bounds_concurrent_grading_runs(teacher_client, db, teacher_user, monkeypatch):
    from backend import grader_service
    from backend.config import Settings
    from backend.models import GradingRun, User, UserRole
    from backend.security import get_password_hash
    from backend.tests.test_grading import _assignment, _classroom, _deployment, _enroll, _link_lab, _spec

    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _spec(db, asgn.id)
    hashed = get_password_hash("GradePass@1234!")
    for index in range(5):
        user = User(
            username=f"grade{index}",
            email=f"grade{index}@test.lab",
            hashed_password=hashed,
            role=UserRole.student,
            is_active=True,
            auth_provider="local",
        )
        db.add(user)
        db.commit()
        _enroll(db, cls.id, user.id)
        dep = _deployment(db, user.id, name=f"tp-test-u{user.id}")
        _link_lab(db, asgn.id, user.id, dep.id)

    monkeypatch.setattr(Settings, "BULK_GRADING_CONCURRENCY", 2)
    state = {"active": 0, "max": 0}
    seen = []

    async def fake_run_grading(run_id: int) -> None:
        state["active"] += 1
        state["max"] = max(state["max"], state["active"])
        await asyncio.sleep(0.05)
        seen.append(run_id)
        state["active"] -= 1

    monkeypatch.setattr(grader_service, "run_grading", fake_run_grading)

    resp = await teacher_client.post(f"/api/v1/classrooms/{cls.id}/assignments/{asgn.id}/run-tests-all")
    assert resp.status_code == 200
    assert resp.json() == {"queued": 5}

    # Un seul lot en arrière-plan, référencé jusqu'à sa fin.
    pending = list(grader_service._background_tasks)
    assert len(pending) == 1
    await asyncio.gather(*pending)
    await asyncio.sleep(0)

    run_ids = [r.id for r in db.query(GradingRun).filter(GradingRun.assignment_id == asgn.id)]
    assert sorted(seen) == sorted(run_ids)
    assert state["max"] == 2
    assert not grader_service._background_tasks


async def test_schedule_grading_keeps_a_reference_until_done(monkeypatch):
    from backend import grader_service

    release = asyncio.Event()
    calls = []

    async def fake_run_grading(run_id: int) -> None:
        calls.append(run_id)
        await release.wait()

    monkeypatch.setattr(grader_service, "run_grading", fake_run_grading)
    task = grader_service.schedule_grading(42)
    assert task in grader_service._background_tasks
    await asyncio.sleep(0)
    release.set()
    await task
    await asyncio.sleep(0)
    assert calls == [42]
    assert task not in grader_service._background_tasks
    assert grader_service.schedule_grading_batch([], 3) is None
