# -*- coding: utf-8 -*-
"""Billing preparation shared by authenticated user entry points."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping
from uuid import uuid4

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
        meter=BillingModelMeter(usage_service),
        usage_service=usage_service,
    )


__all__ = [
    "BillingExecutionClaimError",
    "PreparedBillingExecution",
    "prepare_user_billing_execution",
]
