"""
Router — Classrooms, Enrollments, Assignments (système de classe P0)

Endpoints :
  Classrooms   : CRUD + list
  Students     : enroll/unenroll + CSV import
  Assignments  : CRUD + bulk-spawn
  Dashboard    : vue agrégée enseignant
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from .. import grader_service
from ..database import get_db
from ..deployment_service import deployment_service
from ..models import (
    Assignment,
    AssignmentDeployment,
    AssignmentSubmission,
    Classroom,
    Deployment,
    Enrollment,
    GradingRun,
    GradingSpec,
    Template,
    User,
    UserRole,
)
from ..schemas import (
    AssignmentCreate,
    AssignmentResponse,
    AssignmentSubmissionResponse,
    AssignmentUpdate,
    BulkSpawnReport,
    BulkSpawnResult,
    ClassroomCreate,
    ClassroomResponse,
    ClassroomUpdate,
    EnrollStudentsRequest,
    GradingRunResponse,
    GradingSpecCreate,
    GradingSpecResponse,
    Probe,
    StudentLabStatus,
    SubmissionGradeRequest,
    SubmissionLink,
    TeacherSubmissionRow,
)
from ..security import get_current_user, is_teacher_or_admin
from ..security import get_password_hash, validate_password_strength
from ..config import settings

audit_logger = logging.getLogger("labondemand.audit")

classrooms_router = APIRouter(prefix="/api/v1/classrooms", tags=["classrooms"])
teacher_router = APIRouter(prefix="/api/v1/teacher", tags=["teacher"])

# ── Presets CPU/RAM ────────────────────────────────────────────────────────────

_CPU_PRESETS = {
    "very-low": ("100m", "200m"),
    "low": ("200m", "500m"),
    "medium": ("500m", "1000m"),
    "high": ("1000m", "2000m"),
    "very-high": ("2000m", "4000m"),
}
_RAM_PRESETS = {
    "very-low": ("128Mi", "256Mi"),
    "low": ("256Mi", "512Mi"),
    "medium": ("512Mi", "1024Mi"),
    "high": ("1024Mi", "2048Mi"),
    "very-high": ("2048Mi", "4096Mi"),
}


class StudentCreateAndEnrollRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=120)
    password: str = Field(..., min_length=12)


def _preset_cpu(preset: Optional[str], kind: str) -> str:
    pair = _CPU_PRESETS.get(preset or "low", _CPU_PRESETS["low"])
    return pair[0] if kind == "request" else pair[1]


def _preset_ram(preset: Optional[str], kind: str) -> str:
    pair = _RAM_PRESETS.get(preset or "low", _RAM_PRESETS["low"])
    return pair[0] if kind == "request" else pair[1]


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "assignment"


# ── Guards ─────────────────────────────────────────────────────────────────────


def _get_classroom_or_404(cid: int, db: Session) -> Classroom:
    cls = db.query(Classroom).filter(Classroom.id == cid).first()
    if not cls:
        raise HTTPException(status_code=404, detail="Classe introuvable")
    return cls


def _require_owner_or_admin(cls: Classroom, current_user: User) -> None:
    if current_user.role == UserRole.admin:
        return
    if cls.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Accès refusé : vous n'êtes pas propriétaire de cette classe")


def _require_classroom_access(cls: Classroom, current_user: User, db: Session) -> None:
    if current_user.role == UserRole.admin:
        return
    if current_user.role == UserRole.teacher:
        _require_owner_or_admin(cls, current_user)
        return
    enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.classroom_id == cls.id,
            Enrollment.user_id == current_user.id,
            Enrollment.removed_at.is_(None),
        )
        .first()
    )
    if not enrolled:
        raise HTTPException(status_code=403, detail="Accès refusé : vous n'êtes pas inscrit dans cette classe")


# ── CLASSROOM CRUD ─────────────────────────────────────────────────────────────


@classrooms_router.get("", response_model=List[ClassroomResponse])
def list_classrooms(
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Classroom)
    if current_user.role == UserRole.admin:
        pass
    elif current_user.role == UserRole.teacher:
        q = q.filter(Classroom.owner_id == current_user.id)
    else:
        enrolled_ids = (
            db.query(Enrollment.classroom_id)
            .filter(Enrollment.user_id == current_user.id, Enrollment.removed_at.is_(None))
            .subquery()
        )
        q = q.filter(Classroom.id.in_(enrolled_ids))
    if not include_archived:
        q = q.filter(Classroom.archived == False)  # noqa: E712
    classrooms = q.order_by(Classroom.created_at.desc()).all()
    return [_enrich_classroom(c, db) for c in classrooms]


@classrooms_router.post("", response_model=ClassroomResponse, status_code=201, dependencies=[Depends(is_teacher_or_admin)])
def create_classroom(
    payload: ClassroomCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = Classroom(name=payload.name, description=payload.description, owner_id=current_user.id)
    db.add(cls)
    db.commit()
    db.refresh(cls)
    audit_logger.info("classroom_created", extra={"extra_fields": {"classroom_id": cls.id, "name": cls.name, "owner_id": current_user.id}})
    return _enrich_classroom(cls, db)


@classrooms_router.get("/{cid}", response_model=ClassroomResponse)
def get_classroom(cid: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cls = _get_classroom_or_404(cid, db)
    _require_classroom_access(cls, current_user, db)
    return _enrich_classroom(cls, db)


@classrooms_router.put("/{cid}", response_model=ClassroomResponse, dependencies=[Depends(is_teacher_or_admin)])
def update_classroom(
    cid: int,
    payload: ClassroomUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cls, field, value)
    db.commit()
    db.refresh(cls)
    audit_logger.info("classroom_updated", extra={"extra_fields": {"classroom_id": cls.id, "owner_id": current_user.id}})
    return _enrich_classroom(cls, db)


@classrooms_router.delete("/{cid}", status_code=204, dependencies=[Depends(is_teacher_or_admin)])
def archive_classroom(
    cid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    cls.archived = True
    db.commit()
    audit_logger.info("classroom_archived", extra={"extra_fields": {"classroom_id": cid, "owner_id": current_user.id}})


# ── STUDENTS ───────────────────────────────────────────────────────────────────


@classrooms_router.get("/{cid}/students", response_model=List[StudentLabStatus])
def list_students(
    cid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_classroom_access(cls, current_user, db)

    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.classroom_id == cid, Enrollment.removed_at.is_(None))
        .all()
    )
    result = []
    for enr in enrollments:
        student = db.query(User).filter(User.id == enr.user_id).first()
        if not student:
            continue
        active_dep = (
            db.query(Deployment)
            .filter(Deployment.user_id == enr.user_id, Deployment.status == "active")
            .order_by(Deployment.created_at.desc())
            .first()
        )
        result.append(
            StudentLabStatus(
                user_id=student.id,
                username=student.username,
                email=student.email,
                lab_name=active_dep.name if active_dep else None,
                lab_status=active_dep.status if active_dep else None,
                lab_expires_at=active_dep.expires_at if active_dep else None,
                last_seen_at=active_dep.last_seen_at if active_dep else None,
                enrolled_at=enr.enrolled_at,
            )
        )
    return result


@classrooms_router.post("/{cid}/students", status_code=200, dependencies=[Depends(is_teacher_or_admin)])
def enroll_students(
    cid: int,
    payload: EnrollStudentsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)

    results = []
    for uid in payload.user_ids:
        student = (
            db.query(User)
            .filter(User.id == uid, User.is_active == True, User.role == UserRole.student)  # noqa: E712
            .first()
        )
        if not student:
            results.append({"user_id": uid, "status": "error", "detail": "Utilisateur introuvable, inactif ou non etudiant"})
            continue
        existing = db.query(Enrollment).filter(Enrollment.classroom_id == cid, Enrollment.user_id == uid).first()
        if existing:
            if existing.removed_at is not None:
                existing.removed_at = None
                db.commit()
                results.append({"user_id": uid, "username": student.username, "status": "re-enrolled"})
            else:
                results.append({"user_id": uid, "username": student.username, "status": "skipped", "detail": "Déjà inscrit"})
            continue
        enr = Enrollment(classroom_id=cid, user_id=uid)
        db.add(enr)
        db.commit()
        results.append({"user_id": uid, "username": student.username, "status": "enrolled"})

    enrolled = sum(1 for r in results if r["status"] in ("enrolled", "re-enrolled"))
    audit_logger.info("students_enrolled", extra={"extra_fields": {"classroom_id": cid, "enrolled": enrolled}})
    return {"enrolled": enrolled, "results": results}


@classrooms_router.post("/{cid}/students/create", status_code=201, dependencies=[Depends(is_teacher_or_admin)])
def create_and_enroll_student(
    cid: int,
    payload: StudentCreateAndEnrollRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)

    if settings.SSO_ENABLED:
        raise HTTPException(status_code=403, detail="Creation locale des comptes desactivee car le SSO est active")
    if not validate_password_strength(payload.password):
        raise HTTPException(
            status_code=400,
            detail="Le mot de passe doit contenir au moins 12 caracteres, une majuscule, une minuscule, un chiffre et un caractere special.",
        )
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Ce nom d'utilisateur est deja utilise")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Cet email est deja utilise")

    student = User(
        username=payload.username,
        email=str(payload.email),
        full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        role=UserRole.student,
        is_active=True,
        auth_provider="local",
    )
    db.add(student)
    db.flush()

    enrollment = Enrollment(classroom_id=cid, user_id=student.id)
    db.add(enrollment)
    db.commit()
    db.refresh(student)

    audit_logger.info(
        "student_created_and_enrolled",
        extra={"extra_fields": {"classroom_id": cid, "user_id": student.id, "username": student.username}},
    )
    return {
        "user_id": student.id,
        "username": student.username,
        "email": student.email,
        "status": "created",
    }


@classrooms_router.post("/{cid}/students/import", status_code=200, dependencies=[Depends(is_teacher_or_admin)])
async def import_students_csv(
    cid: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Le fichier doit être au format CSV (.csv)")

    content = await file.read()
    try:
        text_content = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Encodage du fichier invalide (UTF-8 attendu)")

    reader = csv.DictReader(io.StringIO(text_content))
    if not reader.fieldnames or "username" not in reader.fieldnames:
        raise HTTPException(status_code=400, detail="En-tête CSV invalide. Requis : username (et optionnel email)")

    results = []
    for line_num, row in enumerate(reader, start=2):
        username = (row.get("username") or "").strip()
        if not username:
            results.append({"line": line_num, "status": "error", "detail": "username manquant"})
            continue
        student = db.query(User).filter(User.username == username).first()
        if not student:
            results.append({"line": line_num, "username": username, "status": "error", "detail": "Utilisateur inconnu"})
            continue
        if not student.is_active:
            results.append({"line": line_num, "username": username, "status": "error", "detail": "Compte inactif"})
            continue
        if student.role != UserRole.student:
            results.append({
                "line": line_num,
                "username": username,
                "status": "error",
                "detail": "Seuls les comptes etudiants peuvent etre inscrits",
            })
            continue
        existing = db.query(Enrollment).filter(Enrollment.classroom_id == cid, Enrollment.user_id == student.id).first()
        if existing:
            if existing.removed_at is not None:
                existing.removed_at = None
                db.commit()
                results.append({"line": line_num, "username": username, "status": "re-enrolled"})
            else:
                results.append({"line": line_num, "username": username, "status": "skipped"})
            continue
        enr = Enrollment(classroom_id=cid, user_id=student.id)
        db.add(enr)
        db.commit()
        results.append({"line": line_num, "username": username, "status": "enrolled"})

    enrolled = sum(1 for r in results if r["status"] in ("enrolled", "re-enrolled"))
    audit_logger.info("students_imported_csv", extra={"extra_fields": {"classroom_id": cid, "enrolled": enrolled}})
    return {
        "summary": {"enrolled": enrolled, "skipped": sum(1 for r in results if r["status"] == "skipped"), "errors": sum(1 for r in results if r["status"] == "error"), "total": len(results)},
        "results": results,
    }


@classrooms_router.delete("/{cid}/students/{user_id}", status_code=204, dependencies=[Depends(is_teacher_or_admin)])
def unenroll_student(
    cid: int,
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    enr = db.query(Enrollment).filter(Enrollment.classroom_id == cid, Enrollment.user_id == user_id, Enrollment.removed_at.is_(None)).first()
    if not enr:
        raise HTTPException(status_code=404, detail="Inscription introuvable")
    enr.removed_at = datetime.utcnow()
    db.commit()


# ── ASSIGNMENTS ────────────────────────────────────────────────────────────────


@classrooms_router.get("/{cid}/assignments", response_model=List[AssignmentResponse])
def list_assignments(
    cid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_classroom_access(cls, current_user, db)
    assignments = (
        db.query(Assignment)
        .filter(Assignment.classroom_id == cid, Assignment.status == "active")
        .order_by(Assignment.created_at.desc())
        .all()
    )
    return assignments


@classrooms_router.post("/{cid}/assignments", response_model=AssignmentResponse, status_code=201, dependencies=[Depends(is_teacher_or_admin)])
def create_assignment(
    cid: int,
    payload: AssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    asgn = Assignment(classroom_id=cid, **payload.model_dump())
    db.add(asgn)
    db.commit()
    db.refresh(asgn)
    audit_logger.info("assignment_created", extra={"extra_fields": {"assignment_id": asgn.id, "classroom_id": cid, "title": asgn.title}})
    return asgn


@classrooms_router.put("/{cid}/assignments/{aid}", response_model=AssignmentResponse, dependencies=[Depends(is_teacher_or_admin)])
def update_assignment(
    cid: int,
    aid: int,
    payload: AssignmentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    asgn = db.query(Assignment).filter(Assignment.id == aid, Assignment.classroom_id == cid).first()
    if not asgn:
        raise HTTPException(status_code=404, detail="Devoir introuvable")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(asgn, field, value)
    db.commit()
    db.refresh(asgn)
    return asgn


@classrooms_router.delete("/{cid}/assignments/{aid}", status_code=204, dependencies=[Depends(is_teacher_or_admin)])
def archive_assignment(
    cid: int,
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    asgn = db.query(Assignment).filter(Assignment.id == aid, Assignment.classroom_id == cid).first()
    if not asgn:
        raise HTTPException(status_code=404, detail="Devoir introuvable")
    asgn.status = "archived"
    db.commit()


@classrooms_router.post("/{cid}/assignments/{aid}/deploy-all", response_model=BulkSpawnReport, dependencies=[Depends(is_teacher_or_admin)])
async def deploy_assignment_to_class(
    cid: int,
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)

    asgn = db.query(Assignment).filter(Assignment.id == aid, Assignment.classroom_id == cid).first()
    if not asgn:
        raise HTTPException(status_code=404, detail="Devoir introuvable")
    if asgn.status != "active":
        raise HTTPException(status_code=400, detail="Le devoir est archivé")

    template = None
    if asgn.template_key:
        template = db.query(Template).filter(Template.key == asgn.template_key, Template.active == True).first()  # noqa: E712

    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.classroom_id == cid, Enrollment.removed_at.is_(None))
        .all()
    )
    students = [db.query(User).filter(User.id == e.user_id, User.is_active == True).first() for e in enrollments]  # noqa: E712
    students = [s for s in students if s]

    sem = asyncio.Semaphore(5)
    slug = _slugify(asgn.title)

    async def spawn_one(student: User) -> BulkSpawnResult:
        async with sem:
            dep_name = f"{slug}-u{student.id}"
            existing = db.query(Deployment).filter(
                Deployment.user_id == student.id,
                Deployment.name == dep_name,
                Deployment.status.in_(["active", "paused"]),
            ).first()
            if existing:
                return BulkSpawnResult(user_id=student.id, username=student.username, status="skipped", deployment_name=dep_name)
            try:
                image = template.default_image if template else "nginx:latest"
                port = template.default_port if template else 80
                svc_type = template.default_service_type if template else "NodePort"
                dep_type = template.deployment_type if template else "custom"

                result = await deployment_service.create_deployment(
                    name=dep_name,
                    image=image,
                    replicas=1,
                    namespace=None,
                    create_service=True,
                    service_port=port,
                    service_target_port=port,
                    service_type=svc_type,
                    deployment_type=dep_type,
                    cpu_request=_preset_cpu(asgn.cpu_preset, "request"),
                    cpu_limit=_preset_cpu(asgn.cpu_preset, "limit"),
                    memory_request=_preset_ram(asgn.ram_preset, "request"),
                    memory_limit=_preset_ram(asgn.ram_preset, "limit"),
                    additional_labels={"labondemand.io/assignment-id": str(aid)},
                    current_user=student,
                )
                dep_id = None
                if isinstance(result, dict) and "deployment_db_id" in result:
                    dep_id = result["deployment_db_id"]
                ad = AssignmentDeployment(assignment_id=aid, user_id=student.id, deployment_id=dep_id, spawn_status="ok")
                db.add(ad)
                db.commit()
                return BulkSpawnResult(user_id=student.id, username=student.username, status="ok", deployment_name=dep_name)
            except Exception as exc:
                db.rollback()
                ad = AssignmentDeployment(assignment_id=aid, user_id=student.id, spawn_status="error", spawn_error=str(exc)[:500])
                db.add(ad)
                db.commit()
                return BulkSpawnResult(user_id=student.id, username=student.username, status="error", error=str(exc)[:200])

    results = await asyncio.gather(*[spawn_one(s) for s in students])
    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")

    audit_logger.info("assignment_deployed_bulk", extra={"extra_fields": {"assignment_id": aid, "classroom_id": cid, "total": len(results), "ok": ok, "errors": errors}})

    return BulkSpawnReport(
        assignment_id=aid,
        classroom_id=cid,
        total=len(results),
        ok=ok,
        skipped=skipped,
        errors=errors,
        results=list(results),
    )


# ── SUBMISSIONS / CORRECTION ─────────────────────────────────────────────────


def _parse_links(raw: Optional[str]) -> List[SubmissionLink]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    return [SubmissionLink(**l) for l in data if isinstance(l, dict) and l.get("url")]


def _get_assignment_or_404(cid: int, aid: int, db: Session) -> Assignment:
    asgn = db.query(Assignment).filter(Assignment.id == aid, Assignment.classroom_id == cid).first()
    if not asgn:
        raise HTTPException(status_code=404, detail="Devoir introuvable")
    return asgn


def _resolve_assignment_lab(aid: int, user_id: int, db: Session) -> Optional[Deployment]:
    """Lab d'un utilisateur pour un devoir, via AssignmentDeployment (source de vérité)."""
    link = (
        db.query(AssignmentDeployment)
        .filter(
            AssignmentDeployment.assignment_id == aid,
            AssignmentDeployment.user_id == user_id,
            AssignmentDeployment.deployment_id.isnot(None),
        )
        .order_by(AssignmentDeployment.created_at.desc())
        .first()
    )
    if not link or link.deployment_id is None:
        return None
    return (
        db.query(Deployment)
        .filter(Deployment.id == link.deployment_id, Deployment.status.in_(["active", "paused"]))
        .first()
    )


@classrooms_router.get("/{cid}/assignments/{aid}/submissions", response_model=List[TeacherSubmissionRow], dependencies=[Depends(is_teacher_or_admin)])
def list_submissions(
    cid: int,
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Une ligne par étudiant inscrit (ceux qui n'ont pas rendu = not_started)."""
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    _get_assignment_or_404(cid, aid, db)

    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.classroom_id == cid, Enrollment.removed_at.is_(None))
        .all()
    )
    submissions = {
        s.user_id: s
        for s in db.query(AssignmentSubmission).filter(AssignmentSubmission.assignment_id == aid).all()
    }

    rows: List[TeacherSubmissionRow] = []
    for enr in enrollments:
        student = db.query(User).filter(User.id == enr.user_id).first()
        if not student:
            continue
        sub = submissions.get(student.id)
        lab = (
            db.query(Deployment).filter(Deployment.id == sub.deployment_id).first()
            if sub and sub.deployment_id
            else None
        )
        run = grader_service.latest_run_for(aid, student.id, db)
        rows.append(
            TeacherSubmissionRow(
                user_id=student.id,
                username=student.username,
                email=student.email,
                submission_id=sub.id if sub else None,
                submission_status=sub.status if sub else "not_started",
                submitted_at=sub.submitted_at if sub else None,
                is_late=bool(sub.is_late) if sub else False,
                grade=sub.grade if sub else None,
                lab_deployment_name=lab.name if lab else None,
                lab_status=lab.status if lab else None,
                grading_status=run.status if run else None,
                grading_passed=run.passed_checks if run else None,
                grading_total=run.total_checks if run else None,
                score_suggestion=run.score_suggestion if run else None,
            )
        )
    return rows


@classrooms_router.get("/{cid}/assignments/{aid}/submissions/{sid}", response_model=AssignmentSubmissionResponse, dependencies=[Depends(is_teacher_or_admin)])
def get_submission_detail(
    cid: int,
    aid: int,
    sid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Détail complet d'une soumission pour la vue de correction."""
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    _get_assignment_or_404(cid, aid, db)

    sub = (
        db.query(AssignmentSubmission)
        .filter(AssignmentSubmission.id == sid, AssignmentSubmission.assignment_id == aid)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Soumission introuvable")

    snapshot = None
    if sub.lab_snapshot:
        try:
            snapshot = json.loads(sub.lab_snapshot)
        except (ValueError, TypeError):
            snapshot = None

    run = grader_service.latest_run_for(aid, sub.user_id, db)
    return AssignmentSubmissionResponse(
        id=sub.id,
        assignment_id=sub.assignment_id,
        user_id=sub.user_id,
        attempt_no=sub.attempt_no,
        status=sub.status,
        text=sub.text,
        links=_parse_links(sub.links),
        deployment_id=sub.deployment_id,
        lab_snapshot=snapshot,
        submitted_at=sub.submitted_at,
        is_late=sub.is_late,
        due_at_snapshot=sub.due_at_snapshot,
        grade=sub.grade,
        feedback=sub.feedback,
        graded_by=sub.graded_by,
        graded_at=sub.graded_at,
        grading_run=grader_service.run_to_response(run, for_student=False) if run else None,
    )


@classrooms_router.post("/{cid}/assignments/{aid}/submissions/{sid}/grade", response_model=AssignmentSubmissionResponse, dependencies=[Depends(is_teacher_or_admin)])
def grade_submission(
    cid: int,
    aid: int,
    sid: int,
    payload: SubmissionGradeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Corrige une soumission : note + feedback, passe le statut à 'graded'."""
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    _get_assignment_or_404(cid, aid, db)

    sub = (
        db.query(AssignmentSubmission)
        .filter(AssignmentSubmission.id == sid, AssignmentSubmission.assignment_id == aid)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Soumission introuvable")

    sub.grade = payload.grade
    sub.feedback = payload.feedback
    sub.status = "graded"
    sub.graded_by = current_user.id
    sub.graded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sub)

    audit_logger.info(
        "submission_graded",
        extra={"extra_fields": {"assignment_id": aid, "submission_id": sid, "grader_id": current_user.id, "grade": payload.grade}},
    )

    snapshot = None
    if sub.lab_snapshot:
        try:
            snapshot = json.loads(sub.lab_snapshot)
        except (ValueError, TypeError):
            snapshot = None
    return AssignmentSubmissionResponse(
        id=sub.id,
        assignment_id=sub.assignment_id,
        user_id=sub.user_id,
        attempt_no=sub.attempt_no,
        status=sub.status,
        text=sub.text,
        links=_parse_links(sub.links),
        deployment_id=sub.deployment_id,
        lab_snapshot=snapshot,
        submitted_at=sub.submitted_at,
        is_late=sub.is_late,
        due_at_snapshot=sub.due_at_snapshot,
        grade=sub.grade,
        feedback=sub.feedback,
        graded_by=sub.graded_by,
        graded_at=sub.graded_at,
    )


# ── GRADING SPEC (MVP-2) ───────────────────────────────────────────────────────


@classrooms_router.get(
    "/{cid}/assignments/{aid}/grading-spec",
    response_model=GradingSpecResponse,
    dependencies=[Depends(is_teacher_or_admin)],
)
def get_grading_spec(
    cid: int,
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retourne la GradingSpec d'un devoir (probes + script optionnel)."""
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    _get_assignment_or_404(cid, aid, db)

    spec = db.query(GradingSpec).filter(GradingSpec.assignment_id == aid).first()
    if not spec:
        raise HTTPException(status_code=404, detail="Aucune GradingSpec pour ce devoir")

    checks = []
    if spec.checks:
        try:
            raw = json.loads(spec.checks)
            checks = [Probe(**p) for p in raw] if isinstance(raw, list) else []
        except (ValueError, TypeError):
            checks = []

    return GradingSpecResponse(
        id=spec.id,
        assignment_id=spec.assignment_id,
        grader_image=spec.grader_image,
        timeout_seconds=spec.timeout_seconds,
        checks=checks,
        custom_script=spec.custom_script,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
    )


@classrooms_router.post(
    "/{cid}/assignments/{aid}/grading-spec",
    response_model=GradingSpecResponse,
    dependencies=[Depends(is_teacher_or_admin)],
)
def upsert_grading_spec(
    cid: int,
    aid: int,
    payload: GradingSpecCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Crée ou remplace la GradingSpec d'un devoir (upsert)."""
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    asgn = _get_assignment_or_404(cid, aid, db)

    checks_json = json.dumps([p.model_dump() for p in payload.checks])

    spec = db.query(GradingSpec).filter(GradingSpec.assignment_id == aid).first()
    if spec:
        spec.grader_image = payload.grader_image
        spec.timeout_seconds = payload.timeout_seconds
        spec.checks = checks_json
        spec.custom_script = payload.custom_script
        spec.updated_at = datetime.now(timezone.utc)
    else:
        spec = GradingSpec(
            assignment_id=aid,
            grader_image=payload.grader_image,
            timeout_seconds=payload.timeout_seconds,
            checks=checks_json,
            custom_script=payload.custom_script,
        )
        db.add(spec)

    # Activer le grading_mode si pas encore activé et qu'il y a des probes
    if asgn.grading_mode == "none" and (payload.checks or payload.custom_script):
        asgn.grading_mode = "self_check"

    db.commit()
    db.refresh(spec)

    audit_logger.info(
        "grading_spec_upserted",
        extra={"extra_fields": {"assignment_id": aid, "probe_count": len(payload.checks)}},
    )

    return GradingSpecResponse(
        id=spec.id,
        assignment_id=spec.assignment_id,
        grader_image=spec.grader_image,
        timeout_seconds=spec.timeout_seconds,
        checks=payload.checks,
        custom_script=spec.custom_script,
        created_at=spec.created_at,
        updated_at=spec.updated_at,
    )


# ── GRADING RUNS (MVP-2) : exécution des tests côté prof ─────────────────────


def _require_spec_with_tests(aid: int, db: Session) -> GradingSpec:
    spec = db.query(GradingSpec).filter(GradingSpec.assignment_id == aid).first()
    if not spec:
        raise HTTPException(status_code=400, detail="Aucun test n'est défini pour ce devoir")
    has_checks = False
    if spec.checks:
        try:
            has_checks = bool(json.loads(spec.checks))
        except (ValueError, TypeError):
            has_checks = False
    if not has_checks and not spec.custom_script:
        raise HTTPException(status_code=400, detail="Aucun test n'est défini pour ce devoir")
    return spec


@classrooms_router.post(
    "/{cid}/assignments/{aid}/test-now",
    response_model=GradingRunResponse,
    dependencies=[Depends(is_teacher_or_admin)],
)
async def test_now(
    cid: int,
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lance un Grading Run contre le lab de démo du prof, pour valider ses tests."""
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    _get_assignment_or_404(cid, aid, db)
    _require_spec_with_tests(aid, db)

    lab = _resolve_assignment_lab(aid, current_user.id, db)
    if not lab:
        raise HTTPException(
            status_code=400,
            detail="Aucun lab de démo : déployez-vous un lab pour ce devoir avant de tester",
        )

    run = GradingRun(
        assignment_id=aid,
        user_id=current_user.id,
        deployment_id=lab.id,
        trigger="teacher",
        status="queued",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    asyncio.create_task(grader_service.run_grading(run.id))
    audit_logger.info(
        "grading_run_started",
        extra={"extra_fields": {"assignment_id": aid, "user_id": current_user.id, "run_id": run.id, "trigger": "teacher"}},
    )
    return grader_service.run_to_response(run, for_student=False)


@classrooms_router.get(
    "/{cid}/assignments/{aid}/grading-runs/{run_id}",
    response_model=GradingRunResponse,
    dependencies=[Depends(is_teacher_or_admin)],
)
def get_grading_run_teacher(
    cid: int,
    aid: int,
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """État + résultats détaillés (non filtrés) d'un Grading Run, pour le prof."""
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    _get_assignment_or_404(cid, aid, db)
    run = (
        db.query(GradingRun)
        .filter(GradingRun.id == run_id, GradingRun.assignment_id == aid)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run introuvable")
    return grader_service.run_to_response(run, for_student=False)


@classrooms_router.post(
    "/{cid}/assignments/{aid}/run-tests-all",
    dependencies=[Depends(is_teacher_or_admin)],
)
async def run_tests_all(
    cid: int,
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """(Re)lance les tests sur toute la classe : un Grading Run par étudiant ayant un lab."""
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    _get_assignment_or_404(cid, aid, db)
    _require_spec_with_tests(aid, db)

    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.classroom_id == cid, Enrollment.removed_at.is_(None))
        .all()
    )
    run_ids: List[int] = []
    for enr in enrollments:
        lab = _resolve_assignment_lab(aid, enr.user_id, db)
        if not lab:
            continue
        run = GradingRun(
            assignment_id=aid,
            user_id=enr.user_id,
            deployment_id=lab.id,
            trigger="teacher",
            status="queued",
        )
        db.add(run)
        db.flush()
        run_ids.append(run.id)
    db.commit()

    for rid in run_ids:
        asyncio.create_task(grader_service.run_grading(rid))

    audit_logger.info(
        "grading_runs_started_bulk",
        extra={"extra_fields": {"assignment_id": aid, "classroom_id": cid, "queued": len(run_ids)}},
    )
    return {"queued": len(run_ids)}


# ── TEACHER DASHBOARD ──────────────────────────────────────────────────────────


@teacher_router.get("/users/search", dependencies=[Depends(is_teacher_or_admin)])
def search_users(
    q: str = "",
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Recherche des étudiants actifs par username ou email (pour l'inscription manuelle)."""
    query = db.query(User).filter(User.is_active == True, User.role == UserRole.student)  # noqa: E712
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(
            (User.username.ilike(term)) | (User.email.ilike(term))
        )
    users = query.order_by(User.username).limit(min(limit, 50)).all()
    return [{"user_id": u.id, "username": u.username, "email": u.email} for u in users]


@teacher_router.get("/dashboard", dependencies=[Depends(is_teacher_or_admin)])
def teacher_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Classroom).filter(Classroom.archived == False)  # noqa: E712
    if current_user.role != UserRole.admin:
        q = q.filter(Classroom.owner_id == current_user.id)
    classrooms = q.order_by(Classroom.created_at.desc()).all()

    classes_data = []
    for cls in classrooms:
        student_count = db.query(Enrollment).filter(Enrollment.classroom_id == cls.id, Enrollment.removed_at.is_(None)).count()
        active_assignments = db.query(Assignment).filter(Assignment.classroom_id == cls.id, Assignment.status == "active").count()
        classes_data.append({
            "id": cls.id,
            "name": cls.name,
            "description": cls.description,
            "student_count": student_count,
            "active_assignment_count": active_assignments,
            "created_at": cls.created_at,
        })

    return {
        "classroom_count": len(classes_data),
        "classrooms": classes_data,
    }


# ── Helper ─────────────────────────────────────────────────────────────────────


def _enrich_classroom(cls: Classroom, db: Session) -> ClassroomResponse:
    student_count = db.query(Enrollment).filter(Enrollment.classroom_id == cls.id, Enrollment.removed_at.is_(None)).count()
    active_assignments = db.query(Assignment).filter(Assignment.classroom_id == cls.id, Assignment.status == "active").count()
    return ClassroomResponse(
        id=cls.id,
        name=cls.name,
        description=cls.description,
        owner_id=cls.owner_id,
        archived=cls.archived,
        created_at=cls.created_at,
        updated_at=cls.updated_at,
        student_count=student_count,
        active_assignment_count=active_assignments,
    )
