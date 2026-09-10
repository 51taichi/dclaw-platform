# -*- coding: utf-8 -*-
"""Task tracker for background runs: streaming, reconnect, multi-subscriber.

For internal streaming runs, ``run_key`` is typically ``ChatSpec.id``
(chat_id). For externally-managed tasks (registered via
:meth:`TaskTracker.register_external_task`), ``run_key`` is an opaque
identifier chosen by the caller (e.g. a UUID prefixed with ``"ext-"``).
Per run: task, queues, event buffer. Reconnects get buffer replay + new
events. Cleanup when task completes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, AsyncGenerator, Callable, Coroutine, Optional

try:
    from ..runtime.event_bus import RuntimeEvent, get_runtime_event_bus
except ImportError:  # pragma: no cover - exercised by direct-file test imports
    from qwenpaw.app.runtime.event_bus import RuntimeEvent, get_runtime_event_bus

logger = logging.getLogger(__name__)

_SENTINEL = None


@dataclass
class _RunState:
    """Per-run state (task, queues, buffer), guarded by tracker lock."""

    task: asyncio.Future
    queues: list[asyncio.Queue] = field(default_factory=list)
    buffer: list[str] = field(default_factory=list)
    payload: Any | None = None
    buffer_bytes: int = 0
    dropped_buffer_events: int = 0
    start_time: Optional[datetime] = None
    finish_time: Optional[datetime] = None


class TaskTracker:
    """Per-workspace tracker: run_key -> RunState.

    All mutations to _runs under _lock. Producer broadcasts under lock.
    Subscribers use unbounded per-connection queues; disconnect removes them
    via :meth:`detach_subscriber`.
    """

    def __init__(
        self,
        *,
        max_buffer_events: int | None = None,
        max_buffer_bytes: int | None = None,
    ) -> None:
        self._lock = asyncio.Lock()
        self._runs: dict[str, _RunState] = {}
        self._recent_run_stats: dict[str, dict[str, int]] = {}
        self._global_last_run_at: Optional[datetime] = None
        self._global_last_finish_at: Optional[datetime] = None
        self._max_buffer_events = _positive_int(
            max_buffer_events,
            "QWENPAW_TASK_STREAM_MAX_BUFFER_EVENTS",
            200,
        )
        self._max_buffer_bytes = _positive_int(
            max_buffer_bytes,
            "QWENPAW_TASK_STREAM_MAX_BUFFER_BYTES",
            512 * 1024,
        )

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def get_status(self, run_key: str) -> str:
        """Return ``'idle'`` or ``'running'``."""
        async with self._lock:
            state = self._runs.get(run_key)
        if state is None or state.task.done():
            return "idle"
        return "running"

    async def get_payload(self, run_key: str) -> Any | None:
        """Return the active run payload, if a run is currently attached."""
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            return state.payload

    async def get_global_status(self) -> dict:
        """Get global agent status summary.

        Returns:
            dict with keys:
                - status: 'idle' | 'running'
                - running_task_count: int
                - last_run_at: Optional[datetime]
                - last_finish_at: Optional[datetime]
        """
        async with self._lock:
            running_count = sum(
                1 for state in self._runs.values() if not state.task.done()
            )
            status = "running" if running_count > 0 else "idle"

            return {
                "status": status,
                "running_task_count": running_count,
                "last_run_at": self._global_last_run_at,
                "last_finish_at": self._global_last_finish_at,
            }

    async def has_active_tasks(self) -> bool:
        """Check if any tasks are currently running.

        Returns:
            bool: True if any tasks are active, False otherwise
        """
        async with self._lock:
            for state in self._runs.values():
                if not state.task.done():
                    return True
            return False

    async def list_active_tasks(self) -> list[str]:
        """List all currently running task keys.

        Returns:
            list[str]: List of active run_keys
        """
        async with self._lock:
            return [
                run_key
                for run_key, state in self._runs.items()
                if not state.task.done()
            ]

    async def get_buffer_stats(self) -> dict[str, Any]:
        """Return replay-buffer diagnostics for active and recent runs."""
        async with self._lock:
            active = {
                run_key: self._run_buffer_stats(state)
                for run_key, state in self._runs.items()
                if not state.task.done()
            }
            return {
                "max_buffer_events": self._max_buffer_events,
                "max_buffer_bytes": self._max_buffer_bytes,
                "active_runs": active,
                "recent_runs": dict(self._recent_run_stats),
            }

    async def wait_all_done(self, timeout: float = 300.0) -> bool:
        """Wait for all active tasks to complete.

        Args:
            timeout: Maximum time to wait in seconds (default: 300s = 5min)

        Returns:
            bool: True if all tasks completed, False if timeout occurred
        """

        async def _wait_loop() -> None:
            while await self.has_active_tasks():
                await asyncio.sleep(0.5)

        try:
            await asyncio.wait_for(_wait_loop(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def register_external_task(self, run_key: str) -> None:
        """Register an externally-managed task so it is visible to
        :meth:`has_active_tasks` and :meth:`wait_all_done`.

        This is used for tasks managed outside of DClaw's own streaming
        pipeline (e.g. background tasks dispatched through
        ``agentscope_runtime``'s ``AgentApp``).  The caller **must** call
        :meth:`unregister_external_task` when the task completes.

        Args:
            run_key: Unique identifier for the external task.
        """
        start_time = datetime.now(timezone.utc)
        async with self._lock:
            if run_key in self._runs and not self._runs[run_key].task.done():
                logger.debug(
                    "External task already registered: %s",
                    run_key,
                )
                return
            # Use an unresolved Future as the "task" — it stays not-done
            # until unregister_external_task resolves it.
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            self._runs[run_key] = _RunState(
                task=future,
                queues=[],
                buffer=[],
                start_time=start_time,
            )
            self._global_last_run_at = start_time
            logger.debug("Registered external task: %s", run_key)

    async def unregister_external_task(self, run_key: str) -> None:
        """Mark an externally-managed task as done and remove it.

        Sends the sentinel value to any subscriber queues so their
        :meth:`stream_from_queue` consumers terminate cleanly instead of
        hanging. Idempotent — safe to call even if *run_key* was never
        registered or was already unregistered.

        Args:
            run_key: Unique identifier previously passed to
                :meth:`register_external_task`.
        """
        finish_time = datetime.now(timezone.utc)
        async with self._lock:
            state = self._runs.pop(run_key, None)
            if state is None:
                return
            # Notify any subscriber queues so consumers exit cleanly.
            for q in state.queues:
                q.put_nowait(_SENTINEL)
            if not state.task.done():
                state.task.set_result(None)
            state.finish_time = finish_time
            self._global_last_finish_at = finish_time
            logger.debug("Unregistered external task: %s", run_key)

    async def attach(self, run_key: str) -> asyncio.Queue | None:
        """Attach to an existing run.

        Returns a new queue pre-filled with the event buffer, or ``None``
        if no run is active for *run_key*.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None or state.task.done():
                return None
            q: asyncio.Queue = asyncio.Queue()
            for sse in state.buffer:
                q.put_nowait(sse)
            state.queues.append(q)
            return q

    async def detach_subscriber(
        self,
        run_key: str,
        queue: asyncio.Queue,
    ) -> None:
        """Remove *queue* from *run_key*'s subscriber list.

        Idempotent if the run ended or *queue* was already removed.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is None:
                return
            try:
                state.queues.remove(queue)
            except ValueError:
                pass

    async def request_stop(self, run_key: str) -> bool:
        """Cancel the run. Returns ``True`` if it was running."""
        logger.debug("[STOP] request_stop called for run_key=%s", run_key)
        async with self._lock:
            state = self._runs.get(run_key)
            logger.debug(
                "[STOP] run_key=%s state=%s done=%s",
                run_key,
                "found" if state else "not_found",
                state.task.done() if state else "N/A",
            )
            if state is None or state.task.done():
                logger.debug(
                    "[STOP] Cannot stop run_key=%s (not running)",
                    run_key,
                )
                return False
            logger.debug(
                "[STOP] Calling task.cancel() for run_key=%s",
                run_key,
            )
            state.task.cancel()
            logger.debug("[STOP] task.cancel() called for run_key=%s", run_key)
            return True

    async def attach_or_start(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[..., Coroutine],
        on_finish: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[asyncio.Queue, bool]:
        return await self._attach_or_start(run_key, payload, stream_fn, on_finish)

    async def start_new(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[..., Coroutine],
        on_finish: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[asyncio.Queue, bool]:
        """Serialize a new submission without replaying an earlier turn.

        Waiting does not cancel the earlier run if this HTTP request disconnects.
        Reconnects use attach(), independently of new submissions.
        """
        while True:
            queue_or_task, started = await self._attach_or_start(
                run_key, payload, stream_fn, on_finish, attach_existing=False,
            )
            if started:
                return queue_or_task, True
            await asyncio.wait({queue_or_task})

    async def _attach_or_start(
        self,
        run_key: str,
        payload: Any,
        stream_fn: Callable[..., Coroutine],
        on_finish: Callable[[], Awaitable[None]] | None = None,
        *,
        attach_existing: bool = True,
    ) -> tuple[asyncio.Queue | asyncio.Future, bool]:
        """Attach to an existing run or start a new one.

        Returns ``(queue, is_new_run)``.
        """
        async with self._lock:
            state = self._runs.get(run_key)
            if state is not None and not state.task.done():
                if not attach_existing:
                    return state.task, False
                q: asyncio.Queue = asyncio.Queue()
                for sse in state.buffer:
                    q.put_nowait(sse)
                state.queues.append(q)
                return q, False

            my_queue: asyncio.Queue = asyncio.Queue()
            run = _RunState(
                task=asyncio.Future(),  # placeholder, replaced below
                queues=[my_queue],
                buffer=[],
                payload=payload,
            )
            self._runs[run_key] = run

            tracker_ref = weakref.ref(self)

            async def _producer() -> None:
                start_time = datetime.now(timezone.utc)
                final_status = "completed"

                try:
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.start_time = start_time
                            # pylint: disable=protected-access
                            tracker._global_last_run_at = start_time
                    await _publish_task_runtime_event(
                        run_key,
                        payload,
                        status="started",
                        at=start_time,
                    )

                    async for sse in stream_fn(payload):
                        tracker = tracker_ref()
                        if tracker is None:
                            return
                        async with tracker.lock:
                            tracker._append_buffered_event(run, sse)
                            for q in run.queues:
                                q.put_nowait(sse)
                except asyncio.CancelledError:
                    final_status = "cancelled"
                    logger.debug("run cancelled run_key=%s", run_key)
                except Exception:
                    final_status = "failed"
                    logger.exception("run error run_key=%s", run_key)
                    err_sse = (
                        "data: "
                        f"{json.dumps({'error': 'internal server error'})}\n\n"
                    )
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            tracker._append_buffered_event(run, err_sse)
                            for q in run.queues:
                                q.put_nowait(err_sse)
                finally:
                    if on_finish is not None:
                        try:
                            await on_finish()
                        except Exception:
                            logger.exception(
                                "run finish callback failed run_key=%s",
                                run_key,
                            )
                    finish_time = datetime.now(timezone.utc)
                    tracker = tracker_ref()
                    if tracker is not None:
                        async with tracker.lock:
                            run.finish_time = finish_time
                            # pylint: disable=protected-access
                            tracker._global_last_finish_at = finish_time
                            tracker._recent_run_stats[run_key] = (
                                tracker._run_buffer_stats(run)
                            )
                            for q in run.queues:
                                q.put_nowait(_SENTINEL)
                            # pylint: disable=protected-access
                            tracker._runs.pop(
                                run_key,
                                None,
                            )
                    await _publish_task_runtime_event(
                        run_key,
                        payload,
                        status=final_status,
                        at=finish_time,
                    )

            run.task = asyncio.create_task(_producer())
            return my_queue, True

    async def stream_from_queue(
        self,
        queue: asyncio.Queue,
        run_key: str,
    ) -> AsyncGenerator[str, None]:
        """Yield SSE strings from *queue* until the sentinel ``None``.

        Always detaches *queue* from *run_key* when this stream ends or is
        closed (including client disconnect), so reconnects do not leak queues.
        """
        try:
            while True:
                try:
                    event = await queue.get()
                    if event is _SENTINEL:
                        break
                    yield event
                except asyncio.CancelledError:
                    break
        finally:
            await self.detach_subscriber(run_key, queue)

    def _append_buffered_event(self, run: _RunState, event: str) -> None:
        event_bytes = len(event.encode("utf-8"))
        run.buffer.append(event)
        run.buffer_bytes += event_bytes
        self._trim_buffer(run)

    def _trim_buffer(self, run: _RunState) -> None:
        while run.buffer and len(run.buffer) > self._max_buffer_events:
            removed = run.buffer.pop(0)
            run.buffer_bytes -= len(removed.encode("utf-8"))
            run.dropped_buffer_events += 1
        while run.buffer and run.buffer_bytes > self._max_buffer_bytes:
            removed = run.buffer.pop(0)
            run.buffer_bytes -= len(removed.encode("utf-8"))
            run.dropped_buffer_events += 1

    @staticmethod
    def _run_buffer_stats(run: _RunState) -> dict[str, int]:
        return {
            "buffer_event_count": len(run.buffer),
            "buffer_bytes": max(0, run.buffer_bytes),
            "subscriber_count": len(run.queues),
            "dropped_buffer_events": run.dropped_buffer_events,
        }


async def _publish_task_runtime_event(
    run_key: str,
    payload: dict[str, Any],
    *,
    status: str,
    at: datetime,
) -> None:
    event_type = {
        "started": "task.started",
        "completed": "task.completed",
        "failed": "task.failed",
        "cancelled": "task.failed",
    }.get(status, "task.progress")
    try:
        await get_runtime_event_bus().publish(
            RuntimeEvent(
                type=event_type,
                scope="task",
                session_id=_payload_str(payload, "session_id")
                or _payload_str(payload, "root_session_id"),
                chat_id=run_key,
                job_id=run_key,
                status=status,
                message=f"Task {status}",
                payload={
                    "run_key": run_key,
                    "session_id": _payload_str(payload, "session_id"),
                    "root_session_id": _payload_str(payload, "root_session_id"),
                    "user_id": _payload_str(payload, "user_id"),
                    "agent_id": _payload_str(payload, "agent_id"),
                    "channel": _payload_str(payload, "channel"),
                    "status": status,
                    "at": at.isoformat(),
                },
            ),
        )
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.debug("Failed to publish task runtime event: %s", exc)


def _payload_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _positive_int(
    value: int | None,
    env_name: str,
    default: int,
) -> int:
    if value is not None:
        return max(1, int(value))
    try:
        return max(1, int(os.environ.get(env_name, "").strip() or default))
    except ValueError:
        return default
