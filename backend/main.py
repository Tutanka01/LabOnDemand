"""
Application principale LabOnDemand
Principe KISS : configuration simple et routage centralisé
"""

import asyncio
import logging
import time
import uuid
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .logging_config import (
    setup_logging,
    set_request_id,
    reset_request_id,
    shorten_token,
)
from .database import SessionLocal
from .session import setup_session_handler, validate_cookie_settings
from .csrf import CSRFMiddleware
from .error_handlers import global_exception_handler
from . import (
    models,
)  # Importer les modèles pour enregistrer les tables dans Base.metadata
from .security import limiter
from .db_migrate import upgrade_schema
from .seed import seed_admin, seed_templates, seed_runtime_configs
from .rate_limit import rate_limit_exceeded_handler, validate_rate_limit_settings
from slowapi.errors import RateLimitExceeded

setup_logging()
logger = logging.getLogger("labondemand.main")
access_logger = logging.getLogger("labondemand.access")


def _request_user_log_context(request: Request) -> dict:
    """Return user metadata for logs without refreshing detached ORM instances."""
    user_id = getattr(request.state, "user_id", None)
    user_role = getattr(request.state, "user_role", None)
    if user_id is not None or user_role is not None:
        return {"user_id": user_id, "user_role": user_role}

    user = getattr(request.state, "user", None)
    if user is None:
        return {"user_id": None, "user_role": None}

    try:
        user_id = getattr(user, "id", None)
        role = getattr(user, "role", None)
        user_role = getattr(role, "value", None) or (str(role) if role else None)
    except Exception:
        user_id = None
        user_role = None

    return {"user_id": user_id, "user_role": user_role}

# Initialiser Kubernetes
settings.init_kubernetes()

# Créer l'application FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    debug=settings.DEBUG_MODE,
)

# Configuration du rate limiting (429 traduit avec en-tête Retry-After)
validate_rate_limit_settings()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


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
        user_context = _request_user_log_context(request)
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
                    "user_id": user_context["user_id"],
                    "user_role": user_context["user_role"],
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
    user_context = _request_user_log_context(request)
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
                "user_id": user_context["user_id"],
                "user_role": user_context["user_role"],
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

# Protection CSRF : en-tête X-Requested-With obligatoire + Origin/Referer de
# confiance sur toute requête mutante /api/ (voir backend/csrf.py).
# Enregistrée AVANT CORS, donc exécutée APRÈS lui (Starlette empile en sens
# inverse) : les refus 403 portent les en-têtes CORS des origines autorisées.
app.add_middleware(CSRFMiddleware)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Garde-fous des cookies de session : refuse de démarrer sur une configuration
# dangereuse (ex. COOKIE_DOMAIN englobant le domaine des labs étudiants).
validate_cookie_settings()

# Nettoyage périodique des sessions expirées
setup_session_handler(app)

def run_seeds() -> None:
    """Peuple les données par défaut (admin, templates, runtimes).

    Non fatal : chaque seed est idempotent, s'exécute dans sa propre session
    et un échec est journalisé en ERROR sans empêcher les suivants ni le
    démarrage. Le schéma étant à jour, l'application reste cohérente ; refuser
    de démarrer priverait les utilisateurs existants de service pour une
    donnée par défaut, qui sera retentée au prochain démarrage.
    """
    for seed in (seed_admin, seed_templates, seed_runtime_configs):
        with SessionLocal() as db:
            try:
                seed(db)
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "seed_failed",
                    extra={
                        "extra_fields": {
                            "action": "bootstrap",
                            "seed": seed.__name__,
                            "error": str(exc),
                        }
                    },
                )


@app.on_event("startup")
async def bootstrap() -> None:
    """Met le schéma à jour (Alembic), peuple les données par défaut
    et démarre la tâche de fond de nettoyage des labs expirés.

    Un échec de migration est FATAL : l'exception interrompt le démarrage
    (uvicorn s'arrête avec un code non nul) plutôt que de servir des requêtes
    sur un schéma incomplet ou incertain.
    """
    try:
        # Synchrone et exécuté avant toute requête : bloquer la boucle est voulu.
        upgrade_schema()
    except Exception as exc:
        logger.critical(
            "schema_upgrade_failed",
            exc_info=True,
            extra={
                "extra_fields": {
                    "action": "bootstrap",
                    "error": str(exc),
                    "hint": "Démarrage interrompu. Corrigez la base (voir "
                    "documentation/database-migrations.md) puis relancez.",
                }
            },
        )
        raise

    run_seeds()

    # Démarrer la tâche de nettoyage des labs expirés en arrière-plan
    try:
        from .tasks.cleanup import run_cleanup_loop

        asyncio.create_task(run_cleanup_loop())
        logger.info("cleanup_task_scheduled")
    except Exception as exc:
        logger.warning(
            "cleanup_task_start_failed", extra={"extra_fields": {"error": str(exc)}}
        )


# ============= INCLUSION DES ROUTEURS =============

from .auth_router import router as auth_router
from .routers import (
    deployments_router,
    files_router,
    storage_router,
    terminal_router,
    templates_router,
    runtime_configs_router,
    monitoring_router,
    quotas_router,
    audit_router,
    classrooms_router,
    teacher_router,
    student_router,
)

app.include_router(auth_router)
app.include_router(deployments_router)
app.include_router(files_router)
app.include_router(storage_router)
app.include_router(terminal_router)
app.include_router(templates_router)
app.include_router(runtime_configs_router)
app.include_router(monitoring_router)
app.include_router(quotas_router)
app.include_router(audit_router)
app.include_router(classrooms_router)
app.include_router(teacher_router)
app.include_router(student_router)

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
        "debug": settings.DEBUG_MODE,
    }


@app.on_event("startup")
async def configure_threadpool() -> None:
    """Dimensionne le pool de threads AnyIO (voir API_THREADPOOL_SIZE)."""
    size = settings.configure_threadpool()
    logger.info("threadpool_configured", extra={"extra_fields": {"size": size}})


@app.get("/api/v1/health")
async def health_check() -> dict:
    """Vérification de santé : DB, Redis et Kubernetes.

    Sondes en parallèle hors de la boucle, avec un délai court
    (HEALTH_CHECK_TIMEOUT_SECONDS) ; toujours 200, status "healthy" ou
    "degraded" (voir backend/health.py).
    """
    from .health import run_health_checks

    return await run_health_checks()


# ============= POINT D'ENTRÉE =============


def main():
    """Point d'entrée pour lancer l'API"""
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=settings.API_PORT,
        reload=settings.DEBUG_MODE,
    )


if __name__ == "__main__":
    main()
