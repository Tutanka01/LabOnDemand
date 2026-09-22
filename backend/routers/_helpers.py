"""Helpers partagés entre les sous-routeurs Kubernetes."""
import logging
from fastapi import HTTPException
from kubernetes import client
import urllib3

logger = logging.getLogger("labondemand.k8s")
audit_logger = logging.getLogger("labondemand.audit")


def raise_k8s_http(e: Exception):
    """Mappe les erreurs Kubernetes en HTTPException propres."""
    if isinstance(e, HTTPException):
        raise e
    try:
        if isinstance(e, client.exceptions.ApiException):
            status = getattr(e, "status", 0) or 0
            reason = getattr(e, "reason", None) or str(e)
            if not 100 <= status <= 599:
                # `kubernetes.stream` enveloppe toute erreur réseau (flux exec
                # coupé sans frame CLOSE, handshake websocket refusé…) en
                # ApiException(status=0) : c'est un échec de transport, jamais
                # une erreur applicative.
                logger.warning(
                    "k8s_transport_error",
                    extra={"extra_fields": {"reason": reason}},
                )
                raise HTTPException(
                    status_code=502,
                    detail="Connexion au pod interrompue. Réessayez dans un instant.",
                )
            if status == 503:
                reason = "Kubernetes apiserver indisponible (503: Service Unavailable)"
            raise HTTPException(status_code=status, detail=reason)

        if isinstance(e, (urllib3.exceptions.MaxRetryError, urllib3.exceptions.NewConnectionError)):
            raise HTTPException(status_code=503, detail="Impossible de joindre l'API Kubernetes (connexion refusée)")

        if isinstance(e, (TimeoutError, ConnectionError, OSError)):
            raise HTTPException(status_code=503, detail="Kubernetes indisponible (erreur de connexion)")

        logger.warning(
            "k8s_unexpected_error",
            extra={"extra_fields": {"error": f"{type(e).__name__}: {e}"}},
        )
        raise HTTPException(status_code=500, detail=f"Erreur Kubernetes: {str(e)}")
    except HTTPException:
        raise
