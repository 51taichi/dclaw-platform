# -*- coding: utf-8 -*-
"""SQLAlchemy engine helpers for SQLite and Postgres backends."""
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from .settings import StorageSettings, get_storage_settings


def create_engine_from_settings(settings: StorageSettings) -> Engine:
    """Create an SQLAlchemy engine for the configured database backend."""
    if settings.database_backend == "sqlite":
        engine = create_engine(
            f"sqlite:///{settings.sqlite_path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        _attach_sqlite_pragmas(engine)
        return engine

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=_int_env(
            "QWENPAW_DATABASE_POOL_SIZE",
            10,
            fallback_name="QWENPAW_DB_POOL_SIZE",
        ),
        max_overflow=_int_env(
            "QWENPAW_DATABASE_MAX_OVERFLOW",
            20,
            fallback_name="QWENPAW_DB_MAX_OVERFLOW",
        ),
        connect_args={
            "connect_timeout": _int_env("QWENPAW_DB_CONNECT_TIMEOUT", 5),
        },
        future=True,
    )


@lru_cache(maxsize=1)
def get_app_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine."""
    return create_engine_from_settings(get_storage_settings())


def reset_app_engine_cache() -> None:
    """Clear the cached app engine, mainly for tests and reload flows."""
    get_app_engine.cache_clear()


def db_dialect_name(engine: Engine) -> str:
    """Return a short dialect name for diagnostics."""
    return engine.dialect.name


def _attach_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def _int_env(
    name: str,
    default: int,
    *,
    fallback_name: str | None = None,
) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw and fallback_name:
        raw = os.environ.get(fallback_name, "").strip()
    try:
        return max(1, int(raw or default))
    except ValueError:
        return default
