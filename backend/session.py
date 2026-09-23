from fastapi import FastAPI
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
    Planifie le nettoyage périodique des sessions expirées.

    Le cookie de session est posé explicitement par les routes
    d'authentification (login, callback SSO) ; aucun middleware ne recopie
    plus le jeton depuis un en-tête de réponse.
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
