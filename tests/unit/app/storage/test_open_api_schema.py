# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, inspect, text
from sqlalchemy.exc import IntegrityError

import qwenpaw.app.storage.schema as schema_module
from qwenpaw.app.open_api.models import OpenApiInvocation
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def _engine(tmp_path, name: str):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / name)}
    )
    return create_engine_from_settings(settings)


def _insert_invocation_dependencies(conn):
    conn.execute(
        text(
            "INSERT INTO open_api_external_apps (id, owner_user_id, name) "
            "VALUES ('app-1', 'user-1', 'App')"
        ),
    )
    conn.execute(
        text(
            "INSERT INTO open_api_publications ("
            "id, public_id, target_type, target_id, owner_user_id, "
            "bound_user_id, knowledge_base_id, name) VALUES ("
            "'pub-1', 'public-1', 'agent', 'agent-1', 'user-1', "
            "'user-1', 'knowledge-1', 'Publication')"
        ),
    )
    conn.execute(
        text(
            "INSERT INTO open_api_keys ("
            "id, app_id, publication_id, key_hash, key_prefix, key_suffix) "
            "VALUES ('key-1', 'app-1', 'pub-1', 'hash-1', 'prefix', 'suffix')"
        ),
    )
    conn.execute(
        text(
            "INSERT INTO billing_wallets (id, owner_type, owner_id) "
            "VALUES ('wallet-1', 'user', 'user-1')"
        ),
    )
    conn.execute(
        text(
            "INSERT INTO billing_price_catalogs (id, version) "
            "VALUES ('catalog-1', 'v1')"
        ),
    )
    conn.execute(
        text(
            "INSERT INTO billing_usage_orders ("
            "id, wallet_id, catalog_id, business_key, provider_id, model_key, "
            "capability, source_type, source_id) VALUES ("
            "'order-1', 'wallet-1', 'catalog-1', 'order-business-1', "
            "'provider', 'model', 'chat', 'open_api', 'inv-1')"
        ),
    )


def _insert_invocation(conn, invocation_id: str, order_id: str, **values):
    columns = {
        "id": invocation_id,
        "app_id": "app-1",
        "publication_id": "pub-1",
        "api_key_id": "key-1",
        "target_type": "agent",
        "target_id": "agent-1",
        "status": "accepted",
        "billing_usage_order_id": order_id,
        **values,
    }
    names = ", ".join(columns)
    placeholders = ", ".join(f":{name}" for name in columns)
    conn.execute(
        text(
            f"INSERT INTO open_api_invocations ({names}) "
            f"VALUES ({placeholders})"
        ),
        columns,
    )


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
            "execution_owner_token",
            "execution_claimed_at",
            "expert_team_run_id",
            "terminal_event_json",
        } <= invocations
        items = {
            column["name"]
            for column in inspect(engine).get_columns("billing_usage_items")
        }
        assert "execution_outcome" in items

        reflected = {
            column["name"]: column
            for column in inspect(engine).get_columns("open_api_invocations")
        }
        assert all(
            isinstance(reflected[name]["type"], BigInteger)
            for name in (
                "quoted_credits",
                "captured_credits",
                "released_credits",
            )
        )
        check_names = {
            check["name"]
            for check in inspect(engine).get_check_constraints(
                "open_api_invocations"
            )
        }
        assert {
            "ck_open_api_invocations_quoted_nonnegative",
            "ck_open_api_invocations_captured_nonnegative",
            "ck_open_api_invocations_released_nonnegative",
        } <= check_names

        with engine.begin() as conn:
            _insert_invocation_dependencies(conn)
            with pytest.raises(IntegrityError):
                _insert_invocation(
                    conn,
                    "fresh-negative",
                    "order-1",
                    quoted_credits=-1,
                )
    finally:
        engine.dispose()


# pylint: disable=too-many-statements
def test_open_api_billing_upgrade_is_idempotent_and_preserves_history(
    tmp_path,
):
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
                    "token_summary TEXT, error_summary TEXT, "
                    "created_at DATETIME)",
                ),
            )
            conn.execute(
                text(
                    "INSERT INTO open_api_invocations ("
                    "id, app_id, publication_id, api_key_id, target_type, "
                    "target_id, status) VALUES ("
                    "'historic-invocation', 'historic-app', "
                    "'historic-publication', "
                    "'historic-key', 'agent', 'historic-agent', 'accepted')"
                ),
            )
            conn.execute(
                text(
                    "CREATE TABLE billing_usage_orders ("
                    "id VARCHAR PRIMARY KEY, wallet_id VARCHAR, "
                    "catalog_id VARCHAR, price_rule_id VARCHAR, "
                    "business_key VARCHAR, status VARCHAR, "
                    "provider_id VARCHAR, model_key VARCHAR, "
                    "capability VARCHAR, "
                    "quoted_credits BIGINT, held_credits BIGINT, "
                    "captured_credits BIGINT, request_snapshot_json TEXT, "
                    "price_snapshot_json TEXT, supplier_reference VARCHAR, "
                    "supplier_evidence_json TEXT, billability VARCHAR, "
                    "created_at DATETIME, updated_at DATETIME, "
                    "submitted_at DATETIME, "
                    "settled_at DATETIME)",
                ),
            )
            conn.execute(
                text(
                    "CREATE TABLE billing_usage_items ("
                    "id VARCHAR PRIMARY KEY, usage_order_id VARCHAR, "
                    "price_rule_id VARCHAR, status VARCHAR, "
                    "provider_id VARCHAR, model_key VARCHAR, "
                    "capability VARCHAR, supplier_reference VARCHAR, "
                    "input_tokens BIGINT, output_tokens BIGINT, "
                    "quantity BIGINT, "
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
                    "INSERT INTO billing_usage_orders ("
                    "id, wallet_id, catalog_id, business_key, status, "
                    "provider_id, "
                    "model_key, capability, quoted_credits, held_credits, "
                    "captured_credits, billability) VALUES ("
                    "'historic-order', 'historic-wallet', 'historic-catalog', "
                    "'historic-business', 'quoted', 'provider', "
                    "'model', 'chat', "
                    "1, 0, 0, 'unknown')"
                ),
            )
            conn.execute(
                text(
                    "INSERT INTO billing_usage_items ("
                    "id, usage_order_id, status, provider_id, model_key, "
                    "capability, "
                    "input_tokens, output_tokens, quantity, charged_credits, "
                    "supplier_cost_fen) VALUES ("
                    "'historic-item', 'historic-order', 'quoted', 'provider', "
                    "'model', 'chat', 0, 0, 0, 0, 0)"
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
            "execution_owner_token",
            "execution_claimed_at",
            "expert_team_run_id",
            "terminal_event_json",
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
            "execution_outcome",
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
        assert {"billing_usage_orders"} <= {
            foreign_key["referred_table"]
            for foreign_key in inspector.get_foreign_keys(
                "open_api_invocations"
            )
        }

        order_checks = {
            check["name"]
            for check in inspector.get_check_constraints(
                "billing_usage_orders"
            )
        }
        item_checks = {
            check["name"]
            for check in inspector.get_check_constraints("billing_usage_items")
        }
        invocation_checks = {
            check["name"]
            for check in inspector.get_check_constraints(
                "open_api_invocations"
            )
        }
        assert {
            "ck_billing_usage_orders_budget_nonnegative",
            "ck_billing_usage_orders_released_nonnegative",
            "ck_billing_usage_orders_reconciling_nonnegative",
            "ck_billing_usage_orders_billability",
        } <= order_checks
        assert {
            "ck_billing_usage_items_quoted_nonnegative",
            "ck_billing_usage_items_billability",
        } <= item_checks
        assert {
            "ck_open_api_invocations_quoted_nonnegative",
            "ck_open_api_invocations_captured_nonnegative",
            "ck_open_api_invocations_released_nonnegative",
        } <= invocation_checks

        with engine.begin() as conn:
            assert conn.execute(
                text(
                    "SELECT model_name, prompt_tokens, completion_tokens "
                    "FROM token_usage_logs WHERE id = 'token-before-cutover'"
                ),
            ).one() == ("legacy-model", 7, 11)
            assert conn.execute(
                text(
                    "SELECT business_type, business_key "
                    "FROM billing_ledger_entries "
                    "WHERE id = 'ledger-before-cutover'"
                ),
            ).one() == ("legacy", "legacy-key")
            assert conn.execute(
                text(
                    "SELECT billing_status, quoted_credits, captured_credits, "
                    "released_credits, terminal_event_json "
                    "FROM open_api_invocations "
                    "WHERE id = 'historic-invocation'"
                ),
            ).one() == ("unbilled", 0, 0, 0, None)
            assert conn.execute(
                text(
                    "SELECT source_type, source_id FROM billing_usage_orders "
                    "WHERE id = 'historic-order'"
                ),
            ).one() == (None, None)
            assert conn.execute(
                text(
                    "SELECT item_key, execution_outcome "
                    "FROM billing_usage_items "
                    "WHERE id = 'historic-item'"
                ),
            ).one() == (None, "pending")

            _insert_invocation_dependencies(conn)
            with pytest.raises(IntegrityError):
                _insert_invocation(conn, "legacy-dangling", "missing-order")
            with pytest.raises(IntegrityError):
                _insert_invocation(
                    conn,
                    "legacy-negative",
                    "order-1",
                    captured_credits=-1,
                )
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "UPDATE billing_usage_orders "
                        "SET billability = 'invalid' "
                        "WHERE id = 'order-1'"
                    ),
                )
            conn.execute(
                text(
                    "INSERT INTO billing_usage_items ("
                    "id, usage_order_id, item_key, status, provider_id, "
                    "model_key, "
                    "capability, billability) VALUES ("
                    "'item-1', 'order-1', 'item-key-1', 'quoted', 'provider', "
                    "'model', 'chat', 'unknown')"
                ),
            )
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "UPDATE billing_usage_items SET quoted_credits = -1 "
                        "WHERE id = 'item-1'"
                    ),
                )
    finally:
        engine.dispose()


# pylint: enable=too-many-statements


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

    unbilled = OpenApiInvocation(
        id="inv-unbilled",
        app_id="app-1",
        publication_id="pub-1",
        api_key_id="key-1",
        target_type="agent",
        target_id="agent-1",
        status="accepted",
    )
    assert unbilled.billing_status == "unbilled"
    assert (
        unbilled.quoted_credits,
        unbilled.captured_credits,
        unbilled.released_credits,
    ) == (0, 0, 0)


def test_fresh_sqlite_schema_skips_the_legacy_table_rebuild(
    tmp_path, monkeypatch
):
    engine = _engine(tmp_path, "fresh-rebuild-check.db")
    rebuild_calls: list[object] = []
    rebuild = getattr(schema_module, "_rebuild_sqlite_open_api_billing_tables")

    def record_rebuild(rebuild_engine):
        rebuild_calls.append(rebuild_engine)
        rebuild(rebuild_engine)

    monkeypatch.setattr(
        schema_module,
        "_rebuild_sqlite_open_api_billing_tables",
        record_rebuild,
    )
    try:
        create_all(engine)
        assert not rebuild_calls
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("column", "value"),
    (("quoted_credits", -1), ("billability", "invalid")),
)
def test_open_api_billing_upgrade_rejects_invalid_legacy_rows(
    tmp_path,
    column,
    value,
):
    engine = _engine(tmp_path, f"invalid-{column}.db")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE billing_usage_orders ("
                    "id VARCHAR PRIMARY KEY, quoted_credits BIGINT, "
                    "held_credits BIGINT, captured_credits BIGINT, "
                    "billability VARCHAR)"
                ),
            )
            conn.execute(
                text(
                    f"INSERT INTO billing_usage_orders (id, quoted_credits, "
                    f"held_credits, captured_credits, billability) VALUES ("
                    "'invalid-order', "
                    f"{value if column == 'quoted_credits' else 0}, "
                    "0, 0, "
                    f"'{value if column == 'billability' else 'unknown'}')"
                ),
            )

        with pytest.raises(ValueError, match="invalid historical billing"):
            create_all(engine)
    finally:
        engine.dispose()
