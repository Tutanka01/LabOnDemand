"""Application-wide exception handlers.

- ``global_exception_handler`` turns any unhandled error into a JSON 500 without
  leaking internals (the traceback goes to the logs).
- ``k8s_unavailable_handler`` turns Kubernetes transport failures (cluster
  unreachable, timeouts, missing kubeconfig) that escaped a route into a 503,
  so a cluster outage is never reported as an internal bug nor as an empty
  success.
"""

import logging

import urllib3
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from kubernetes.config.config_exception import ConfigException
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("labondemand.error")

K8S_UNAVAILABLE_DETAIL = "Kubernetes est indisponible pour le moment. Réessayez dans un instant."
DB_UNAVAILABLE_DETAIL = "La base de données est indisponible pour le moment. Réessayez dans un instant."

# Transport-level failures: the cluster could not be reached or answered too
# late. urllib3.exceptions.HTTPError covers MaxRetryError, NewConnectionError,
# connect/read timeouts, protocol and SSL errors. Defined here (no backend
# imports) so services can use it without importing the routers package.
K8S_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
    urllib3.exceptions.HTTPError,
    ConfigException,
    TimeoutError,
    ConnectionError,
)


def k8s_unavailable() -> HTTPException:
    """HTTP 503 used whenever the Kubernetes API cannot be reached."""
    return HTTPException(status_code=503, detail=K8S_UNAVAILABLE_DETAIL)


def db_unavailable() -> HTTPException:
    """HTTP 503 used when a lookup the request depends on cannot read the DB."""
    return HTTPException(status_code=503, detail=DB_UNAVAILABLE_DETAIL)


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: always answer valid JSON, never expose exception text."""
    logger.exception(
        "unhandled_exception",
        exc_info=exc,
        extra={
            "extra_fields": {
                "path": request.url.path,
                "method": request.method,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )

    if isinstance(exc, SQLAlchemyError):
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "database_error",
                "message": "Erreur de base de données",
                "details": None,
            },
        )

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "internal_error",
            "message": "Erreur interne du serveur",
            "details": "Consultez les logs pour plus de détails",
        },
    )


async def k8s_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map an uncaught Kubernetes transport error to HTTP 503."""
    logger.warning(
        "k8s_unavailable",
        extra={
            "extra_fields": {
                "path": request.url.path,
                "method": request.method,
                "request_id": getattr(request.state, "request_id", None),
                "error": f"{type(exc).__name__}: {exc}",
            }
        },
    )
    return JSONResponse(status_code=503, content={"detail": K8S_UNAVAILABLE_DETAIL})
