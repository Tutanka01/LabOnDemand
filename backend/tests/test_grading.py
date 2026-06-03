"""Tests du Grader Pod et du triage (MVP-2).

Couvre :
  - propriétés de sécurité du manifeste Job + NetworkPolicy ;
  - parsing des logs, calcul du score, filtrage de visibilité ;
  - endpoints d'exécution (étudiant / prof) + autorisations ;
  - pipeline « pull » complet du watcher avec K8s mocké.
"""
import json

from backend import grader_service
from backend.models import (
    Assignment,
    AssignmentDeployment,
    Classroom,
    Deployment,
    Enrollment,
    GradingRun,
    GradingSpec,
)

BASE = "/api/v1"


# ── Helpers ───────────────────────────────────────────────────────────────


def _classroom(db, owner_id, name="Classe test"):
    c = Classroom(name=name, owner_id=owner_id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _assignment(db, classroom_id, title="TP test", grading_mode="self_check"):
    a = Assignment(classroom_id=classroom_id, title=title, instructions="x", grading_mode=grading_mode)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _enroll(db, classroom_id, user_id):
    db.add(Enrollment(classroom_id=classroom_id, user_id=user_id))
    db.commit()


def _probe(pid="h1", kind="http", visibility="student", weight=1):
    return {
        "id": pid,
        "name": f"Probe {pid}",
        "kind": kind,
        "vantage": "outside",
        "config": {"url": "/health"},
        "expect": {"status": 200},
        "weight": weight,
        "visibility": visibility,
    }


def _spec(db, aid, checks=None, custom_script=None, timeout=60):
    s = GradingSpec(
        assignment_id=aid,
        timeout_seconds=timeout,
        checks=json.dumps(checks if checks is not None else [_probe()]),
        custom_script=custom_script,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _deployment(db, user_id, name="tp-test-u1", ns="labondemand-user-1", dtype="custom", status="active"):
    d = Deployment(user_id=user_id, name=name, namespace=ns, deployment_type=dtype, status=status)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def _link_lab(db, aid, user_id, dep_id):
    db.add(AssignmentDeployment(assignment_id=aid, user_id=user_id, deployment_id=dep_id, spawn_status="ok"))
    db.commit()


def _run(db, aid, user_id, **kw):
    r = GradingRun(assignment_id=aid, user_id=user_id, trigger=kw.pop("trigger", "teacher"),
                   status=kw.pop("status", "done"), **kw)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _noop_async(*_a, **_k):
    async def _inner():
        return None
    return _inner()


# ── Unitaires : manifeste & sécurité ───────────────────────────────────────


def test_job_manifest_is_isolated():
    target = {"url": "http://svc.ns.svc:80", "host": "svc.ns.svc", "port": 80}
    spec_json = json.dumps({"checks": [_probe(), _probe("h2")]})
    manifest = grader_service.build_job_manifest(
        run_id=42, image="labondemand/grader:test", timeout_seconds=90,
        spec_json=spec_json, target=target, custom_script=None,
    )
    spec = manifest["spec"]
    pod = spec["template"]["spec"]
    container = pod["containers"][0]

    # Pas d'accès cluster : SA sans token monté.
    assert pod["automountServiceAccountToken"] is False
    assert pod["serviceAccountName"] == grader_service.GRADER_SA_NAME
    # Time-box + pas de retry + TTL.
    assert spec["activeDeadlineSeconds"] == 90
    assert spec["backoffLimit"] == 0
    assert "ttlSecondsAfterFinished" in spec
    assert pod["restartPolicy"] == "Never"
    # Limites de ressources présentes.
    assert container["resources"]["limits"]["cpu"]
    assert container["resources"]["limits"]["memory"]
    # Durcissement conteneur.
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert "ALL" in container["securityContext"]["capabilities"]["drop"]


def test_network_policy_restricts_egress():
    np = grader_service.build_network_policy("labondemand-grader")
    spec = np["spec"]
    assert spec["policyTypes"] == ["Ingress", "Egress"]
    assert spec["ingress"] == []  # tout entrant refusé
    # Egress : labs (namespaceSelector managed-by) + DNS port 53.
    dumped = json.dumps(spec["egress"])
    assert "managed-by" in dumped
    assert "53" in dumped


# ── Unitaires : parsing / score / visibilité ───────────────────────────────


def test_parse_results_from_logs():
    logs = (
        "bruit avant\n"
        f"{grader_service.RESULT_BEGIN}\n"
        '{"checks": [{"id": "h1", "name": "H", "status": "pass", "weight": 1, "visibility": "student"}]}\n'
        f"{grader_service.RESULT_END}\n"
    )
    results = grader_service.parse_results_from_logs(logs)
    assert results is not None
    assert results[0]["id"] == "h1"
    assert results[0]["status"] == "pass"


def test_parse_results_invalid_returns_none():
    assert grader_service.parse_results_from_logs("rien d'utile") is None
    assert grader_service.parse_results_from_logs("") is None


def test_summarize_weighted_score():
    results = [
        {"status": "pass", "weight": 3},
        {"status": "fail", "weight": 1},
        {"status": "skip", "weight": 5},  # ignoré du calcul
    ]
    s = grader_service.summarize(results)
    assert s["total"] == 2
    assert s["passed"] == 1
    # 3/(3+1) * 20 = 15
    assert s["score_suggestion"] == "15/20"


def test_filter_results_for_student_hides_and_collapses():
    results = [
        {"id": "a", "name": "A", "status": "pass", "message": "ok", "output": "x", "weight": 1, "visibility": "student"},
        {"id": "b", "name": "B", "status": "fail", "message": "secret", "output": "leak", "weight": 1, "visibility": "summary"},
        {"id": "c", "name": "C", "status": "pass", "message": "hidden", "output": "h", "weight": 1, "visibility": "teacher_only"},
    ]
    filtered = grader_service.filter_results_for_student(results)
    ids = [r["id"] for r in filtered]
    assert ids == ["a", "b"]  # teacher_only retiré
    summary = next(r for r in filtered if r["id"] == "b")
    assert summary["message"] is None and summary["output"] is None  # résumé : pas de détail


# ── Endpoints étudiant ─────────────────────────────────────────────────────


async def test_student_run_tests_requires_lab(student_client, db, teacher_user, student_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)
    _spec(db, asgn.id)
    # pas de lab lié
    r = await student_client.post(f"{BASE}/student/assignments/{asgn.id}/run-tests")
    assert r.status_code == 400


async def test_student_run_tests_creates_queued_run(
    student_client, db, teacher_user, student_user, monkeypatch
):
    monkeypatch.setattr("backend.grader_service.run_grading", _noop_async)
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)
    _spec(db, asgn.id)
    dep = _deployment(db, student_user.id)
    _link_lab(db, asgn.id, student_user.id, dep.id)

    r = await student_client.post(f"{BASE}/student/assignments/{asgn.id}/run-tests")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["trigger"] == "student_self"
    assert db.query(GradingRun).filter(GradingRun.assignment_id == asgn.id).count() == 1


async def test_run_tests_disabled_when_grading_mode_none(
    student_client, db, teacher_user, student_user
):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id, grading_mode="none")
    _enroll(db, cls.id, student_user.id)
    _spec(db, asgn.id)
    dep = _deployment(db, student_user.id)
    _link_lab(db, asgn.id, student_user.id, dep.id)

    r = await student_client.post(f"{BASE}/student/assignments/{asgn.id}/run-tests")
    assert r.status_code == 400


async def test_non_enrolled_cannot_run_tests(student_client, db, teacher_user, student_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _spec(db, asgn.id)
    r = await student_client.post(f"{BASE}/student/assignments/{asgn.id}/run-tests")
    assert r.status_code == 404


async def test_get_grading_run_filters_visibility(student_client, db, teacher_user, student_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)
    results = [
        {"id": "a", "name": "A", "status": "pass", "message": "m", "output": "o", "weight": 1, "visibility": "student"},
        {"id": "c", "name": "C", "status": "fail", "message": "x", "output": "y", "weight": 1, "visibility": "teacher_only"},
    ]
    run = _run(db, asgn.id, student_user.id, status="done", trigger="student_self",
               results=json.dumps(results), total_checks=2, passed_checks=1)

    r = await student_client.get(f"{BASE}/student/assignments/{asgn.id}/grading-runs/{run.id}")
    assert r.status_code == 200
    got = r.json()
    ids = [x["id"] for x in got["results"]]
    assert ids == ["a"]  # teacher_only masquée à l'étudiant


# ── Endpoints prof ─────────────────────────────────────────────────────────


async def test_teacher_test_now_requires_demo_lab(teacher_client, db, teacher_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _spec(db, asgn.id)
    r = await teacher_client.post(f"{BASE}/classrooms/{cls.id}/assignments/{asgn.id}/test-now")
    assert r.status_code == 400


async def test_teacher_run_tests_all_queues_per_student_with_lab(
    teacher_client, db, teacher_user, student_user, monkeypatch
):
    monkeypatch.setattr("backend.grader_service.run_grading", _noop_async)
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _spec(db, asgn.id)
    # student_user a un lab, un second étudiant n'en a pas.
    from backend.models import User, UserRole
    from backend.security import get_password_hash

    other = User(username="stud2", email="stud2@test.lab", hashed_password=get_password_hash("Pass@12345678!"),
                 role=UserRole.student, is_active=True, auth_provider="local")
    db.add(other)
    db.commit()
    db.refresh(other)

    _enroll(db, cls.id, student_user.id)
    _enroll(db, cls.id, other.id)
    dep = _deployment(db, student_user.id)
    _link_lab(db, asgn.id, student_user.id, dep.id)

    r = await teacher_client.post(f"{BASE}/classrooms/{cls.id}/assignments/{asgn.id}/run-tests-all")
    assert r.status_code == 200
    assert r.json()["queued"] == 1


async def test_submissions_list_includes_verdict(teacher_client, db, teacher_user, student_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)
    _run(db, asgn.id, student_user.id, status="done", trigger="teacher",
         total_checks=4, passed_checks=3, score_suggestion="15/20")

    r = await teacher_client.get(f"{BASE}/classrooms/{cls.id}/assignments/{asgn.id}/submissions")
    assert r.status_code == 200
    row = r.json()[0]
    assert row["grading_status"] == "done"
    assert row["grading_passed"] == 3
    assert row["grading_total"] == 4
    assert row["score_suggestion"] == "15/20"


# ── Pipeline pull complet (watcher) ────────────────────────────────────────


async def test_run_grading_pull_pipeline(db, teacher_user, student_user, monkeypatch):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _spec(db, asgn.id, checks=[_probe("h1", weight=2), _probe("h2", weight=2)])
    dep = _deployment(db, student_user.id)
    run = _run(db, asgn.id, student_user.id, status="queued", trigger="student_self", deployment_id=dep.id)

    logs = (
        f"{grader_service.RESULT_BEGIN}\n"
        + json.dumps({"checks": [
            {"id": "h1", "name": "H1", "status": "pass", "weight": 2, "visibility": "student"},
            {"id": "h2", "name": "H2", "status": "fail", "weight": 2, "visibility": "student"},
        ]})
        + f"\n{grader_service.RESULT_END}\n"
    )

    # On court-circuite tous les appels K8s : infra, création de Job, lecture.
    monkeypatch.setattr(grader_service, "ensure_grader_infra", lambda: None)
    monkeypatch.setattr(grader_service, "_create_job", lambda manifest: None)
    monkeypatch.setattr(grader_service, "_delete_job", lambda name: None)
    monkeypatch.setattr(grader_service, "_read_job_status", lambda j, n: type("S", (), {"succeeded": 1, "failed": 0})())
    monkeypatch.setattr(grader_service, "_read_job_logs", lambda j, n: logs)
    monkeypatch.setattr(grader_service.settings, "GRADER_POLL_INTERVAL_SECONDS", 0)

    await grader_service.run_grading(run.id)

    db.expire_all()
    refreshed = db.query(GradingRun).filter(GradingRun.id == run.id).first()
    assert refreshed.status == "done"
    assert refreshed.total_checks == 2
    assert refreshed.passed_checks == 1
    assert refreshed.score_suggestion == "10/20"  # 2/(2+2)*20
    stored = json.loads(refreshed.results)
    assert {r["id"] for r in stored} == {"h1", "h2"}
