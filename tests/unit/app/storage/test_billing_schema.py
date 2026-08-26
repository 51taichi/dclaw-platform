# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, Integer, inspect

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all
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
            "held_credits",
            "captured_credits",
        },
        "billing_usage_items": {
            "input_tokens",
            "output_tokens",
            "quantity",
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
    assert "billability" in usage_columns

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
