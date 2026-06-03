"""
Schémas Pydantic pour LabOnDemand
Principe KISS : Uniquement les schémas utilisés
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime
from enum import Enum

# Schémas pour les rôles d'utilisateur
class UserRoleEnum(str, Enum):
    student = "student"
    teacher = "teacher"
    admin = "admin"

# Schéma pour la création d'utilisateur
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: Optional[str] = None
    password: str = Field(..., min_length=8)
    role: UserRoleEnum = UserRoleEnum.student
    is_active: Optional[bool] = True
    auth_provider: Optional[str] = None
    external_id: Optional[str] = None

# Schéma pour la mise à jour d'utilisateur
class UserUpdate(BaseModel):
    # str au lieu de EmailStr pour accepter les domaines internes (.local, .internal, etc.)
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    role: Optional[UserRoleEnum] = None
    is_active: Optional[bool] = None

    @field_validator("email")
    @classmethod
    def validate_email_loose(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and "@" not in v:
            raise ValueError("Adresse email invalide (le caractère @ est requis)")
        return v

# Schéma pour l'authentification
class UserLogin(BaseModel):
    username: str
    password: str

# Schéma pour la réponse utilisateur (sans mot de passe)
class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    role: UserRoleEnum
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    auth_provider: Optional[str] = None
    external_id: Optional[str] = None

    class Config:
        from_attributes = True

# Schéma pour la session utilisateur
class SessionData(BaseModel):
    user_id: int
    username: str
    role: UserRoleEnum

# Schéma pour la réponse de connexion
class LoginResponse(BaseModel):
    user: UserResponse
    session_id: str


# ====== Templates ======
class TemplateBase(BaseModel):
    key: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    icon: Optional[str] = Field(None, max_length=100)
    # Autoriser n'importe quel runtime déclaré (slug a-z0-9-)
    deployment_type: str = Field("custom", pattern=r"^[a-z0-9][a-z0-9\-]{1,49}$")
    default_image: Optional[str] = Field(None, max_length=200)
    default_port: Optional[int] = Field(None, ge=1, le=65535)
    default_service_type: str = Field("NodePort", pattern=r"^(ClusterIP|NodePort|LoadBalancer)$")
    active: bool = True
    tags: Optional[List[str]] = None


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=255)
    icon: Optional[str] = Field(None, max_length=100)
    deployment_type: Optional[str] = Field(None, pattern=r"^[a-z0-9][a-z0-9\-]{1,49}$")
    default_image: Optional[str] = Field(None, max_length=200)
    default_port: Optional[int] = Field(None, ge=1, le=65535)
    default_service_type: Optional[str] = Field(None, pattern=r"^(ClusterIP|NodePort|LoadBalancer)$")
    active: Optional[bool] = None
    tags: Optional[List[str]] = None


class TemplateResponse(TemplateBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ====== Runtime Configs ======
class RuntimeConfigBase(BaseModel):
    key: str = Field(..., min_length=2, max_length=50)
    default_image: Optional[str] = Field(None, max_length=200)
    target_port: Optional[int] = Field(None, ge=1, le=65535)
    default_service_type: str = Field("NodePort", pattern=r"^(ClusterIP|NodePort|LoadBalancer)$")
    allowed_for_students: bool = True
    min_cpu_request: Optional[str] = Field(None, max_length=20)
    min_memory_request: Optional[str] = Field(None, max_length=20)
    min_cpu_limit: Optional[str] = Field(None, max_length=20)
    min_memory_limit: Optional[str] = Field(None, max_length=20)
    active: bool = True


class RuntimeConfigCreate(RuntimeConfigBase):
    pass


class RuntimeConfigUpdate(BaseModel):
    default_image: Optional[str] = Field(None, max_length=200)
    target_port: Optional[int] = Field(None, ge=1, le=65535)
    default_service_type: Optional[str] = Field(None, pattern=r"^(ClusterIP|NodePort|LoadBalancer)$")
    allowed_for_students: Optional[bool] = None
    min_cpu_request: Optional[str] = Field(None, max_length=20)
    min_memory_request: Optional[str] = Field(None, max_length=20)
    min_cpu_limit: Optional[str] = Field(None, max_length=20)
    min_memory_limit: Optional[str] = Field(None, max_length=20)
    active: Optional[bool] = None


class RuntimeConfigResponse(RuntimeConfigBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ====== Persistent Volumes ======
class PVCInfo(BaseModel):
    name: str
    namespace: str
    phase: Optional[str] = None
    storage: Optional[str] = None
    access_modes: List[str] = []
    storage_class: Optional[str] = None
    volume_name: Optional[str] = None
    managed_by: Optional[str] = None
    app_type: Optional[str] = None
    last_bound_app: Optional[str] = None
    created_at: Optional[str] = None
    bound: bool = False
    labels: Dict[str, str] = {}
    annotations: Dict[str, str] = {}


class PVCListResponse(BaseModel):
    items: List[PVCInfo]


# ====== Change Password ======
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=12)


# ====== Classroom / Enrollment / Assignment ======
class ClassroomBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)


class ClassroomCreate(ClassroomBase):
    pass


class ClassroomUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    archived: Optional[bool] = None


class ClassroomResponse(ClassroomBase):
    id: int
    owner_id: int
    archived: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    student_count: Optional[int] = None
    active_assignment_count: Optional[int] = None

    class Config:
        from_attributes = True


class EnrollmentResponse(BaseModel):
    id: int
    classroom_id: int
    user_id: int
    username: Optional[str] = None
    email: Optional[str] = None
    enrolled_at: datetime
    removed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EnrollStudentsRequest(BaseModel):
    user_ids: List[int]


class AssignmentBase(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    instructions: Optional[str] = None
    deliverables: Optional[str] = None
    template_key: Optional[str] = Field(None, max_length=50)
    cpu_preset: Optional[str] = Field(None, pattern=r"^(very-low|low|medium|high|very-high)$")
    ram_preset: Optional[str] = Field(None, pattern=r"^(very-low|low|medium|high|very-high)$")
    due_at: Optional[datetime] = None
    grading_mode: str = Field("none", pattern=r"^(none|self_check|graded)$")


class AssignmentCreate(AssignmentBase):
    pass


class AssignmentUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=200)
    instructions: Optional[str] = None
    deliverables: Optional[str] = None
    template_key: Optional[str] = Field(None, max_length=50)
    cpu_preset: Optional[str] = Field(None, pattern=r"^(very-low|low|medium|high|very-high)$")
    ram_preset: Optional[str] = Field(None, pattern=r"^(very-low|low|medium|high|very-high)$")
    due_at: Optional[datetime] = None
    status: Optional[str] = Field(None, pattern=r"^(active|archived)$")
    grading_mode: Optional[str] = Field(None, pattern=r"^(none|self_check|graded)$")


class AssignmentResponse(AssignmentBase):
    id: int
    classroom_id: int
    status: str
    grading_mode: str = "none"
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ====== Grading Spec & Runs (MVP-2) ======

PROBE_KINDS = {"http", "tcp", "sql", "file", "command", "script"}
PROBE_VISIBILITIES = {"student", "summary", "teacher_only"}
PROBE_VANTAGES = {"outside", "inside"}


class Probe(BaseModel):
    """Une vérification boîte noire définie par l'enseignant."""
    id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=200)
    kind: str = Field(..., description="http|tcp|sql|file|command|script")
    vantage: str = Field("outside", description="outside|inside")
    config: Dict = Field(default_factory=dict)
    expect: Dict = Field(default_factory=dict)
    weight: int = Field(1, ge=0, le=100)
    visibility: str = Field("student", description="student|summary|teacher_only")

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        if v not in PROBE_KINDS:
            raise ValueError(f"kind doit être l'un de : {', '.join(sorted(PROBE_KINDS))}")
        return v

    @field_validator("vantage")
    @classmethod
    def validate_vantage(cls, v: str) -> str:
        if v not in PROBE_VANTAGES:
            raise ValueError(f"vantage doit être l'un de : {', '.join(sorted(PROBE_VANTAGES))}")
        return v

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, v: str) -> str:
        if v not in PROBE_VISIBILITIES:
            raise ValueError(f"visibility doit être l'un de : {', '.join(sorted(PROBE_VISIBILITIES))}")
        return v


class GradingSpecCreate(BaseModel):
    grader_image: Optional[str] = Field(None, max_length=300)
    timeout_seconds: int = Field(120, ge=10, le=600)
    checks: List[Probe] = Field(default_factory=list)
    custom_script: Optional[str] = Field(None, max_length=50000)


class GradingSpecResponse(BaseModel):
    id: int
    assignment_id: int
    grader_image: Optional[str] = None
    timeout_seconds: int
    checks: List[Probe] = []
    custom_script: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProbeResult(BaseModel):
    """Résultat d'une probe après exécution par le Grader Pod."""
    id: str
    name: str
    status: str  # pass | fail | error | skip
    message: Optional[str] = None
    output: Optional[str] = None
    weight: int = 1
    visibility: str = "student"


class GradingRunResponse(BaseModel):
    id: int
    assignment_id: int
    user_id: int
    submission_id: Optional[int] = None
    deployment_id: Optional[int] = None
    trigger: str
    status: str  # queued | running | done | error
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total_checks: Optional[int] = None
    passed_checks: Optional[int] = None
    score_suggestion: Optional[str] = None
    results: Optional[List[ProbeResult]] = None
    error: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class GradingRunCallbackRequest(BaseModel):
    """Payload POSTé par le Grader Pod vers l'endpoint interne."""
    token: str = Field(..., min_length=32, max_length=128)
    status: str = Field(..., pattern=r"^(done|error)$")
    results: Optional[List[ProbeResult]] = None
    error: Optional[str] = Field(None, max_length=500)


class BulkSpawnResult(BaseModel):
    user_id: int
    username: str
    status: str  # ok | skipped | error
    error: Optional[str] = None
    deployment_name: Optional[str] = None


class BulkSpawnReport(BaseModel):
    assignment_id: int
    classroom_id: int
    total: int
    ok: int
    skipped: int
    errors: int
    results: List[BulkSpawnResult]


class StudentLabStatus(BaseModel):
    user_id: int
    username: str
    email: str
    lab_name: Optional[str] = None
    lab_status: Optional[str] = None
    lab_expires_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    enrolled_at: datetime


# ====== Assignment Submissions (MVP-1) ======
class SubmissionLink(BaseModel):
    label: Optional[str] = Field(None, max_length=120)
    url: str = Field(..., min_length=1, max_length=2000)


class AssignmentSubmissionCreate(BaseModel):
    text: Optional[str] = Field(None, max_length=20000)
    links: Optional[List[SubmissionLink]] = None


class SubmissionGradeRequest(BaseModel):
    grade: Optional[str] = Field(None, max_length=20)
    feedback: Optional[str] = Field(None, max_length=20000)


class AssignmentSubmissionResponse(BaseModel):
    id: int
    assignment_id: int
    user_id: int
    attempt_no: int
    status: str
    text: Optional[str] = None
    links: List[SubmissionLink] = []
    deployment_id: Optional[int] = None
    lab_snapshot: Optional[Dict] = None
    submitted_at: Optional[datetime] = None
    is_late: bool = False
    due_at_snapshot: Optional[datetime] = None
    grade: Optional[str] = None
    feedback: Optional[str] = None
    graded_by: Optional[int] = None
    graded_at: Optional[datetime] = None
    # Dernier Grading Run de cet étudiant (vue prof : résultats détaillés non filtrés)
    grading_run: Optional[GradingRunResponse] = None


class StudentProbe(BaseModel):
    """Probe telle qu'exposée à l'étudiant : nom + type, SANS la config/expect interne
    (qui révélerait la réponse attendue)."""
    id: str
    name: str
    kind: str
    weight: int = 1
    visibility: str = "student"


class StudentAssignmentItem(BaseModel):
    """Un devoir tel que vu par l'étudiant (vue liste 'Mes devoirs')."""
    id: int
    classroom_id: int
    classroom_name: Optional[str] = None
    title: str
    instructions: Optional[str] = None
    template_key: Optional[str] = None
    due_at: Optional[datetime] = None
    # Lab poussé par le prof (push deploy-all)
    lab_ready: bool = False
    lab_deployment_name: Optional[str] = None
    lab_namespace: Optional[str] = None
    lab_status: Optional[str] = None
    # Statut dérivé de la soumission
    submission_status: str = "not_started"  # not_started | submitted | graded
    submitted_at: Optional[datetime] = None
    is_late: bool = False
    grade: Optional[str] = None


class StudentAssignmentDetail(StudentAssignmentItem):
    """Détail d'un devoir + la soumission de l'étudiant si elle existe."""
    deliverables: Optional[str] = None
    submission: Optional[AssignmentSubmissionResponse] = None
    # Tests boîte noire (MVP-2)
    grading_mode: str = "none"
    visible_probes: List[StudentProbe] = []
    latest_run: Optional[GradingRunResponse] = None


class TeacherSubmissionRow(BaseModel):
    """Une ligne du tableau de correction (un étudiant inscrit)."""
    user_id: int
    username: str
    email: Optional[str] = None
    submission_id: Optional[int] = None
    submission_status: str = "not_started"  # not_started | submitted | graded
    submitted_at: Optional[datetime] = None
    is_late: bool = False
    grade: Optional[str] = None
    lab_deployment_name: Optional[str] = None
    lab_status: Optional[str] = None
    # Verdict du dernier Grading Run (colonne « 4/5 » du tableau de triage)
    grading_status: Optional[str] = None  # queued | running | done | error
    grading_passed: Optional[int] = None
    grading_total: Optional[int] = None
    score_suggestion: Optional[str] = None
