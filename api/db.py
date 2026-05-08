"""
ratethat.tennis — Database connection for API.

Uses a single shared psycopg2 connection pool sized for Railway's Postgres
limit. Every query checks a connection out of the pool and returns it on
exit, so the API can never leak connections (which previously exhausted
Postgres and made every endpoint hang under load).
"""
import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
from psycopg2 import pool as _pg_pool
from sqlalchemy import create_engine

# Connection string: prefer env var, fall back to hardcoded Railway DSN
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway",
)

# ─────────────────────────────────────────────────────────────────────────────
# Connection pool
# ─────────────────────────────────────────────────────────────────────────────
# Railway's Postgres typically allows ~100 concurrent connections. We size
# our pool well below that ceiling so other services (pipeline, dashboard)
# can still connect when this API is under load.
#
# minconn=1: one warm connection always ready.
# maxconn=15: hard cap. If all 15 are in use, additional requests will wait
# briefly for one to free instead of opening a new connection on top.
# ─────────────────────────────────────────────────────────────────────────────

_POOL: _pg_pool.ThreadedConnectionPool | None = None


def _get_pool() -> _pg_pool.ThreadedConnectionPool:
    """Return the singleton connection pool, creating it lazily on first use."""
    global _POOL
    if _POOL is None:
        _POOL = _pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=15,
            dsn=DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
            application_name="ratethat-api",
            # Avoid hanging forever on a slow query — fail fast so the
            # connection comes back to the pool.
            options="-c statement_timeout=15000",
        )
    return _POOL


# SQLAlchemy engine kept for any code that needs an engine (e.g. pandas)
_engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)


def get_engine():
    return _engine


@contextmanager
def get_conn():
    """
    Check a connection out of the pool, yield it, then return it on exit.

    The connection is committed on success and rolled back on exception, so
    callers don't need to worry about transaction state. The connection is
    always returned to the pool — even on errors — so we can't leak them.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        pool.putconn(conn)


def query(sql: str, params=None) -> list[dict]:
    """Execute a SELECT query and return list of dicts."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
            return [dict(r) for r in rows]


def query_one(sql: str, params=None) -> dict | None:
    """Execute a SELECT query and return first row as dict, or None."""
    rows = query(sql, params)
    return rows[0] if rows else None
