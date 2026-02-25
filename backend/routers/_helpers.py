"""Helpers partagés entre les sous-routeurs Kubernetes."""
import logging
from fastapi import HTTPException
from kubernetes import client
import urllib3

logger = logging.getLogger("labondemand.k8s")
audit_logger = logging.getLogger("labondemand.audit")


def raise_k8s_http(e: Exception):
    """Mappe les erreurs Kubernetes en HTTPException propres."""
    try:
        if isinstance(e, client.exceptions.ApiException):
            status = getattr(e, "status", 500) or 500
            reason = getattr(e, "reason", None) or str(e)
            if status == 503:
                reason = "Kubernetes apiserver indisponible (503: Service Unavailable)"
            raise HTTPException(status_code=status, detail=reason)

        if isinstance(e, (urllib3.exceptions.MaxRetryError, urllib3.exceptions.NewConnectionError)):
            raise HTTPException(status_code=503, detail="Impossible de joindre l'API Kubernetes (connexion refusée)")

        if isinstance(e, (TimeoutError, ConnectionError, OSError)):
            raise HTTPException(status_code=503, detail="Kubernetes indisponible (erreur de connexion)")

        raise HTTPException(status_code=500, detail=f"Erreur Kubernetes: {str(e)}")
    except HTTPException:
        raise
