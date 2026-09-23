"""Tests du verrou distribué Redis (backend/redis_lock.py).

Couvre acquisition, contention, libération (jamais celle d'un autre
détenteur), prolongation, expiration, attente bornée, gestionnaire de
contexte et Redis injoignable. Chaque test utilise son propre FakeServer.
"""
import threading
import time

import fakeredis
import pytest
import redis

from backend.redis_lock import LockNotAcquired, RedisLock

KEY = "labondemand:lock:test"


@pytest.fixture()
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture()
def redis_client(redis_server) -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(server=redis_server)


def test_acquire_sets_unique_token_with_ttl(redis_client):
    lock = RedisLock(redis_client, KEY, ttl_seconds=10)
    assert lock.acquire() is True
    assert lock.owned
    token = redis_client.get(KEY)
    assert token and len(token) == 32
    assert 0 < redis_client.pttl(KEY) <= 10_000

    other = RedisLock(redis_client, "labondemand:lock:other", ttl_seconds=10)
    other.acquire()
    assert redis_client.get("labondemand:lock:other") != token


def test_second_holder_cannot_acquire(redis_client):
    first = RedisLock(redis_client, KEY, ttl_seconds=10)
    second = RedisLock(redis_client, KEY, ttl_seconds=10)
    assert first.acquire()
    assert second.acquire() is False
    assert not second.owned


def test_release_frees_the_lock(redis_client):
    first = RedisLock(redis_client, KEY, ttl_seconds=10)
    second = RedisLock(redis_client, KEY, ttl_seconds=10)
    first.acquire()
    assert first.release() is True
    assert not first.owned
    assert redis_client.exists(KEY) == 0
    assert second.acquire() is True
    # Relâcher un verrou non détenu est sans effet.
    assert first.release() is False


def test_expired_lock_is_taken_over_and_never_released_by_old_holder(redis_client):
    first = RedisLock(redis_client, KEY, ttl_seconds=0.1)
    second = RedisLock(redis_client, KEY, ttl_seconds=10)
    first.acquire()
    time.sleep(0.2)
    assert second.acquire() is True
    token = redis_client.get(KEY)

    # L'ancien détenteur ne peut ni prolonger ni supprimer le verrou du nouveau.
    assert first.extend() is False
    assert not first.owned
    assert first.release() is False
    assert redis_client.get(KEY) == token


def test_extend_rearms_full_ttl(redis_client):
    lock = RedisLock(redis_client, KEY, ttl_seconds=1)
    lock.acquire()
    time.sleep(0.3)
    assert redis_client.pttl(KEY) < 800
    assert lock.extend() is True
    assert redis_client.pttl(KEY) > 900


def test_blocking_acquire_waits_for_release(redis_client):
    first = RedisLock(redis_client, KEY, ttl_seconds=10)
    second = RedisLock(redis_client, KEY, ttl_seconds=10, retry_interval=0.02)
    first.acquire()
    timer = threading.Timer(0.2, first.release)
    timer.start()
    try:
        start = time.monotonic()
        assert second.acquire(blocking_timeout=2) is True
        assert time.monotonic() - start >= 0.15
    finally:
        timer.cancel()


def test_blocking_acquire_gives_up_after_timeout(redis_client):
    first = RedisLock(redis_client, KEY, ttl_seconds=10)
    second = RedisLock(redis_client, KEY, ttl_seconds=10, blocking_timeout=0.2)
    first.acquire()
    start = time.monotonic()
    assert second.acquire() is False
    assert time.monotonic() - start >= 0.2


def test_context_manager_acquires_and_releases(redis_client):
    with RedisLock(redis_client, KEY, ttl_seconds=10) as lock:
        assert lock.owned
        assert redis_client.exists(KEY) == 1
        with pytest.raises(LockNotAcquired):
            with RedisLock(redis_client, KEY, ttl_seconds=10):
                pass  # pragma: no cover
    assert redis_client.exists(KEY) == 0


def test_abandon_leaves_lock_until_ttl(redis_client):
    lock = RedisLock(redis_client, KEY, ttl_seconds=10)
    lock.acquire()
    lock.abandon()
    assert not lock.owned
    assert lock.release() is False
    assert redis_client.exists(KEY) == 1


def test_redis_down_raises_redis_error(redis_server, redis_client):
    redis_server.connected = False
    lock = RedisLock(redis_client, KEY, ttl_seconds=10)
    with pytest.raises(redis.RedisError):
        lock.acquire()
    assert not lock.owned


def test_invalid_usage_is_rejected(redis_client):
    with pytest.raises(ValueError):
        RedisLock(redis_client, KEY, ttl_seconds=0)
    lock = RedisLock(redis_client, KEY, ttl_seconds=10)
    lock.acquire()
    with pytest.raises(RuntimeError):
        lock.acquire()
