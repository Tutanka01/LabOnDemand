"""Tests du système de devoirs côté étudiant + correction (MVP-1)."""
from datetime import datetime, timedelta, timezone

from backend.models import (
    Assignment,
    AssignmentSubmission,
    Classroom,
    Enrollment,
)

BASE = "/api/v1"


def _classroom(db, owner_id, name="Classe test"):
    c = Classroom(name=name, owner_id=owner_id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _assignment(db, classroom_id, title="TP test", due_at=None):
    a = Assignment(classroom_id=classroom_id, title=title, instructions="Consignes", due_at=due_at)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _enroll(db, classroom_id, user_id):
    db.add(Enrollment(classroom_id=classroom_id, user_id=user_id))
    db.commit()


# ── Accès gardé par l'inscription ──────────────────────────────────────────


async def test_non_enrolled_student_cannot_see_assignment(
    student_client, db, teacher_user, student_user
):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    # pas d'inscription
    r = await student_client.get(f"{BASE}/student/assignments/{asgn.id}")
    assert r.status_code == 404


async def test_non_enrolled_student_cannot_submit(
    student_client, db, teacher_user, student_user
):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    r = await student_client.post(
        f"{BASE}/student/assignments/{asgn.id}/submit",
        json={"text": "tentative"},
    )
    assert r.status_code == 404


async def test_enrolled_student_sees_assignment_in_list(
    student_client, db, teacher_user, student_user
):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)

    r = await student_client.get(f"{BASE}/student/assignments")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == asgn.id
    assert items[0]["submission_status"] == "not_started"


# ── Soumission ──────────────────────────────────────────────────────────────


async def test_submit_creates_submission(student_client, db, teacher_user, student_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id, due_at=datetime.now(timezone.utc) + timedelta(days=1))
    _enroll(db, cls.id, student_user.id)

    r = await student_client.post(
        f"{BASE}/student/assignments/{asgn.id}/submit",
        json={"text": "Mon rendu", "links": [{"label": "Repo", "url": "https://git/x"}]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "submitted"
    assert body["is_late"] is False
    assert body["attempt_no"] == 1
    assert body["links"][0]["url"] == "https://git/x"


async def test_submit_empty_is_rejected(student_client, db, teacher_user, student_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)

    r = await student_client.post(f"{BASE}/student/assignments/{asgn.id}/submit", json={})
    assert r.status_code == 400


async def test_submit_after_due_is_late(student_client, db, teacher_user, student_user):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id, due_at=datetime.now(timezone.utc) - timedelta(days=1))
    _enroll(db, cls.id, student_user.id)

    r = await student_client.post(
        f"{BASE}/student/assignments/{asgn.id}/submit", json={"text": "en retard"}
    )
    assert r.status_code == 200
    assert r.json()["is_late"] is True


async def test_resubmission_increments_attempt_and_updates_same_row(
    student_client, db, teacher_user, student_user
):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)

    await student_client.post(f"{BASE}/student/assignments/{asgn.id}/submit", json={"text": "v1"})
    r2 = await student_client.post(
        f"{BASE}/student/assignments/{asgn.id}/submit", json={"text": "v2"}
    )
    assert r2.status_code == 200
    assert r2.json()["attempt_no"] == 2
    assert r2.json()["text"] == "v2"

    count = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == asgn.id,
            AssignmentSubmission.user_id == student_user.id,
        )
        .count()
    )
    assert count == 1


# ── Correction côté enseignant ────────────────────────────────────────────


async def test_teacher_list_includes_not_started_students(
    teacher_client, db, teacher_user, student_user
):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)

    r = await teacher_client.get(f"{BASE}/classrooms/{cls.id}/assignments/{asgn.id}/submissions")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["user_id"] == student_user.id
    assert rows[0]["submission_status"] == "not_started"
    assert rows[0]["submission_id"] is None


async def test_teacher_can_grade_submission(
    teacher_client, student_client, db, teacher_user, student_user
):
    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)
    _enroll(db, cls.id, student_user.id)

    sub_resp = await student_client.post(
        f"{BASE}/student/assignments/{asgn.id}/submit", json={"text": "rendu"}
    )
    sid = sub_resp.json()["id"]

    r = await teacher_client.post(
        f"{BASE}/classrooms/{cls.id}/assignments/{asgn.id}/submissions/{sid}/grade",
        json={"grade": "15/20", "feedback": "Bien"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "graded"
    assert body["grade"] == "15/20"
    assert body["graded_by"] == teacher_user.id
    assert body["graded_at"] is not None


async def test_other_teacher_cannot_list_submissions(
    client, db, teacher_user, student_user
):
    from backend.models import User, UserRole
    from backend.security import create_session, get_password_hash

    other = User(
        username="otherprof",
        email="otherprof@test.lab",
        hashed_password=get_password_hash("OtherPass@1234!"),
        role=UserRole.teacher,
        is_active=True,
        auth_provider="local",
    )
    db.add(other)
    db.commit()
    db.refresh(other)

    cls = _classroom(db, teacher_user.id)
    asgn = _assignment(db, cls.id)

    client.cookies.set("session_id", create_session(other.id, other.username, other.role))
    r = await client.get(f"{BASE}/classrooms/{cls.id}/assignments/{asgn.id}/submissions")
    assert r.status_code == 403
