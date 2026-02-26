"""
Modèles SQLAlchemy pour LabOnDemand
Principe KISS : Uniquement les modèles utilisés
"""

from sqlalchemy import Boolean, Column, Integer, String, DateTime, Enum, ForeignKey
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
