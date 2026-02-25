"""
Application principale LabOnDemand
Principe KISS : configuration simple et routage centralisé
"""
import logging
import os
import time
import uuid
import uvicorn
from datetime import datetime
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from .config import settings
from .logging_config import (
    setup_logging,
    set_request_id,
    reset_request_id,
    shorten_token,
)
from .database import Base, engine, get_db, SessionLocal
from .session import setup_session_handler
from .error_handlers import global_exception_handler
from . import models  # Importer les modèles pour enregistrer les tables avant create_all
from .security import limiter
from .migrations import run_migrations
from .seed import seed_admin, seed_templates, seed_runtime_configs
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

# When running in debug inside a Docker volume on Windows, watchfiles can fail
# with "Invalid argument" unless it falls back to polling. Force this behaviour
# before we initialise logging and start uvicorn.
if settings.DEBUG_MODE and os.getenv("WATCHFILES_FORCE_POLLING", "").lower() not in {"true", "1", "yes"}:
    os.environ["WATCHFILES_FORCE_POLLING"] = "true"

setup_logging()
logger = logging.getLogger("labondemand.main")
access_logger = logging.getLogger("labondemand.access")

# Initialiser Kubernetes
settings.init_kubernetes()

# Créer l'application FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    debug=settings.DEBUG_MODE,
)

# Configuration du rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every incoming HTTP request with structured metadata."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = set_request_id(request_id)
    start_time = time.perf_counter()
    client = request.client or None
    client_host = getattr(client, "host", None)
    client_port = getattr(client, "port", None)

    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
        user = getattr(request.state, "user", None)
        session_data = getattr(request.state, "session", None)
        session_id_preview = shorten_token(getattr(request.state, "session_id", None))
        status_code = getattr(exc, "status_code", 500)

        access_logger.error(
            "request_failed",
            extra={
                "extra_fields": {
                    "method": request.method,
                    "path": request.url.path,
                    "query": request.url.query,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": client_host,
                    "client_port": client_port,
                    "user_id": getattr(user, "id", None),
                    "user_role": getattr(getattr(user, "role", None), "value", None),
                    "session_role": getattr(session_data, "role", None),
                    "session_id": session_id_preview,
                    "user_agent": request.headers.get("user-agent"),
                    "error": str(exc),
                    "success": False,
                }
            },
        )
        reset_request_id(token)
        raise

    duration_ms = round((time.perf_counter() - start_time) * 1000, 3)
    user = getattr(request.state, "user", None)
    session_data = getattr(request.state, "session", None)
    session_id_preview = shorten_token(getattr(request.state, "session_id", None))

    access_logger.info(
        "request_completed",
        extra={
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "client_ip": client_host,
                "client_port": client_port,
                "user_id": getattr(user, "id", None),
                "user_role": getattr(getattr(user, "role", None), "value", None),
                "session_role": getattr(session_data, "role", None),
                "session_id": session_id_preview,
                "user_agent": request.headers.get("user-agent"),
                "content_length": response.headers.get("content-length"),
                "success": True,
            }
        },
    )

    response.headers["X-Request-ID"] = request_id
    reset_request_id(token)
    return response

# Ajouter le gestionnaire d'erreurs global
app.add_exception_handler(Exception, global_exception_handler)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration du middleware de session
setup_session_handler(app)

# Création des tables de base de données (nécessite l'import de models ci-dessus)
Base.metadata.create_all(bind=engine)

@app.on_event("startup")
def bootstrap():
    """Initialise la base de données, applique les migrations et peuple les données par défaut."""
    try:
        with SessionLocal() as db:
            Base.metadata.create_all(bind=engine)
            run_migrations(db)
            seed_admin(db)
            seed_templates(db)
            seed_runtime_configs(db)
    except Exception as exc:
        logger.exception(
            "Bootstrap failed",
            extra={"extra_fields": {"action": "bootstrap", "error": str(exc)}}
        )

# ============= INCLUSION DES ROUTEURS =============

from .auth_router import router as auth_router
from .routers import (
    deployments_router,
    storage_router,
    terminal_router,
    templates_router,
    runtime_configs_router,
    monitoring_router,
    quotas_router,
)

app.include_router(auth_router)
app.include_router(deployments_router)
app.include_router(storage_router)
app.include_router(terminal_router)
app.include_router(templates_router)
app.include_router(runtime_configs_router)
app.include_router(monitoring_router)
app.include_router(quotas_router)

# ============= ENDPOINTS DE BASE =============

@app.get("/")
async def read_root():
    """Endpoint racine - Message de bienvenue"""
    return {"message": "Bienvenue sur l'API LabOnDemand !"}

@app.get("/api/v1/status")
async def get_status():
    """Status de l'API"""
    return {
        "status": "API en cours d'exécution", 
        "version": app.version,
        "debug": settings.DEBUG_MODE
    }

@app.get("/api/v1/health")
async def health_check(db: Session = Depends(get_db)):
    """Vérification de santé de l'API"""
    try:
        # Test de connexion DB
        db.execute(text("SELECT 1"))
        
        # Test des tables
        from .models import User
        user_count = db.query(User).count()
        
        return {
            "status": "healthy",
            "database": "connected",
            "users": user_count,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "database": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ============= ENDPOINT DE DIAGNOSTIC =============

if settings.DEBUG_MODE:
    @app.post("/api/v1/diagnostic/test-auth")
    async def test_auth(request: Request, db: Session = Depends(get_db)):
        """
        Endpoint de diagnostic pour tester l'authentification.
        Disponible uniquement en mode DEBUG.
        """
        try:
            body = await request.json()
            username = body.get("username")
            password = body.get("password")

            if not username or not password:
                return {
                    "success": False,
                    "message": "Le nom d'utilisateur et le mot de passe sont requis",
                    "details": None,
                }

            from .security import authenticate_user
            user = authenticate_user(db, username, password)

            if user:
                return {
                    "success": True,
                    "message": "Authentification réussie",
                    "details": {
                        "user_id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "role": user.role.value,
                        "is_active": user.is_active,
                    },
                }
            else:
                return {
                    "success": False,
                    "message": "Échec de l'authentification",
                    "details": None,
                }
        except Exception as e:
            import traceback
            return {
                "success": False,
                "message": f"Erreur lors de l'authentification: {str(e)}",
                "details": traceback.format_exc(),
            }

# ============= POINT D'ENTRÉE =============

def main():
    """Point d'entrée pour lancer l'API"""
    uvicorn.run(
        "backend.main:app", 
        host="0.0.0.0", 
        port=settings.API_PORT, 
        reload=settings.DEBUG_MODE
    )

if __name__ == "__main__":
    main()
