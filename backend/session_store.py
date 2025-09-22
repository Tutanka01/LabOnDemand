from datetime import timedelta
import os
from typing import Dict, Any, Optional
import json

# Nouveau backend: Redis
try:
    import redis
except ImportError as e:
    raise RuntimeError(
        "Le paquet 'redis' est requis pour le stockage des sessions. Ajoutez-le à requirements.txt."
    ) from e

# Configuration via variables d'environnement (simples et explicites)
REDIS_URL = os.getenv("REDIS_URL")
SESSION_EXPIRY_HOURS = int(os.getenv("SESSION_EXPIRY_HOURS", "24"))
SESSION_TTL_SECONDS = SESSION_EXPIRY_HOURS * 3600
REDIS_NAMESPACE = os.getenv("REDIS_NAMESPACE", "session:")


import time


class RedisSessionStore:
    """Stockage des sessions dans Redis avec TTL par clé (pas d'overengineering)."""

    def __init__(self, redis_url: str, ttl_seconds: int, namespace: str = "session:"):
        if not redis_url:
            raise RuntimeError(
                "REDIS_URL n'est pas défini. Configurez un Redis externe (ex: redis://redis:6379/0)."
            )
        # decode_responses=True pour travailler avec des str et non des bytes
        self._r = redis.from_url(redis_url, decode_responses=True)
        # Vérification avec quelques retries pour tolérer le démarrage lent de Redis
        last_err: Optional[Exception] = None
        for attempt in range(6):  # ~12s max (0.5,1,2,3,3,3)
            try:
                self._r.ping()
                last_err = None
                break
            except Exception as e:
                last_err = e
                sleep_s = 0.5 if attempt == 0 else min(3, attempt)
                time.sleep(sleep_s)
        if last_err:
            raise RuntimeError(f"Impossible de se connecter à Redis: {last_err}") from last_err
        self.ttl = ttl_seconds
        self.ns = namespace

    def _key(self, session_id: str) -> str:
        return f"{self.ns}{session_id}"

    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        payload = json.dumps(data, separators=(",", ":"))
        # setex applique le TTL sur la clé
        self._r.setex(self._key(session_id), self.ttl, payload)

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        raw = self._r.get(self._key(session_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # Si le contenu est corrompu, on supprime la clé pour éviter des erreurs futures
            try:
                self.delete(session_id)
            except Exception:
                pass
            return None

    def delete(self, session_id: str) -> bool:
        return self._r.delete(self._key(session_id)) > 0

    def cleanup(self) -> int:
        """
        Pas nécessaire avec Redis (expiration gérée par le serveur).
        Conservée pour compatibilité avec l'appelant; retourne toujours 0.
        """
        return 0

    @property
    def sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        Propriété de compatibilité pour le code de debug existant qui itère
        sur session_store.sessions. Pour Redis, on évite le SCAN coûteux ici.
        """
        return {}


# Instance globale du gestionnaire de sessions
session_store = RedisSessionStore(
    redis_url=REDIS_URL,
    ttl_seconds=SESSION_TTL_SECONDS,
    namespace=REDIS_NAMESPACE,
)
