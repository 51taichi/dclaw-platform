# -*- coding: utf-8 -*-
"""Billing preparation shared by authenticated user entry points."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from typing import Any, Iterator, Mapping
from uuid import uuid4

from sqlalchemy import func, select, update

from .context import BillingSession, BillingSource, billing_context
from .coordinator import BillingCommand, BillingCoordinator
from .model_meter import BillingModelMeter
from .pricing import PriceCatalogService
from .usage import UsageService
from ..storage.engine import get_app_engine
from ..storage.repos.billing_execution_repo import (
    BillingExecutionFence,
    BillingExecutionRepository,
)
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from ..storage.schema import (
    billing_executions,
    billing_usage_orders,
    expert_team_member_runs,
    expert_team_runs,
)


class BillingExecutionClaimError(RuntimeError):
    """The prepared execution could not acquire durable ownership."""


@dataclass
class PreparedBillingExecution:
    """A claimed request execution owned by a TaskTracker producer."""

    session: BillingSession
    fence: BillingExecutionFence
    execution_repository: BillingExecutionRepository
    meter: BillingModelMeter
    usage_service: UsageService

    @contextmanager
    def activate(self) -> Iterator[None]:
        """Install billing for the complete producer lifetime."""
        with billing_context(self.session, self.fence, self.meter):
            yield

    def finalize(self, state: str, error_code: str | None = None) -> bool:
        """Finalize only while this producer still owns the execution."""
        return self.execution_repository.finalize(
            self.session.execution_id,
            self.fence,
            state=state,
            error_code=error_code,
        )

    def finalize_completed(self) -> bool:
        """Converge success to reconciling when any model item is unknown."""
        items = self.usage_service.list_items(self.session.usage_order_id)
        state = (
            "reconciling"
            if any(str(item["status"]) == "reconciling" for item in items)
            else "succeeded"
        )
        return self.finalize(state)

    def renew(self, *, lease_seconds: float = 600) -> bool:
        """Extend this producer's execution lease while it still owns it."""
        return self.execution_repository.renew(
            self.session.execution_id,
            self.fence,
            lease_seconds=lease_seconds,
        )

    def pause_insufficient(
        self,
        *,
        next_member_key: str,
        required_credits: int,
    ) -> bool:
        """Persist a resumable insufficient-balance checkpoint."""
        return self.execution_repository.pause_for_insufficient_balance(
            self.session.execution_id,
            self.fence,
            resume_state_json=json.dumps(
                {
                    "next_member_key": next_member_key,
                    "required_credits": required_credits,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )

    def pause_expert_team_insufficient(
        self,
        *,
        run_id: str,
        payer_user_id: str,
        next_member_key: str,
        required_credits: int,
    ) -> bool:
        """Atomically pause the team checkpoint and its billing owner."""
        resume_json = json.dumps(
            {
                "next_member_key": next_member_key,
                "required_credits": required_credits,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            with self.execution_repository.engine.begin() as conn:
                team_result = conn.execute(
                    update(expert_team_runs)
                    .where(
                        expert_team_runs.c.id == run_id,
                        expert_team_runs.c.user_id == str(payer_user_id),
                        expert_team_runs.c.state == "running",
                    )
                    .values(
                        state="paused_insufficient_balance",
                        next_member_key=next_member_key,
                        required_credits=required_credits,
                        billing_usage_order_id=self.session.usage_order_id,
                        error=None,
                        updated_at=func.current_timestamp(),
                    ),
                )
                execution_result = conn.execute(
                    update(billing_executions)
                    .where(
                        billing_executions.c.id == self.session.execution_id,
                        billing_executions.c.state == "running",
                        billing_executions.c.owner_token
                        == self.fence.owner_token,
                        billing_executions.c.fence_generation
                        == self.fence.generation,
                        billing_executions.c.lease_expires_at
                        > func.current_timestamp(),
                    )
                    .values(
                        state="paused_insufficient_balance",
                        owner_token=None,
                        lease_expires_at=None,
                        resume_state_json=resume_json,
                        error_code="INSUFFICIENT_CREDITS",
                        updated_at=func.current_timestamp(),
                    ),
                )
                if team_result.rowcount != 1 or execution_result.rowcount != 1:
                    raise BillingExecutionClaimError(
                        "expert team billing pause lost ownership",
                    )
                conn.execute(
                    update(expert_team_member_runs)
                    .where(
                        expert_team_member_runs.c.run_id == run_id,
                        expert_team_member_runs.c.member_key
                        == next_member_key,
                        expert_team_member_runs.c.state == "running",
                    )
                    .values(
                        state="pending",
                        updated_at=func.current_timestamp(),
                    ),
                )
            return True
        except BillingExecutionClaimError:
            return False


def _meter_for_source(
    usage_service: UsageService,
    source: BillingSource,
) -> BillingModelMeter:
    """Use the same base/expert budgets for all authenticated entry points."""
    from ..sealed_agents.registry import get_sealed_agent_registry

    output_tokens = 2048
    if source.expert_id:
        record = get_sealed_agent_registry().get_agent(source.expert_id)
        if (
            record is not None
            and record.enabled
            and record.active_release is not None
        ):
            from ...plugins.registry import PluginRegistry

            if PluginRegistry().sealed_package_type_supports(
                record.active_release.package_type,
                "extended_output",
            ):
                output_tokens = 4096
    return BillingModelMeter(
        usage_service,
        default_max_output_tokens=output_tokens,
    )


def prepare_user_billing_execution(
    payer_user_id: str,
    source: BillingSource,
    request_key: str,
    request_fingerprint: Mapping[str, Any],
    *,
    lease_seconds: float = 300,
) -> PreparedBillingExecution:
    """Create and claim one enforced user billing execution."""
    engine = get_app_engine()
    repository = BillingRepository(engine)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    session = BillingCoordinator(repository, pricing).begin_execution(
        BillingCommand(
            payer_user_id=payer_user_id,
            source=source,
            request_key=request_key,
            payload=request_fingerprint,
        ),
    )
    execution_repository = BillingExecutionRepository(engine)
    fence = execution_repository.claim(
        session.execution_id,
        f"user-entrypoint:{uuid4()}",
        lease_seconds=lease_seconds,
    )
    if fence is None:
        raise BillingExecutionClaimError(
            "billing execution is already owned or terminal",
        )
    usage_service = UsageService(repository, pricing, mode="enforced")
    return PreparedBillingExecution(
        session=session,
        fence=fence,
        execution_repository=execution_repository,
        meter=_meter_for_source(usage_service, session.source),
        usage_service=usage_service,
    )


def resume_user_billing_execution(
    usage_order_id: str,
    payer_user_id: str,
    *,
    lease_seconds: float = 300,
) -> PreparedBillingExecution | None:
    """Claim and reconstruct the original paused user billing execution."""
    engine = get_app_engine()
    execution_repository = BillingExecutionRepository(engine)
    record = execution_repository.get_by_usage_order(usage_order_id)
    if (
        record is None
        or record.payer_user_id != str(payer_user_id)
        or record.state != "paused_insufficient_balance"
    ):
        return None
    fence = execution_repository.claim_paused(
        record.id,
        f"user-resume:{uuid4()}",
        lease_seconds=lease_seconds,
    )
    if fence is None:
        return None
    with engine.connect() as conn:
        order = (
            conn.execute(
                select(billing_usage_orders).where(
                    billing_usage_orders.c.id == usage_order_id,
                ),
            )
            .mappings()
            .one()
        )
    request_snapshot = json.loads(order["request_snapshot_json"] or "{}")
    source_snapshot = request_snapshot.get("source") or {}
    price_snapshot = json.loads(order["price_snapshot_json"] or "{}")
    session = BillingSession(
        execution_id=record.id,
        usage_order_id=usage_order_id,
        wallet_id=str(order["wallet_id"]),
        payer_user_id=str(payer_user_id),
        catalog_version=str(price_snapshot["catalog_version"]),
        source=BillingSource(
            type=record.source_type,
            id=record.source_id,
            expert_id=source_snapshot.get("expert_id"),
            expert_team_run_id=source_snapshot.get("expert_team_run_id"),
        ),
        mode="enforced",
    )
    repository = BillingRepository(engine)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    usage_service = UsageService(repository, pricing, mode="enforced")
    return PreparedBillingExecution(
        session=session,
        fence=fence,
        execution_repository=execution_repository,
        meter=_meter_for_source(usage_service, session.source),
        usage_service=usage_service,
    )


__all__ = [
    "BillingExecutionClaimError",
    "PreparedBillingExecution",
    "prepare_user_billing_execution",
    "resume_user_billing_execution",
]
