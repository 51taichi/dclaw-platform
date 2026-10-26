"""Map durable AIGC progress to the original expert scope, never into review."""

from __future__ import annotations

import json
import asyncio
from contextlib import suppress
import hashlib
from threading import Event
import time
from typing import Callable, Any

from qwenpaw.app.aigc.events import (
    AigcDeliveryOutcome,
    AigcDomainEvent,
    AigcEventConsumer,
)
from qwenpaw.app.aigc.resource_store import AigcResourceError
from qwenpaw.app.aigc.workflow_execution import validate_execution_capability
from qwenpaw.app.runtime.event_bus import RuntimeEvent
from qwenpaw.app.storage.repos.aigc_execution_repo import (
    AigcExecutionRepository,
    job_creation_timestamp,
)
from qwenpaw.app.storage.json_file_lock import JsonFileLock
from .events import SuperExpertEventEnvelope
from .models import AigcTaskStatus
from .service import SuperExpertPlatformService


class AigcEventAdapter:
    def __init__(
        self,
        platform_service: SuperExpertPlatformService,
        execution_repository: AigcExecutionRepository,
        *,
        scope_resolver: Callable[[str], dict[str, Any] | None],
        installation_is_active: Callable[[Any], bool],
        clock=time.time,
        timeout_seconds: float = 10,
    ) -> None:
        self.platform = platform_service
        self.repository = execution_repository
        self.scope_resolver = scope_resolver
        self.installation_is_active = installation_is_active
        self._delivery_locks = JsonFileLock(
            platform_service.event_repository.root,
        )
        self.consumer = AigcEventConsumer(
            execution_repository,
            "super-expert-aigc-v1",
            self._deliver,
            clock=clock,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _blocked(code: str) -> AigcDeliveryOutcome:
        return AigcDeliveryOutcome(status="blocked", error_code=code)

    async def _deliver(
        self,
        event: AigcDomainEvent,
    ) -> AigcDeliveryOutcome | None:
        # Keep one node's fresh validation, persistence and publication ordered
        # across consumers/processes. The worker owns the file lock; the event
        # loop still owns the async bus. Cancellation drains before lock release.
        loop = asyncio.get_running_loop()
        prepared = loop.create_future()
        finished, cancelled = Event(), Event()

        def settle(value=None, error=None):
            if not prepared.done():
                if error is not None:
                    prepared.set_exception(error)
                else:
                    prepared.set_result(value)

        def prepare_ordered():
            try:
                result = self.repository.get_job_result(event.resource_id)
                snapshot = json.loads(result["snapshot"]) if result else {}
                key = hashlib.sha256(
                    json.dumps(
                        [
                            event.owner_user_id,
                            snapshot.get("canvas_id"),
                            snapshot.get("node_id"),
                        ],
                    ).encode(),
                ).hexdigest()
                lock_target = (
                    self._delivery_locks.root / "progress" / f"{key}.json"
                )
                with self._delivery_locks.hold(lock_target):
                    if cancelled.is_set():
                        return
                    value = self._prepare_delivery(event)
                    loop.call_soon_threadsafe(settle, value)
                    finished.wait()
            except Exception as exc:
                loop.call_soon_threadsafe(settle, None, exc)

        pending = asyncio.create_task(asyncio.to_thread(prepare_ordered))
        try:
            value = await prepared
            if isinstance(value, RuntimeEvent):
                await self.platform.event_bus.publish(value)
                return None
            return value
        finally:
            cancelled.set()
            finished.set()
            try:
                await asyncio.shield(pending)
            except asyncio.CancelledError:
                with suppress(Exception):
                    await pending
                raise

    def _prepare_delivery(
        self,
        event: AigcDomainEvent,
    ) -> RuntimeEvent | AigcDeliveryOutcome | None:
        # asset.ready is already represented by the same job's output list.
        # Resource cancellation changes production progress, not expert approval.
        if event.event_type not in {"job.succeeded", "job.failed"} and not (
            event.event_type == "resource.changed"
            and event.payload.get("status") == "cancelled"
        ):
            return None
        result = self.repository.get_job_result(event.resource_id)
        if (
            result is None
            or result["owner_user_id"] != event.owner_user_id
            or result["resource_version"] != event.resource_version
        ):
            return self._blocked("OBSOLETE_JOB_RESULT")
        job = json.loads(result["snapshot"])
        tasks = self.platform.task_repository.find_tasks_for_node(
            canvas_id=job["canvas_id"],
            node_id=job["node_id"],
        )
        if not tasks:
            return self._blocked("NO_EXPERT_BINDING")
        if len(tasks) != 1:
            return self._blocked("AMBIGUOUS_EXPERT_BINDING")
        task = tasks[0]
        binding = task.binding
        if task.status not in {
            AigcTaskStatus.WAITING_TO_START,
            AigcTaskStatus.IN_PROGRESS,
            AigcTaskStatus.PAUSED,
            AigcTaskStatus.REVISION_REQUIRED,
        }:
            return self._blocked("TASK_NO_LONGER_PRODUCING")
        grant = self.platform.grant_repository.get(binding.installation_id)
        if grant is None or not self.installation_is_active(grant):
            return self._blocked("INSTALLATION_UNAVAILABLE")
        scope = self.scope_resolver(binding.conversation_id)
        if (
            not scope
            or str(scope.get("user_id", "")) != event.owner_user_id
            or scope.get("agent_id") != grant.agent_id
            or scope.get("tenant_id", "local") != grant.tenant_id
        ):
            return self._blocked("ORIGINAL_SCOPE_MISMATCH")
        create_capability = (
            "aigc.workflow.create/1"
            if task.workflow is not None
            else "aigc.task.create/2"
            if task.operation_id
            else "aigc.task.create"
        )
        if not self.platform.grant_repository.authorize_capability(
            binding.installation_id,
            create_capability,
            "1",
            tenant_id=grant.tenant_id,
        ).allowed:
            return self._blocked("CAPABILITY_NOT_GRANTED")
        adapter = self.platform.aigc
        if adapter is None:
            return self._blocked("AIGC_SERVICE_UNAVAILABLE")
        try:
            canvas = adapter.canvases.get(
                event.owner_user_id,
                binding.canvas_id,
            )
            head = self.repository.get_node_result(
                binding.canvas_id,
                job["node_id"],
            )
            if (
                head is not None
                and head["job_id"] != job["id"]
                and job_creation_timestamp(job) <= head["job_created_at"]
            ):
                return self._blocked("OBSOLETE_NODE_RESULT")
            if not any(node.id == job["node_id"] for node in canvas.nodes):
                return self._blocked("NODE_UNAVAILABLE")
            if binding.execution_mode == "PREBUILT_WORKFLOW":
                core = self.repository.get_binding(
                    event.owner_user_id,
                    binding.canvas_id,
                    job["node_id"],
                )
                if (
                    core is None
                    or core.workflow_id != binding.workflow_id
                    or core.workflow_revision != binding.workflow_revision
                    or binding.node_bindings.get(core.logical_node_id)
                    != core.node_id
                    or task.workflow.workflow_revision
                    != binding.workflow_revision
                ):
                    return self._blocked("WORKFLOW_REVISION_MISMATCH")
                validate_execution_capability(
                    core,
                    capability=job["capability"],
                )
            for output in job["outputs"]:
                asset = adapter.assets.resolve_owned(
                    event.owner_user_id,
                    output["id"],
                )
                adapter.assets.validate_review_binding(
                    asset,
                    canvas_id=binding.canvas_id,
                    node_ids={job["node_id"]},
                )
                if asset.model_dump(mode="json") != output:
                    return self._blocked("ASSET_REVISION_MISMATCH")
        except AigcResourceError:
            return self._blocked("RESOURCE_UNAVAILABLE")
        except ValueError:
            return self._blocked("WORKFLOW_BINDING_MISMATCH")

        envelope = SuperExpertEventEnvelope(
            event_id=f"aigc-progress:{event.event_id}",
            **binding.model_dump(
                include={
                    "installation_id",
                    "conversation_id",
                    "agent_task_id",
                    "content_revision",
                    "material_task_id",
                    "canvas_id",
                    "node_id",
                },
            ),
            asset_id=task.asset_id,
            event_type="aigc.guide.updated",
            payload={
                "task_status": task.status.value,
                "task_version": task.version,
                "domain_event_id": event.event_id,
                "resource_version": event.resource_version,
                "workflow_revision": binding.workflow_revision,
                "job_id": job["id"],
                "producer_node_id": job["node_id"],
                "job_status": job["status"],
                "asset_ids": [asset["id"] for asset in job["outputs"]],
            },
        )
        prior = self.platform.event_repository.get(envelope.event_id)
        if prior is not None and prior != envelope:
            return self._blocked("TASK_VERSION_CHANGED")
        self.platform.event_repository.append(envelope)
        # Persist-before-notify and publish even on replay. The core delivery
        # receipt acknowledges only after the bus succeeds; the stable event ID
        # lets consumers deduplicate a crash between publish and acknowledgment.
        return RuntimeEvent(
            id=envelope.event_id,
            type="super_expert_event",
            scope="session",
            session_id=str(scope.get("session_id") or binding.conversation_id),
            job_id=binding.material_task_id,
            status=task.status.value,
            payload={"envelope": envelope.model_dump(mode="json")},
        )

    async def deliver_pending(self, limit: int = 100) -> int:
        return await self.consumer.deliver_pending(limit)
