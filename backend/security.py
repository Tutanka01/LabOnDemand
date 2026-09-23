import logging
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
    # Limiteur de débit : défini dans rate_limit.py, réexporté ici pour les
    # imports existants (``from .security import limiter``).
    from .rate_limit import limiter  # noqa: F401
except ImportError:
    # Pour l'utilisation comme script direct
    from database import get_db
    from models import User, UserRole
    from schemas import SessionData
    from session_store import session_store
    from logging_config import shorten_token
    from rate_limit import limiter  # noqa: F401

# Hachage des mots de passe : bcrypt direct, compatible avec les hachages
# produits par passlib (voir password_hashing.py)
try:
    from .password_hashing import hash_password, verify_password as _verify_password_hash
except ImportError:
    from password_hashing import hash_password, verify_password as _verify_password_hash

# Clé API pour la sécurité basée sur les cookies
cookie_security = APIKeyCookie(name="session_id", auto_error=False)

logger = logging.getLogger("labondemand.security")

# Vérification des mots de passe (un hachage vide ou invalide renvoie False)
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _verify_password_hash(plain_password, hashed_password)

# Génération de hachage de mot de passe (bcrypt $2b$, coût 12)
def get_password_hash(password: str) -> str:
    return hash_password(password)

# Validation de la force du mot de passe
def validate_password_strength(password: str) -> bool:
    """
    Vérifie que le mot de passe respecte les critères de sécurité :
    - Au moins 12 caractères
    - Au moins une majuscule
    - Au moins une minuscule
    - Au moins un chiffre
    - Au moins un caractère spécial
    """
    if len(password) < 12:
        return False
    if not any(c.isupper() for c in password):
        return False
    if not any(c.islower() for c in password):
        return False
    if not any(c.isdigit() for c in password):
        return False
    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?/~`" for c in password):
        return False
    return True

# Gestion des sessions
def create_session(user_id: int, username: str, role: UserRole) -> str:
    """Create a new server-side session and return the opaque session token.

    Generates a 32-byte cryptographically random token, stores the session
    payload (user_id, username, role) in the configured session store (Redis
    when available, in-memory fallback otherwise), and returns the token to
    be set as the ``session_id`` cookie.

    Args:
        user_id:  Database ID of the authenticated user.
        username: Login name (used for logging).
        role:     RBAC role of the user (student / teacher / admin).

    Returns:
        URL-safe base64 session token (opaque to the client).
    """
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
    """FastAPI dependency: resolve the ``session_id`` cookie to a SessionData object.

    Reads the ``session_id`` cookie (via :data:`cookie_security`), looks up
    the session in the session store, and returns the deserialized
    :class:`~schemas.SessionData`.  Raises ``401`` if the cookie is absent
    or the session is unknown / expired.  On success the raw session ID and
    the parsed object are attached to ``request.state`` for downstream use.

    Raises:
        HTTPException 401: Missing, invalid or expired session.
    """
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


def delete_user_sessions(user_id: int) -> int:
    """Invalide toutes les sessions Redis appartenant à ``user_id``.

    Scanne les clés du namespace de session Redis, désérialise chaque entrée
    et supprime celles dont ``user_id`` correspond.  Retourne le nombre de
    sessions supprimées.

    Cette fonction doit être appelée avant la suppression d'un utilisateur
    (``DELETE /users/{id}``) pour éviter les sessions orphelines.
    """
    deleted_count = 0
    try:
        # Accès direct au client Redis via session_store
        r = session_store._r
        ns = session_store.ns
        pattern = f"{ns}*"
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=pattern, count=200)
            for key in keys:
                try:
                    raw = r.get(key)
                    if not raw:
                        continue
                    import json
                    data = json.loads(raw)
                    if data.get("user_id") == user_id:
                        r.delete(key)
                        deleted_count += 1
                except Exception:
                    continue
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning(
            "delete_user_sessions_error",
            extra={"extra_fields": {"user_id": user_id, "error": str(exc)}},
        )
    logger.info(
        "user_sessions_deleted",
        extra={"extra_fields": {"user_id": user_id, "count": deleted_count}},
    )
    return deleted_count

# Empreinte bcrypt constante d'un mot de passe aléatoire jamais conservé :
# aucune saisie ne peut la valider. Coût 12, identique aux empreintes réelles
# (vérifié par test_rate_limiting.py) : à régénérer si ce coût change.
_DUMMY_PASSWORD_HASH = "$2b$12$Nhlh8YP12962NELT6UCtQOCvPX6OI9d.JT6xAOvMSOsEWqtgWpmFC"


def _equalize_password_check_timing(password: str) -> None:
    """Consomme le coût d'une vérification bcrypt sans résultat exploitable.

    Sans cela, un nom inconnu (ou un compte SSO) répond sans calcul bcrypt,
    donc nettement plus vite qu'un mauvais mot de passe : la durée de la
    réponse révélerait quels comptes locaux existent (énumération).
    """
    verify_password(password, _DUMMY_PASSWORD_HASH)


# Authentification utilisateur
def authenticate_user(db: Session, username: str, password: str):
    logger.debug(
        "authenticate_user_attempt",
        extra={"extra_fields": {"username": username}},
    )

    user = db.query(User).filter(User.username == username).first()
    if not user:
        _equalize_password_check_timing(password)
        logger.warning(
            "authenticate_user_failed",
            extra={"extra_fields": {"username": username, "reason": "user_not_found"}},
        )
        return False
    
    if getattr(user, "auth_provider", "local") != "local":
        _equalize_password_check_timing(password)
        logger.warning(
            "authenticate_user_failed",
            extra={"extra_fields": {"username": username, "reason": "non_local_auth"}},
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
    """FastAPI dependency: return the authenticated :class:`~models.User` ORM object.

    Chains on :func:`get_session_data` to validate the session, then fetches
    the corresponding :class:`~models.User` row from the database.  Raises
    ``401`` if the user no longer exists or has been deactivated.

    The resolved user is also stored on ``request.state.user`` for use in
    middleware or background tasks.

    Raises:
        HTTPException 401: User not found in DB or account inactive.
    """
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
    request.state.user_id = user.id
    request.state.user_role = (
        user.role.value if hasattr(user.role, "value") else str(user.role)
    )
    return user
