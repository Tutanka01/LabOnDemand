"""
Schémas Pydantic pour LabOnDemand
Principe KISS : Uniquement les schémas utilisés
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
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
