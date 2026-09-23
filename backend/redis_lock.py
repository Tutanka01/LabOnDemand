"""
Verrou distribué minimal sur Redis.

Sert à élire un « leader » parmi plusieurs processus API (workers uvicorn,
réplicas) pour les tâches de fond qui ne doivent tourner qu'à un seul
endroit à la fois (ex. nettoyage périodique des labs).

Principe (algorithme mono-instance classique) :
  - acquisition : ``SET key token NX PX ttl`` avec un jeton aléatoire propre
    au détenteur ; le TTL libère le verrou si le détenteur meurt ;
  - libération / prolongation : scripts Lua « compare-and-delete » et
    « compare-and-pexpire » — on ne touche jamais au verrou d'un autre
    détenteur (ex. après expiration puis ré-acquisition ailleurs).

Toutes les méthodes sont synchrones (client ``redis`` bloquant) : depuis la
boucle asyncio, les appeler via ``asyncio.to_thread``. Les erreurs de
connexion Redis (``redis.RedisError``) sont propagées à l'appelant, qui
décide quoi faire (ex. sauter une itération).
"""

from __future__ import annotations

import logging
import secrets
import time
from types import TracebackType
from typing import Optional, Type

import redis

logger = logging.getLogger("labondemand.redis_lock")

# Supprime la clé seulement si elle contient encore notre jeton.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

# Réarme le TTL seulement si la clé contient encore notre jeton.
_EXTEND_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


class LockNotAcquired(Exception):
    """Levée par le gestionnaire de contexte si le verrou n'a pas pu être pris."""


class RedisLock:
    """Verrou exclusif à durée de vie limitée, identifié par ``key``.

    ``ttl_seconds`` : durée de vie du verrou sans prolongation (> 0).
    ``blocking_timeout`` : délai d'attente par défaut de :meth:`acquire`
    (``None`` ou 0 → une seule tentative, non bloquante).

    Utilisable comme gestionnaire de contexte::

        with RedisLock(client, "labondemand:lock:x", ttl_seconds=30):
            ...  # LockNotAcquired si le verrou est déjà détenu ailleurs
    """

    def __init__(
        self,
        client: redis.Redis,
        key: str,
        ttl_seconds: float,
        *,
        blocking_timeout: Optional[float] = None,
        retry_interval: float = 0.1,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds doit être strictement positif")
        self._client = client
        self.key = key
        self.ttl_seconds = float(ttl_seconds)
        self.blocking_timeout = blocking_timeout
        self.retry_interval = max(0.01, retry_interval)
        self._token: Optional[str] = None

    @property
    def ttl_ms(self) -> int:
        return max(1, int(self.ttl_seconds * 1000))

    @property
    def owned(self) -> bool:
        """Vue locale : True si ce verrou a été acquis et non relâché/perdu.

        Ne garantit pas que la clé n'a pas expiré entre-temps : utiliser
        :meth:`extend` pour le vérifier auprès de Redis.
        """
        return self._token is not None

    def acquire(self, blocking_timeout: Optional[float] = None) -> bool:
        """Tente de prendre le verrou.

        ``blocking_timeout`` (sinon celui du constructeur) : durée maximale
        d'attente en secondes ; ``None``/0 → une seule tentative. Retourne
        True si le verrou est acquis. Lève ``redis.RedisError`` si Redis est
        injoignable.
        """
        if self._token is not None:
            raise RuntimeError(f"Verrou {self.key!r} déjà détenu par cette instance")
        timeout = self.blocking_timeout if blocking_timeout is None else blocking_timeout
        deadline = time.monotonic() + timeout if timeout and timeout > 0 else None
        token = secrets.token_hex(16)
        while True:
            if self._client.set(self.key, token, nx=True, px=self.ttl_ms):
                self._token = token
                return True
            if deadline is None:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(self.retry_interval, remaining))

    def extend(self) -> bool:
        """Réarme le TTL complet si le verrou nous appartient toujours.

        Retourne False (et oublie le jeton) si le verrou a expiré ou a été
        repris par un autre détenteur.
        """
        if self._token is None:
            return False
        extended = bool(self._client.eval(_EXTEND_SCRIPT, 1, self.key, self._token, self.ttl_ms))
        if not extended:
            self._token = None
        return extended

    def release(self) -> bool:
        """Relâche le verrou s'il nous appartient encore.

        Retourne True si la clé a été supprimée. Le jeton local est oublié
        dans tous les cas (même si Redis lève une erreur : le TTL fera foi).
        """
        if self._token is None:
            return False
        token, self._token = self._token, None
        return bool(self._client.eval(_RELEASE_SCRIPT, 1, self.key, token))

    def abandon(self) -> None:
        """Oublie le verrou localement sans le relâcher : il expirera avec son TTL.

        Utile quand le travail protégé continue hors de notre contrôle (ex. un
        thread qu'on ne peut pas interrompre) : relâcher permettrait à un autre
        processus de démarrer un travail concurrent.
        """
        self._token = None

    def __enter__(self) -> "RedisLock":
        if not self.acquire():
            raise LockNotAcquired(self.key)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        try:
            self.release()
        except redis.RedisError as err:
            # Le TTL libérera le verrou ; on ne masque pas l'exception d'origine.
            logger.warning(
                "redis_lock_release_failed",
                extra={"extra_fields": {"key": self.key, "error": str(err)}},
            )
