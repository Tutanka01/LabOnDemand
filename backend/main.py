"""LabOnDemand API entry point: app factory, middleware, routers and lifecycle."""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Callable, Dict

import urllib3
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from kubernetes.config.config_exception import ConfigException
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from . import database
from . import models  # noqa: F401  (registers the ORM tables on Base.metadata)
from .config import settings
from .error_handlers import global_exception_handler, k8s_unavailable_handler
from .logging_config import (
    reset_request_id,
    set_request_id,
    setup_logging,
    shorten_token,
)
from .migrations import run_migrations
from .security import client_ip, limiter
from .seed import seed_admin, seed_runtime_configs, seed_templates

setup_logging()
logger = logging.getLogger("labondemand.main")
access_logger = logging.getLogger("labondemand.access")

# Upper bound for each dependency probe of GET /api/v1/health.
HEALTH_PROBE_TIMEOUT_SECONDS = 3.0


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
    except Exception:  # logging must never break a request
        user_id = None
        user_role = None

    return {"user_id": user_id, "user_role": user_role}


def _bootstrap_database() -> None:
    """Create tables, apply migrations and seed defaults (blocking; run in a thread)."""
    database.Base.metadata.create_all(bind=database.engine)
    with database.SessionLocal() as db:
        run_migrations(db)
        seed_admin(db)
        seed_templates(db)
        seed_runtime_configs(db)

        from . import grader_service

        # Single process: grading runs still active belong to a previous one.
        grader_service.reconcile_orphaned_runs(db)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bootstrap the database, run background loops, stop them cleanly on shutdown."""
    try:
        await asyncio.to_thread(_bootstrap_database)
    except Exception:
        # The API still starts so /health can report the problem.
        logger.exception("bootstrap_failed", extra={"extra_fields": {"action": "bootstrap"}})

    from .tasks.cleanup import run_cleanup_loop

    background = [asyncio.create_task(run_cleanup_loop(), name="lab-cleanup-loop")]
    logger.info("cleanup_task_scheduled")
    try:
        yield
    finally:
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)

        from . import grader_service

        grader_service.shutdown()
        logger.info("background_tasks_stopped")


# Initialise the Kubernetes client configuration (kubeconfig or in-cluster).
settings.init_kubernetes()

app = FastAPI(
    title=settings.API_TITLE,
    description=settings.API_DESCRIPTION,
    version=settings.API_VERSION,
    debug=settings.DEBUG_MODE,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every incoming HTTP request with structured metadata."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = set_request_id(request_id)
    start_time = time.perf_counter()
    client_host = client_ip(request)
    client_port = getattr(request.client, "port", None)

    def _fields(status_code: int) -> dict:
        user_context = _request_user_log_context(request)
        session_data = getattr(request.state, "session", None)
        return {
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "status_code": status_code,
            "duration_ms": round((time.perf_counter() - start_time) * 1000, 3),
            "client_ip": client_host,
            "client_port": client_port,
            "user_id": user_context["user_id"],
            "user_role": user_context["user_role"],
            "session_role": getattr(session_data, "role", None),
            "session_id": shorten_token(getattr(request.state, "session_id", None)),
            "user_agent": request.headers.get("user-agent"),
        }

    try:
        response = await call_next(request)
    except Exception as exc:
        fields = _fields(getattr(exc, "status_code", 500))
        fields.update({"error": str(exc), "success": False})
        access_logger.error("request_failed", extra={"extra_fields": fields})
        reset_request_id(token)
        raise

    fields = _fields(response.status_code)
    fields.update({"content_length": response.headers.get("content-length"), "success": True})
    access_logger.info("request_completed", extra={"extra_fields": fields})

    response.headers["X-Request-ID"] = request_id
    reset_request_id(token)
    return response


app.add_exception_handler(Exception, global_exception_handler)
# Kubernetes transport failures that escaped a route become 503, not 500.
app.add_exception_handler(urllib3.exceptions.HTTPError, k8s_unavailable_handler)
app.add_exception_handler(ConfigException, k8s_unavailable_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============= ROUTERS =============

from .auth_router import router as auth_router  # noqa: E402
from .routers import (  # noqa: E402
    audit_router,
    classrooms_router,
    deployments_router,
    files_router,
    monitoring_router,
    quotas_router,
    runtime_configs_router,
    storage_router,
    student_router,
    teacher_router,
    templates_router,
    terminal_router,
)
from .routers.k8s_monitoring import k8s_reachable  # noqa: E402

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

# ============= BASE ENDPOINTS =============


@app.get("/")
async def read_root() -> Dict[str, str]:
    """Welcome message."""
    return {"message": "Bienvenue sur l'API LabOnDemand !"}


@app.get("/api/v1/status")
async def get_status() -> Dict[str, object]:
    """API status."""
    return {
        "status": "API en cours d'exécution",
        "version": app.version,
        "debug": settings.DEBUG_MODE,
    }


def _probe_db() -> bool:
    with database.SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return True


def _probe_redis() -> bool:
    from .session_store import session_store

    return bool(session_store._r.ping())


async def _run_probe(name: str, probe: Callable[[], bool]) -> str:
    """Run a blocking probe in a thread, bounded in time; never raises."""
    try:
        ok = await asyncio.wait_for(asyncio.to_thread(probe), HEALTH_PROBE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("health_probe_timeout", extra={"extra_fields": {"component": name}})
        return "error"
    except Exception as exc:
        logger.warning(
            "health_probe_failed",
            extra={"extra_fields": {"component": name, "error": f"{type(exc).__name__}: {exc}"}},
        )
        return "error"
    return "ok" if ok else "error"


@app.get("/api/v1/health")
async def health_check() -> Dict[str, str]:
    """Health of the API dependencies: database, Redis and Kubernetes.

    Unauthenticated: each component reports only ``"ok"`` or ``"error"``; the
    failure details go to the logs. Probes run concurrently, off the event
    loop, each bounded by ``HEALTH_PROBE_TIMEOUT_SECONDS``.
    """
    db_status, redis_status, k8s_status = await asyncio.gather(
        _run_probe("db", _probe_db),
        _run_probe("redis", _probe_redis),
        _run_probe("k8s", k8s_reachable),
    )
    healthy = db_status == redis_status == k8s_status == "ok"
    return {
        "status": "healthy" if healthy else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db": db_status,
        "redis": redis_status,
        "k8s": k8s_status,
    }


def main() -> None:
    """Run the API with uvicorn."""
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=settings.API_PORT,
        reload=settings.DEBUG_MODE,
    )


if __name__ == "__main__":
    main()
