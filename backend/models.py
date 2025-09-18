"""
Modèles SQLAlchemy pour LabOnDemand  
Principe KISS : Uniquement les modèles utilisés
"""
from sqlalchemy import Boolean, Column, Integer, String, DateTime, Enum
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
    role = Column(Enum(UserRole), default=UserRole.student, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Modèle pour les templates d'application (déploiements)
class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, index=True, nullable=False)  # identifiant fonctionnel (ex: vscode, jupyter)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)
    icon = Column(String(100), nullable=True)  # ex: fa-solid fa-code
    deployment_type = Column(String(30), nullable=False, default="custom")  # vscode|jupyter|custom
    default_image = Column(String(200), nullable=True)
    default_port = Column(Integer, nullable=True)
    default_service_type = Column(String(30), nullable=False, default="NodePort")  # ClusterIP|NodePort|LoadBalancer
    # Types multiples (tags) stockés en CSV pour simplicité (ex: "web,python,education")
    tags = Column(String(255), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# Modèle pour la configuration des runtimes (ex: vscode, jupyter)
class RuntimeConfig(Base):
    __tablename__ = "runtime_configs"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(50), unique=True, index=True, nullable=False)  # ex: vscode, jupyter
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
