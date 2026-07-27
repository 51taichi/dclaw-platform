# -*- coding: utf-8 -*-
"""Application storage bootstrap helpers."""
from __future__ import annotations

from sqlalchemy.engine import Engine

from .engine import get_app_engine
from .schema import create_all
from .settings import StorageSettings, get_storage_settings


def ensure_durable_schema(
    *,
    settings: StorageSettings | None = None,
    engine: Engine | None = None,
) -> bool:
    """Ensure SQLAlchemy-backed durable tables exist.

    The legacy SQLite path still owns its own migrations in ``app.db``.  For
    Postgres deployments we must create the SQLAlchemy schema before auth
    auto-registration, repositories, diagnostics, or background tasks touch it.
    """
    resolved_settings = settings or get_storage_settings()
    if resolved_settings.database_backend != "postgres":
        return False

    create_all(engine or get_app_engine())
    return True
