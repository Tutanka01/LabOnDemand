from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import secrets
import os
import json
import base64

from .database import get_db
from .models import User, UserRole
from .schemas import SessionData
from .session_store import session_store

# Configuration du contexte de hachage de mot de passe
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Clé API pour la sécurité basée sur les cookies
cookie_security = APIKeyCookie(name="session_id", auto_error=False)

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
    
    # Créer les données de session
    session_data = SessionData(
        user_id=user_id,
        username=username,
        role=role.value
    )
    
    # Stocker la session avec notre gestionnaire de sessions
    session_store.set(session_id, session_data.model_dump())
    
    return session_id

def get_session_data(session_id: str = Depends(cookie_security)) -> SessionData:
    print(f"[Session] Vérification de la session avec ID: {session_id[:10] if session_id else 'None'}...")
    
    if not session_id:
        print("[Session] Aucun ID de session fourni dans les cookies")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session non fournie",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Récupérer les données de session
    session_data = session_store.get(session_id)
    
    if not session_data:
        print(f"[Session] Session introuvable ou expirée: {session_id[:10]}...")
        # Afficher toutes les sessions actives pour le débogage
        print("[Session] Sessions actives:")
        for sid, data in session_store.sessions.items():
            print(f"  - {sid[:10]}... (expire le {data['expiry']})")
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalide ou expirée",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    print(f"[Session] Session valide trouvée pour l'utilisateur: {session_data.get('username', 'inconnu')}")
    return SessionData(**session_data)

def delete_session(session_id: str) -> bool:
    return session_store.delete(session_id)

# Authentification utilisateur
def authenticate_user(db: Session, username: str, password: str):
    # Ajouter des logs de debug pour comprendre le processus d'authentification
    print(f"Tentative d'authentification pour l'utilisateur: {username}")
    
    user = db.query(User).filter(User.username == username).first()
    if not user:
        print(f"Échec d'authentification: Utilisateur '{username}' non trouvé")
        return False
    
    # Vérifier le mot de passe
    print(f"Utilisateur trouvé. Vérification du mot de passe...")
    password_valid = verify_password(password, user.hashed_password)
    if not password_valid:
        print(f"Échec d'authentification: Mot de passe incorrect pour '{username}'")
        return False
    
    if not user.is_active:
        print(f"Échec d'authentification: Compte '{username}' inactif")
        return False
    
    print(f"Authentification réussie pour l'utilisateur: {username}")
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
    return user
