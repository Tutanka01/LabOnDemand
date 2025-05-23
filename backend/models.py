from sqlalchemy import Boolean, Column, Integer, String, ForeignKey, DateTime, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from .database import Base

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
    
    # Relation avec les laboratoires (sera implémentée plus tard)
    labs = relationship("Lab", back_populates="owner")

# Modèle pour les laboratoires (version simplifiée)
class Lab(Base):
    __tablename__ = "labs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), index=True)
    description = Column(Text, nullable=True)
    lab_type = Column(String(50))  # jupyter, vscode, etc.
    k8s_namespace = Column(String(100))
    deployment_name = Column(String(100))
    service_name = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relation avec l'utilisateur propriétaire
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="labs")
