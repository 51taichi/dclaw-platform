"""Generic durable events, with no installation, conversation or expert fields."""

import asyncio
import math
import time
from typing import Any, Awaitable, Callable, Literal, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ..storage.repos.aigc_execution_repo import AigcExecutionRepository


class AigcDomainEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    schema_version: Literal[1] = 1
    owner_user_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    resource_version: int = Field(ge=1)
    event_type: Literal["job.succeeded", "job.failed", "asset.ready", "resource.changed"]
    operation_id: str = Field(min_length=1)
    payload: dict[str, Any]


class AigcDeliveryOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["delivered", "blocked", "retry"] = "delivered"
    error_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{1,80}$")


class AigcEventConsumer:
    """Bounded at-least-once delivery; adapters must make their effects idempotent."""

    def __init__(self, repository: "AigcExecutionRepository", consumer_id: str,
                 handler: Callable[[AigcDomainEvent], Awaitable[AigcDeliveryOutcome | None]],
                 *, timeout_seconds: float = 10, clock: Callable[[], float] = time.time):
        if not consumer_id.strip() or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("INVALID_EVENT_CONSUMER")
        self.repository = repository
        self.consumer_id = consumer_id
        self.handler = handler
        self.timeout_seconds = timeout_seconds
        self.clock = clock

    async def deliver_pending(self, limit: int = 100) -> int:
        completed = 0
        for _ in range(max(0, min(limit, 100))):
            # Yield before claiming, so cancellation never reserves an entire batch.
            await asyncio.sleep(0)
            claims = self.repository.claim_domain_events(
                self.consumer_id, now=self.clock(), limit=1,
                lease_seconds=max(30, self.timeout_seconds * 2),
            )
            if not claims:
                break
            claim = claims[0]
            try:
                outcome = await asyncio.wait_for(self.handler(claim["event"]), self.timeout_seconds)
                outcome = outcome or AigcDeliveryOutcome()
            except asyncio.TimeoutError:
                outcome = AigcDeliveryOutcome(status="retry", error_code="DELIVERY_TIMEOUT")
            except Exception:
                outcome = AigcDeliveryOutcome(status="retry", error_code="DELIVERY_FAILED")
            # CancelledError is deliberately not acknowledged: another worker can
            # reclaim it after the lease. Never persist raw exception text.
            acknowledged = self.repository.complete_domain_delivery(
                self.consumer_id, claim["event"].event_id, claim["lease_token"],
                now=self.clock(), outcome=outcome.status, error_code=outcome.error_code,
            )
            if acknowledged and outcome.status == "delivered":
                completed += 1
        return completed
