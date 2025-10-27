import logging
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import secrets
import os
import json
import base64

# Gestion des importations pour fonctionner à la fois comme module et comme script
try:
    # Pour l'utilisation comme module dans l'application
    from .database import get_db
    from .models import User, UserRole
    from .schemas import SessionData
    from .session_store import session_store
    from .logging_config import shorten_token
except ImportError:
    # Pour l'utilisation comme script direct
    from database import get_db
    from models import User, UserRole
    from schemas import SessionData
    from session_store import session_store
    from logging_config import shorten_token

# Configuration du contexte de hachage de mot de passe
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Clé API pour la sécurité basée sur les cookies
cookie_security = APIKeyCookie(name="session_id", auto_error=False)

logger = logging.getLogger("labondemand.security")

# Vérification des mots de passe
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Génération de hachage de mot de passe
def get_password_hash(password):
    return pwd_context.hash(password)

# Gestion des sessions
def create_session(user_id: int, username: str, role: UserRole) -> str:
    # Générer un ID de session unique
    session_id = secrets.token_urlsafe(32)
    session_preview = shorten_token(session_id)
    
    # Créer les données de session
    session_data = SessionData(
        user_id=user_id,
        username=username,
        role=role.value
    )
    
    # Stocker la session avec notre gestionnaire de sessions
    session_store.set(session_id, session_data.model_dump())
    logger.info(
        "session_created",
        extra={
            "extra_fields": {
                "user_id": user_id,
                "username": username,
                "role": role.value,
                "session_id": session_preview,
            }
        },
    )
    
    return session_id

def get_session_data(
    request: Request,
    session_id: str = Depends(cookie_security),
) -> SessionData:
    session_preview = shorten_token(session_id)

    if not session_id:
        logger.warning(
            "session_cookie_missing",
            extra={"extra_fields": {"path": request.url.path, "client_ip": getattr(request.client, "host", None)}},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session non fournie",
            headers={"WWW-Authenticate": "Bearer"},
        )

    session_data = session_store.get(session_id)

    if not session_data:
        logger.warning(
            "session_invalid",
            extra={
                "extra_fields": {
                    "session_id": session_preview,
                    "path": request.url.path,
                    "client_ip": getattr(request.client, "host", None),
                }
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalide ou expirée",
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.session_id = session_id
    session_obj = SessionData(**session_data)
    request.state.session = session_obj

    logger.debug(
        "session_valid",
        extra={
            "extra_fields": {
                "session_id": session_preview,
                "user_id": session_obj.user_id,
                "username": session_obj.username,
                "role": session_obj.role,
            }
        },
    )

    return session_obj

def delete_session(session_id: str) -> bool:
    if not session_id:
        return False
    session_preview = shorten_token(session_id)
    removed = session_store.delete(session_id)
    logger.info(
        "session_deleted",
        extra={"extra_fields": {"session_id": session_preview, "removed": removed}},
    )
    return removed

# Authentification utilisateur
def authenticate_user(db: Session, username: str, password: str):
    logger.debug(
        "authenticate_user_attempt",
        extra={"extra_fields": {"username": username}},
    )

    user = db.query(User).filter(User.username == username).first()
    if not user:
        logger.warning(
            "authenticate_user_failed",
            extra={"extra_fields": {"username": username, "reason": "user_not_found"}},
        )
        return False
    
    # Vérifier le mot de passe
    password_valid = verify_password(password, user.hashed_password)
    if not password_valid:
        logger.warning(
            "authenticate_user_failed",
            extra={"extra_fields": {"username": username, "reason": "invalid_password"}},
        )
        return False
    
    if not user.is_active:
        logger.warning(
            "authenticate_user_failed",
            extra={"extra_fields": {"username": username, "reason": "inactive"}},
        )
        return False

    logger.debug(
        "authenticate_user_success",
        extra={"extra_fields": {"user_id": user.id, "username": username}},
    )
    return user

# Vérifier les permissions utilisateur
def is_admin(session_data: SessionData = Depends(get_session_data)):
    if session_data.role != UserRole.admin.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission refusée. Rôle admin requis."
        )
    return session_data

def is_teacher_or_admin(session_data: SessionData = Depends(get_session_data)):
    if session_data.role not in [UserRole.teacher.value, UserRole.admin.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission refusée. Rôle professeur ou admin requis."
        )
    return session_data

# Récupération de l'utilisateur actuel
def get_current_user(
    request: Request,
    session_data: SessionData = Depends(get_session_data),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == session_data.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur non trouvé",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur inactif",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.user = user
    return user
