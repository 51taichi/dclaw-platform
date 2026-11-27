# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, insert, select

from qwenpaw.app.billing.shadow_backfill import ShadowChargeBackfill
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.schema import (
    billing_ledger_entries,
    billing_price_catalogs,
    billing_reconciliation_audits,
    billing_rollout_settings,
    billing_usage_items,
    billing_usage_orders,
    create_all,
    users,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "shadow-backfill.db")},
    )
    value = create_engine_from_settings(settings)
    create_all(value)
    try:
        yield value
    finally:
        value.dispose()


def _seed_shadow_usage(engine) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    repo = BillingRepository(engine)
    with engine.begin() as conn:
        admin_id = conn.execute(
            insert(users).values(
                username="szzz_admin",
                password_hash="hash",
                password_salt="salt",
                role="admin",
                billing_overdraft_enabled=True,
            ),
        ).inserted_primary_key[0]
        user_id = conn.execute(
            insert(users).values(
                username="ordinary",
                password_hash="hash",
                password_salt="salt",
                role="user",
            ),
        ).inserted_primary_key[0]
        conn.execute(
            insert(billing_price_catalogs).values(
                id="catalog",
                version="v1",
                status="published",
            ),
        )
        conn.execute(
            insert(billing_rollout_settings).values(
                id="global",
                mode="enforced",
                billing_cutover_at=now,
                updated_by="admin",
            ),
        )
    admin_wallet = repo.ensure_wallet("user", str(admin_id))
    user_wallet = repo.ensure_wallet("user", str(user_id))
    repo.grant(
        admin_wallet["id"],
        credits=2,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="admin-grant",
    )
    repo.grant(
        user_wallet["id"],
        credits=2,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="user-grant",
    )
    with engine.begin() as conn:
        for name, wallet in (("admin", admin_wallet), ("user", user_wallet)):
            conn.execute(
                insert(billing_usage_orders).values(
                    id=f"order-{name}",
                    wallet_id=wallet["id"],
                    catalog_id="catalog",
                    business_key=f"request-{name}",
                    source_type="open_api",
                    status="settled",
                    provider_id="dashscope",
                    model_key="qwen",
                    capability="chat",
                    quoted_credits=5,
                    captured_credits=5,
                    request_snapshot_json=json.dumps(
                        {"billing_mode": "shadow"},
                    ),
                    created_at=now - timedelta(days=1),
                ),
            )
            conn.execute(
                insert(billing_usage_items).values(
                    id=f"item-{name}",
                    usage_order_id=f"order-{name}",
                    item_key="model-1",
                    status="captured",
                    provider_id="dashscope",
                    model_key="qwen",
                    capability="chat",
                    input_tokens=100,
                    output_tokens=20,
                    charged_credits=5,
                    billability="billable",
                    execution_outcome="succeeded",
                    created_at=now - timedelta(days=1),
                ),
            )
    return {
        "admin_wallet": admin_wallet["id"],
        "user_wallet": user_wallet["id"],
    }


def test_preview_is_read_only_and_reports_admin_debt_and_user_cap(engine):
    wallets = _seed_shadow_usage(engine)
    service = ShadowChargeBackfill(engine)

    result = service.run(apply=False)

    assert result == {
        "mode": "preview",
        "eligible_items": 2,
        "already_processed_items": 0,
        "desired_credits": 10,
        "charged_credits": 7,
        "uncollected_credits": 3,
        "admin_debt_credits": 3,
    }
    repo = BillingRepository(engine)
    assert repo.balance(wallets["admin_wallet"]).available == 2
    assert repo.balance(wallets["user_wallet"]).available == 2
    with engine.connect() as conn:
        audit_count = select(func.count()).select_from(
            billing_reconciliation_audits,
        )
        assert conn.scalar(audit_count) == 0


def test_apply_charges_admin_debt_caps_user_and_is_idempotent(engine):
    wallets = _seed_shadow_usage(engine)
    service = ShadowChargeBackfill(engine)

    first = service.run(apply=True)
    second = service.run(apply=True)

    assert first["charged_credits"] == 7
    assert first["uncollected_credits"] == 3
    assert second == {
        "mode": "apply",
        "eligible_items": 2,
        "already_processed_items": 2,
        "desired_credits": 0,
        "charged_credits": 0,
        "uncollected_credits": 0,
        "admin_debt_credits": 0,
    }
    repo = BillingRepository(engine)
    admin = repo.balance(wallets["admin_wallet"])
    ordinary = repo.balance(wallets["user_wallet"])
    assert (admin.available, admin.debt) == (-3, 3)
    assert (ordinary.available, ordinary.debt) == (0, 0)
    with engine.connect() as conn:
        captures = conn.execute(
            select(
                billing_ledger_entries.c.business_key,
                billing_ledger_entries.c.credit_delta,
            )
            .where(billing_ledger_entries.c.event_type == "usage_capture")
            .order_by(billing_ledger_entries.c.business_key),
        ).all()
        assert captures == [
            ("open-api-item:order-admin:model-1", -5),
            ("open-api-item:order-user:model-1", -2),
        ]
        audits = conn.execute(
            select(
                billing_reconciliation_audits.c.usage_item_id,
                billing_reconciliation_audits.c.charged_credits,
            ).order_by(billing_reconciliation_audits.c.usage_item_id),
        ).all()
        assert audits == [("item-admin", 5), ("item-user", 2)]
