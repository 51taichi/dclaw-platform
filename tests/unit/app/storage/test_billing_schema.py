# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

from contextlib import AbstractContextManager
from types import SimpleNamespace

import pytest
from sqlalchemy import BigInteger, Integer, inspect
from sqlalchemy.dialects import postgresql

import qwenpaw.app.storage.schema as schema_module
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import (
    _ensure_billing_bigint_columns,
    create_all,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def sqlite_engine(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "billing.db")},
    )
    engine = create_engine_from_settings(settings)
    try:
        yield engine
    finally:
        engine.dispose()


def test_billing_schema_is_idempotent(sqlite_engine):
    create_all(sqlite_engine)
    create_all(sqlite_engine)

    inspector = inspect(sqlite_engine)
    names = set(inspector.get_table_names())
    assert {
        "billing_wallets",
        "billing_credit_lots",
        "billing_ledger_entries",
        "billing_ledger_allocations",
        "billing_price_catalogs",
        "billing_price_rules",
        "billing_usage_orders",
        "billing_usage_items",
    } <= names

    wallet_indexes = inspector.get_indexes("billing_wallets")
    wallet_uniques = inspector.get_unique_constraints("billing_wallets")
    unique_column_sets = {
        tuple(index["column_names"])
        for index in wallet_indexes
        if index.get("unique")
    } | {tuple(constraint["column_names"]) for constraint in wallet_uniques}
    assert ("owner_type", "owner_id") in unique_column_sets

    ledger_indexes = inspector.get_indexes("billing_ledger_entries")
    ledger_uniques = inspector.get_unique_constraints("billing_ledger_entries")
    ledger_unique_column_sets = {
        tuple(index["column_names"])
        for index in ledger_indexes
        if index.get("unique")
    } | {tuple(constraint["column_names"]) for constraint in ledger_uniques}
    assert ("idempotency_key",) in ledger_unique_column_sets

    usage_indexes = inspector.get_indexes("billing_usage_orders")
    usage_uniques = inspector.get_unique_constraints("billing_usage_orders")
    usage_unique_column_sets = {
        tuple(index["column_names"])
        for index in usage_indexes
        if index.get("unique")
    } | {tuple(constraint["column_names"]) for constraint in usage_uniques}
    assert ("business_key",) in usage_unique_column_sets

    catalog_indexes = inspector.get_indexes("billing_price_catalogs")
    catalog_uniques = inspector.get_unique_constraints(
        "billing_price_catalogs",
    )
    catalog_unique_column_sets = {
        tuple(index["column_names"])
        for index in catalog_indexes
        if index.get("unique")
    } | {tuple(constraint["column_names"]) for constraint in catalog_uniques}
    assert ("version",) in catalog_unique_column_sets

    amount_columns = {
        "billing_wallets": {
            "available_credits",
            "held_credits",
            "purchased_credits",
            "promotional_credits",
            "package_credits",
        },
        "billing_credit_lots": {
            "granted_credits",
            "available_credits",
            "held_credits",
        },
        "billing_ledger_entries": {"credit_delta", "cash_delta_fen"},
        "billing_ledger_allocations": {"credits"},
        "billing_price_rules": {
            "credits_per_unit",
            "input_credits_per_1k",
            "output_credits_per_1k",
        },
        "billing_usage_orders": {
            "quoted_credits",
            "budget_credits",
            "held_credits",
            "captured_credits",
            "released_credits",
            "reconciling_credits",
        },
        "billing_usage_items": {
            "input_tokens",
            "output_tokens",
            "quantity",
            "quoted_credits",
            "charged_credits",
            "supplier_cost_fen",
        },
    }
    for table_name, columns in amount_columns.items():
        reflected = {
            column["name"]: column["type"]
            for column in inspector.get_columns(table_name)
        }
        assert columns <= reflected.keys()
        assert all(
            isinstance(reflected[column], Integer) for column in columns
        )

    bigint_columns = {
        "billing_wallets": amount_columns["billing_wallets"],
        "billing_credit_lots": amount_columns["billing_credit_lots"],
        "billing_ledger_entries": amount_columns["billing_ledger_entries"],
        "billing_ledger_allocations": amount_columns[
            "billing_ledger_allocations"
        ],
        "billing_usage_orders": amount_columns["billing_usage_orders"],
        "billing_usage_items": amount_columns["billing_usage_items"],
    }
    for table_name, columns in bigint_columns.items():
        reflected = {
            column["name"]: column["type"]
            for column in inspector.get_columns(table_name)
        }
        assert all(
            isinstance(reflected[column], BigInteger) for column in columns
        )

    usage_columns = {
        column["name"]
        for column in inspector.get_columns("billing_usage_orders")
    }
    assert {
        "billability",
        "source_type",
        "source_id",
        "budget_credits",
        "released_credits",
        "reconciling_credits",
    } <= usage_columns

    item_columns = {
        column["name"]
        for column in inspector.get_columns("billing_usage_items")
    }
    assert {
        "item_key",
        "billability",
        "execution_outcome",
        "quoted_credits",
        "price_snapshot_json",
        "started_at",
        "finished_at",
    } <= item_columns

    source_uniques = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("billing_usage_orders")
        if index.get("unique")
    } | {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(
            "billing_usage_orders"
        )
    }
    assert ("source_type", "source_id") in source_uniques

    item_uniques = {
        tuple(index["column_names"])
        for index in inspector.get_indexes("billing_usage_items")
        if index.get("unique")
    } | {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(
            "billing_usage_items"
        )
    }
    assert ("usage_order_id", "item_key") in item_uniques

    foreign_key_targets = {
        "billing_credit_lots": {"billing_wallets"},
        "billing_ledger_entries": {"billing_wallets"},
        "billing_ledger_allocations": {
            "billing_ledger_entries",
            "billing_credit_lots",
        },
        "billing_price_rules": {"billing_price_catalogs"},
        "billing_usage_orders": {"billing_wallets", "billing_price_catalogs"},
        "billing_usage_items": {"billing_usage_orders"},
    }
    for table_name, expected_targets in foreign_key_targets.items():
        targets = {
            foreign_key["referred_table"]
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        assert expected_targets <= targets


def test_postgresql_bigint_upgrade_only_targets_existing_billing_amounts():
    class RecordingConnection:
        def __init__(self):
            self.statements: list[str] = []

        def execute(self, statement, *_args):
            self.statements.append(str(statement))

    class RecordingBegin(AbstractContextManager):
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self.connection

        def __exit__(self, exc_type, exc_value, traceback):
            return None

    class RecordingEngine:
        def __init__(self):
            self.dialect = SimpleNamespace(name="postgresql")
            self.connection = RecordingConnection()

        def begin(self):
            return RecordingBegin(self.connection)

    engine = RecordingEngine()
    _ensure_billing_bigint_columns(engine)

    statements = "\n".join(engine.connection.statements)
    assert (
        'ALTER TABLE "billing_usage_orders" ALTER COLUMN '
        '"budget_credits" TYPE BIGINT' in statements
    )
    assert (
        'ALTER TABLE "billing_usage_orders" ALTER COLUMN '
        '"reconciling_credits" TYPE BIGINT' in statements
    )
    assert (
        'ALTER TABLE "billing_usage_items" ALTER COLUMN '
        '"quoted_credits" TYPE BIGINT' in statements
    )
    assert (
        'ALTER TABLE "billing_usage_items" ALTER COLUMN '
        '"charged_credits" TYPE BIGINT' in statements
    )
    assert (
        'ALTER TABLE "billing_ledger_entries" ALTER COLUMN '
        '"credit_delta" TYPE BIGINT' in statements
    )
    assert (
        'ALTER TABLE "billing_ledger_entries" ALTER COLUMN '
        '"cash_delta_fen" TYPE BIGINT' in statements
    )
    assert (
        'ALTER TABLE "billing_ledger_entries" ALTER COLUMN '
        '"credits" TYPE BIGINT' not in statements
    )
    assert (
        'ALTER TABLE "billing_usage_orders" ALTER COLUMN '
        '"supplier_cost_fen" TYPE BIGINT' not in statements
    )
    assert (
        'ALTER TABLE "billing_usage_items" ALTER COLUMN "credits" TYPE BIGINT'
        not in statements
    )


def test_postgresql_billing_upgrade_uses_typed_timestamps_and_scoped_guards(
    monkeypatch,
):
    class RecordingResult:
        @staticmethod
        def scalars():
            return ()

    class RecordingConnection:
        def __init__(self):
            self.statements: list[str] = []

        def execute(self, statement, *_args):
            self.statements.append(str(statement))
            return RecordingResult()

        def scalar(self, _statement):
            return None

    class RecordingBegin(AbstractContextManager):
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            return self.connection

        def __exit__(self, exc_type, exc_value, traceback):
            return None

    class RecordingInspector:
        def get_table_names(self):
            return [
                "open_api_invocations",
                "billing_usage_orders",
                "billing_usage_items",
            ]

        def get_columns(self, table_name):
            columns = {
                "open_api_invocations": {"id"},
                "billing_usage_orders": {
                    "id",
                    "quoted_credits",
                    "held_credits",
                    "captured_credits",
                    "billability",
                },
                "billing_usage_items": {
                    "id",
                    "usage_order_id",
                },
            }
            return [{"name": name} for name in columns[table_name]]

    class RecordingEngine:
        def __init__(self):
            self.dialect = postgresql.dialect()
            self.connection = RecordingConnection()

        def begin(self):
            return RecordingBegin(self.connection)

        def connect(self):
            return RecordingBegin(self.connection)

    engine = RecordingEngine()
    monkeypatch.setattr(
        schema_module, "inspect", lambda _: RecordingInspector()
    )

    ensure_billing_columns = getattr(
        schema_module, "_ensure_open_api_billing_columns"
    )
    ensure_billing_columns(engine)
    _ensure_billing_bigint_columns(engine)
    ensure_credit_lot_constraint = getattr(
        schema_module, "_ensure_billing_constraints"
    )
    ensure_credit_lot_constraint(engine)

    statements = "\n".join(engine.connection.statements)
    assert "started_at TIMESTAMP WITH TIME ZONE" in statements
    assert "finished_at TIMESTAMP WITH TIME ZONE" in statements
    assert "DATETIME" not in statements
    expected_constraints = {
        "ck_open_api_invocations_quoted_nonnegative",
        "ck_open_api_invocations_captured_nonnegative",
        "ck_open_api_invocations_released_nonnegative",
        "ck_billing_usage_orders_quoted_nonnegative",
        "ck_billing_usage_orders_held_nonnegative",
        "ck_billing_usage_orders_captured_nonnegative",
        "ck_billing_usage_orders_budget_nonnegative",
        "ck_billing_usage_orders_released_nonnegative",
        "ck_billing_usage_orders_reconciling_nonnegative",
        "ck_billing_usage_orders_billability",
        "ck_billing_usage_items_input_nonnegative",
        "ck_billing_usage_items_output_nonnegative",
        "ck_billing_usage_items_quantity_nonnegative",
        "ck_billing_usage_items_charged_nonnegative",
        "ck_billing_usage_items_quoted_nonnegative",
        "ck_billing_usage_items_supplier_cost_nonnegative",
        "ck_billing_usage_items_billability",
        "fk_open_api_invocations_billing_usage_order",
        "ck_billing_credit_lots_purchased_no_expiry",
    }
    assert all(name in statements for name in expected_constraints)
    assert "pc.conrelid = relation.oid" in statements
    assert "pc.contype = 'c'" in statements
    assert "pc.contype = 'f'" in statements
    assert "pg_constraint AS constraint" not in statements
    assert "namespace.nspname = current_schema()" in statements
    assert "NOT VALID" in statements
    assert (
        "VALIDATE CONSTRAINT ck_billing_credit_lots_purchased_no_expiry"
        in statements
    )
    assert (
        'ALTER TABLE "billing_usage_items" ALTER COLUMN '
        '"quoted_credits" TYPE BIGINT' in statements
    )
