"""Application adapter from durable AIGC events to the existing UI event bus."""

import asyncio
from contextlib import suppress
import logging
import time

from ..aigc.events import AigcDeliveryOutcome, AigcDomainEvent, AigcEventConsumer
from ..aigc.job_lifecycle import AigcJobLifecycle
from ..storage.repos.aigc_execution_repo import AigcExecutionRepository
from .event_bus import RuntimeEvent, RuntimeEventBus

logger = logging.getLogger(__name__)


class AigcRuntimeNotifications:
    def __init__(self, repository: AigcExecutionRepository, bus: RuntimeEventBus, *, clock=time.time):
        self.repository = repository
        self.bus = bus
        self.consumer = AigcEventConsumer(repository, "aigc-runtime-ui-v1", self._publish, clock=clock)

    async def _publish(self, event: AigcDomainEvent) -> AigcDeliveryOutcome | None:
        cancelled = event.event_type == "resource.changed" and event.payload.get("status") == "cancelled"
        if event.event_type not in {"job.succeeded", "job.failed"} and not cancelled:
            return None
        current = self.repository.get_job_result(event.resource_id)
        if (current is None or current["owner_user_id"] != event.owner_user_id
                or current["resource_version"] != event.resource_version):
            return AigcDeliveryOutcome(status="blocked", error_code="OBSOLETE_JOB_RESULT")
        payload = {key: event.payload[key] for key in (
            "job_id", "canvas_id", "node_id", "capability", "provider_id", "model_id",
            "status", "output_count", "updated_at",
        )}
        # Preserve the UI error field without rebroadcasting arbitrary provider
        # response text, signed asset URLs, local paths or credentials.
        payload["error"] = "AIGC_GENERATION_FAILED" if payload["status"] == "failed" else None
        payload["domain_event_id"] = event.event_id
        payload["resource_version"] = event.resource_version
        await self.bus.publish(RuntimeEvent(
            type="aigc.job.updated", scope="aigc", job_id=event.resource_id,
            status=payload["status"], message=f"AIGC job {payload['status']}", payload=payload,
        ))
        return None

    async def deliver_pending(self, limit: int = 100) -> int:
        return await self.consumer.deliver_pending(limit=limit)


class AigcRecoveryWorker:
    """Recover local projections and deliver events; never submit provider work."""

    def __init__(self, lifecycle: AigcJobLifecycle, consumers: list):
        self.lifecycle = lifecycle
        self.consumers = consumers
        self._task: asyncio.Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> None:
        try:
            rows = await self._blocking(self.lifecycle.repository.pending_job_results, 100)
            for row in rows:
                await self._blocking(self.lifecycle.project_result, row)
        except Exception:
            logger.warning("AIGC projection recovery temporarily unavailable")
        for consumer in self.consumers:
            try:
                await consumer.deliver_pending(limit=100)
            except Exception:
                logger.warning("AIGC event delivery temporarily unavailable")

    @staticmethod
    async def _blocking(function, *args):
        # Cancellation does not stop a Python thread. Drain this one atomic
        # projection before shutdown; never start the rest of the batch.
        pending = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            with suppress(Exception):
                await pending
            raise

    async def _run(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(5)

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
