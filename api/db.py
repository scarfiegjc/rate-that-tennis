"""
ratethat.tennis — Database connection for API.
Uses SQLAlchemy connection pool for async-safe usage under FastAPI.
"""
import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
import psycopg2.extras
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Connection string: prefer env var, fall back to hardcoded Railway DSN
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:DEKANqBEjmOvOGLCfzaQIBaKzhKcyKwS@switchyard.proxy.rlwy.net:39343/railway",
)

# SQLAlchemy engine with connection pool
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
    """Raw psycopg2 connection context manager — for queries returning dicts."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
