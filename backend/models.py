"""
Modèles SQLAlchemy pour LabOnDemand
Principe KISS : Uniquement les modèles utilisés
"""

from sqlalchemy import Boolean, Column, Integer, String, DateTime, Enum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.sql import func
import enum

# Changement d'importation relative à absolue pour fonctionner à la fois comme module et script
try:
    # Pour l'utilisation comme module dans l'application
    from .database import Base
except ImportError:
    # Pour l'utilisation comme script direct
    from database import Base


# Définition de l'énumération pour les rôles
class UserRole(enum.Enum):
    student = "student"
    teacher = "teacher"
    admin = "admin"


# Modèle pour les utilisateurs
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(100), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    auth_provider = Column(String(20), nullable=False, default="local")
    external_id = Column(String(255), nullable=True, unique=True, index=True)
    role = Column(Enum(UserRole), default=UserRole.student, nullable=False)
    # Si True, le rôle a été défini manuellement par un admin et ne sera pas
    # écrasé lors des connexions SSO suivantes (voir auth_router.sso_callback).
    role_override = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Modèle pour les templates d'application (déploiements)
class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(
        String(50), unique=True, index=True, nullable=False
    )  # identifiant fonctionnel (ex: vscode, jupyter)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    icon = Column(String(100), nullable=True)  # ex: fa-solid fa-code
    deployment_type = Column(
        String(30), nullable=False, default="custom"
    )  # vscode|jupyter|custom
    default_image = Column(String(200), nullable=True)
    default_port = Column(Integer, nullable=True)
    default_service_type = Column(
        String(30), nullable=False, default="NodePort"
    )  # ClusterIP|NodePort|LoadBalancer
    # Types multiples (tags) stockés en CSV pour simplicité (ex: "web,python,education")
    tags = Column(String(255), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Modèle pour le suivi des déploiements (IMP-1)
class Deployment(Base):
    """Trace chaque déploiement LabOnDemand avec son cycle de vie complet.

    Permet l'audit, le TTL, l'historique et la détection de zombies.
    """

    __tablename__ = "deployments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String(100), nullable=False, index=True)
    deployment_type = Column(String(50), nullable=False, default="custom")
    namespace = Column(String(100), nullable=False)
    stack_name = Column(String(100), nullable=True)
    # active | paused | expired | deleted
    status = Column(String(30), nullable=False, default="active", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    cpu_requested = Column(String(20), nullable=True)
    mem_requested = Column(String(20), nullable=True)


# Modèle pour les dérogations de quota par utilisateur (IMP-3)
class UserQuotaOverride(Base):
    """Permet à un admin d'accorder une dérogation de quota temporaire ou permanente.

    Prioritaire sur les limites par défaut du rôle dans ``get_role_limits()``.
    """

    __tablename__ = "user_quota_overrides"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    max_apps = Column(Integer, nullable=True)  # None = utiliser la valeur du rôle
    max_cpu_m = Column(Integer, nullable=True)  # en millicores
    max_mem_mi = Column(Integer, nullable=True)  # en MiB
    max_storage_gi = Column(Integer, nullable=True)  # en GiB
    expires_at = Column(DateTime(timezone=True), nullable=True)  # None = permanent
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(
        Integer, nullable=True
    )  # user_id de l'admin qui a créé l'override


# ====== Classroom system ======

class Classroom(Base):
    __tablename__ = "classrooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    description = Column(String(500), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    archived = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("classroom_id", "user_id", name="uq_enrollment_classroom_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now())
    removed_at = Column(DateTime(timezone=True), nullable=True)


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    classroom_id = Column(Integer, ForeignKey("classrooms.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    instructions = Column(Text, nullable=True)  # énoncé du devoir (Markdown)
    deliverables = Column(Text, nullable=True)  # ce qu'il faut rendre (Markdown)
    template_key = Column(String(50), nullable=True)
    cpu_preset = Column(String(20), nullable=True)
    ram_preset = Column(String(20), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(20), default="active", nullable=False)
    # none | self_check | graded — contrôle si un Grader Pod est lancé
    grading_mode = Column(String(20), default="none", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AssignmentDeployment(Base):
    """Trace quel déploiement a été créé pour quel étudiant dans un assignment."""

    __tablename__ = "assignment_deployments"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    deployment_id = Column(Integer, ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True, index=True)
    spawn_status = Column(String(20), nullable=False)  # ok | skipped | error
    spawn_error = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AssignmentSubmission(Base):
    """Preuve de travail rendue par un étudiant pour un devoir (MVP-1 : texte + liens).

    Une seule ligne par (assignment, étudiant) : la re-soumission met à jour la même
    ligne et incrémente ``attempt_no`` (on corrige toujours la dernière version).
    """

    __tablename__ = "assignment_submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", "user_id", name="uq_submission_assignment_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_no = Column(Integer, nullable=False, default=1)
    # submitted | graded
    status = Column(String(20), nullable=False, default="submitted")
    text = Column(Text, nullable=True)
    # JSON encodé : liste de {"label": str|None, "url": str}
    links = Column(Text, nullable=True)
    # Lab lié au moment du rendu (peut disparaître ensuite : voir lab_snapshot)
    deployment_id = Column(Integer, ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True, index=True)
    # JSON encodé : {name, namespace, deployment_type, status, created_at}
    lab_snapshot = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    is_late = Column(Boolean, default=False, nullable=False)
    due_at_snapshot = Column(DateTime(timezone=True), nullable=True)
    grade = Column(String(20), nullable=True)  # libre : "15/20", "A"...
    feedback = Column(Text, nullable=True)
    graded_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    graded_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ====== Grading (MVP-2) ======

class GradingSpec(Base):
    """Batterie de tests (probes) définie par l'enseignant pour un devoir.

    Une seule ligne par devoir. Les probes sont stockées en JSON dans ``checks``.
    """

    __tablename__ = "grading_specs"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(
        Integer, ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    # Image grader à utiliser (None → image plateforme par défaut)
    grader_image = Column(String(300), nullable=True)
    # Délai max d'exécution du Job grader en secondes
    timeout_seconds = Column(Integer, nullable=False, default=120)
    # JSON : liste de Probe {id, name, kind, vantage, config, expect, weight, visibility}
    checks = Column(Text, nullable=True)
    # Script bash/python fourni par l'enseignant (contrat JSON de sortie, §8)
    custom_script = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class GradingRun(Base):
    """Exécution du Grader Pod contre le lab d'un étudiant.

    Cycle de vie : queued → running → done | error.
    Le résultat brut (verdict par probe) est stocké en JSON dans ``results``.
    """

    __tablename__ = "grading_runs"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Soumission liée (nullable : un run peut précéder le rendu formel)
    submission_id = Column(Integer, ForeignKey("assignment_submissions.id", ondelete="SET NULL"), nullable=True, index=True)
    # Lab ciblé par le grader
    deployment_id = Column(Integer, ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True, index=True)
    # Qui a déclenché ce run
    trigger = Column(String(20), nullable=False)  # student_self | on_submit | teacher
    # queued | running | done | error
    status = Column(String(20), nullable=False, default="queued", index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    total_checks = Column(Integer, nullable=True)
    passed_checks = Column(Integer, nullable=True)
    # Somme pondérée des probes passées (indicatif, non contraignant)
    score_suggestion = Column(String(20), nullable=True)
    # JSON : [{id, name, status, message, output, weight, visibility}]
    results = Column(Text, nullable=True)
    error = Column(String(500), nullable=True)
    # Sécurité du callback Grader → API : hash SHA-256 du token usage unique
    result_token_hash = Column(String(64), nullable=True)
    token_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# Modèle pour la configuration des runtimes (ex: vscode, jupyter)
class RuntimeConfig(Base):
    __tablename__ = "runtime_configs"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(
        String(50), unique=True, index=True, nullable=False
    )  # ex: vscode, jupyter
    default_image = Column(String(200), nullable=True)
    target_port = Column(Integer, nullable=True)
    default_service_type = Column(String(30), nullable=False, default="NodePort")
    allowed_for_students = Column(Boolean, default=True)
    min_cpu_request = Column(String(20), nullable=True)
    min_memory_request = Column(String(20), nullable=True)
    min_cpu_limit = Column(String(20), nullable=True)
    min_memory_limit = Column(String(20), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
