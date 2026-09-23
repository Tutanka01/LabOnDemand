"""Vérification de santé de l'API (``GET /api/v1/health``).

Chaque dépendance (base de données, Redis, Kubernetes) est sondée dans un
thread, en parallèle, avec un délai court (``HEALTH_CHECK_TIMEOUT_SECONDS``) :
une dépendance lente ou figée ne bloque ni la boucle d'événements ni la
réponse, qui reste 200 avec ``status="degraded"``. Les threads que des sondes
abandonnées peuvent immobiliser sont plafonnés (``_MAX_PROBE_THREADS``) : au-delà,
la sonde répond ``error: busy`` sans lancer de nouvel appel.
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

# Threads réservés aux sondes. Le limiteur AnyIO (un par boucle d'événements)
# les tient à l'écart du pool des endpoints, mais rend son jeton dès qu'une
# sonde est abandonnée après son délai alors que son thread continue (dépendance
# figée). Le sémaphore, pris et rendu dans le thread lui-même, borne donc les
# sondes réellement en cours : des appels répétés à /health pendant une panne
# ne peuvent pas accumuler de threads.
_MAX_PROBE_THREADS = 6
_probe_limiters: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, anyio.CapacityLimiter]" = (
    weakref.WeakKeyDictionary()
)
_probe_slots = threading.BoundedSemaphore(_MAX_PROBE_THREADS)


class ProbeBusyError(RuntimeError):
    """Toutes les places de sonde sont tenues par des sondes encore en cours."""

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
    # Délai entier : kubernetes 32.x ignore un _request_timeout float
    # (36.x l'accepte) ; un int est pris en compte par toutes les versions.
    k8s_client.CoreV1Api().list_namespace(limit=1, _request_timeout=timeout)


def _run_bounded(check: Callable[[int], None], timeout: int) -> None:
    """Exécute la sonde si une place est libre (thread de travail)."""
    if not _probe_slots.acquire(blocking=False):
        raise ProbeBusyError()
    try:
        check(timeout)
    finally:
        _probe_slots.release()


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
                functools.partial(_run_bounded, check, timeout),
                limiter=limiter,
                abandon_on_cancel=True,
            )
    except ProbeBusyError:
        logger.warning(
            "health_check_busy",
            extra={"extra_fields": {"component": component, "max_probe_threads": _MAX_PROBE_THREADS}},
        )
        return "error: busy (previous probes still running)"
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
