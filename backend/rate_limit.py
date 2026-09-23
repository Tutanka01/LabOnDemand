"""
Limitation de débit de l'API LabOnDemand.

Modèle
------
- **Stockage partagé** : les compteurs vivent dans Redis (``REDIS_URL`` ou
  ``RATE_LIMIT_STORAGE_URI``), donc partagés entre workers et redémarrages.
  Si Redis est injoignable, slowapi bascule sur un stockage mémoire local au
  processus (les limites restent appliquées, par worker) et revérifie Redis
  avec un recul exponentiel ; en dernier recours l'erreur est avalée (la
  requête passe) plutôt que de transformer une panne Redis en erreurs 500.
- **Connexion** : deux protections complémentaires.

  1. Par IP (``RATE_LIMIT_LOGIN``, 30/minute par défaut) : large, car toute
     une salle de TP peut sortir par la même IP (NAT universitaire).
  2. Par nom d'utilisateur (``RATE_LIMIT_LOGIN_FAILURES``, 10 échecs / 15 min)
     toutes IP confondues : freine le « password spraying » distribué. Le
     compteur est remis à zéro par une connexion réussie ; une fois le seuil
     atteint, la tentative est refusée (429 + ``Retry-After``) AVANT toute
     vérification bcrypt. Les noms inconnus sont comptés comme les autres
     (pas d'oracle d'énumération).
- **Création de déploiements** (``RATE_LIMIT_DEPLOY``) : clé = identifiant de
  l'utilisateur authentifié, IP à défaut (une salle derrière un NAT ne
  partage donc pas le même quota).

L'IP cliente est ``request.client.host`` : derrière nginx, uvicorn la
réécrit depuis ``X-Forwarded-For`` uniquement si la connexion provient d'un
proxy listé dans ``FORWARDED_ALLOW_IPS`` (``--proxy-headers``, voir
``compose.yaml``). Un client qui forge cet en-tête sans passer par un proxy
de confiance est donc ignoré.
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
import unicodedata
from typing import Callable, Dict, List, TypeVar

from limits import RateLimitItem, parse_many
from limits.storage import MemoryStorage, storage_from_string
from limits.strategies import FixedWindowRateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

try:
    from .config import settings
    from .i18n import get_locale, t
except ImportError:  # exécution en script (répertoire backend/ dans sys.path)
    from config import settings
    from i18n import get_locale, t

logger = logging.getLogger("labondemand.rate_limit")
audit_logger = logging.getLogger("labondemand.audit")

_T = TypeVar("_T")

# Délais réseau courts vers Redis : une panne doit basculer vite sur le
# stockage mémoire plutôt que bloquer les requêtes.
_REDIS_SOCKET_TIMEOUT_SECONDS = 1.0
_REDIS_SCHEMES = frozenset({"redis", "rediss"})

# Paramètres validés au démarrage (syntaxe « limits »).
LIMIT_SETTING_NAMES = ("RATE_LIMIT_LOGIN", "RATE_LIMIT_LOGIN_FAILURES", "RATE_LIMIT_DEPLOY")

# Espace de noms des compteurs d'échecs de connexion.
_LOGIN_FAILURE_SCOPE = "login_failures"
# Après une erreur Redis, durée pendant laquelle le compteur d'échecs
# utilise le stockage mémoire avant de retenter Redis.
_LOGIN_THROTTLE_RETRY_PRIMARY_SECONDS = 30.0


def _storage_options(storage_uri: str) -> Dict[str, float]:
    """Options du client Redis (délais courts) ; aucune pour les autres schémas."""
    scheme = storage_uri.split(":", 1)[0].strip().lower()
    if scheme in _REDIS_SCHEMES:
        return {
            "socket_connect_timeout": _REDIS_SOCKET_TIMEOUT_SECONDS,
            "socket_timeout": _REDIS_SOCKET_TIMEOUT_SECONDS,
        }
    return {}


def _seconds_until(reset_time: float) -> int:
    """Secondes (entier ≥ 1) jusqu'à ``reset_time`` (horodatage epoch)."""
    return max(1, math.ceil(reset_time - time.time()))


# ============================================================
# Clés de limitation
# ============================================================

def client_ip(request: Request) -> str:
    """IP cliente effective (déjà résolue par uvicorn ``--proxy-headers``)."""
    client = request.client
    return client.host if client and client.host else "unknown"


def ip_key(request: Request) -> str:
    """Clé par adresse IP."""
    return f"ip:{client_ip(request)}"


def user_or_ip_key(request: Request) -> str:
    """Clé par utilisateur authentifié, IP à défaut.

    slowapi évalue la limite après la résolution des dépendances FastAPI :
    ``get_current_user`` / ``get_session_data`` ont déjà renseigné
    ``request.state`` sur les routes authentifiées.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        session = getattr(request.state, "session", None)
        user_id = getattr(session, "user_id", None)
    if user_id is not None:
        return f"user:{user_id}"
    return ip_key(request)


# ============================================================
# Limites (évaluées à chaque requête : modifiables à chaud en test)
# ============================================================

def login_ip_limit() -> str:
    """Limite par IP de ``POST /api/v1/auth/login``."""
    return settings.RATE_LIMIT_LOGIN


def validate_rate_limit_settings() -> None:
    """Refuse de démarrer si une limite configurée est invalide.

    Sans ce contrôle, slowapi journaliserait l'erreur et n'appliquerait
    silencieusement AUCUNE limite sur la route concernée.

    Raises:
        RuntimeError: syntaxe invalide ou quantité nulle.
    """
    for name in LIMIT_SETTING_NAMES:
        value = getattr(settings, name)
        try:
            items = parse_many(value)
        except ValueError as exc:
            raise RuntimeError(
                f"{name}={value!r} est invalide : syntaxe attendue « 30/minute », "
                "« 10/5minute » (plusieurs limites séparées par « ; »)."
            ) from exc
        if not items or any(item.amount < 1 for item in items):
            raise RuntimeError(f"{name}={value!r} est invalide : quantité ≥ 1 requise.")


# ============================================================
# Limiteur slowapi (décorateurs @limiter.limit)
# ============================================================

limiter = Limiter(
    key_func=user_or_ip_key,
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
    storage_options=_storage_options(settings.RATE_LIMIT_STORAGE_URI),
    # Redis en panne : compteurs en mémoire (par processus), Redis revérifié
    # avec un recul exponentiel.
    in_memory_fallback_enabled=True,
    # Dernier recours : ne jamais transformer une erreur de stockage en 500.
    swallow_errors=True,
)


def rate_limit_retry_after(request: Request, exc: RateLimitExceeded) -> int:
    """Délai (secondes) avant la réouverture de la fenêtre dépassée."""
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit is not None:
        try:
            item, args = view_limit
            reset_time, _remaining = limiter.limiter.get_window_stats(item, *args)
            return _seconds_until(reset_time)
        except Exception:
            logger.debug("rate_limit_window_stats_unavailable", exc_info=True)
    try:
        return max(1, int(exc.limit.limit.get_expiry()))
    except Exception:
        return 60


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Réponse 429 traduite, avec ``Retry-After`` (remplace celle de slowapi).

    Le champ ``error`` reprend le format historique de slowapi
    (« Rate limit exceeded: … ») pour les clients existants.
    """
    retry_after = rate_limit_retry_after(request, exc)
    audit_logger.warning(
        "rate_limit_exceeded",
        extra={
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "limit": str(exc.detail),
                "client_ip": client_ip(request),
                "user_id": getattr(request.state, "user_id", None),
                "retry_after": retry_after,
            }
        },
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": t("error.rate_limited", get_locale(request), seconds=retry_after),
            "error": f"Rate limit exceeded: {exc.detail}",
        },
        headers={"Retry-After": str(retry_after)},
    )


# ============================================================
# Échecs de connexion par nom d'utilisateur
# ============================================================

def normalize_username(username: str) -> str:
    """Forme canonique (par excès) d'un nom d'utilisateur pour le compteur.

    MariaDB compare les noms avec une collation insensible à la casse et
    aux accents, qui ignore aussi les espaces finaux : « Admin », « ádmin »
    ou « admin  » désignent le même compte. Sans cette normalisation, un
    attaquant contournerait le seuil en variant la graphie. On supprime
    donc casse, diacritiques, espaces et caractères de format ou de
    contrôle ; fusionner à tort deux noms réellement distincts est sans
    danger (au pire un compteur partagé).
    """
    decomposed = unicodedata.normalize("NFKD", (username or "").casefold())
    return "".join(ch for ch in decomposed if unicodedata.category(ch)[0] not in ("M", "C", "Z"))


class LoginFailureThrottle:
    """Compteur d'échecs de connexion par nom d'utilisateur.

    Fenêtre fixe démarrant au premier échec. Stocké dans Redis (partagé
    entre workers) avec repli mémoire temporaire si Redis est injoignable.
    Seule une empreinte SHA-256 du nom normalisé est stockée.
    """

    def __init__(self, storage_uri: str) -> None:
        self._primary = FixedWindowRateLimiter(
            storage_from_string(storage_uri, **_storage_options(storage_uri))
        )
        self._fallback = FixedWindowRateLimiter(MemoryStorage())
        self._primary_down_until = 0.0

    @staticmethod
    def _items() -> List[RateLimitItem]:
        value = settings.RATE_LIMIT_LOGIN_FAILURES
        try:
            return list(parse_many(value))
        except ValueError:
            # Validé au démarrage : ne peut arriver qu'après un patch à chaud.
            logger.error("login_throttle_invalid_limit", extra={"extra_fields": {"value": value}})
            return []

    @staticmethod
    def _identifier(username: str) -> str:
        return hashlib.sha256(normalize_username(username).encode("utf-8")).hexdigest()

    def _run(self, operation: Callable[[FixedWindowRateLimiter], _T]) -> _T:
        """Exécute ``operation`` sur Redis, ou sur la mémoire si Redis est en panne."""
        if time.monotonic() >= self._primary_down_until:
            try:
                return operation(self._primary)
            except Exception as exc:
                self._primary_down_until = time.monotonic() + _LOGIN_THROTTLE_RETRY_PRIMARY_SECONDS
                logger.warning(
                    "login_throttle_storage_unavailable",
                    extra={
                        "extra_fields": {
                            "error": type(exc).__name__,
                            "retry_in_seconds": _LOGIN_THROTTLE_RETRY_PRIMARY_SECONDS,
                        }
                    },
                )
        return operation(self._fallback)

    def retry_after(self, username: str) -> int:
        """0 si une tentative est permise, sinon secondes avant la prochaine."""
        items = self._items()
        if not items:
            return 0
        identifier = self._identifier(username)

        def check(strategy: FixedWindowRateLimiter) -> int:
            wait = 0
            for item in items:
                if not strategy.test(item, _LOGIN_FAILURE_SCOPE, identifier):
                    reset_time, _remaining = strategy.get_window_stats(item, _LOGIN_FAILURE_SCOPE, identifier)
                    wait = max(wait, _seconds_until(reset_time))
            return wait

        return self._run(check)

    def record_failure(self, username: str) -> None:
        """Comptabilise un échec de connexion pour ``username``."""
        items = self._items()
        if not items:
            return
        identifier = self._identifier(username)

        def hit(strategy: FixedWindowRateLimiter) -> None:
            for item in items:
                strategy.hit(item, _LOGIN_FAILURE_SCOPE, identifier)

        self._run(hit)

    def clear(self, username: str) -> None:
        """Remet à zéro le compteur de ``username`` (connexion réussie)."""
        items = self._items()
        if not items:
            return
        identifier = self._identifier(username)

        def clear(strategy: FixedWindowRateLimiter) -> None:
            for item in items:
                strategy.clear(item, _LOGIN_FAILURE_SCOPE, identifier)

        # Le repli mémoire est toujours purgé : un compteur périmé ne doit
        # pas bloquer l'utilisateur lors d'une prochaine panne de Redis.
        clear(self._fallback)
        self._run(clear)

    def reset(self) -> None:
        """Purge tous les compteurs (tests / maintenance)."""
        for strategy in (self._primary, self._fallback):
            try:
                strategy.storage.reset()
            except Exception:
                logger.warning("login_throttle_reset_failed", exc_info=True)
        self._primary_down_until = 0.0


login_failure_throttle = LoginFailureThrottle(settings.RATE_LIMIT_STORAGE_URI)


def reset_rate_limit_state() -> None:
    """Remet à zéro tous les compteurs et l'état de repli (tests / maintenance)."""
    for storage in (limiter._storage, getattr(limiter, "_fallback_storage", None)):
        if storage is None:
            continue
        try:
            storage.reset()
        except Exception:
            logger.warning("rate_limit_reset_failed", exc_info=True)
    limiter._storage_dead = False
    login_failure_throttle.reset()
