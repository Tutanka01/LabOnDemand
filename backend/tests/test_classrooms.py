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
