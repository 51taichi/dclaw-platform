# -*- coding: utf-8 -*-
"""Application storage bootstrap helpers."""
from __future__ import annotations

from sqlalchemy.engine import Engine

from .engine import get_app_engine
from .schema import create_all
from .repos.top_up_repo import TopUpRepository
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


def bootstrap_top_up_products(*, engine: Engine | None = None) -> int:
    """Seed the confirmed fixed products once, without overwriting operators."""
    repository = TopUpRepository(engine or get_app_engine())
    if repository.list_products():
        return 0
    products = (
        ("CNY 10", 1_000, 1_000, 0),
        ("CNY 50", 5_000, 5_000, 300),
        ("CNY 100", 10_000, 10_000, 1_000),
        ("CNY 500", 50_000, 50_000, 7_500),
        ("CNY 1,000", 100_000, 100_000, 20_000),
    )
    for order, (name, amount, purchased, promotional) in enumerate(products):
        repository.create_product(
            {
                "name": name,
                "description": "Permanent purchased credits"
                + (" plus a 90-day bonus" if promotional else ""),
                "payment_amount_fen": amount,
                "purchased_credits": purchased,
                "promotional_credits": promotional,
                "promotional_expiry_days": 90 if promotional else None,
                "status": "active",
                "display_order": order,
                "created_by": "system:bootstrap",
            },
        )
    return len(products)
