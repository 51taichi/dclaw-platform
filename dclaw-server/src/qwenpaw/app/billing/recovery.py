# -*- coding: utf-8 -*-
"""Crash recovery for durable non-OpenAPI billing executions."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.engine import Engine

from .pricing import PriceCatalogService
from .usage import SettleModelCall, UsageExecutionGuard, UsageService
from ..storage.engine import get_app_engine
from ..storage.repos.billing_execution_repo import (
    BillingExecutionFence,
    BillingExecutionRecord,
    BillingExecutionRepository,
)
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.price_catalog_repo import PriceCatalogRepository


def recover_general_billing(engine: Engine | None = None) -> int:
    """Recover expired general executions exactly once.

    Paused executions are deliberate durable checkpoints and are never
    treated as crashed work. Active leases likewise remain owned by their
    live producer.
    """
    active_engine = engine or get_app_engine()
    execution_repository = BillingExecutionRepository(active_engine)
    repository = BillingRepository(active_engine)
    usage_service = UsageService(
        repository,
        PriceCatalogService(PriceCatalogRepository(active_engine)),
        mode="enforced",
    )
    recovered = 0
    for execution in execution_repository.list_recoverable():
        fence = _claim_recovery(execution_repository, execution)
        if fence is None or execution.usage_order_id is None:
            continue
        order_id = execution.usage_order_id
        guard = UsageExecutionGuard(
            kind="general",
            execution_id=execution.id,
            owner_token=fence.owner_token,
            generation=fence.generation,
        )
        for item in usage_service.list_items(order_id):
            if str(item["status"]) != "held":
                continue
            usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=order_id,
                    item_key=str(item["item_key"]),
                    supplier_reference="",
                    billability="not_billable",
                    execution_outcome="failed",
                    evidence={
                        "adapter_version": "general-recovery-v1",
                        "response_class": "recovered_before_provider_contact",
                        "timestamp": datetime.now(timezone.utc).isoformat(
                            timespec="seconds",
                        ),
                    },
                    execution_guard=guard,
                ),
            )

        items = usage_service.list_items(order_id)
        if any(str(item["status"]) == "reconciling" for item in items):
            state = "reconciling"
            error_code = "RECOVERY_RECONCILING"
        elif items and all(
            str(item["execution_outcome"]) == "succeeded" for item in items
        ):
            state = "succeeded"
            error_code = None
        else:
            state = "failed"
            error_code = "PROCESS_RESTARTED"
        if execution_repository.finalize(
            execution.id,
            fence,
            state=state,
            error_code=error_code,
        ):
            recovered += 1
    return recovered


def _claim_recovery(
    repository: BillingExecutionRepository,
    execution: BillingExecutionRecord,
) -> BillingExecutionFence | None:
    owner_token = f"recovery:{uuid4().hex}"
    if execution.state == "accepted":
        return repository.claim(
            execution.id,
            owner_token,
            lease_seconds=30,
        )
    return repository.takeover(
        execution.id,
        owner_token,
        lease_seconds=30,
    )


__all__ = ["recover_general_billing"]
