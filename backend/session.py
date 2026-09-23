from typing import Optional

from fastapi import FastAPI, Response
import logging

from .config import settings

logger = logging.getLogger("labondemand.session")

# Nom du cookie portant le jeton de session opaque (HttpOnly).
SESSION_COOKIE_NAME = "session_id"

_VALID_SAMESITE = frozenset({"lax", "strict", "none"})


def _normalize_domain(value: Optional[str]) -> str:
    """Normalise un nom de domaine : minuscules, sans point initial ni final."""
    return (value or "").strip().strip(".").lower()


def cookie_domain_covers(cookie_domain: Optional[str], host_domain: Optional[str]) -> bool:
    """Indique si un cookie posé sur ``cookie_domain`` serait envoyé à ``host_domain``.

    Vrai si ``host_domain`` est égal à ``cookie_domain`` ou en est un
    sous-domaine (le point initial éventuel de ``COOKIE_DOMAIN`` est ignoré,
    comme le font les navigateurs).
    """
    cookie = _normalize_domain(cookie_domain)
    host = _normalize_domain(host_domain)
    if not cookie or not host:
        return False
    return host == cookie or host.endswith("." + cookie)


def validate_cookie_settings() -> None:
    """Refuse de démarrer si la configuration des cookies de session est dangereuse.

    - ``SESSION_SAMESITE`` doit valoir lax, strict ou none ;
    - ``SameSite=None`` exige ``SECURE_COOKIES`` (sinon les navigateurs
      rejettent le cookie et la connexion échoue silencieusement) ;
    - ``COOKIE_DOMAIN`` ne doit pas englober ``INGRESS_BASE_DOMAIN`` : les
      labs étudiants (contenu contrôlé par l'étudiant) recevraient alors le
      cookie de session de tout utilisateur qui les visite.

    Raises:
        RuntimeError: configuration refusée, avec un message explicite.
    """
    samesite = settings.SESSION_SAMESITE
    if samesite not in _VALID_SAMESITE:
        raise RuntimeError(
            f"SESSION_SAMESITE={samesite!r} invalide : valeurs acceptées "
            "Lax, Strict ou None."
        )
    if samesite == "none" and not settings.SECURE_COOKIES:
        raise RuntimeError(
            "SESSION_SAMESITE=None exige SECURE_COOKIES=True (HTTPS) : les "
            "navigateurs refusent un cookie SameSite=None non sécurisé."
        )
    if cookie_domain_covers(settings.COOKIE_DOMAIN, settings.INGRESS_BASE_DOMAIN):
        raise RuntimeError(
            f"COOKIE_DOMAIN={settings.COOKIE_DOMAIN!r} englobe "
            f"INGRESS_BASE_DOMAIN={settings.INGRESS_BASE_DOMAIN!r} : le cookie "
            "de session serait envoyé aux labs étudiants. Laissez COOKIE_DOMAIN "
            "vide (cookie limité à l'hôte) ou servez les labs sur un domaine "
            "distinct (idéalement un autre domaine enregistrable)."
        )


def set_session_cookie(response: Response, session_id: str) -> None:
    """Pose le cookie de session HttpOnly selon la configuration centrale."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=settings.SECURE_COOKIES,
        samesite=settings.SESSION_SAMESITE,
        max_age=settings.SESSION_EXPIRY_HOURS * 3600,
        path="/",
        domain=settings.COOKIE_DOMAIN or None,
    )


def clear_session_cookie(response: Response) -> None:
    """Expire le cookie de session avec les mêmes attributs que sa création."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        domain=settings.COOKIE_DOMAIN or None,
        secure=settings.SECURE_COOKIES,
        httponly=True,
        samesite=settings.SESSION_SAMESITE,
    )

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
