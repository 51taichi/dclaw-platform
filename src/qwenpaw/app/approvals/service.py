# -*- coding: utf-8 -*-
"""Approval service for sensitive tool execution.

The ``ApprovalService`` is the single central store for pending /
completed approval records.  Approval is granted exclusively via
the ``/daemon approve`` command in the chat interface.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
from ...security.tool_guard.approval import ApprovalDecision
from ..runtime.approval_store import (
    ApprovalMetadataStore,
    ApprovalRecord,
    MemoryApprovalStore,
    RedisApprovalStore,
)
from ..runtime.event_bus import RuntimeEvent, get_runtime_event_bus
from ..storage.settings import get_storage_settings

if TYPE_CHECKING:
    from ...security.tool_guard.models import ToolGuardResult

logger = logging.getLogger(__name__)

_GC_MAX_AGE_SECONDS = 3600.0
_GC_MAX_COMPLETED = 500
_GC_PENDING_MAX_AGE_SECONDS = 1800.0
_GC_MAX_PENDING = 200
_METADATA_MAX_RECORDS = _GC_MAX_PENDING
_METADATA_MAX_AGE_SECONDS = int(_GC_PENDING_MAX_AGE_SECONDS)


# ------------------------------------------------------------------
# Data model
# ------------------------------------------------------------------


@dataclass
class PendingApproval:
    """In-memory record for one pending approval."""

    request_id: str
    session_id: str
    root_session_id: str  # Root session for cross-session approval routing
    owner_agent_id: str  # Conversation owner/root agent
    user_id: str
    channel: str
    agent_id: str  # Which agent is requesting approval
    tool_name: str
    created_at: float
    future: asyncio.Future[ApprovalDecision]
    timeout_seconds: float = 300.0  # Approval timeout in seconds
    status: str = "pending"
    resolved_at: float | None = None
    result_summary: str = ""
    findings_count: int = 0
    severity: str = "medium"  # For frontend display
    extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------
# Service
# ------------------------------------------------------------------


class ApprovalService:
    """Global singleton approval service.

    Manages all tool approval requests across sessions and agents.
    Approval is resolved via ``/approval`` control command.
    """

    def __init__(
        self,
        *,
        metadata_store: ApprovalMetadataStore | None = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._pending: dict[str, PendingApproval] = {}
        self._channel_manager: Any | None = None
        self._metadata_store = metadata_store or MemoryApprovalStore(
            max_records=_METADATA_MAX_RECORDS,
            max_age_seconds=_METADATA_MAX_AGE_SECONDS,
        )

    def set_channel_manager(self, channel_manager: Any) -> None:
        """Store a reference to the channel manager for push notifications."""
        self._channel_manager = channel_manager

    # ------------------------------------------------------------------
    # Core approval lifecycle
    # ------------------------------------------------------------------

    async def create_pending(
        self,
        *,
        session_id: str,
        root_session_id: str,
        owner_agent_id: str,
        user_id: str,
        channel: str,
        agent_id: str,
        tool_name: str,
        result: "ToolGuardResult",
        timeout_seconds: float = TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS,
        extra: dict[str, Any] | None = None,
    ) -> PendingApproval:
        """Create a pending approval record and return it."""
        from ...security.tool_guard.approval import format_findings_summary

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()

        pending = PendingApproval(
            request_id=request_id,
            session_id=session_id,
            root_session_id=root_session_id,
            owner_agent_id=owner_agent_id,
            user_id=user_id,
            channel=channel,
            agent_id=agent_id,
            tool_name=tool_name,
            created_at=time.time(),
            future=loop.create_future(),
            timeout_seconds=timeout_seconds,
            result_summary=format_findings_summary(result),
            findings_count=result.findings_count,
            severity=result.max_severity.value,
            extra=dict(extra or {}),
        )

        async with self._lock:
            self._pending[request_id] = pending
            self._gc_pending_locked()
        await self._metadata_put(pending)
        await self._publish_runtime_event(
            RuntimeEvent(
                type="approval.created",
                scope="approval",
                session_id=root_session_id,
                chat_id=root_session_id,
                status="pending",
                message=f"Approval required for {tool_name}",
                payload=_approval_event_payload(pending),
            ),
        )

        logger.info(
            "Approval pending created: request_id=%s agent_id=%s tool=%s "
            "severity=%s session=%s root=%s",
            request_id[:8],
            agent_id,
            tool_name,
            pending.severity,
            session_id[:8],
            root_session_id[:8],
        )

        return pending

    async def resolve_request(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> PendingApproval | ApprovalRecord | None:
        """Resolve pending approval by setting Future result."""
        async with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is not None:
                pending.status = decision.value
                pending.resolved_at = time.time()

        if pending is None:
            remote = await self._metadata_store.get(request_id)
            if remote is None:
                logger.warning(
                    "Approval request %s not found (already resolved?)",
                    request_id[:8],
                )
                return None
            remote.status = decision.value
            remote.resolved_at = time.time()
            await self._metadata_publish_resolution(request_id, decision)
            await self._metadata_delete(request_id)
            await self._publish_runtime_event(
                RuntimeEvent(
                    type="approval.resolved",
                    scope="approval",
                    session_id=remote.root_session_id,
                    chat_id=remote.root_session_id,
                    status=decision.value,
                    message=f"Approval {decision.value} for {remote.tool_name}",
                    payload=_approval_record_event_payload(remote),
                ),
            )
            logger.info(
                "Remote approval request %s resolved: decision=%s tool=%s",
                request_id[:8],
                decision.value,
                remote.tool_name,
            )
            return remote

        # Set Future result outside lock
        if not pending.future.done():
            pending.future.set_result(decision)
        await self._metadata_publish_resolution(request_id, decision)
        await self._metadata_delete(request_id)
        await self._publish_runtime_event(
            RuntimeEvent(
                type="approval.resolved",
                scope="approval",
                session_id=pending.root_session_id,
                chat_id=pending.root_session_id,
                status=decision.value,
                message=f"Approval {decision.value} for {pending.tool_name}",
                payload=_approval_event_payload(pending),
            ),
        )

        logger.info(
            "Approval request %s resolved: decision=%s tool=%s",
            request_id[:8],
            decision.value,
            pending.tool_name,
        )

        return pending

    async def get_request(
        self,
        request_id: str,
    ) -> PendingApproval | ApprovalRecord | None:
        """Get a pending request by id."""
        async with self._lock:
            pending = self._pending.get(request_id)
        if pending is not None:
            return pending
        return await self._metadata_store.get(request_id)

    async def list_all_pending(self) -> list[ApprovalRecord]:
        """List serializable metadata for all visible pending approvals."""
        return await self._metadata_store.list_all_pending()

    async def list_pending_metadata_by_root_session(
        self,
        root_session_id: str,
    ) -> list[ApprovalRecord]:
        """List serializable pending metadata for a root session."""
        return await self._metadata_store.list_pending_by_root_session(
            root_session_id,
        )

    async def list_pending_metadata_by_agent(
        self,
        agent_id: str,
    ) -> list[ApprovalRecord]:
        """List serializable pending metadata for an agent."""
        return await self._metadata_store.list_pending_by_agent(agent_id)

    async def metadata_stats(self) -> dict[str, Any]:
        """Return metadata-store counters for admin diagnostics."""
        return await self._metadata_store.stats()

    async def get_pending_by_session(
        self,
        session_id: str,
    ) -> PendingApproval | None:
        """Return the next pending approval for *session_id* (FIFO).

        Pending approvals are consumed in creation order, so repeated
        ``/approve`` inputs walk the queue from oldest to newest.
        """
        async with self._lock:
            for pending in self._pending.values():
                if (
                    pending.session_id == session_id
                    and pending.status == "pending"
                ):
                    return pending
        return None

    async def get_all_pending_by_session(
        self,
        session_id: str,
    ) -> list[PendingApproval]:
        """Return all pending approvals for *session_id* (FIFO order)."""
        async with self._lock:
            return [
                p
                for p in self._pending.values()
                if p.session_id == session_id and p.status == "pending"
            ]

    async def list_pending_by_session(
        self,
        session_id: str,
        include_subagents: bool = True,  # pylint: disable=unused-argument
    ) -> list[PendingApproval]:
        """List all pending approvals for a session (FIFO order).

        Args:
            session_id: Session ID to filter
            include_subagents: If False, exclude sub-agent approvals (future)

        Returns:
            List of pending approvals sorted by creation time
        """
        async with self._lock:
            result = [
                p
                for p in self._pending.values()
                if p.session_id == session_id and p.status == "pending"
            ]
            return sorted(result, key=lambda p: p.created_at)

    async def get_pending_by_root_session(
        self,
        root_session_id: str,
    ) -> list[PendingApproval]:
        """Get all pending approvals for root session and its children.

        Args:
            root_session_id: Root session ID

        Returns:
            List of pending approvals sorted by creation time (FIFO)
        """
        async with self._lock:
            result = [
                p
                for p in self._pending.values()
                if p.root_session_id == root_session_id
                and p.status == "pending"
            ]
            return sorted(result, key=lambda p: p.created_at)

    async def get_all_pending_by_agent(
        self,
        agent_id: str,
    ) -> list[PendingApproval]:
        """Get all pending approvals for an agent (across all sessions).

        Used by /approval list --all command.

        Args:
            agent_id: Agent ID

        Returns:
            List of pending approvals sorted by creation time (FIFO)
        """
        async with self._lock:
            result = [
                p
                for p in self._pending.values()
                if p.agent_id == agent_id and p.status == "pending"
            ]
            return sorted(result, key=lambda p: p.created_at)

    async def wait_for_approval(
        self,
        request_id: str,
        timeout_seconds: float,
    ) -> ApprovalDecision:
        """Block and wait for approval decision with timeout.

        Args:
            request_id: Approval request ID
            timeout_seconds: Maximum wait time in seconds

        Returns:
            ApprovalDecision (APPROVED/DENIED/TIMEOUT)

        Raises:
            ValueError: If request_id not found
        """
        async with self._lock:
            pending = self._pending.get(request_id)

        if pending is None:
            raise ValueError(f"Approval request {request_id} not found")

        remote_wait_task: asyncio.Task[str | None] | None = None
        waitables: list[asyncio.Future[Any]] = [pending.future]
        if getattr(self._metadata_store, "supports_resolution_pubsub", False):
            remote_wait_task = asyncio.create_task(
                self._metadata_store.wait_for_resolution(
                    request_id,
                    timeout_seconds=timeout_seconds,
                ),
            )
            waitables.append(remote_wait_task)

        done, pending_waitables = await asyncio.wait(
            waitables,
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for waitable in pending_waitables:
            if waitable is remote_wait_task:
                waitable.cancel()

        if not done:
            decision = ApprovalDecision.TIMEOUT
            await self.resolve_request(request_id, decision)
            return decision

        result = next(iter(done)).result()
        if result is None:
            decision = ApprovalDecision.TIMEOUT
            await self.resolve_request(request_id, decision)
            return decision

        decision = (
            result
            if isinstance(result, ApprovalDecision)
            else ApprovalDecision(str(result))
        )
        if not pending.future.done():
            await self._complete_local_request_from_remote(
                request_id,
                decision,
            )
        return decision

    async def cancel_stale_pending_for_tool_call(
        self,
        session_id: str,
        tool_call_id: str,
    ) -> int:
        """Cancel pending approvals whose stored tool_call id matches.

        When a tool call is replayed (e.g. after approval triggers
        sibling replay), the guard may create a *new* pending for the
        same logical tool call.  This method cancels the old pending
        first so orphaned records don't accumulate.

        Returns the number of records cancelled.
        """
        now = time.time()
        cancelled = 0
        cancelled_ids: list[str] = []
        async with self._lock:
            to_cancel = [
                k
                for k, p in self._pending.items()
                if p.session_id == session_id
                and p.status == "pending"
                and isinstance(p.extra.get("tool_call"), dict)
                and p.extra["tool_call"].get("id") == tool_call_id
            ]
            for k in to_cancel:
                pending = self._pending.pop(k)
                if not pending.future.done():
                    pending.future.set_result(ApprovalDecision.TIMEOUT)
                pending.status = "superseded"
                pending.resolved_at = now
                cancelled_ids.append(k)
                cancelled += 1
        for request_id in cancelled_ids:
            await self._metadata_delete(request_id)
        if cancelled:
            logger.info(
                "Tool guard: cancelled %d stale pending approval(s) "
                "for tool_call %s (session %s)",
                cancelled,
                tool_call_id,
                session_id[:8],
            )
        return cancelled

    async def cancel_all_pending_by_root_session(
        self,
        root_session_id: str,
    ) -> int:
        """Cancel all pending approvals for root session and its children.

        Called when user stops/cancels a task (e.g., /stop command or
        SSE disconnect). Auto-denies all pending approvals to unblock
        waiting tasks.

        Args:
            root_session_id: Root session ID

        Returns:
            Number of approvals cancelled
        """
        now = time.time()
        cancelled = 0
        cancelled_ids: list[str] = []
        async with self._lock:
            to_cancel = [
                k
                for k, p in self._pending.items()
                if p.root_session_id == root_session_id
                and p.status == "pending"
            ]
            for k in to_cancel:
                pending = self._pending.pop(k)
                if not pending.future.done():
                    pending.future.set_result(ApprovalDecision.DENIED)
                pending.status = "cancelled"
                pending.resolved_at = now
                cancelled_ids.append(k)
                cancelled += 1
        for request_id in cancelled_ids:
            await self._metadata_delete(request_id)
        if cancelled:
            logger.info(
                "Cancelled %d pending approval(s) for root session %s",
                cancelled,
                root_session_id[:8]
                if len(root_session_id) >= 8
                else root_session_id,
            )
        return cancelled

    # ------------------------------------------------------------------
    # Garbage collection
    # ------------------------------------------------------------------

    def _gc_pending_locked(self) -> None:
        """Evict stale pending records whose futures were never resolved.

        Caller must hold ``_lock``.
        """
        now = time.time()
        expired = [
            k
            for k, v in self._pending.items()
            if now - v.created_at > _GC_PENDING_MAX_AGE_SECONDS
        ]
        for k in expired:
            pending = self._pending.pop(k)
            if not pending.future.done():
                pending.future.set_result(ApprovalDecision.TIMEOUT)
            pending.status = "timeout"
            pending.resolved_at = now

        overflow = len(self._pending) - _GC_MAX_PENDING
        if overflow <= 0:
            return
        ordered = sorted(
            self._pending.items(),
            key=lambda item: item[1].created_at,
        )
        for key, pending in ordered[:overflow]:
            del self._pending[key]
            if not pending.future.done():
                pending.future.set_result(ApprovalDecision.TIMEOUT)
            pending.status = "timeout"
            pending.resolved_at = now

    async def _metadata_put(self, pending: PendingApproval) -> None:
        try:
            await self._metadata_store.put(ApprovalRecord.from_pending(pending))
        except Exception:  # pragma: no cover - defensive diagnostics
            logger.exception(
                "Failed to persist approval metadata: request_id=%s",
                pending.request_id[:8],
            )

    async def _metadata_delete(self, request_id: str) -> None:
        try:
            await self._metadata_store.delete(request_id)
        except Exception:  # pragma: no cover - defensive diagnostics
            logger.exception(
                "Failed to delete approval metadata: request_id=%s",
                request_id[:8],
            )

    async def _metadata_publish_resolution(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> None:
        try:
            await self._metadata_store.publish_resolution(
                request_id,
                decision.value,
            )
        except Exception:  # pragma: no cover - defensive diagnostics
            logger.exception(
                "Failed to publish approval resolution: request_id=%s",
                request_id[:8],
            )

    async def _complete_local_request_from_remote(
        self,
        request_id: str,
        decision: ApprovalDecision,
    ) -> None:
        async with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return
            pending.status = decision.value
            pending.resolved_at = time.time()

        if not pending.future.done():
            pending.future.set_result(decision)
        await self._metadata_delete(request_id)

    async def _publish_runtime_event(self, event: RuntimeEvent) -> None:
        try:
            await get_runtime_event_bus().publish(event)
        except Exception:  # pragma: no cover - defensive diagnostics
            logger.exception(
                "Failed to publish approval runtime event: type=%s request=%s",
                event.type,
                event.payload.get("request_id"),
            )


# ------------------------------------------------------------------
# Singleton
# ------------------------------------------------------------------

_approval_service: ApprovalService | None = None


def _make_redis_client(redis_url: str):
    from redis import asyncio as redis_asyncio

    return redis_asyncio.from_url(redis_url, decode_responses=True)


def _make_default_metadata_store() -> ApprovalMetadataStore:
    settings = get_storage_settings()
    if settings.runtime_backend == "redis":
        if not settings.redis_url:
            raise RuntimeError(
                "QWENPAW_REDIS_URL is required for Redis approval metadata store",
            )
        return RedisApprovalStore(
            _make_redis_client(settings.redis_url),
            max_records=_METADATA_MAX_RECORDS,
            max_age_seconds=_METADATA_MAX_AGE_SECONDS,
        )
    return MemoryApprovalStore(
        max_records=_METADATA_MAX_RECORDS,
        max_age_seconds=_METADATA_MAX_AGE_SECONDS,
    )


def get_approval_service() -> ApprovalService:
    """Return the process-wide approval service singleton."""
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService(
            metadata_store=_make_default_metadata_store(),
        )
    return _approval_service


def _approval_event_payload(pending: PendingApproval) -> dict[str, Any]:
    return {
        "request_id": pending.request_id,
        "session_id": pending.session_id,
        "root_session_id": pending.root_session_id,
        "owner_agent_id": pending.owner_agent_id,
        "agent_id": pending.agent_id,
        "tool_name": pending.tool_name,
        "created_at": pending.created_at,
        "severity": pending.severity,
        "findings_count": pending.findings_count,
        "result_summary": pending.result_summary,
        "timeout_seconds": pending.timeout_seconds,
        "extra": pending.extra,
    }


def _approval_record_event_payload(record: ApprovalRecord) -> dict[str, Any]:
    return {
        "request_id": record.request_id,
        "session_id": record.session_id,
        "root_session_id": record.root_session_id,
        "owner_agent_id": record.owner_agent_id,
        "agent_id": record.agent_id,
        "tool_name": record.tool_name,
        "created_at": record.created_at,
        "severity": record.severity,
        "findings_count": record.findings_count,
        "result_summary": record.result_summary,
        "timeout_seconds": record.timeout_seconds,
        "extra": record.extra,
    }
