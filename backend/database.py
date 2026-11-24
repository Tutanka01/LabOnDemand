"""Database engine, session factory and the ``get_db`` FastAPI dependency."""

import os
from contextlib import contextmanager
from typing import Any, Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, declarative_base, object_session, sessionmaker

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DB_USER = os.getenv("DB_USER", "labondemand")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = _int_env("DB_PORT", 3306)
DB_NAME = os.getenv("DB_NAME", "labondemand")

# Pool sizing. A request keeps its session's connection for the whole handler
# (``get_current_user`` opens the transaction), Kubernetes calls included.
# Worst case of connections checked out at the same time:
#   FastAPI threadpool (anyio default limiter)  40 threads x 2 = 80
#       (request session + one short write session: DB row tracking or
#        lifecycle status; read-only lookups reuse the request session)
#   grader workers (GRADER_MAX_CONCURRENT_RUNS)  16 x 1      = 16
#   bulk lab spawn workers (BULK_SPAWN_CONCURRENCY) 4 x 1    =  4
#   asyncio default executor (cleanup cycle, terminal auth, health probes)
#       min(32, cpu + 4) threads x 1, + 1 nested write of the cleanup cycle
# i.e. 80 + 16 + 4 + min(32, cpu + 4) + 1 <= 133. The default pool is that
# worst case plus 10 connections of headroom (<= 143, below MariaDB's default
# max_connections of 151); override with DB_POOL_SIZE / DB_MAX_OVERFLOW.
_GRADER_WORKERS = max(1, _int_env("GRADER_MAX_CONCURRENT_RUNS", 16))
_ASYNCIO_EXECUTOR_THREADS = min(32, (os.cpu_count() or 1) + 4)
_WORST_CASE_CONNECTIONS = 40 * 2 + _GRADER_WORKERS + 4 + _ASYNCIO_EXECUTOR_THREADS + 1
DB_POOL_SIZE = _int_env("DB_POOL_SIZE", 40)
DB_MAX_OVERFLOW = _int_env(
    "DB_MAX_OVERFLOW", max(0, _WORST_CASE_CONNECTIONS + 10 - DB_POOL_SIZE)
)
DB_POOL_TIMEOUT = _int_env("DB_POOL_TIMEOUT", 10)
DB_POOL_RECYCLE = _int_env("DB_POOL_RECYCLE", 1800)

# URL.create escapes credentials, so passwords containing '@', ':' or '/' work.
SQLALCHEMY_DATABASE_URL = URL.create(
    "mysql+pymysql",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # transparently replace connections dropped by MariaDB
    pool_recycle=DB_POOL_RECYCLE,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_timeout=DB_POOL_TIMEOUT,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def read_session(owner: Any = None) -> Iterator[Session]:
    """Session for a read-only lookup made on behalf of ``owner``.

    When ``owner`` (typically the current ``User``) is attached to a session,
    that session is reused, so a request never checks out a second pooled
    connection for a lookup. Otherwise a short-lived session is opened and
    closed. Callers must not commit through it.
    """
    existing = object_session(owner) if owner is not None else None
    if existing is not None:
        yield existing
        return
    with SessionLocal() as db:
        yield db
