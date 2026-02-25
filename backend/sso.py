"""
SSO via OpenID Connect (OIDC) — compatible CAS/OIDC (ex: https://sso.univ-pau.fr/cas/oidc)

Flow:
  1. GET /api/v1/auth/sso/login  → redirige vers l'IdP avec un state
  2. GET /api/v1/auth/sso/callback → reçoit code+state, échange vs token, crée session
"""
import logging
import re
from typing import Dict, List, Optional
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

from .config import settings

logger = logging.getLogger("labondemand.sso")

# Cache du document de découverte OIDC (évite une requête à chaque login)
_discovery_cache: Optional[Dict] = None


def _get_discovery() -> Dict:
    """Récupère (et met en cache) le document de découverte OIDC."""
    global _discovery_cache
    if _discovery_cache is not None:
        return _discovery_cache

    url = f"{settings.OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration"
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        _discovery_cache = resp.json()
        logger.info("oidc_discovery_loaded", extra={"extra_fields": {"issuer": settings.OIDC_ISSUER}})
        return _discovery_cache
    except httpx.HTTPError as e:
        logger.error("oidc_discovery_failed", extra={"extra_fields": {"url": url, "error": str(e)}})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Impossible de contacter le serveur SSO: {e}",
        )


def get_authorization_url(redirect_uri: str, state: str) -> str:
    """Construit l'URL de redirection vers l'IdP OIDC."""
    if not settings.SSO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO désactivé")

    discovery = _get_discovery()
    auth_endpoint = discovery["authorization_endpoint"]
    params = {
        "client_id": settings.OIDC_CLIENT_ID,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"{auth_endpoint}?{urlencode(params)}"


def exchange_code(code: str, redirect_uri: str) -> Dict:
    """Échange le code d'autorisation contre les tokens."""
    discovery = _get_discovery()
    token_endpoint = discovery["token_endpoint"]
    try:
        resp = httpx.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.OIDC_CLIENT_ID,
                "client_secret": settings.OIDC_CLIENT_SECRET,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("oidc_token_exchange_failed", extra={"extra_fields": {"error": str(e)}})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Échec de l'échange de code SSO",
        )


def get_userinfo(access_token: str) -> Dict:
    """Récupère les informations utilisateur depuis le endpoint userinfo."""
    discovery = _get_discovery()
    userinfo_endpoint = discovery["userinfo_endpoint"]
    try:
        resp = httpx.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as e:
        logger.error("oidc_userinfo_failed", extra={"extra_fields": {"error": str(e)}})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Impossible de récupérer les informations utilisateur SSO",
        )


def _split_csv(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def map_role(claims: Dict) -> str:
    """Détermine le rôle de l'utilisateur depuis les claims OIDC."""
    role_claim = settings.OIDC_ROLE_CLAIM
    teacher_values = set(_split_csv(settings.OIDC_TEACHER_VALUES))
    student_values = set(_split_csv(settings.OIDC_STUDENT_VALUES))

    raw = claims.get(role_claim, []) if role_claim else []
    if isinstance(raw, str):
        values = {raw.strip().lower()}
    elif isinstance(raw, list):
        values = {v.strip().lower() for v in raw if v}
    else:
        values = set()

    if values & teacher_values:
        return "teacher"
    if values & student_values:
        return "student"
    return settings.OIDC_DEFAULT_ROLE


def sanitize_username(raw: str) -> str:
    if not raw:
        return "user"
    cleaned = re.sub(r"[^a-zA-Z0-9._-]", "-", raw.strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-_.")
    return cleaned or "user"
