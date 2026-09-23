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
- **Connexion** : trois protections complémentaires.

  1. Par IP (``RATE_LIMIT_LOGIN``, 60/minute par défaut), toutes tentatives
     confondues : simple garde-fou contre l'inondation, large car toute une
     salle de TP peut sortir par la même IP (NAT universitaire).
  2. Par couple (compte, IP) (``RATE_LIMIT_LOGIN_FAILURES``, 10 / 15 min) :
     freine la force brute depuis une source sans bloquer le titulaire du
     compte, qui se connecte depuis une autre IP.
  3. Par compte, toutes IP confondues (``RATE_LIMIT_LOGIN_FAILURES_ACCOUNT``,
     50 / 15 min) : plafonne le « password spraying » distribué. Une IP
     déjà bloquée au niveau 2 n'alimente plus ce compteur : bloquer un compte
     exige donc plusieurs sources (5 avec les valeurs par défaut).

  Les niveaux 2 et 3 incrémentent leurs compteurs de façon atomique AVANT la
  vérification bcrypt (pas de course « lecture puis écriture » entre
  requêtes parallèles) ; au-delà du seuil, la tentative est refusée (429 +
  ``Retry-After``) sans vérifier le mot de passe. Une connexion réussie remet
  les deux compteurs à zéro. Les noms inconnus sont comptés comme les autres
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
import ipaddress
import logging
import math
import time
import unicodedata
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, TypeVar

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
LIMIT_SETTING_NAMES = (
    "RATE_LIMIT_LOGIN",
    "RATE_LIMIT_LOGIN_FAILURES",
    "RATE_LIMIT_LOGIN_FAILURES_ACCOUNT",
    "RATE_LIMIT_DEPLOY",
)

# Espaces de noms des compteurs de tentatives de connexion.
_LOGIN_FAILURE_SCOPE_ACCOUNT_IP = "login_failures_account_ip"
_LOGIN_FAILURE_SCOPE_ACCOUNT = "login_failures_account"
# Seuls les premiers caractères d'un nom sont normalisés : coût borné même
# si un appelant oublie la validation de longueur (voir schemas.UserLogin).
_MAX_NORMALIZED_USERNAME_CHARS = 256
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
# Tentatives de connexion par compte et par (compte, IP)
# ============================================================

def normalize_username(username: str) -> str:
    """Forme canonique (par excès) d'un nom d'utilisateur pour les compteurs.

    MariaDB compare les noms avec une collation insensible à la casse et
    aux accents, qui ignore aussi les espaces finaux : « Admin », « ádmin »
    ou « admin  » désignent le même compte. Sans cette normalisation, un
    attaquant contournerait le seuil en variant la graphie. On supprime
    donc casse, diacritiques, espaces et caractères de format ou de
    contrôle ; fusionner à tort deux noms réellement distincts est sans
    danger (au pire un compteur partagé). Les graphies que la collation
    confond mais que Unicode ne rapproche pas (đ, ł, ø…) sont couvertes par
    l'appelant, qui passe le nom tel qu'enregistré en base.
    """
    truncated = (username or "")[:_MAX_NORMALIZED_USERNAME_CHARS]
    decomposed = unicodedata.normalize("NFKD", truncated.casefold())
    return "".join(ch for ch in decomposed if unicodedata.category(ch)[0] not in ("M", "C", "Z"))


def ip_bucket(ip: str) -> str:
    """Regroupement d'IP du compteur (compte, IP) : IPv4 exacte, IPv6 par /64.

    Un poste IPv6 dispose couramment de tout un /64 : sans regroupement,
    chaque adresse du préfixe obtiendrait son propre quota d'échecs.
    """
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if address.version == 6:
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


@dataclass(frozen=True)
class LoginThrottleBlock:
    """Tentative refusée : niveau atteint et délai avant la réouverture."""

    scope: str  # "account_ip" ou "account"
    retry_after: int


class LoginFailureThrottle:
    """Compteurs de tentatives de connexion : par (compte, IP) et par compte.

    Fenêtres fixes ouvertes à la première tentative. Chaque tentative est
    comptée (incrément atomique) avant la vérification du mot de passe, puis
    une connexion réussie remet les compteurs à zéro : seuls les échecs
    s'accumulent. Stocké dans Redis (partagé entre workers) avec repli
    mémoire temporaire si Redis est injoignable. Seules des empreintes
    SHA-256 (nom normalisé, IP) sont stockées.
    """

    def __init__(self, storage_uri: str) -> None:
        self._primary = FixedWindowRateLimiter(
            storage_from_string(storage_uri, **_storage_options(storage_uri))
        )
        self._fallback = FixedWindowRateLimiter(MemoryStorage())
        self._primary_down_until = 0.0

    @staticmethod
    def _items(setting_name: str) -> List[RateLimitItem]:
        value = getattr(settings, setting_name)
        try:
            return list(parse_many(value))
        except ValueError:
            # Validé au démarrage : ne peut arriver qu'après un patch à chaud.
            logger.error(
                "login_throttle_invalid_limit",
                extra={"extra_fields": {"setting": setting_name, "value": value}},
            )
            return []

    @staticmethod
    def _account_identifier(account: str) -> str:
        return hashlib.sha256(normalize_username(account).encode("utf-8")).hexdigest()

    @staticmethod
    def _account_ip_identifier(account: str, ip: str) -> str:
        material = f"{normalize_username(account)}\x00{ip_bucket(ip)}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

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

    @staticmethod
    def _hit(
        strategy: FixedWindowRateLimiter, items: List[RateLimitItem], scope: str, identifier: str
    ) -> int:
        """Incrémente chaque fenêtre ; 0 si toutes sont respectées, sinon le délai."""
        wait = 0
        for item in items:
            if not strategy.hit(item, scope, identifier):
                reset_time, _remaining = strategy.get_window_stats(item, scope, identifier)
                wait = max(wait, _seconds_until(reset_time))
        return wait

    def register_attempt(self, account: str, ip: str) -> Optional[LoginThrottleBlock]:
        """Compte une tentative sur ``account`` depuis ``ip`` ; bloc si refusée.

        Le compteur par compte n'est incrémenté que si le couple (compte, IP)
        est sous son seuil : une source unique ne peut donc pas, à elle
        seule, bloquer le compte pour toutes les autres.
        """
        account_ip_items = self._items("RATE_LIMIT_LOGIN_FAILURES")
        account_items = self._items("RATE_LIMIT_LOGIN_FAILURES_ACCOUNT")
        account_ip_id = self._account_ip_identifier(account, ip)
        account_id = self._account_identifier(account)

        def attempt(strategy: FixedWindowRateLimiter) -> Optional[LoginThrottleBlock]:
            wait = self._hit(strategy, account_ip_items, _LOGIN_FAILURE_SCOPE_ACCOUNT_IP, account_ip_id)
            if wait:
                return LoginThrottleBlock(scope="account_ip", retry_after=wait)
            wait = self._hit(strategy, account_items, _LOGIN_FAILURE_SCOPE_ACCOUNT, account_id)
            if wait:
                return LoginThrottleBlock(scope="account", retry_after=wait)
            return None

        return self._run(attempt)

    def clear(self, account: str, ip: str) -> None:
        """Remet à zéro les compteurs de ``account`` (connexion réussie depuis ``ip``)."""
        targets = [
            (self._items("RATE_LIMIT_LOGIN_FAILURES"), _LOGIN_FAILURE_SCOPE_ACCOUNT_IP,
             self._account_ip_identifier(account, ip)),
            (self._items("RATE_LIMIT_LOGIN_FAILURES_ACCOUNT"), _LOGIN_FAILURE_SCOPE_ACCOUNT,
             self._account_identifier(account)),
        ]

        def clear(strategy: FixedWindowRateLimiter) -> None:
            for items, scope, identifier in targets:
                for item in items:
                    strategy.clear(item, scope, identifier)

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
