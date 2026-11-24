"""Small thread-safe TTL cache for expensive, slowly-changing lookups.

Used to avoid hitting the Kubernetes API on every request for data that
barely changes (node addresses, cluster-wide stats, availability pings).
"""

import threading
import time
from typing import Callable, Dict, Generic, Hashable, Optional, Tuple, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Cache values for ``ttl_seconds``; safe to share between worker threads."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: Dict[Hashable, Tuple[float, T]] = {}

    def get(self, key: Hashable) -> Optional[T]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= time.monotonic():
                del self._entries[key]
                return None
            return value

    def set(self, key: Hashable, value: T) -> None:
        with self._lock:
            self._entries[key] = (time.monotonic() + self._ttl, value)

    def get_or_set(self, key: Hashable, factory: Callable[[], T]) -> T:
        """Return the cached value, computing it with ``factory`` on a miss.

        The factory runs outside the lock so a slow Kubernetes call never
        blocks readers of other keys; concurrent misses may compute twice.
        Exceptions raised by the factory propagate and nothing is cached.
        """
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value)
        return value

    def invalidate(self, key: Optional[Hashable] = None) -> None:
        with self._lock:
            if key is None:
                self._entries.clear()
            else:
                self._entries.pop(key, None)
