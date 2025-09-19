from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import os

from .database import get_db
from .models import User, UserRole
from .schemas import UserCreate, UserLogin, UserResponse, UserUpdate, LoginResponse
from .security import (
    authenticate_user, create_session, get_password_hash, 
    get_current_user, delete_session, is_admin, is_teacher_or_admin
)
from .session import SECURE_COOKIES, SESSION_EXPIRY_HOURS, SESSION_SAMESITE, COOKIE_DOMAIN

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post("/login", response_model=LoginResponse)
def login(user_credentials: UserLogin, response: Response, db: Session = Depends(get_db)):
    """
    Connecte un utilisateur et crée une session
    """
    print(f"[Login] Tentative de connexion pour l'utilisateur: {user_credentials.username}")
    
    user = authenticate_user(db, user_credentials.username, user_credentials.password)
    if not user:
        print(f"[Login] Échec d'authentification pour {user_credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Créer une session pour l'utilisateur
    print(f"[Login] Authentification réussie pour {user_credentials.username}, création d'une session...")
    session_id = create_session(user.id, user.username, user.role)
    print(f"[Login] Session créée avec ID: {session_id[:10]}...")
    
    # Créer la réponse
    resp = LoginResponse(
        user=UserResponse.model_validate(user),
        session_id=session_id
    )
    
    # Ajouter l'ID de session aux headers pour que le middleware puisse créer le cookie
    response.headers["session_id"] = session_id
    print(f"[Login] ID de session ajouté aux headers de réponse")
    
    # Ajouter le cookie directement (en plus du middleware)
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=SESSION_SAMESITE.lower(),
        max_age=SESSION_EXPIRY_HOURS * 3600,
        path="/",
        domain=COOKIE_DOMAIN or None
    )
    print(f"[Login] Cookie session_id créé directement dans la réponse")
    
    return resp

@router.post("/logout")
def logout(response: Response, request: Request, user: User = Depends(get_current_user)):
    """
    Déconnecte l'utilisateur actuel en supprimant son cookie de session
    et en invalidant la session côté serveur
    """
    # Récupérer l'ID de session depuis le cookie
    session_id = request.cookies.get("session_id")
    if session_id:
        # Supprimer la session côté serveur
        delete_session(session_id)
    
    # Supprimer le cookie côté client
    response.delete_cookie(key="session_id", path="/")
    
    return {"message": "Déconnexion réussie"}

@router.get("/me", response_model=UserResponse)
def read_user_me(current_user: User = Depends(get_current_user)):
    """
    Renvoie les informations de l'utilisateur actuellement connecté
    """
    return current_user

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(is_admin)])
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    """
    Enregistre un nouvel utilisateur (accessible uniquement aux admin dans une implémentation finale)
    """
    # Vérifier si le nom d'utilisateur existe déjà
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce nom d'utilisateur est déjà utilisé"
        )
    
    # Vérifier si l'email existe déjà
    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cet email est déjà utilisé"
        )
    
    # Créer un nouvel utilisateur
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        hashed_password=hashed_password,
        role=UserRole[user.role],
        is_active=user.is_active if user.is_active is not None else True
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user

@router.get("/users", response_model=List[UserResponse], dependencies=[Depends(is_admin)])
def get_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    Récupère la liste des utilisateurs (admins seulement)
    """
    users = db.query(User).offset(skip).limit(limit).all()
    return users

@router.get("/users/{user_id}", response_model=UserResponse, dependencies=[Depends(is_admin)])
def get_user(user_id: int, db: Session = Depends(get_db)):
    """
    Récupère les informations d'un utilisateur par son ID (admins seulement)
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    return user

@router.put("/users/{user_id}", response_model=UserResponse, dependencies=[Depends(is_admin)])
def update_user(user_id: int, user_update: UserUpdate, db: Session = Depends(get_db)):
    """
    Met à jour les informations d'un utilisateur (admins seulement)
    """
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    # Mise à jour des champs fournis
    if user_update.email is not None:
        # Vérifier si l'email est déjà utilisé
        email_exists = db.query(User).filter(
            User.email == user_update.email, 
            User.id != user_id
        ).first()
        if email_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cet email est déjà utilisé"
            )
        db_user.email = user_update.email
    
    if user_update.full_name is not None:
        db_user.full_name = user_update.full_name
    
    if user_update.password is not None:
        db_user.hashed_password = get_password_hash(user_update.password)
    
    if user_update.role is not None:
        db_user.role = UserRole[user_update.role]
    
    if user_update.is_active is not None:
        db_user.is_active = user_update.is_active
    
    db.commit()
    db.refresh(db_user)
    
    return db_user

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(is_admin)])
def delete_user(user_id: int, db: Session = Depends(get_db)):
    """
    Supprime un utilisateur (admins seulement)
    """
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )
    
    db.delete(db_user)
    db.commit()
    
    return None

@router.put("/me", response_model=UserResponse)
def update_user_me(user_update: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Permet à l'utilisateur connecté de mettre à jour son propre profil
    (sauf le rôle qui ne peut être modifié que par un admin)
    """
    # On ne permet pas à l'utilisateur de changer son propre rôle 
    # pour des raisons de sécurité
    if user_update.role is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas modifier votre propre rôle"
        )
    
    # On ne permet pas à l'utilisateur de désactiver son propre compte
    if user_update.is_active is not None and user_update.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vous ne pouvez pas désactiver votre propre compte"
        )
    
    # Vérifier que l'email n'existe pas déjà si fourni
    if user_update.email is not None:
        email_exists = db.query(User).filter(
            User.email == user_update.email, 
            User.id != current_user.id
        ).first()
        if email_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cet email est déjà utilisé"
            )
        current_user.email = user_update.email
    
    # Mise à jour du nom complet
    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name
    
    # Mise à jour du mot de passe
    if user_update.password is not None:
        current_user.hashed_password = get_password_hash(user_update.password)
    
    db.commit()
    db.refresh(current_user)
    
    return current_user

@router.get("/check-role")
def check_user_role(current_user: User = Depends(get_current_user)):
    """
    Renvoie le rôle de l'utilisateur actuel et les permissions associées
    """
    role = current_user.role.value
    permissions = {
        "can_manage_users": role == UserRole.admin.value,
        "can_create_labs": role in [UserRole.admin.value, UserRole.teacher.value],
        "can_view_all_labs": role in [UserRole.admin.value, UserRole.teacher.value],
        "role": role
    }
    return permissions

@router.post("/change-password", response_model=UserResponse)
def change_password(
    old_password: str, 
    new_password: str, 
    current_user: User = Depends(get_current_user), 
    db: Session = Depends(get_db)
):
    """
    Permet à l'utilisateur de changer son mot de passe en fournissant 
    l'ancien mot de passe pour vérification
    """
    from .security import verify_password
    
    # Vérifier l'ancien mot de passe
    if not verify_password(old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe actuel est incorrect"
        )
    
    # Vérifier que le nouveau mot de passe est différent
    if old_password == new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit être différent de l'ancien"
        )
    
    # Vérifier que le nouveau mot de passe a une longueur minimale
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le nouveau mot de passe doit comporter au moins 8 caractères"
        )
    
    # Mettre à jour le mot de passe
    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    db.refresh(current_user)
    
    return current_user

@router.get("/debug-auth-status")
def debug_auth_status(db: Session = Depends(get_db)):
    """
    Endpoint de débogage pour vérifier l'état de l'authentification
    """
    try:
        # Vérifier si l'admin existe
        admin = db.query(User).filter(User.username == "admin").first()
        
        # Obtenir tous les utilisateurs
        users = db.query(User).all()
        user_list = []
        for user in users:
            user_list.append({
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role.value,
                "is_active": user.is_active
            })
        
        # Statistiques
        stats = {
            "admin_exists": admin is not None,
            "total_users": len(users),
            "connection_string": os.environ.get("DB_HOST", "localhost")
        }
        
        return {
            "status": "success",
            "database_connection": "ok",
            "stats": stats,
            "users": user_list
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
