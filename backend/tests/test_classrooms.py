from backend.models import Classroom, Enrollment, User, UserRole
from backend.security import create_session, get_password_hash


BASE = "/api/v1"


def _make_extra_user(db, username, role):
    user = User(
        username=username,
        email=f"{username}@test.lab",
        hashed_password=get_password_hash("ExtraPass@1234!"),
        role=role,
        is_active=True,
        auth_provider="local",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


async def test_teacher_cannot_read_other_teacher_class_students(client, db, teacher_user):
    other_teacher = _make_extra_user(db, "otherteacher", UserRole.teacher)
    classroom = Classroom(name="Other class", owner_id=other_teacher.id)
    db.add(classroom)
    db.commit()
    db.refresh(classroom)

    token = create_session(teacher_user.id, teacher_user.username, teacher_user.role)
    client.cookies.set("session_id", token)

    r = await client.get(f"{BASE}/classrooms/{classroom.id}/students")
    assert r.status_code == 403


async def test_student_enrolled_can_read_own_class_assignments(
    student_client, db, teacher_user, student_user
):
    classroom = Classroom(name="Student class", owner_id=teacher_user.id)
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    db.add(Enrollment(classroom_id=classroom.id, user_id=student_user.id))
    db.commit()

    r = await student_client.get(f"{BASE}/classrooms/{classroom.id}/assignments")
    assert r.status_code == 200


async def test_teacher_cannot_enroll_non_student(teacher_client, db, teacher_user):
    classroom = Classroom(name="Teacher class", owner_id=teacher_user.id)
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    other_teacher = _make_extra_user(db, "teacher2", UserRole.teacher)

    r = await teacher_client.post(
        f"{BASE}/classrooms/{classroom.id}/students",
        json={"user_ids": [other_teacher.id]},
    )

    assert r.status_code == 200
    body = r.json()
    assert body["enrolled"] == 0
    assert body["results"][0]["status"] == "error"


async def test_classroom_lists_report_counts_and_active_labs(teacher_client, db, teacher_user, student_user):
    from backend.models import Assignment, Deployment

    classroom = Classroom(name="Counts", owner_id=teacher_user.id)
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    other = _make_extra_user(db, "student2", UserRole.student)
    db.add_all([
        Enrollment(classroom_id=classroom.id, user_id=student_user.id),
        Enrollment(classroom_id=classroom.id, user_id=other.id),
        Assignment(classroom_id=classroom.id, title="A1", instructions="x"),
        Assignment(classroom_id=classroom.id, title="A2", instructions="x", status="archived"),
        Deployment(user_id=student_user.id, name="old-lab", namespace="ns", deployment_type="custom", status="deleted"),
        Deployment(user_id=student_user.id, name="lab-1", namespace="ns", deployment_type="custom", status="active"),
    ])
    db.commit()

    r = await teacher_client.get(f"{BASE}/classrooms")
    assert r.status_code == 200
    row = next(c for c in r.json() if c["id"] == classroom.id)
    assert (row["student_count"], row["active_assignment_count"]) == (2, 1)

    r = await teacher_client.get(f"{BASE}/teacher/dashboard")
    assert r.status_code == 200
    row = next(c for c in r.json()["classrooms"] if c["id"] == classroom.id)
    assert (row["student_count"], row["active_assignment_count"]) == (2, 1)

    r = await teacher_client.get(f"{BASE}/classrooms/{classroom.id}/students")
    assert r.status_code == 200
    students = {s["username"]: s for s in r.json()}
    assert students[student_user.username]["lab_name"] == "lab-1"
    assert students[student_user.username]["lab_status"] == "active"
    assert students["student2"]["lab_name"] is None
