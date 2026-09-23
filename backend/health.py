"""Vérification de santé de l'API (``GET /api/v1/health``).

Chaque dépendance (base de données, Redis, Kubernetes) est sondée dans un
thread, en parallèle, avec un délai court (``HEALTH_CHECK_TIMEOUT_SECONDS``) :
une dépendance lente ou figée ne bloque ni la boucle d'événements ni la
réponse, qui reste 200 avec ``status="degraded"``.
"""
from __future__ import annotations

import asyncio
import functools
import logging
import threading
import weakref
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import anyio
import redis
from kubernetes import client as k8s_client
from sqlalchemy import text

from . import database
from .config import settings

logger = logging.getLogger("labondemand.health")

# Threads réservés aux sondes, par boucle d'événements. Une sonde abandonnée
# après son délai (dépendance figée) finit dans son thread : ce plafond borne
# les threads qu'elles peuvent accumuler sans toucher au pool des endpoints.
_MAX_PROBE_THREADS = 6
_probe_limiters: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, anyio.CapacityLimiter]" = (
    weakref.WeakKeyDictionary()
)

_redis_client: Optional[redis.Redis] = None
_redis_client_lock = threading.Lock()


def _probe_limiter() -> anyio.CapacityLimiter:
    loop = asyncio.get_running_loop()
    limiter = _probe_limiters.get(loop)
    if limiter is None:
        limiter = anyio.CapacityLimiter(_MAX_PROBE_THREADS)
        _probe_limiters[loop] = limiter
    return limiter


def _health_redis_client(timeout: float) -> redis.Redis:
    """Client Redis dédié, avec délais de connexion/lecture courts (le client
    du store de sessions n'en a pas)."""
    global _redis_client
    with _redis_client_lock:
        if _redis_client is None:
            _redis_client = redis.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=timeout,
                socket_timeout=timeout,
            )
        return _redis_client


def _check_database(timeout: int) -> None:
    with database.SessionLocal() as db:
        db.execute(text("SELECT 1"))


def _check_redis(timeout: int) -> None:
    _health_redis_client(timeout).ping()


def _check_kubernetes(timeout: int) -> None:
    # Délai entier : le client Kubernetes ignore un _request_timeout float.
    k8s_client.CoreV1Api().list_namespace(limit=1, _request_timeout=timeout)


_CHECKS: Dict[str, Callable[[int], None]] = {
    "db": _check_database,
    "redis": _check_redis,
    "k8s": _check_kubernetes,
}


async def _probe(
    component: str,
    check: Callable[[int], None],
    timeout: int,
    limiter: anyio.CapacityLimiter,
) -> str:
    """Exécute une sonde dans un thread ; renvoie "ok" ou "error: ..."."""
    try:
        with anyio.fail_after(timeout):
            await anyio.to_thread.run_sync(
                functools.partial(check, timeout),
                limiter=limiter,
                abandon_on_cancel=True,
            )
    except TimeoutError:
        logger.warning(
            "health_check_timeout",
            extra={"extra_fields": {"component": component, "timeout_seconds": timeout}},
        )
        return f"error: timeout after {timeout}s"
    except Exception as exc:
        logger.warning(
            "health_check_failed",
            extra={"extra_fields": {"component": component, "error": str(exc)}},
        )
        return f"error: {exc}"
    return "ok"


async def run_health_checks() -> Dict[str, Any]:
    """Sonde DB, Redis et Kubernetes en parallèle, hors de la boucle.

    Forme de réponse inchangée : ``status`` ("healthy" ou "degraded"),
    ``timestamp``, puis "ok" ou "error: ..." pour ``db``, ``redis`` et ``k8s``.
    """
    timeout = settings.HEALTH_CHECK_TIMEOUT_SECONDS
    limiter = _probe_limiter()
    result: Dict[str, Any] = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "db": "ok",
        "redis": "ok",
        "k8s": "ok",
    }

    async def _run(component: str, check: Callable[[int], None]) -> None:
        result[component] = await _probe(component, check, timeout, limiter)

    async with anyio.create_task_group() as task_group:
        for component, check in _CHECKS.items():
            task_group.start_soon(_run, component, check)

    healthy = all(result[component] == "ok" for component in _CHECKS)
    result["status"] = "healthy" if healthy else "degraded"
    return result
