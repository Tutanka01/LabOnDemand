import logging
import os
import secrets
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .logging_config import shorten_token

from .database import get_db
from .models import User, UserRole, UserQuotaOverride
from .schemas import UserCreate, UserLogin, UserResponse, UserUpdate, LoginResponse, SessionData
from .security import (
    authenticate_user, create_session, get_password_hash,
    get_current_user, delete_session, delete_user_sessions,
    is_admin, is_teacher_or_admin, limiter, validate_password_strength
)
from .session import SECURE_COOKIES, SESSION_EXPIRY_HOURS, SESSION_SAMESITE, COOKIE_DOMAIN
from .config import settings
from .sso import (
    get_authorization_url,
    exchange_code,
    get_userinfo,
    map_role,
    sanitize_username,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

logger = logging.getLogger("labondemand.auth")
audit_logger = logging.getLogger("labondemand.audit")

@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(
    user_credentials: UserLogin,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Connecte un utilisateur et crée une session
    """
    client = request.client or None
    logger.info(
        "login_attempt",
        extra={
            "extra_fields": {
                "username": user_credentials.username,
                "client_ip": getattr(client, "host", None),
                "client_port": getattr(client, "port", None),
            }
        },
    )
    
    user = authenticate_user(db, user_credentials.username, user_credentials.password)
    if user and settings.SSO_ENABLED and user.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Connexion locale désactivée pour les comptes SSO",
        )
    if not user:
        audit_logger.warning(
            "login_failed",
            extra={
                "extra_fields": {
                    "username": user_credentials.username,
                    "client_ip": getattr(client, "host", None),
                    "reason": "invalid_credentials",
                }
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Créer une session pour l'utilisateur
    session_id = create_session(user.id, user.username, user.role)
    session_preview = shorten_token(session_id)
    request.state.session_id = session_id
    request.state.user = user
    
    # Créer la réponse
    resp = LoginResponse(
        user=UserResponse.model_validate(user),
        session_id=session_id
    )
    
    # Ajouter l'ID de session aux headers pour que le middleware puisse créer le cookie
    response.headers["session_id"] = session_id
    
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

    audit_logger.info(
        "login_success",
        extra={
            "extra_fields": {
                "user_id": user.id,
                "username": user.username,
                "role": user.role.value,
                "session_id": session_preview,
                "client_ip": getattr(client, "host", None),
            }
        },
    )
    
    return resp


def _get_redirect_uri(request: Request) -> str:
    """Construit l'URL de callback OIDC."""
    if settings.OIDC_REDIRECT_URI:
        return settings.OIDC_REDIRECT_URI
    # Dérivé automatiquement depuis l'URL de la requête
    base = f"{request.url.scheme}://{request.url.netloc}"
    return f"{base}/api/v1/auth/sso/callback"


@router.get("/sso/status")
def sso_status():
    """Expose l'état du SSO."""
    return {"sso_enabled": settings.SSO_ENABLED}


@router.get("/sso/login")
def sso_login(request: Request, response: Response):
    """Démarre l'authentification OIDC — redirige vers l'IdP."""
    if not settings.SSO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO désactivé")
    if not settings.OIDC_CLIENT_ID or not settings.OIDC_ISSUER:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration OIDC incomplète (OIDC_CLIENT_ID ou OIDC_ISSUER manquant)",
        )

    state = secrets.token_urlsafe(32)
    redirect_uri = _get_redirect_uri(request)
    auth_url = get_authorization_url(redirect_uri=redirect_uri, state=state)

    resp = RedirectResponse(url=auth_url)
    # Stocke le state dans un cookie HttpOnly pour vérification CSRF au retour
    resp.set_cookie(
        key="oidc_state",
        value=state,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="lax",
        max_age=600,  # 10 minutes
        path="/",
    )
    return resp


@router.get("/sso/callback")
def sso_callback(request: Request, db: Session = Depends(get_db)):
    """Callback OIDC : échange le code, récupère l'utilisateur, crée la session.

    Flux complet :
    1. Vérifie le paramètre ``error`` renvoyé par l'IdP.
    2. Valide le ``state`` CSRF (comparaison avec le cookie ``oidc_state``).
    3. Échange le code d'autorisation contre un access token.
    4. Récupère les claims utilisateur via le endpoint userinfo.
    5. Recherche le compte existant par ``external_id`` (sub) puis par email.
    6. Crée le compte s'il n'existe pas encore.
    7. Met à jour les champs de profil (username, email, full_name) à chaque
       connexion, **sauf le rôle** dans les cas suivants :
         - L'utilisateur est admin (protection contre la rétrogradation).
         - ``user.role_override`` est ``True`` : un admin a défini le rôle
           manuellement via l'API et ce choix prime sur les claims IdP.
    8. Crée la session et redirige vers ``FRONTEND_BASE_URL``.
    """
    if not settings.SSO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO désactivé")

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"SSO refusé par l'IdP: {error}",
        )
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code OIDC manquant")

    # Vérification CSRF via le state
    expected_state = request.cookies.get("oidc_state")
    if not expected_state or expected_state != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="State OIDC invalide (possible attaque CSRF)",
        )

    redirect_uri = _get_redirect_uri(request)
    tokens = exchange_code(code=code, redirect_uri=redirect_uri)
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'accès OIDC manquant",
        )

    claims = get_userinfo(access_token)

    # Extraction des informations utilisateur depuis les claims OIDC
    sub = claims.get("sub") or ""
    email = claims.get("email") or ""
    full_name = claims.get("name") or claims.get("displayName") or ""
    username_raw = (
        claims.get("preferred_username")
        or claims.get("uid")
        or email.split("@")[0]
        or sub
    )
    username = sanitize_username(username_raw)

    if not email:
        email = f"{username}@{settings.OIDC_EMAIL_FALLBACK_DOMAIN}"

    if not sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SSO: identifiant unique (sub) manquant dans les claims",
        )

    role = map_role(claims)

    def ensure_unique_username(base_name: str, user_id: Optional[int]) -> str:
        candidate = base_name
        counter = 1
        while True:
            query = db.query(User).filter(User.username == candidate)
            if user_id is not None:
                query = query.filter(User.id != user_id)
            if not query.first():
                return candidate
            counter += 1
            candidate = f"{base_name}-{counter}"

    def ensure_unique_email(base_email: str, user_id: Optional[int]) -> str:
        candidate = base_email
        counter = 1
        while True:
            query = db.query(User).filter(User.email == candidate)
            if user_id is not None:
                query = query.filter(User.id != user_id)
            if not query.first():
                return candidate
            counter += 1
            local, domain = base_email.split("@", 1)
            candidate = f"{local}+{counter}@{domain}"

    # Recherche ou création de l'utilisateur
    user = db.query(User).filter(User.external_id == sub).first()
    if not user and email:
        user = db.query(User).filter(User.email == email).first()

    if not user:
        username = ensure_unique_username(username, None)
        email = ensure_unique_email(email, None)
        user = User(
            username=username,
            email=email,
            full_name=full_name or None,
            hashed_password=get_password_hash(os.urandom(24).hex()),
            role=UserRole[role],
            is_active=True,
            auth_provider="oidc",
            external_id=sub,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("oidc_user_created", extra={"extra_fields": {"username": username, "role": role}})
    else:
        username = ensure_unique_username(username, user.id)
        email = ensure_unique_email(email, user.id)
        user.username = username
        user.email = email
        user.full_name = full_name or user.full_name
        user.auth_provider = "oidc"
        user.external_id = sub
        # Ne pas écraser le rôle si : (a) admin (protection), ou
        # (b) role_override=True — un admin a manuellement défini ce rôle.
        if user.role != UserRole.admin and not user.role_override:
            user.role = UserRole[role]
        db.commit()
        db.refresh(user)

    session_id = create_session(user.id, user.username, user.role)
    request.state.session_id = session_id
    request.state.user = user

    redirect_to = settings.FRONTEND_BASE_URL or "/"
    response = RedirectResponse(url=redirect_to)
    # Supprime le cookie de state OIDC
    response.delete_cookie(key="oidc_state", path="/")
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite=SESSION_SAMESITE.lower(),
        max_age=SESSION_EXPIRY_HOURS * 3600,
        path="/",
        domain=COOKIE_DOMAIN or None,
    )
    return response

@router.post("/logout")
def logout(response: Response, request: Request, user: User = Depends(get_current_user)):
    """
    Déconnecte l'utilisateur actuel en supprimant son cookie de session
    et en invalidant la session côté serveur
    """
    # Récupérer l'ID de session depuis le cookie
    session_id = request.cookies.get("session_id")
    session_preview = shorten_token(session_id)
    if session_id:
        delete_session(session_id)

    response.delete_cookie(key="session_id", path="/")

    audit_logger.info(
        "logout",
        extra={
            "extra_fields": {
                "user_id": user.id,
                "username": user.username,
                "role": user.role.value,
                "session_id": session_preview,
            }
        },
    )

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
    if settings.SSO_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inscription locale désactivée (SSO activé)",
        )
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
    
    # Vérifier la force du mot de passe
    if not validate_password_strength(user.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins 12 caractères, une majuscule, une minuscule, un chiffre et un caractère spécial."
        )

    # Créer un nouvel utilisateur
    hashed_password = get_password_hash(user.password)
    db_user = User(
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        hashed_password=hashed_password,
        auth_provider="local",
        external_id=None,
        role=UserRole[user.role],
        is_active=user.is_active if user.is_active is not None else True
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    audit_logger.info(
        "user_registered",
        extra={
            "extra_fields": {
                "user_id": db_user.id,
                "username": db_user.username,
                "role": db_user.role.value,
                "is_active": db_user.is_active,
            }
        },
    )
    
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
        if settings.SSO_ENABLED and db_user.auth_provider == "oidc":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe indisponible pour les comptes SSO",
            )
        if not validate_password_strength(user_update.password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le mot de passe doit contenir au moins 12 caractères, une majuscule, une minuscule, un chiffre et un caractère spécial."
            )
        db_user.hashed_password = get_password_hash(user_update.password)
    
    if user_update.role is not None:
        db_user.role = UserRole[user_update.role]
        # Marque le rôle comme défini manuellement : le callback SSO
        # n'écrasera plus ce choix lors des prochaines connexions.
        db_user.role_override = True

    if user_update.is_active is not None:
        db_user.is_active = user_update.is_active
    
    db.commit()
    db.refresh(db_user)

    audit_logger.info(
        "user_updated",
        extra={
            "extra_fields": {
                "user_id": db_user.id,
                "username": db_user.username,
                "role": db_user.role.value,
                "is_active": db_user.is_active,
                "updated_by": "admin",
            }
        },
    )
    
    return db_user

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(is_admin)])
def delete_user(user_id: int, db: Session = Depends(get_db)):
    """
    Supprime un utilisateur (admins seulement).

    Avant la suppression en base :
    1. Invalide toutes les sessions Redis de l'utilisateur (ROB-2).
    2. Supprime le namespace Kubernetes de l'utilisateur (CRITIQUE-5).
    """
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur non trouvé"
        )

    # 1. Invalider toutes les sessions Redis
    sessions_deleted = delete_user_sessions(user_id)

    # 2. Nettoyer le namespace K8s (erreurs non bloquantes)
    try:
        from .deployment_service import deployment_service
        ns_result = deployment_service.cleanup_user_namespace(user_id)
    except Exception as exc:
        logger.warning(
            "user_namespace_cleanup_skipped",
            extra={"extra_fields": {"user_id": user_id, "error": str(exc)}},
        )
        ns_result = {"deleted": False, "error": str(exc)}

    db.delete(db_user)
    db.commit()

    audit_logger.info(
        "user_deleted",
        extra={
            "extra_fields": {
                "user_id": user_id,
                "username": db_user.username,
                "role": db_user.role.value,
                "sessions_revoked": sessions_deleted,
                "namespace_deleted": ns_result.get("deleted", False),
            }
        },
    )

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
        if settings.SSO_ENABLED and current_user.auth_provider == "oidc":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mot de passe indisponible pour les comptes SSO",
            )
        if not validate_password_strength(user_update.password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le mot de passe doit contenir au moins 12 caractères, une majuscule, une minuscule, un chiffre et un caractère spécial."
            )
        current_user.hashed_password = get_password_hash(user_update.password)
    
    db.commit()
    db.refresh(current_user)

    audit_logger.info(
        "user_self_update",
        extra={
            "extra_fields": {
                "user_id": current_user.id,
                "username": current_user.username,
                "fields": [
                    field
                    for field in [
                        "email" if user_update.email is not None else None,
                        "full_name" if user_update.full_name is not None else None,
                        "password" if user_update.password is not None else None,
                    ]
                    if field
                ],
            }
        },
    )
    
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
    
    if settings.SSO_ENABLED and current_user.auth_provider == "oidc":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mot de passe indisponible pour les comptes SSO",
        )
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
    
    # Vérifier la force du nouveau mot de passe
    if not validate_password_strength(new_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins 12 caractères, une majuscule, une minuscule, un chiffre et un caractère spécial."
        )
    
    # Mettre à jour le mot de passe
    current_user.hashed_password = get_password_hash(new_password)
    db.commit()
    db.refresh(current_user)

    audit_logger.info(
        "password_changed",
        extra={
            "extra_fields": {
                "user_id": current_user.id,
                "username": current_user.username,
                "self_service": True,
            }
        },
    )
    
    return current_user


# ============= QUOTA OVERRIDES (admin) — IMP-3 =============

from datetime import datetime as _dt
from typing import Optional as _Opt


@router.get("/users/{user_id}/quota-override", dependencies=[Depends(is_admin)])
def get_quota_override(user_id: int, db: Session = Depends(get_db)):
    """Récupère la dérogation de quota d'un utilisateur (admins seulement)."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")
    override = db.query(UserQuotaOverride).filter(UserQuotaOverride.user_id == user_id).first()
    if override is None:
        return {"user_id": user_id, "override": None}
    return {
        "user_id": user_id,
        "override": {
            "id": override.id,
            "max_apps": override.max_apps,
            "max_cpu_m": override.max_cpu_m,
            "max_mem_mi": override.max_mem_mi,
            "max_storage_gi": override.max_storage_gi,
            "expires_at": override.expires_at.isoformat() if override.expires_at else None,
            "created_at": override.created_at.isoformat() if override.created_at else None,
        },
    }


@router.put("/users/{user_id}/quota-override", dependencies=[Depends(is_admin)])
def set_quota_override(
    user_id: int,
    max_apps: _Opt[int] = None,
    max_cpu_m: _Opt[int] = None,
    max_mem_mi: _Opt[int] = None,
    max_storage_gi: _Opt[int] = None,
    expires_at: _Opt[str] = None,
    admin: SessionData = Depends(is_admin),
    db: Session = Depends(get_db),
):
    """Crée ou met à jour la dérogation de quota d'un utilisateur (admins seulement).

    Passe ``expires_at`` au format ISO 8601 pour une dérogation temporaire,
    ou omis pour une dérogation permanente.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")

    expires_dt: _Opt[_dt] = None
    if expires_at:
        try:
            expires_dt = _dt.fromisoformat(expires_at)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Format expires_at invalide (ISO 8601 attendu, ex: 2026-06-01T00:00:00)",
            )

    override = db.query(UserQuotaOverride).filter(UserQuotaOverride.user_id == user_id).first()
    if override is None:
        override = UserQuotaOverride(user_id=user_id, created_by=admin.user_id)
        db.add(override)

    override.max_apps = max_apps
    override.max_cpu_m = max_cpu_m
    override.max_mem_mi = max_mem_mi
    override.max_storage_gi = max_storage_gi
    override.expires_at = expires_dt
    db.commit()
    db.refresh(override)

    audit_logger.info(
        "quota_override_set",
        extra={
            "extra_fields": {
                "target_user_id": user_id,
                "admin_user_id": admin.user_id,
                "max_apps": max_apps,
                "max_cpu_m": max_cpu_m,
                "max_mem_mi": max_mem_mi,
                "expires_at": expires_at,
            }
        },
    )
    return {"message": "Dérogation de quota mise à jour", "user_id": user_id}


@router.delete("/users/{user_id}/quota-override", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(is_admin)])
def delete_quota_override(user_id: int, db: Session = Depends(get_db)):
    """Supprime la dérogation de quota d'un utilisateur (admins seulement)."""
    override = db.query(UserQuotaOverride).filter(UserQuotaOverride.user_id == user_id).first()
    if override:
        db.delete(override)
        db.commit()
    return None


# ============= IMPORT CSV UTILISATEURS (admin) — FEAT-3 =============

import csv
import io
from fastapi import UploadFile, File


@router.post("/users/import", dependencies=[Depends(is_admin)], status_code=status.HTTP_200_OK)
async def import_users_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Importe des utilisateurs depuis un fichier CSV (admins seulement).

    Format CSV attendu (avec en-tête) ::

        username,email,full_name,role,password

    Retourne un rapport ligne par ligne avec le statut de chaque import.
    """
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le fichier doit être au format CSV (.csv)",
        )

    content = await file.read()
    try:
        text_content = content.decode("utf-8-sig")  # gère le BOM UTF-8
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encodage du fichier invalide (UTF-8 attendu)",
        )

    results = []
    reader = csv.DictReader(io.StringIO(text_content))
    required_fields = {"username", "email", "role", "password"}

    if not reader.fieldnames or not required_fields.issubset(set(reader.fieldnames)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"En-têtes CSV invalides. Requis : {', '.join(sorted(required_fields))}",
        )

    for line_num, row in enumerate(reader, start=2):
        username = (row.get("username") or "").strip()
        email = (row.get("email") or "").strip()
        full_name = (row.get("full_name") or "").strip() or None
        role_raw = (row.get("role") or "student").strip().lower()
        password = (row.get("password") or "").strip()

        # Validation de base
        if not username or not email or not password:
            results.append({"line": line_num, "username": username, "status": "error", "detail": "Champs obligatoires manquants"})
            continue

        if role_raw not in ("student", "teacher", "admin"):
            results.append({"line": line_num, "username": username, "status": "error", "detail": f"Rôle invalide : {role_raw}"})
            continue

        if "@" not in email:
            results.append({"line": line_num, "username": username, "status": "error", "detail": "Email invalide"})
            continue

        if not validate_password_strength(password):
            results.append({"line": line_num, "username": username, "status": "error", "detail": "Mot de passe trop faible (12 car., maj., min., chiffre, spécial)"})
            continue

        if db.query(User).filter(User.username == username).first():
            results.append({"line": line_num, "username": username, "status": "skipped", "detail": "Nom d'utilisateur déjà utilisé"})
            continue

        if db.query(User).filter(User.email == email).first():
            results.append({"line": line_num, "username": username, "status": "skipped", "detail": "Email déjà utilisé"})
            continue

        try:
            new_user = User(
                username=username,
                email=email,
                full_name=full_name,
                hashed_password=get_password_hash(password),
                auth_provider="local",
                role=UserRole[role_raw],
                is_active=True,
            )
            db.add(new_user)
            db.commit()
            db.refresh(new_user)
            results.append({"line": line_num, "username": username, "status": "created", "user_id": new_user.id})
        except Exception as exc:
            db.rollback()
            results.append({"line": line_num, "username": username, "status": "error", "detail": str(exc)})

    created = sum(1 for r in results if r["status"] == "created")
    errors = sum(1 for r in results if r["status"] == "error")
    skipped = sum(1 for r in results if r["status"] == "skipped")

    audit_logger.info(
        "users_imported_csv",
        extra={"extra_fields": {"created": created, "errors": errors, "skipped": skipped}},
    )

    return {
        "summary": {"created": created, "errors": errors, "skipped": skipped, "total": len(results)},
        "results": results,
    }
