"""
Gestionnaire d'erreurs global pour l'API
Principe KISS : gestion d'erreurs simple et robuste
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
import logging

logger = logging.getLogger("labondemand.error")

async def global_exception_handler(request: Request, exc: Exception):
    """
    Gestionnaire global d'exceptions qui retourne toujours du JSON valide
    """
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "unhandled_exception",
        extra={
            "extra_fields": {
                "path": request.url.path,
                "method": request.method,
                "request_id": request_id,
            }
        },
    )
    
    # Erreurs de base de données
    if isinstance(exc, SQLAlchemyError):
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "database_error",
                "message": "Erreur de base de données. Vérifiez que la base est initialisée.",
                "details": "La table ou la base de données n'existe pas."
            }
        )
    
    # Erreurs HTTP FastAPI
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": "http_error",
                "message": exc.detail,
                "details": None
            }
        )
    
    # Erreurs de validation
    if isinstance(exc, RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "validation_error",
                "message": "Données invalides",
                "details": str(exc)
            }
        )
    
    # Toutes les autres erreurs
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "internal_error",
            "message": "Erreur interne du serveur",
            "details": "Consultez les logs pour plus de détails"
        }
    )
