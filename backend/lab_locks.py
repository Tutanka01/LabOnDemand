"""Per-user serialisation of lab operations (single API process).

Route handlers run concurrently in FastAPI's threadpool, the class-wide lab
spawn and the cleanup loop run in their own threads. Operations that read the
user's labs and then change them (quota check -> Kubernetes creation -> DB
row, deletion -> soft delete, list -> missing-row reconciliation) must not
interleave for the same user, otherwise quotas are bypassed and DB rows drift
from the cluster. ``user_lab_lock(user_id)`` serialises them.

The locks are in-process: the API runs as a single uvicorn process (see
compose.yaml). They are re-entrant, so a code path that already holds a
user's lock can call another locked operation of the same user. Acquisition
is bounded by ``LAB_LOCK_TIMEOUT_SECONDS``; while it is held, only bounded
work happens (Kubernetes calls carry a default timeout, DB checkouts a pool
timeout).
"""

import os
import threading
from contextlib import contextmanager
from typing import Dict, Hashable, Iterator, List, Optional

from fastapi import HTTPException

LAB_LOCK_TIMEOUT_SECONDS = float(os.getenv("LAB_LOCK_TIMEOUT_SECONDS", "90"))


class LabLockTimeout(HTTPException):
    """Another operation on the same user's labs did not finish in time."""

    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            detail="Une autre opération sur vos labs est en cours. Réessayez dans un instant.",
        )


class KeyedLocks:
    """One re-entrant lock per key, created on demand and dropped when unused."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        # key -> [lock, number of threads holding or waiting for it]
        self._entries: Dict[Hashable, List] = {}

    def _checkout(self, key: Hashable) -> threading.RLock:
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                entry = self._entries[key] = [threading.RLock(), 0]
            entry[1] += 1
            return entry[0]

    def _checkin(self, key: Hashable) -> None:
        with self._guard:
            entry = self._entries[key]
            entry[1] -= 1
            if entry[1] == 0:
                del self._entries[key]

    @contextmanager
    def hold(self, key: Hashable, timeout: Optional[float] = None) -> Iterator[None]:
        """Hold the lock of ``key``; raise ``LabLockTimeout`` after ``timeout`` s."""
        lock = self._checkout(key)
        try:
            if not lock.acquire(timeout=-1 if timeout is None else timeout):
                raise LabLockTimeout()
            try:
                yield
            finally:
                lock.release()
        finally:
            self._checkin(key)

    def __len__(self) -> int:
        with self._guard:
            return len(self._entries)


_USER_LAB_LOCKS = KeyedLocks()


@contextmanager
def user_lab_lock(user_id: int, timeout: Optional[float] = None) -> Iterator[None]:
    """Serialise quota-sensitive / DB-row-changing lab operations of one user."""
    with _USER_LAB_LOCKS.hold(
        int(user_id), LAB_LOCK_TIMEOUT_SECONDS if timeout is None else timeout
    ):
        yield
