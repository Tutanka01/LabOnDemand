"""
Schémas Pydantic pour LabOnDemand
Principe KISS : Uniquement les schémas utilisés
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
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

# Schéma pour la mise à jour d'utilisateur
class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)
    role: Optional[UserRoleEnum] = None
    is_active: Optional[bool] = None

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
    deployment_type: str = Field("custom", pattern=r"^(custom|vscode|jupyter|wordpress|mysql)$")
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
    deployment_type: Optional[str] = Field(None, pattern=r"^(custom|vscode|jupyter|wordpress|mysql)$")
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
