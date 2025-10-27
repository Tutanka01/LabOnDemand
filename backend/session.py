from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
import logging
import os

# Récupération des paramètres de configuration
SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "True").lower() in ["true", "1", "yes"]
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)
SESSION_SAMESITE = os.getenv("SESSION_SAMESITE", "Lax")  # Lax ou Strict

logger = logging.getLogger("labondemand.session")

# Exécution périodique du nettoyage des sessions expirées
def setup_session_handler(app: FastAPI):
    """
    Configure les middleware pour la gestion des sessions côté serveur
    et planifie le nettoyage périodique des sessions expirées
    """
    from .session_store import session_store
    
    # Planifier le nettoyage des sessions
    @app.on_event("startup")
    async def schedule_session_cleanup():
        import asyncio
        
        async def cleanup_expired_sessions():
            while True:
                # Nettoyage toutes les heures
                await asyncio.sleep(3600)
                try:
                    cleaned_count = session_store.cleanup()
                    if cleaned_count:
                        logger.info(
                            "session_cleanup",
                            extra={"extra_fields": {"removed": cleaned_count}},
                        )
                except Exception as e:
                    logger.exception(
                        "session_cleanup_error",
                        extra={"extra_fields": {"error": str(e)}},
                    )
        
        # Démarrer la tâche de nettoyage en arrière-plan
        asyncio.create_task(cleanup_expired_sessions())
    @app.middleware("http")
    async def session_middleware(request: Request, call_next):
        logger.debug(
            "session_middleware_request",
            extra={
                "extra_fields": {
                    "method": request.method,
                    "path": request.url.path,
                }
            },
        )
        
        response = await call_next(request)
        
        # Si la réponse est un JSONResponse et qu'elle contient un session_id dans les headers
        if isinstance(response, JSONResponse) and "session_id" in response.headers:
            session_id = response.headers.pop("session_id")
            logger.info(
                "session_header_found",
                extra={
                    "extra_fields": {
                        "session_id": session_id[:10] + "...",
                        "path": request.url.path,
                    }
                },
            )
            
            # Créer un cookie pour la session
            response.set_cookie(
                key="session_id",
                value=session_id,
                httponly=True,  # Toujours true pour la sécurité
                secure=SECURE_COOKIES,
                samesite=SESSION_SAMESITE.lower(),
                max_age=SESSION_EXPIRY_HOURS * 3600,  # En secondes
                path="/",
                domain=COOKIE_DOMAIN or None
            )
            logger.debug(
                "session_cookie_set",
                extra={
                    "extra_fields": {
                        "path": request.url.path,
                        "expiry_hours": SESSION_EXPIRY_HOURS,
                    }
                },
            )
        
        return response
