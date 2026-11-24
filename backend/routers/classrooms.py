"""
Router — Classrooms, Enrollments, Assignments (système de classe P0)

Endpoints :
  Classrooms   : CRUD + list
  Students     : enroll/unenroll + CSV import
  Assignments  : CRUD + bulk-spawn
  Dashboard    : vue agrégée enseignant
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import database, grader_service
from ..database import get_db
from ..deployment_service import deployment_service
from ..error_handlers import K8S_UNAVAILABLE_DETAIL
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
from ._helpers import K8S_TRANSPORT_ERRORS, resolve_assignment_labs

audit_logger = logging.getLogger("labondemand.audit")
logger = logging.getLogger("labondemand.classrooms")

# Student labs created in parallel by "deploy to all students".
BULK_SPAWN_CONCURRENCY = 4

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
    students, assignments = _classroom_counts([c.id for c in classrooms], db)
    return [
        _classroom_response(c, students.get(c.id, 0), assignments.get(c.id, 0))
        for c in classrooms
    ]


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

    rows = _enrolled_students(cid, db)
    # Most recent active lab per student, in one query.
    active_labs: Dict[int, Deployment] = {}
    if rows:
        for dep in (
            db.query(Deployment)
            .filter(
                Deployment.user_id.in_([student.id for _, student in rows]),
                Deployment.status == "active",
            )
            .order_by(Deployment.created_at.desc(), Deployment.id.desc())
        ):
            active_labs.setdefault(dep.user_id, dep)

    result = []
    for enr, student in rows:
        active_dep = active_labs.get(student.id)
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
def import_students_csv(
    cid: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Le fichier doit être au format CSV (.csv)")

    # The upload is already spooled when a sync handler runs: read it directly.
    content = file.file.read()
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
    enr.removed_at = datetime.now(timezone.utc)
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


@dataclass(frozen=True)
class _SpawnSpec:
    """Everything a worker needs to create one student lab (plain data, no ORM)."""

    assignment_id: int
    image: str
    port: int
    service_type: str
    deployment_type: str
    cpu_request: str
    cpu_limit: str
    memory_request: str
    memory_limit: str
    labels: Dict[str, str] = field(default_factory=dict)


def _spawn_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    if isinstance(exc, K8S_TRANSPORT_ERRORS):
        return K8S_UNAVAILABLE_DETAIL
    return str(exc) or type(exc).__name__


def _created_deployment_id(result: Any, user_id: int, dep_name: str, db: Session) -> Optional[int]:
    """DB id of the lab just created (the service records it in its own session)."""
    if isinstance(result, dict) and result.get("deployment_db_id"):
        return int(result["deployment_db_id"])
    row = (
        db.query(Deployment.id)
        .filter(
            Deployment.user_id == user_id,
            Deployment.name == dep_name,
            Deployment.deleted_at.is_(None),
        )
        .order_by(Deployment.id.desc())
        .first()
    )
    return row[0] if row else None


def _spawn_student_lab(spec: _SpawnSpec, user_id: int, username: str, dep_name: str) -> BulkSpawnResult:
    """Create one student's lab and record the outcome (runs in a worker thread).

    Each step opens its own short-lived session: no session is shared between
    threads, and no connection is held while Kubernetes works. Failures are
    recorded per student and never propagate to the other workers.
    """
    dep_id: Optional[int] = None
    error: Optional[str] = None
    try:
        with database.SessionLocal() as db:
            student = db.query(User).filter(User.id == user_id).first()
            if student is None:
                raise HTTPException(status_code=404, detail="Utilisateur introuvable")
            db.expunge(student)  # detached copy with its columns loaded

        result = deployment_service.create_deployment(
            name=dep_name,
            image=spec.image,
            replicas=1,
            namespace=None,
            create_service=True,
            service_port=spec.port,
            service_target_port=spec.port,
            service_type=spec.service_type,
            deployment_type=spec.deployment_type,
            cpu_request=spec.cpu_request,
            cpu_limit=spec.cpu_limit,
            memory_request=spec.memory_request,
            memory_limit=spec.memory_limit,
            additional_labels=dict(spec.labels),
            current_user=student,
        )
        with database.SessionLocal() as db:
            dep_id = _created_deployment_id(result, user_id, dep_name, db)
    except Exception as exc:  # one student's failure must not abort the class
        error = _spawn_error_message(exc)
        logger.warning(
            "bulk_spawn_student_failed",
            exc_info=not isinstance(exc, HTTPException),
            extra={
                "extra_fields": {
                    "assignment_id": spec.assignment_id,
                    "user_id": user_id,
                    "deployment_name": dep_name,
                    "error": error,
                }
            },
        )

    try:
        with database.SessionLocal() as db:
            db.add(
                AssignmentDeployment(
                    assignment_id=spec.assignment_id,
                    user_id=user_id,
                    deployment_id=dep_id if error is None else None,
                    spawn_status="ok" if error is None else "error",
                    spawn_error=error[:500] if error else None,
                )
            )
            db.commit()
    except Exception:
        # The lab itself may exist; report the bookkeeping failure for this student only.
        logger.exception(
            "bulk_spawn_record_failed",
            extra={"extra_fields": {"assignment_id": spec.assignment_id, "user_id": user_id}},
        )
        if error is None:
            error = "Lab créé mais non rattaché au devoir (erreur base de données)"

    if error is not None:
        return BulkSpawnResult(
            user_id=user_id, username=username, status="error", error=error[:200], deployment_name=dep_name
        )
    return BulkSpawnResult(user_id=user_id, username=username, status="ok", deployment_name=dep_name)


@classrooms_router.post("/{cid}/assignments/{aid}/deploy-all", response_model=BulkSpawnReport, dependencies=[Depends(is_teacher_or_admin)])
def deploy_assignment_to_class(
    cid: int,
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create the assignment lab for every active enrolled student.

    Labs are created by a bounded pool of ``BULK_SPAWN_CONCURRENCY`` worker
    threads, each with its own DB sessions; students that already have the lab
    are skipped and a failing student is reported without stopping the others.
    """
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

    spec = _SpawnSpec(
        assignment_id=aid,
        image=template.default_image if template else "nginx:latest",
        port=template.default_port if template else 80,
        service_type=template.default_service_type if template else "NodePort",
        deployment_type=template.deployment_type if template else "custom",
        cpu_request=_preset_cpu(asgn.cpu_preset, "request"),
        cpu_limit=_preset_cpu(asgn.cpu_preset, "limit"),
        memory_request=_preset_ram(asgn.ram_preset, "request"),
        memory_limit=_preset_ram(asgn.ram_preset, "limit"),
        labels={"labondemand.io/assignment-id": str(aid)},
    )

    slug = _slugify(asgn.title)
    students = [
        (student.id, student.username, f"{slug}-u{student.id}")
        for _, student in _enrolled_students(cid, db, active_only=True)
    ]
    existing = {
        (user_id, name)
        for user_id, name in db.query(Deployment.user_id, Deployment.name).filter(
            Deployment.user_id.in_([sid for sid, _, _ in students] or [-1]),
            Deployment.name.in_([name for _, _, name in students] or [""]),
            Deployment.status.in_(["active", "paused"]),
        )
    }
    # End the read transaction so the request's pooled connection is released
    # while the workers wait on Kubernetes.
    db.rollback()

    results: List[Optional[BulkSpawnResult]] = [None] * len(students)
    pending = []
    for index, (user_id, username, dep_name) in enumerate(students):
        if (user_id, dep_name) in existing:
            results[index] = BulkSpawnResult(
                user_id=user_id, username=username, status="skipped", deployment_name=dep_name
            )
        else:
            pending.append((index, user_id, username, dep_name))

    if pending:
        workers = min(BULK_SPAWN_CONCURRENCY, len(pending))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bulk-spawn") as pool:
            futures = {
                index: pool.submit(_spawn_student_lab, spec, user_id, username, dep_name)
                for index, user_id, username, dep_name in pending
            }
            for index, future in futures.items():
                results[index] = future.result()

    final = [r for r in results if r is not None]
    ok = sum(1 for r in final if r.status == "ok")
    skipped = sum(1 for r in final if r.status == "skipped")
    errors = sum(1 for r in final if r.status == "error")

    audit_logger.info("assignment_deployed_bulk", extra={"extra_fields": {"assignment_id": aid, "classroom_id": cid, "total": len(final), "ok": ok, "errors": errors}})

    return BulkSpawnReport(
        assignment_id=aid,
        classroom_id=cid,
        total=len(final),
        ok=ok,
        skipped=skipped,
        errors=errors,
        results=final,
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
    return resolve_assignment_labs(db, [aid], [user_id]).get((aid, user_id))


def _latest_runs(aid: int, user_ids: Iterable[int], db: Session) -> Dict[int, GradingRun]:
    """Most recent Grading Run per student for an assignment, in one query."""
    ids = set(user_ids)
    if not ids:
        return {}
    latest: Dict[int, GradingRun] = {}
    for run in (
        db.query(GradingRun)
        .filter(GradingRun.assignment_id == aid, GradingRun.user_id.in_(ids))
        .order_by(GradingRun.id.desc())
    ):
        latest.setdefault(run.user_id, run)
    return latest


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

    students = [student for _, student in _enrolled_students(cid, db)]
    submissions = {
        s.user_id: s
        for s in db.query(AssignmentSubmission).filter(AssignmentSubmission.assignment_id == aid).all()
    }
    lab_ids = {s.deployment_id for s in submissions.values() if s.deployment_id}
    labs = (
        {d.id: d for d in db.query(Deployment).filter(Deployment.id.in_(lab_ids))}
        if lab_ids
        else {}
    )
    runs = _latest_runs(aid, [student.id for student in students], db)

    rows: List[TeacherSubmissionRow] = []
    for student in students:
        sub = submissions.get(student.id)
        lab = labs.get(sub.deployment_id) if sub and sub.deployment_id else None
        run = runs.get(student.id)
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
def test_now(
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

    user_id = current_user.id
    run = grader_service.enqueue_run(
        db, assignment_id=aid, user_id=user_id, deployment_id=lab.id, trigger="teacher"
    )
    if run is None:
        raise HTTPException(status_code=409, detail=grader_service.RUN_ALREADY_ACTIVE_DETAIL)

    grader_service.schedule_grading(run.id)
    audit_logger.info(
        "grading_run_started",
        extra={"extra_fields": {"assignment_id": aid, "user_id": user_id, "run_id": run.id, "trigger": "teacher"}},
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
def run_tests_all(
    cid: int,
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """(Re)lance les tests sur toute la classe : un Grading Run par étudiant ayant un lab.

    Students whose previous run for this assignment is still queued/running
    are skipped (counted in ``skipped``), never queued twice.
    """
    cls = _get_classroom_or_404(cid, db)
    _require_owner_or_admin(cls, current_user)
    _get_assignment_or_404(cid, aid, db)
    _require_spec_with_tests(aid, db)

    enrolled_ids = [
        user_id
        for (user_id,) in db.query(Enrollment.user_id)
        .filter(Enrollment.classroom_id == cid, Enrollment.removed_at.is_(None))
        .order_by(Enrollment.id)
    ]
    labs = resolve_assignment_labs(db, [aid], enrolled_ids)
    lab_ids = {user_id: labs[(aid, user_id)].id for user_id in enrolled_ids if (aid, user_id) in labs}
    run_ids: List[int] = []
    skipped = 0
    for user_id, lab_id in lab_ids.items():
        run = grader_service.enqueue_run(
            db, assignment_id=aid, user_id=user_id, deployment_id=lab_id, trigger="teacher"
        )
        if run is None:
            skipped += 1
            continue
        run_ids.append(run.id)

    for rid in run_ids:
        grader_service.schedule_grading(rid)

    audit_logger.info(
        "grading_runs_started_bulk",
        extra={"extra_fields": {"assignment_id": aid, "classroom_id": cid, "queued": len(run_ids), "skipped": skipped}},
    )
    return {"queued": len(run_ids), "skipped": skipped}


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

    students, assignments = _classroom_counts([c.id for c in classrooms], db)
    classes_data = [
        {
            "id": cls.id,
            "name": cls.name,
            "description": cls.description,
            "student_count": students.get(cls.id, 0),
            "active_assignment_count": assignments.get(cls.id, 0),
            "created_at": cls.created_at,
        }
        for cls in classrooms
    ]

    return {
        "classroom_count": len(classes_data),
        "classrooms": classes_data,
    }


# ── Helper ─────────────────────────────────────────────────────────────────────


def _enrolled_students(cid: int, db: Session, *, active_only: bool = False) -> List[tuple[Enrollment, User]]:
    """Current enrollments of a classroom with their users, in one joined query."""
    query = (
        db.query(Enrollment, User)
        .join(User, User.id == Enrollment.user_id)
        .filter(Enrollment.classroom_id == cid, Enrollment.removed_at.is_(None))
    )
    if active_only:
        query = query.filter(User.is_active == True)  # noqa: E712
    return [(enr, user) for enr, user in query.order_by(Enrollment.id).all()]


def _classroom_counts(classroom_ids: List[int], db: Session) -> tuple[Dict[int, int], Dict[int, int]]:
    """``(students, active assignments)`` per classroom, two grouped queries."""
    if not classroom_ids:
        return {}, {}
    students = dict(
        db.query(Enrollment.classroom_id, func.count(Enrollment.id))
        .filter(Enrollment.classroom_id.in_(classroom_ids), Enrollment.removed_at.is_(None))
        .group_by(Enrollment.classroom_id)
        .all()
    )
    assignments = dict(
        db.query(Assignment.classroom_id, func.count(Assignment.id))
        .filter(Assignment.classroom_id.in_(classroom_ids), Assignment.status == "active")
        .group_by(Assignment.classroom_id)
        .all()
    )
    return students, assignments


def _enrich_classroom(cls: Classroom, db: Session) -> ClassroomResponse:
    students, assignments = _classroom_counts([cls.id], db)
    return _classroom_response(cls, students.get(cls.id, 0), assignments.get(cls.id, 0))


def _classroom_response(cls: Classroom, student_count: int, active_assignments: int) -> ClassroomResponse:
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
