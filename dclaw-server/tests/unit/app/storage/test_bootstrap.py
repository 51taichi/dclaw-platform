# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, event, inspect

from qwenpaw.app.billing import service as wallet_service_module
from qwenpaw.app.billing.service import WalletService
from qwenpaw.app.open_api import runtime as open_api_runtime
from qwenpaw.app.routers import billing as billing_router
from qwenpaw.app.storage import bootstrap
from qwenpaw.app.storage.schema import create_all, table_names


def test_ensure_durable_schema_creates_tables_for_postgres_backend():
    engine = create_engine("sqlite:///:memory:", future=True)
    settings = SimpleNamespace(database_backend="postgres")

    assert (
        bootstrap.ensure_durable_schema(settings=settings, engine=engine)
        is True
    )

    inspector = inspect(engine)
    assert table_names().issubset(set(inspector.get_table_names()))


def test_ensure_durable_schema_migrates_sqlite_at_explicit_startup():
    engine = create_engine("sqlite:///:memory:", future=True)
    settings = SimpleNamespace(database_backend="sqlite")

    assert (
        bootstrap.ensure_durable_schema(settings=settings, engine=engine)
        is False
    )
    assert table_names().issubset(set(inspect(engine).get_table_names()))


def test_runtime_service_factories_never_emit_schema_ddl(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    create_all(engine)
    statements: list[str] = []

    def record_statement(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    for module in (
        billing_router,
        wallet_service_module,
        open_api_runtime,
    ):
        monkeypatch.setattr(module, "get_app_engine", lambda: engine)

    billing_router.get_billing_repository()
    billing_router.get_price_catalog_service()
    wallet_service_module.get_wallet_service()
    open_api_runtime.create_open_api_billing_runtime()

    assert not any(
        statement.lstrip().upper().startswith(("ALTER ", "CREATE ", "DROP "))
        for statement in statements
    )


def test_wallet_service_factory_does_not_run_backfill_migration(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    create_all(engine)
    monkeypatch.setattr(
        wallet_service_module,
        "get_app_engine",
        lambda: engine,
    )

    def fail_backfill(_self):
        raise AssertionError("wallet backfill belongs to startup migration")

    monkeypatch.setattr(
        WalletService,
        "backfill_personal_wallets",
        fail_backfill,
    )

    wallet_service_module.get_wallet_service()
