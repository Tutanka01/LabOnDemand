"""
Router — Expérience étudiant : « Mes devoirs » (MVP-1).

Endpoints centrés sur le geste produit, pas sur l'infrastructure :
  - lister mes devoirs (toutes mes classes)
  - voir le détail d'un devoir + ma soumission
  - rendre (texte + liens)
  - consulter ma soumission

Le lab est poussé par le prof via ``deploy-all`` (modèle push) : l'étudiant ne fait
qu'ouvrir le lab existant. Le lien devoir<->lab fait foi via ``AssignmentDeployment``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Assignment,
    AssignmentDeployment,
    AssignmentSubmission,
    Classroom,
    Deployment,
    Enrollment,
    User,
)
from ..schemas import (
    AssignmentSubmissionCreate,
    AssignmentSubmissionResponse,
    StudentAssignmentDetail,
    StudentAssignmentItem,
)
from ..security import get_current_user

audit_logger = logging.getLogger("labondemand.audit")

student_router = APIRouter(prefix="/api/v1/student", tags=["student"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _require_enrolled(assignment: Assignment, user: User, db: Session) -> None:
    """L'étudiant doit être inscrit (active) dans la classe du devoir."""
    enrolled = (
        db.query(Enrollment)
        .filter(
            Enrollment.classroom_id == assignment.classroom_id,
            Enrollment.user_id == user.id,
            Enrollment.removed_at.is_(None),
        )
        .first()
    )
    if not enrolled:
        raise HTTPException(status_code=404, detail="Devoir introuvable")


def _resolve_lab(assignment_id: int, user_id: int, db: Session) -> Optional[Deployment]:
    """Retrouve le lab d'un étudiant pour un devoir via AssignmentDeployment (source de vérité)."""
    link = (
        db.query(AssignmentDeployment)
        .filter(
            AssignmentDeployment.assignment_id == assignment_id,
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
        .filter(
            Deployment.id == link.deployment_id,
            Deployment.status.in_(["active", "paused"]),
        )
        .first()
    )


def _parse_links(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def _submission_to_response(sub: AssignmentSubmission) -> AssignmentSubmissionResponse:
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


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_past_due(due_at: Optional[datetime]) -> bool:
    if not due_at:
        return False
    # due_at peut être naïf (stocké sans tz) : on le rend comparable en UTC.
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    return _now_utc() > due_at


def _build_item(assignment: Assignment, classroom_name: Optional[str], db: Session, user_id: int) -> StudentAssignmentItem:
    lab = _resolve_lab(assignment.id, user_id, db)
    sub = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == assignment.id,
            AssignmentSubmission.user_id == user_id,
        )
        .first()
    )
    return StudentAssignmentItem(
        id=assignment.id,
        classroom_id=assignment.classroom_id,
        classroom_name=classroom_name,
        title=assignment.title,
        instructions=assignment.instructions,
        template_key=assignment.template_key,
        due_at=assignment.due_at,
        lab_ready=bool(lab and lab.status == "active"),
        lab_deployment_name=lab.name if lab else None,
        lab_namespace=lab.namespace if lab else None,
        lab_status=lab.status if lab else None,
        submission_status=(sub.status if sub else "not_started"),
        submitted_at=sub.submitted_at if sub else None,
        is_late=bool(sub.is_late) if sub else False,
        grade=sub.grade if sub else None,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@student_router.get("/assignments", response_model=List[StudentAssignmentItem])
def list_my_assignments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Liste les devoirs actifs des classes où l'étudiant est inscrit."""
    enrollments = (
        db.query(Enrollment)
        .filter(Enrollment.user_id == current_user.id, Enrollment.removed_at.is_(None))
        .all()
    )
    classroom_ids = [e.classroom_id for e in enrollments]
    if not classroom_ids:
        return []

    classroom_names = {
        c.id: c.name
        for c in db.query(Classroom).filter(Classroom.id.in_(classroom_ids)).all()
    }
    assignments = (
        db.query(Assignment)
        .filter(Assignment.classroom_id.in_(classroom_ids), Assignment.status == "active")
        .order_by(Assignment.due_at.is_(None), Assignment.due_at.asc(), Assignment.created_at.desc())
        .all()
    )
    return [
        _build_item(a, classroom_names.get(a.classroom_id), db, current_user.id)
        for a in assignments
    ]


def _get_my_assignment_or_404(aid: int, current_user: User, db: Session) -> Assignment:
    assignment = (
        db.query(Assignment)
        .filter(Assignment.id == aid, Assignment.status == "active")
        .first()
    )
    if not assignment:
        raise HTTPException(status_code=404, detail="Devoir introuvable")
    _require_enrolled(assignment, current_user, db)
    return assignment


@student_router.get("/assignments/{aid}", response_model=StudentAssignmentDetail)
def get_my_assignment(
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Détail d'un devoir + l'état de mon lab + ma soumission."""
    assignment = _get_my_assignment_or_404(aid, current_user, db)
    classroom = db.query(Classroom).filter(Classroom.id == assignment.classroom_id).first()
    item = _build_item(assignment, classroom.name if classroom else None, db, current_user.id)
    sub = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == aid,
            AssignmentSubmission.user_id == current_user.id,
        )
        .first()
    )
    return StudentAssignmentDetail(
        **item.model_dump(),
        deliverables=assignment.deliverables,
        submission=_submission_to_response(sub) if sub else None,
    )


@student_router.get("/assignments/{aid}/submission", response_model=AssignmentSubmissionResponse)
def get_my_submission(
    aid: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ma soumission pour ce devoir (404 si je n'ai pas encore rendu)."""
    _get_my_assignment_or_404(aid, current_user, db)
    sub = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == aid,
            AssignmentSubmission.user_id == current_user.id,
        )
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Aucune soumission")
    return _submission_to_response(sub)


@student_router.post("/assignments/{aid}/submit", response_model=AssignmentSubmissionResponse)
def submit_assignment(
    aid: int,
    payload: AssignmentSubmissionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rend un devoir (texte + liens). Upsert : la re-soumission met à jour la même ligne."""
    assignment = _get_my_assignment_or_404(aid, current_user, db)

    if not (payload.text and payload.text.strip()) and not payload.links:
        raise HTTPException(status_code=400, detail="Le rendu ne peut pas être vide")

    links_json = json.dumps([l.model_dump() for l in payload.links]) if payload.links else None
    is_late = _is_past_due(assignment.due_at)

    # Snapshot léger du lab au moment du rendu (le lab peut disparaître ensuite).
    lab = _resolve_lab(aid, current_user.id, db)
    snapshot_json = None
    deployment_id = None
    if lab:
        deployment_id = lab.id
        snapshot_json = json.dumps(
            {
                "name": lab.name,
                "namespace": lab.namespace,
                "deployment_type": lab.deployment_type,
                "status": lab.status,
                "created_at": lab.created_at.isoformat() if lab.created_at else None,
            }
        )

    sub = (
        db.query(AssignmentSubmission)
        .filter(
            AssignmentSubmission.assignment_id == aid,
            AssignmentSubmission.user_id == current_user.id,
        )
        .first()
    )
    if sub:
        sub.attempt_no = (sub.attempt_no or 1) + 1
        sub.status = "submitted"
        sub.text = payload.text
        sub.links = links_json
        sub.deployment_id = deployment_id
        sub.lab_snapshot = snapshot_json
        sub.submitted_at = _now_utc()
        sub.is_late = is_late
        sub.due_at_snapshot = assignment.due_at
        # Une re-soumission efface la correction précédente.
        sub.grade = None
        sub.feedback = None
        sub.graded_by = None
        sub.graded_at = None
    else:
        sub = AssignmentSubmission(
            assignment_id=aid,
            user_id=current_user.id,
            attempt_no=1,
            status="submitted",
            text=payload.text,
            links=links_json,
            deployment_id=deployment_id,
            lab_snapshot=snapshot_json,
            is_late=is_late,
            due_at_snapshot=assignment.due_at,
        )
        db.add(sub)

    db.commit()
    db.refresh(sub)
    audit_logger.info(
        "submission_created",
        extra={"extra_fields": {"assignment_id": aid, "user_id": current_user.id, "attempt_no": sub.attempt_no, "is_late": is_late}},
    )
    return _submission_to_response(sub)
