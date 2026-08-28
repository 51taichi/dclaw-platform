# -*- coding: utf-8 -*-
from __future__ import annotations

from sqlalchemy import inspect, text

from qwenpaw.app.open_api.models import OpenApiInvocation
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def _engine(tmp_path, name: str):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / name)})
    return create_engine_from_settings(settings)


def test_open_api_billing_columns_exist(tmp_path):
    engine = _engine(tmp_path, "fresh-billing.db")
    try:
        create_all(engine)

        invocations = {
            column["name"]
            for column in inspect(engine).get_columns("open_api_invocations")
        }
        assert {
            "billing_usage_order_id",
            "billing_status",
            "quoted_credits",
            "captured_credits",
            "released_credits",
            "billing_error_code",
        } <= invocations
    finally:
        engine.dispose()


def test_open_api_billing_upgrade_is_idempotent_and_preserves_history(tmp_path):
    engine = _engine(tmp_path, "pre-bridge.db")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE open_api_invocations ("
                    "id VARCHAR PRIMARY KEY, app_id VARCHAR, "
                    "publication_id VARCHAR, api_key_id VARCHAR, "
                    "target_type VARCHAR, target_id VARCHAR, chat_id VARCHAR, "
                    "external_session_id VARCHAR, external_user_id VARCHAR, "
                    "status VARCHAR, status_code INTEGER, latency_ms INTEGER, "
                    "token_summary TEXT, error_summary TEXT, created_at DATETIME)",
                ),
            )
            conn.execute(
                text(
                    "CREATE TABLE billing_usage_orders ("
                    "id VARCHAR PRIMARY KEY, wallet_id VARCHAR, catalog_id VARCHAR, "
                    "price_rule_id VARCHAR, business_key VARCHAR, status VARCHAR, "
                    "provider_id VARCHAR, model_key VARCHAR, capability VARCHAR, "
                    "quoted_credits BIGINT, held_credits BIGINT, "
                    "captured_credits BIGINT, request_snapshot_json TEXT, "
                    "price_snapshot_json TEXT, supplier_reference VARCHAR, "
                    "supplier_evidence_json TEXT, billability VARCHAR, "
                    "created_at DATETIME, updated_at DATETIME, submitted_at DATETIME, "
                    "settled_at DATETIME)",
                ),
            )
            conn.execute(
                text(
                    "CREATE TABLE billing_usage_items ("
                    "id VARCHAR PRIMARY KEY, usage_order_id VARCHAR, "
                    "price_rule_id VARCHAR, status VARCHAR, provider_id VARCHAR, "
                    "model_key VARCHAR, capability VARCHAR, supplier_reference VARCHAR, "
                    "input_tokens BIGINT, output_tokens BIGINT, quantity BIGINT, "
                    "charged_credits BIGINT, supplier_cost_fen BIGINT, "
                    "usage_snapshot_json TEXT, supplier_evidence_json TEXT, "
                    "created_at DATETIME, updated_at DATETIME)",
                ),
            )
            conn.execute(
                text(
                    "CREATE TABLE token_usage_logs ("
                    "id VARCHAR PRIMARY KEY, model_name VARCHAR, "
                    "prompt_tokens INTEGER, completion_tokens INTEGER)",
                ),
            )
            conn.execute(
                text(
                    "CREATE TABLE billing_ledger_entries ("
                    "id VARCHAR PRIMARY KEY, business_type VARCHAR, "
                    "business_key VARCHAR, created_at DATETIME)",
                ),
            )
            conn.execute(
                text(
                    "INSERT INTO token_usage_logs "
                    "(id, model_name, prompt_tokens, completion_tokens) "
                    "VALUES ('token-before-cutover', 'legacy-model', 7, 11)",
                ),
            )
            conn.execute(
                text(
                    "INSERT INTO billing_ledger_entries "
                    "(id, business_type, business_key) "
                    "VALUES ('ledger-before-cutover', 'legacy', 'legacy-key')",
                ),
            )

        create_all(engine)
        create_all(engine)

        inspector = inspect(engine)
        invocation_columns = {
            column["name"]
            for column in inspector.get_columns("open_api_invocations")
        }
        order_columns = {
            column["name"]
            for column in inspector.get_columns("billing_usage_orders")
        }
        item_columns = {
            column["name"]
            for column in inspector.get_columns("billing_usage_items")
        }
        assert {
            "billing_usage_order_id",
            "billing_status",
            "quoted_credits",
            "captured_credits",
            "released_credits",
            "billing_error_code",
        } <= invocation_columns
        assert {
            "source_type",
            "source_id",
            "budget_credits",
            "released_credits",
            "reconciling_credits",
        } <= order_columns
        assert {
            "item_key",
            "billability",
            "quoted_credits",
            "price_snapshot_json",
            "started_at",
            "finished_at",
        } <= item_columns

        order_uniques = {
            tuple(index["column_names"])
            for index in inspector.get_indexes("billing_usage_orders")
            if index.get("unique")
        }
        item_uniques = {
            tuple(index["column_names"])
            for index in inspector.get_indexes("billing_usage_items")
            if index.get("unique")
        }
        assert ("source_type", "source_id") in order_uniques
        assert ("usage_order_id", "item_key") in item_uniques

        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT model_name, prompt_tokens, completion_tokens "
                     "FROM token_usage_logs WHERE id = 'token-before-cutover'"),
            ).one() == ("legacy-model", 7, 11)
            assert conn.execute(
                text("SELECT business_type, business_key FROM billing_ledger_entries "
                     "WHERE id = 'ledger-before-cutover'"),
            ).one() == ("legacy", "legacy-key")
    finally:
        engine.dispose()


def test_open_api_invocation_exposes_billing_fields():
    invocation = OpenApiInvocation(
        id="inv-1",
        app_id="app-1",
        publication_id="pub-1",
        api_key_id="key-1",
        target_type="agent",
        target_id="agent-1",
        status="accepted",
        billing_usage_order_id="order-1",
        billing_status="quoted",
        quoted_credits=12,
        captured_credits=4,
        released_credits=8,
        billing_error_code="",
    )

    assert invocation.billing_usage_order_id == "order-1"
    assert invocation.billing_status == "quoted"
    assert invocation.quoted_credits == 12
    assert invocation.captured_credits == 4
    assert invocation.released_credits == 8
    assert invocation.billing_error_code == ""
