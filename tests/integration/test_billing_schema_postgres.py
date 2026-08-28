# -*- coding: utf-8 -*-
"""Live PostgreSQL parser coverage for billing constraint migration DDL."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.schema import CreateSchema, DropSchema

import qwenpaw.app.storage.schema as schema_module
from qwenpaw.app.storage.settings import normalize_postgres_url


@pytest.fixture
def postgres_billing_ddl_engine():
    """Provide an isolated PostgreSQL schema for DDL-only verification."""
    raw_url = os.environ.get("QWENPAW_TEST_POSTGRES_URL", "").strip()
    if not raw_url:
        pytest.skip(
            "QWENPAW_TEST_POSTGRES_URL is not configured; "
            "live PostgreSQL billing DDL verification was not run",
        )

    database_url = normalize_postgres_url(raw_url)
    schema_name = f"billing_ddl_test_{uuid4().hex}"
    admin_engine = create_engine(database_url, future=True, pool_pre_ping=True)
    with admin_engine.begin() as conn:
        conn.execute(CreateSchema(schema_name))

    engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(DropSchema(schema_name, cascade=True))
        admin_engine.dispose()


@pytest.mark.integration
def test_postgresql_constraint_guard_ddl_executes_in_isolated_schema(
    postgres_billing_ddl_engine,
):
    """Execute every bridge and credit-lot guard without business rows."""
    with postgres_billing_ddl_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE billing_usage_orders ("
                "id VARCHAR PRIMARY KEY, quoted_credits BIGINT, "
                "held_credits BIGINT, captured_credits BIGINT, "
                "budget_credits BIGINT, released_credits BIGINT, "
                "reconciling_credits BIGINT, billability VARCHAR)",
            ),
        )
        conn.execute(
            text(
                "CREATE TABLE billing_usage_items ("
                "input_tokens BIGINT, output_tokens BIGINT, quantity BIGINT, "
                "quoted_credits BIGINT, charged_credits BIGINT, "
                "supplier_cost_fen BIGINT, billability VARCHAR)",
            ),
        )
        conn.execute(
            text(
                "CREATE TABLE open_api_invocations ("
                "billing_usage_order_id VARCHAR, quoted_credits BIGINT, "
                "captured_credits BIGINT, released_credits BIGINT)",
            ),
        )
        conn.execute(
            text(
                "CREATE TABLE billing_credit_lots ("
                "credit_type VARCHAR, expires_at TIMESTAMP WITH TIME ZONE)",
            ),
        )

    ensure_constraints = getattr(
        schema_module, "_ensure_postgresql_open_api_billing_constraints"
    )
    ensure_credit_lot_constraint = getattr(
        schema_module, "_ensure_billing_constraints"
    )
    ensure_constraints(postgres_billing_ddl_engine)
    ensure_credit_lot_constraint(postgres_billing_ddl_engine)
    ensure_constraints(postgres_billing_ddl_engine)
    ensure_credit_lot_constraint(postgres_billing_ddl_engine)

    inspector = inspect(postgres_billing_ddl_engine)
    assert {
        "ck_open_api_invocations_quoted_nonnegative",
        "ck_open_api_invocations_captured_nonnegative",
        "ck_open_api_invocations_released_nonnegative",
    } <= {
        check["name"]
        for check in inspector.get_check_constraints("open_api_invocations")
    }
    assert {
        "ck_billing_usage_orders_budget_nonnegative",
        "ck_billing_usage_orders_quoted_nonnegative",
        "ck_billing_usage_orders_held_nonnegative",
        "ck_billing_usage_orders_captured_nonnegative",
        "ck_billing_usage_orders_released_nonnegative",
        "ck_billing_usage_orders_reconciling_nonnegative",
        "ck_billing_usage_orders_billability",
    } <= {
        check["name"]
        for check in inspector.get_check_constraints("billing_usage_orders")
    }
    assert {
        "ck_billing_usage_items_input_nonnegative",
        "ck_billing_usage_items_output_nonnegative",
        "ck_billing_usage_items_quantity_nonnegative",
        "ck_billing_usage_items_charged_nonnegative",
        "ck_billing_usage_items_quoted_nonnegative",
        "ck_billing_usage_items_supplier_cost_nonnegative",
        "ck_billing_usage_items_billability",
    } <= {
        check["name"]
        for check in inspector.get_check_constraints("billing_usage_items")
    }
    assert {"fk_open_api_invocations_billing_usage_order"} <= {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys("open_api_invocations")
    }
    assert {"ck_billing_credit_lots_purchased_no_expiry"} <= {
        check["name"]
        for check in inspector.get_check_constraints("billing_credit_lots")
    }
