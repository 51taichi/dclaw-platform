# -*- coding: utf-8 -*-
"""One-time, auditable collection of historical shadow-mode usage."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, insert, select
from sqlalchemy.engine import Engine

from .models import LedgerTransaction
from ..storage.repos.billing_repo import BillingRepository
from ..storage.schema import (
    billing_reconciliation_audits,
    billing_rollout_settings,
    billing_usage_items,
    billing_usage_orders,
    billing_wallets,
    users,
)


class ShadowChargeBackfill:
    """Collect settled shadow charges once, through the immutable ledger."""

    marker_prefix = "historical-shadow-backfill:v1"

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.repository = BillingRepository(engine)

    def run(self, *, apply: bool = False) -> dict[str, int | str]:
        setting = self._rollout_setting()
        cutover = setting["billing_cutover_at"]
        if setting["mode"] != "enforced" or cutover is None:
            raise RuntimeError(
                "billing rollout must be enforced with billing_cutover_at",
            )
        rows = self._eligible_rows(cutover)
        processed = self._processed_item_ids()
        pending = [row for row in rows if row["item_id"] not in processed]
        projected = self._project(pending)
        if apply:
            charged = uncollected = admin_debt = 0
            for row in pending:
                result = self._apply_item(row)
                charged += result["charged"]
                uncollected += result["uncollected"]
                admin_debt += result["admin_debt"]
            projected = {
                "desired": sum(int(row["desired"]) for row in pending),
                "charged": charged,
                "uncollected": uncollected,
                "admin_debt": admin_debt,
            }
        return {
            "mode": "apply" if apply else "preview",
            "eligible_items": len(rows),
            "already_processed_items": len(rows) - len(pending),
            "desired_credits": projected["desired"],
            "charged_credits": projected["charged"],
            "uncollected_credits": projected["uncollected"],
            "admin_debt_credits": projected["admin_debt"],
        }

    def _rollout_setting(self) -> dict[str, Any]:
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(billing_rollout_settings).where(
                        billing_rollout_settings.c.id == "global",
                    ),
                )
                .mappings()
                .first()
            )
        if row is None:
            raise RuntimeError("billing rollout setting is missing")
        return dict(row)

    def _eligible_rows(self, cutover: datetime) -> list[dict[str, Any]]:
        wallet_matches_order = (  # noqa: E501
            billing_usage_orders.c.wallet_id == billing_wallets.c.id
        )
        wallet_matches_user = billing_wallets.c.owner_id == users.c.id.cast(
            billing_wallets.c.owner_id.type
        )
        with self.engine.connect() as conn:
            records = conn.execute(
                select(
                    billing_usage_items.c.id.label("item_id"),
                    billing_usage_items.c.item_key,
                    billing_usage_items.c.input_tokens,
                    billing_usage_items.c.output_tokens,
                    billing_usage_items.c.charged_credits.label("desired"),
                    billing_usage_orders.c.id.label("order_id"),
                    billing_usage_orders.c.source_type,
                    billing_usage_orders.c.request_snapshot_json,
                    billing_usage_orders.c.created_at,
                    billing_wallets.c.id.label("wallet_id"),
                    users.c.username,
                    users.c.billing_overdraft_enabled,
                )
                .select_from(
                    billing_usage_items.join(
                        billing_usage_orders,
                        billing_usage_items.c.usage_order_id
                        == billing_usage_orders.c.id,
                    )
                    .join(
                        billing_wallets,
                        wallet_matches_order,
                    )
                    .join(
                        users,
                        and_(
                            billing_wallets.c.owner_type == "user",
                            wallet_matches_user,
                        ),
                    ),
                )
                .where(
                    billing_usage_orders.c.status == "settled",
                    billing_usage_orders.c.created_at < cutover,
                    billing_usage_items.c.status == "captured",
                    billing_usage_items.c.charged_credits > 0,
                )
                .order_by(
                    billing_usage_orders.c.created_at,
                    billing_usage_items.c.created_at,
                    billing_usage_items.c.id,
                ),
            ).mappings()
            result = []
            for record in records:
                snapshot = json.loads(record["request_snapshot_json"] or "{}")
                if snapshot.get("billing_mode") == "shadow":
                    result.append(dict(record))
            return result

    def _processed_item_ids(self) -> set[str]:
        item_id = billing_reconciliation_audits.c.usage_item_id
        with self.engine.connect() as conn:
            return set(
                conn.scalars(
                    select(item_id).where(
                        billing_reconciliation_audits.c.idempotency_key.like(
                            f"{self.marker_prefix}:%",
                        ),
                    ),
                ),
            )

    def _project(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        available: dict[str, int] = {}
        totals = defaultdict(
            int,
            desired=0,
            charged=0,
            uncollected=0,
            admin_debt=0,
        )
        for row in rows:
            wallet_id = str(row["wallet_id"])
            if wallet_id not in available:
                available[wallet_id] = self.repository.balance(
                    wallet_id,
                ).funded_available
            desired = int(row["desired"])
            if row["username"] == "szzz_admin":
                if not row["billing_overdraft_enabled"]:
                    raise RuntimeError("szzz_admin overdraft is not enabled")
                charged = desired
                debt = max(desired - available[wallet_id], 0)
            else:
                charged = min(desired, available[wallet_id])
                debt = 0
            available[wallet_id] = max(available[wallet_id] - charged, 0)
            totals["desired"] += desired
            totals["charged"] += charged
            totals["uncollected"] += desired - charged
            totals["admin_debt"] += debt
        return dict(totals)

    def _apply_item(self, row: dict[str, Any]) -> dict[str, int]:
        item_id = str(row["item_id"])
        marker = f"{self.marker_prefix}:{item_id}"
        with self.engine.begin() as conn:
            if conn.execute(
                select(billing_reconciliation_audits.c.id).where(
                    billing_reconciliation_audits.c.idempotency_key == marker,
                ),
            ).first():
                return {"charged": 0, "uncollected": 0, "admin_debt": 0}
            wallet_id = str(row["wallet_id"])
            # These helpers keep expiry and wallet locking in this transaction.
            self.repository._expire_available_lots(  # pylint: disable=W0212
                conn,
                wallet_id,
                datetime.now(timezone.utc),
            )
            # pylint: disable-next=protected-access
            balance = self.repository._balance_for_update(
                conn,
                wallet_id,
            )
            desired = int(row["desired"])
            if row["username"] == "szzz_admin":
                if not self.repository.overdraft_enabled_in_connection(
                    conn,
                    wallet_id,
                ):
                    raise RuntimeError("szzz_admin overdraft is not enabled")
                charged = desired
                admin_debt = max(desired - balance.funded_available, 0)
            else:
                charged = min(desired, balance.funded_available)
                admin_debt = 0
            uncollected = desired - charged
            business_key = self._business_key(row)
            metadata = {
                "migration": self.marker_prefix,
                "usage_item_id": item_id,
                "desired_credits": desired,
                "uncollected_credits": uncollected,
            }
            if charged:
                for event in ("usage_hold", "usage_capture"):
                    self.repository.append_transaction_in_connection(
                        conn,
                        LedgerTransaction(
                            wallet_id=wallet_id,
                            event_type=event,
                            credits=charged,
                            business_type="usage",
                            business_key=business_key,
                            idempotency_key=f"{marker}:{event}",
                            actor_type="system",
                            actor_id="historical-shadow-backfill",
                            reason="collect historical settled shadow usage",
                            metadata=metadata,
                        ),
                    )
            request_sha = hashlib.sha256(
                json.dumps(
                    {
                        "item_id": item_id,
                        "desired": desired,
                        "charged": charged,
                    },
                    sort_keys=True,
                ).encode(),
            ).hexdigest()
            conn.execute(
                insert(billing_reconciliation_audits).values(
                    id=str(uuid4()),
                    usage_item_id=item_id,
                    usage_order_id=str(row["order_id"]),
                    idempotency_key=marker,
                    request_sha256=request_sha,
                    actor_id="historical-shadow-backfill",
                    reason=(
                        f"historical shadow charge; desired={desired}; "
                        f"uncollected={uncollected}"
                    ),
                    billability="billable",
                    actual_input_tokens=int(row["input_tokens"]),
                    actual_output_tokens=int(row["output_tokens"]),
                    charged_credits=charged,
                    previous_status="captured",
                    resolved_status="captured",
                ),
            )
        return {
            "charged": charged,
            "uncollected": uncollected,
            "admin_debt": admin_debt,
        }

    @staticmethod
    def _business_key(row: dict[str, Any]) -> str:
        is_open_api = row.get("source_type") == "open_api"
        prefix = "open-api-item" if is_open_api else "billing-item"
        return f"{prefix}:{row['order_id']}:{row['item_key']}"
