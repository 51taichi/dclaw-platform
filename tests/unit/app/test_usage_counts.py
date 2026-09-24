# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from sqlalchemy import insert

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import (
    billing_price_catalogs,
    billing_usage_orders,
    billing_wallets,
    create_all,
)
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.app.usage_counts import get_settled_agent_usage_counts


def test_settled_agent_usage_counts_ignore_unsettled_and_invalid_rows(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "usage-counts.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)

    def order(order_id: str, status: str, expert_id: str | None):
        source = {"type": "client", "id": order_id}
        if expert_id is not None:
            source["expert_id"] = expert_id
        return {
            "id": order_id,
            "wallet_id": "wallet-1",
            "catalog_id": "catalog-1",
            "business_key": f"business-{order_id}",
            "source_type": "client",
            "source_id": order_id,
            "status": status,
            "provider_id": "request",
            "model_key": "request",
            "capability": "text",
            "request_snapshot_json": json.dumps({"source": source}),
            "price_snapshot_json": "{}",
        }

    with engine.begin() as conn:
        conn.execute(
            insert(billing_wallets).values(
                id="wallet-1",
                owner_type="user",
                owner_id="user-1",
            ),
        )
        conn.execute(
            insert(billing_price_catalogs).values(
                id="catalog-1",
                version="test-v1",
            ),
        )
        conn.execute(
            insert(billing_usage_orders),
            [
                order("settled-1", "settled", "luyu"),
                order("settled-2", "settled", "luyu"),
                order("quoted", "quoted", "luyu"),
                order("other", "settled", "default"),
                order("missing", "settled", None),
            ],
        )
        conn.execute(
            insert(billing_usage_orders).values(
                **{
                    **order("invalid", "settled", None),
                    "request_snapshot_json": "not-json",
                },
            ),
        )

    assert get_settled_agent_usage_counts(engine) == {
        "luyu": 2,
        "default": 1,
    }

    engine.dispose()
