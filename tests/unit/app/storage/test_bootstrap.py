# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import create_engine, inspect

from qwenpaw.app.storage import bootstrap
from qwenpaw.app.storage.schema import table_names


def test_ensure_durable_schema_creates_tables_for_postgres_backend():
    engine = create_engine("sqlite:///:memory:", future=True)
    settings = SimpleNamespace(database_backend="postgres")

    assert bootstrap.ensure_durable_schema(settings=settings, engine=engine) is True

    inspector = inspect(engine)
    assert table_names().issubset(set(inspector.get_table_names()))


def test_ensure_durable_schema_skips_legacy_sqlite_backend(monkeypatch):
    def fail_create_all(_engine):
        raise AssertionError("create_all should not be called for sqlite")

    monkeypatch.setattr(bootstrap, "create_all", fail_create_all)
    settings = SimpleNamespace(database_backend="sqlite")

    assert bootstrap.ensure_durable_schema(settings=settings, engine=object()) is False
