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

    This is the single application-startup boundary for SQLAlchemy schema
    creation and legacy upgrades.  Request dependencies only assemble
    repositories and services; they never run DDL.
    """
    resolved_settings = settings or get_storage_settings()
    create_all(engine or get_app_engine())
    return resolved_settings.database_backend == "postgres"
