# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements
"""External Open API message runtime routes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, StreamingResponse

from ..billing.execution import OpenApiExecutionFence
from ..billing.open_api import (
    CatalogNotReadyError,
    OpenApiBillingCommand,
    OpenApiPublicationNotFoundError,
)
from ..billing.pricing import ModelNotPricedError
from ..billing.usage import (
    IdempotencyConflictError,
    InsufficientUsageCreditsError,
)
from ..expert_teams import (
    ExpertTeamOrchestrator,
    attach_run_to_chat,
    create_expert_team_run,
    get_expert_team_template,
    get_latest_expert_team_run_by_chat,
)
from ..open_api.runtime import (
    ExecutionLeaseLostError,
    OpenMessageRequest,
    OpenApiOutputProfile,
    PreparedOpenRun,
    create_open_api_billing_runtime,
    open_api_billing_context,
    prepare_open_agent_chat,
    prepare_open_expert_team_chat,
)
from ..sealed_agents.registry import get_sealed_agent_registry
from ..sealed_agents.models import SealedReleaseRecord
from ..storage.repos.open_api_repo import get_open_api_repository
from ..task_limits import get_task_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/open/v1", tags=["open-api"])


@dataclass(frozen=True)
class _OpenApiStreamFailure:
    status: str
    code: str
    message: str
    http_status: int
    error_summary: str


@dataclass
class _OpenApiQueueTicket:
    queue: "_OpenApiWaitQueue"
    publication_id: str
    api_key_id: str
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        await self.queue.leave(self.publication_id, self.api_key_id)


@dataclass
class _OpenApiTaskPermit:
    permit: Any
    queue: "_OpenApiWaitQueue"
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        try:
            await self.permit.release()
        finally:
            await self.queue.release_execution_slot()


class _OpenApiWaitQueue:
    """Bounded in-process wait queue for the single-worker OpenAPI runtime."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._by_publication: dict[str, int] = {}
        self._by_api_key: dict[str, int] = {}
        self._running_global = 0

    async def try_acquire_execution_slot(self, max_running: int) -> bool:
        async with self._condition:
            if self._running_global >= max_running:
                return False
            self._running_global += 1
            return True

    async def release_execution_slot(self) -> None:
        async with self._condition:
            self._running_global = max(0, self._running_global - 1)
            self._condition.notify_all()

    async def try_join(
        self,
        publication_id: str,
        api_key_id: str,
        *,
        max_per_publication: int,
        max_per_api_key: int,
    ) -> _OpenApiQueueTicket | None:
        async with self._condition:
            if (
                self._by_publication.get(publication_id, 0)
                >= max_per_publication
            ):
                return None
            if self._by_api_key.get(api_key_id, 0) >= max_per_api_key:
                return None
            self._by_publication[publication_id] = (
                self._by_publication.get(publication_id, 0) + 1
            )
            self._by_api_key[api_key_id] = (
                self._by_api_key.get(api_key_id, 0) + 1
            )
            return _OpenApiQueueTicket(self, publication_id, api_key_id)

    async def leave(self, publication_id: str, api_key_id: str) -> None:
        async with self._condition:
            self._decrement(self._by_publication, publication_id)
            self._decrement(self._by_api_key, api_key_id)

    async def wait_for_slot(self, timeout: float) -> None:
        async with self._condition:
            try:
                await asyncio.wait_for(self._condition.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    async def notify_slot_available(self) -> None:
        async with self._condition:
            self._condition.notify_all()

    async def snapshot(self) -> dict[str, Any]:
        async with self._condition:
            return {
                "running_global": self._running_global,
                "waiting_global": sum(self._by_publication.values()),
                "waiting_by_publication": dict(self._by_publication),
                "waiting_by_api_key": dict(self._by_api_key),
            }

    @staticmethod
    def _decrement(bucket: dict[str, int], key: str) -> None:
        next_value = bucket.get(key, 0) - 1
        if next_value > 0:
            bucket[key] = next_value
        else:
            bucket.pop(key, None)


_DIRECT_AGENT_FAILURES: dict[str, tuple[int, str]] = {
    "response_format_adapter_unavailable": (
        500,
        "Configured response format is unavailable",
    ),
    "model_execution_failed": (502, "Model execution failed"),
    "tool_execution_failed": (502, "Tool execution failed"),
    "empty_final_response": (502, "Model returned an empty final response"),
    "invalid_final_response": (502, "Model returned an invalid JSON response"),
}


def _resolve_sealed_publication_release(
    publication: dict[str, Any],
) -> SealedReleaseRecord | None:
    """Resolve control-plane availability without changing execution."""

    if not (
        str(publication.get("target_type")) == "agent"
        and str(publication.get("response_policy")) == "sealed"
    ):
        return None
    record = get_sealed_agent_registry().get_agent(
        str(publication.get("target_id")),
    )
    if record is None or not record.enabled or record.active_release is None:
        raise HTTPException(
            status_code=503,
            detail="Sealed agent target is unavailable",
        )
    return record.active_release


def _output_profile_for_release(
    release: SealedReleaseRecord | None,
) -> OpenApiOutputProfile:
    """Resolve optional output behavior from the package-type plugin."""

    if release is not None:
        from ...plugins.registry import PluginRegistry

        if PluginRegistry().sealed_package_type_supports(
            release.package_type,
            "extended_output",
        ):
            return "extended"
    return "default"


@router.post(
    "/targets/{public_id}/messages",
    status_code=200,
    response_model=None,
)
async def post_open_message(
    public_id: str,
    payload: OpenMessageRequest,
    request: Request,
) -> StreamingResponse | JSONResponse:
    # pylint: disable=too-many-branches,too-many-statements
    started_at = time.monotonic()
    repo = get_open_api_repository()
    publication = repo.get_enabled_publication_by_public_id(public_id)
    if publication is None:
        raise HTTPException(
            status_code=404,
            detail="Open API publication not found",
        )
    if str(getattr(request.state, "open_publication_id", "")) != str(
        publication["id"],
    ):
        raise HTTPException(
            status_code=403,
            detail="Open API key is not allowed for this publication",
        )

    active_sealed_release = _resolve_sealed_publication_release(publication)
    sealed_runtime_audit = (
        {
            "release_id": active_sealed_release.release_id,
            "version": active_sealed_release.version,
            "content_digest": active_sealed_release.content_digest,
        }
        if active_sealed_release is not None
        else None
    )

    if payload.stream is False:
        raise HTTPException(
            status_code=400,
            detail="Open API messages currently require stream=true",
        )
    if (
        payload.execution_mode == "isolated_attempt"
        and str(publication["target_type"]) != "agent"
    ):
        raise HTTPException(
            status_code=400,
            detail="isolated_attempt is supported only for agent targets",
        )
    bound_user_id = str(publication.get("bound_user_id") or "").strip()
    if not bound_user_id:
        raise HTTPException(
            status_code=401,
            detail="Open API bound user is unavailable",
        )
    # Authentication already derived this identity from the publication.  Set
    # it again from the just-locked server row so caller attribution can never
    # become a wallet selector in direct or nested runtime paths.
    request.state.user_id = bound_user_id

    billing = create_open_api_billing_runtime(
        output_profile=_output_profile_for_release(active_sealed_release),
    )
    billing_payload = payload.model_dump(mode="json")
    if payload.execution_mode == "persistent":
        billing_payload.pop("execution_mode", None)
    try:
        billing_session = billing.coordinator.begin_invocation(
            OpenApiBillingCommand(
                app_id=str(request.state.open_app_id),
                publication_id=str(publication["id"]),
                api_key_id=str(request.state.open_api_key_id),
                target_type=str(publication["target_type"]),
                target_id=str(publication["target_id"]),
                external_user_id=payload.external_user_id,
                external_session_id=payload.external_session_id or "default",
                payload=billing_payload,
                idempotency_key=request.headers.get("Idempotency-Key"),
                mode=billing.mode,  # type: ignore[arg-type]
                budget_credits=billing.budget_credits,
                sealed_runtime=sealed_runtime_audit,
            ),
        )
    except IdempotencyConflictError:
        return JSONResponse(
            status_code=409,
            content={"code": "idempotency_conflict"},
        )
    except CatalogNotReadyError:
        return JSONResponse(
            status_code=503,
            content={"code": "catalog_not_ready"},
        )
    except OpenApiPublicationNotFoundError as exc:
        raise HTTPException(
            status_code=401,
            detail="Open API publication binding changed",
        ) from exc

    bound_user_id = billing_session.bound_user_id
    request.state.user_id = bound_user_id
    invocation_id = billing_session.invocation_id
    run_key = f"open-api:{invocation_id}"
    execution_owner_token = str(uuid.uuid4())
    lease_seconds = _positive_seconds_env(
        "DCLAW_OPEN_API_EXECUTION_LEASE_SECONDS",
        30.0,
    )
    heartbeat_seconds = _positive_seconds_env(
        "DCLAW_OPEN_API_EXECUTION_HEARTBEAT_SECONDS",
        10.0,
    )
    execution_fence = None
    if not billing_session.replayed:
        execution_fence = (
            billing.open_api_repository.claim_invocation_execution(
                invocation_id,
                execution_owner_token,
                lease_seconds=lease_seconds,
            )
        )
    owns_execution = execution_fence is not None
    execution = None
    heartbeat_task = None
    if execution_fence is not None:
        execution = billing.execution(
            invocation_id,
            execution_fence,
            lease_seconds,
        )
        execution.producer_task = asyncio.current_task()
        heartbeat_task = asyncio.create_task(
            _execution_heartbeat(
                execution,
                heartbeat_seconds=heartbeat_seconds,
                producer_task=None,
            ),
        )

    if billing_session.replayed:
        existing = billing.open_api_repository.get_invocation(invocation_id)
        if isinstance((existing or {}).get("terminal_event_json"), dict):
            return _terminal_replay_response(
                billing,
                billing_session,
                None,
                str((existing or {}).get("expert_team_run_id") or ""),
            )

    prepared: PreparedOpenRun | None = None
    expert_team_run_id = ""
    try:
        target_type = str(publication["target_type"])
        if target_type == "agent":
            prepared = await prepare_open_agent_chat(
                request,
                publication,
                payload,
                invocation_id=invocation_id,
            )
            stream_fn = prepared.console_channel.stream_one
            stream_payload = prepared.payload
        elif target_type == "expert_team":
            team = get_expert_team_template(str(publication["target_id"]))
            if team is None or not bool(getattr(team, "enabled", False)):
                raise HTTPException(
                    status_code=404,
                    detail="Open API expert team not found",
                )
            prepared = await prepare_open_expert_team_chat(
                request,
                publication,
                payload,
                leader_agent_id=str(getattr(team, "leader_agent_id")),
            )
            invocation = (
                billing.open_api_repository.get_invocation(invocation_id) or {}
            )
            expert_team_run_id = str(
                invocation.get("expert_team_run_id") or "",
            )
            if owns_execution and not expert_team_run_id:
                assert execution_fence is not None
                expert_team_run_id = str(uuid.uuid4())
                updated = (
                    billing.open_api_repository.update_claimed_invocation(
                        invocation_id,
                        execution_fence,
                        expert_team_run_id=expert_team_run_id,
                    )
                )
                if updated is None:
                    raise ExecutionLeaseLostError(
                        "Open API invocation execution lease was lost",
                    )
            stream_payload = {
                "run_id": expert_team_run_id,
                "team_id": str(team.id),
                "root_chat_id": prepared.chat_id,
                "root_session_id": prepared.session_id,
                "native_payload": prepared.payload,
            }
            orchestrator = ExpertTeamOrchestrator(
                workspace=prepared.workspace,
                console_channel=prepared.console_channel,
            )

            async def stream_fn(team_payload):
                run = create_expert_team_run(
                    team_id=str(team.id),
                    root_chat_id=prepared.chat_id,
                    root_session_id=prepared.session_id,
                    user_id=str(request.state.user_id),
                    input_text=payload.message,
                    run_id=str(team_payload["run_id"]),
                )
                team_payload["run_id"] = str(run.id)
                await attach_run_to_chat(
                    prepared.workspace,
                    prepared.chat_id,
                    run,
                )
                async for item in orchestrator.stream_one(team_payload):
                    yield item

        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported Open API target type",
            )

        if owns_execution:
            assert execution_fence is not None
            updated = billing.open_api_repository.update_claimed_invocation(
                invocation_id,
                execution_fence,
                chat_id=prepared.chat_id,
            )
            if updated is None:
                raise ExecutionLeaseLostError(
                    "Open API invocation execution lease was lost",
                )

        tracker = prepared.workspace.task_tracker
        if billing_session.replayed or not owns_execution:
            queue = await _attach_tracker_queue(tracker, run_key)
            if queue is not None:
                first_event = await queue.get()
                if first_event is None or _is_insufficient_terminal_event(
                    first_event,
                ):
                    await _detach_tracker_queue(tracker, run_key, queue)
                    await _wait_for_durable_terminal(
                        billing.open_api_repository,
                        invocation_id,
                    )
                    return _terminal_replay_response(
                        billing,
                        billing_session,
                        prepared,
                        expert_team_run_id,
                    )
                return _streaming_response(
                    tracker,
                    queue,
                    run_key,
                    prepared,
                    invocation_id,
                    expert_team_run_id,
                    billing.open_api_repository.get_invocation(invocation_id)
                    or {},
                    initial_event=first_event,
                )
            await _wait_for_durable_terminal(
                billing.open_api_repository,
                invocation_id,
            )
            return _terminal_replay_response(
                billing,
                billing_session,
                prepared,
                expert_team_run_id,
            )

        permit = None
        if owns_execution:
            permit = await _acquire_open_api_permit(
                request.app,
                publication_id=str(billing_session.publication_id),
                api_key_id=str(billing_session.api_key_id),
            )
            if permit is None:
                retry_after = _positive_int_env(
                    "DCLAW_OPEN_API_RETRY_AFTER_SECONDS",
                    5,
                )
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "OpenAPI capacity is busy and the wait queue timed out "
                        "or is full. Please retry shortly."
                    ),
                    headers={"Retry-After": str(retry_after)},
                )

        assert execution_fence is not None
        assert execution is not None

        async def limited_stream_fn(stream_payload):
            stream_started_at = time.monotonic()
            stream_failure: _OpenApiStreamFailure | None = None
            stream_exception: Exception | None = None
            cancelled = False
            terminal: dict[str, Any] | None = None
            execution.producer_task = asyncio.current_task()
            try:
                with open_api_billing_context(
                    billing_session,
                    execution_fence,
                    execution.meter,
                ):
                    async for item in stream_fn(stream_payload):
                        execution.note_stream_ready()
                        if stream_failure is None:
                            stream_failure = _extract_stream_failure(item)
                        yield item
            except InsufficientUsageCreditsError as exc:
                execution.note_insufficient(exc)
            except asyncio.CancelledError:
                cancelled = True
            except ExecutionLeaseLostError:
                cancelled = True
            except Exception as exc:  # supplier details stay private
                stream_exception = exc
                if stream_failure is None:
                    yield _sse({"error": "internal server error"})
            finally:
                execution.note_stream_ready()
                try:
                    terminal = await _shielded_finalize(
                        billing,
                        billing_session,
                        execution,
                        stream_started_at=stream_started_at,
                        stream_failure=stream_failure,
                        stream_exception=stream_exception,
                        cancelled=cancelled,
                        expert_team_run_id=expert_team_run_id,
                        execution_fence=execution_fence,
                    )
                finally:
                    assert heartbeat_task is not None
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
            assert terminal is not None
            yield _sse(terminal)
            if cancelled:
                raise asyncio.CancelledError

        try:
            (
                queue,
                is_new_run,
            ) = await prepared.workspace.task_tracker.attach_or_start(
                run_key,
                stream_payload,
                limited_stream_fn,
                on_finish=permit.release if permit is not None else None,
            )
        except Exception:
            if permit is not None:
                await permit.release()
            raise
        updated = billing.open_api_repository.update_claimed_invocation(
            invocation_id,
            execution_fence,
            status="running",
            status_code=202,
            latency_ms=_latency_ms(started_at),
            error_summary="",
        )
        if updated is None:
            execution.note_lease_lost()
        if not is_new_run and permit is not None:
            await permit.release()
        if not is_new_run and target_type == "expert_team":
            expert_team_run_id = ""
            running_payload = await _get_tracker_payload(
                prepared.workspace.task_tracker,
                run_key,
            )
            if isinstance(running_payload, dict):
                expert_team_run_id = str(running_payload.get("run_id") or "")
            if not expert_team_run_id:
                latest_run = get_latest_expert_team_run_by_chat(
                    prepared.chat_id,
                )
                expert_team_run_id = str(latest_run.id) if latest_run else ""

        if is_new_run:
            try:
                await execution.wait_for_preflight()
            except InsufficientUsageCreditsError:
                await _detach_tracker_queue(tracker, run_key, queue)
                terminal = await execution.wait_for_finalization()
                return _snapshot_json_response(terminal)
    except asyncio.CancelledError:
        seal_task = asyncio.create_task(
            _seal_preproducer_failure(
                billing,
                billing_session,
                execution_fence,
                owns_execution=owns_execution,
                status_code=499,
                message="Request cancelled",
                started_at=started_at,
            ),
        )
        try:
            await asyncio.shield(seal_task)
        except asyncio.CancelledError:
            await seal_task
        await _cancel_heartbeat(heartbeat_task)
        raise
    except HTTPException as exc:
        response = await _seal_preproducer_failure(
            billing,
            billing_session,
            execution_fence,
            owns_execution=owns_execution,
            status_code=exc.status_code,
            message=str(exc.detail),
            started_at=started_at,
            response_headers=exc.headers,
        )
        await _cancel_heartbeat(heartbeat_task)
        return response
    except Exception:
        logger.exception("Open API failed before supplier producer start")
        response = await _seal_preproducer_failure(
            billing,
            billing_session,
            execution_fence,
            owns_execution=owns_execution,
            status_code=500,
            message="Internal server error",
            started_at=started_at,
        )
        await _cancel_heartbeat(heartbeat_task)
        return response

    current = billing.open_api_repository.get_invocation(invocation_id) or {}
    return _streaming_response(
        tracker,
        queue,
        run_key,
        prepared,
        invocation_id,
        expert_team_run_id,
        current,
    )


def _terminal_replay_response(
    billing: Any,
    session: Any,
    prepared: PreparedOpenRun | None,
    expert_team_run_id: str,
) -> StreamingResponse | JSONResponse:
    invocation = (
        billing.open_api_repository.get_invocation(
            session.invocation_id,
        )
        or {}
    )
    payload = invocation.get("terminal_event_json")
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=503,
            detail="Open API invocation is still finalizing",
        )
    if int(payload.get("http_status") or 200) != 200:
        return _snapshot_json_response(payload)

    async def replay_event() -> AsyncGenerator[str, None]:
        yield _sse(payload)

    sealed_headers = payload.get("headers")
    response_headers = (
        {str(key): str(value) for key, value in sealed_headers.items()}
        if isinstance(sealed_headers, dict)
        else {}
    )
    response_headers.update(
        {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-QwenPaw-Chat-Id": prepared.chat_id if prepared else "",
            "X-QwenPaw-Session-Id": prepared.session_id if prepared else "",
            "X-QwenPaw-Open-Invocation-Id": session.invocation_id,
            "X-QwenPaw-Expert-Team-Run-Id": expert_team_run_id,
        },
    )
    return StreamingResponse(
        replay_event(),
        media_type="text/event-stream",
        headers=response_headers,
    )


def _terminal_billing_payload(
    billing: Any,
    session: Any,
    insufficient: InsufficientUsageCreditsError | None,
) -> dict[str, Any]:
    items = billing.usage_service.list_items(session.usage_order_id)
    order = billing.usage_service.get_order(session.usage_order_id)
    balance = billing.repository.balance(session.wallet_id)
    completed = sum(
        1 for item in items if item.get("execution_outcome") == "succeeded"
    )
    if insufficient is not None:
        return {
            "type": "billing.interrupted",
            "code": "insufficient_credits",
            "status": "partially_completed" if completed else "failed",
            "completed_steps": completed,
            "remaining_credits": insufficient.available,
            "required_credits_for_next_step": insufficient.required,
            "invocation_id": session.invocation_id,
        }
    billing_status = (
        "settled"
        if not items and str(order["status"]) == "quoted"
        else str(order["status"])
    )
    if billing_status == "settled" and int(order["captured_credits"]):
        billing_status = "captured"
    return {
        "type": "billing.completed",
        "invocation_id": session.invocation_id,
        "credits_used": int(order["captured_credits"]),
        "credits_remaining": balance.available,
        "billing_status": billing_status,
    }


async def _shielded_finalize(
    billing: Any,
    session: Any,
    execution: Any,
    *,
    stream_started_at: float,
    stream_failure: _OpenApiStreamFailure | None,
    stream_exception: Exception | None,
    cancelled: bool,
    expert_team_run_id: str,
    execution_fence: OpenApiExecutionFence,
) -> dict[str, Any]:
    # pylint: disable=too-many-statements
    """Finish the durable bridge even when its producer is cancelled."""

    async def finalize() -> dict[str, Any]:
        # pylint: disable=too-many-statements
        invocation = (
            billing.open_api_repository.get_invocation(session.invocation_id)
            or {}
        )
        stored = invocation.get("terminal_event_json")
        if isinstance(stored, dict):
            execution.note_finalized(stored)
            return stored

        no_items = not billing.usage_service.list_items(
            session.usage_order_id,
        )
        terminal = _terminal_billing_payload(
            billing,
            session,
            execution.insufficient,
        )
        if execution.insufficient is not None:
            status = (
                "partially_completed"
                if terminal["completed_steps"]
                else "failed"
            )
            status_code = 409
            error_summary = "insufficient credits"
            billing_error_code = "insufficient_credits"
            public_code = "insufficient_credits"
            public_message = "Insufficient credits"
            required_credits = terminal.get(
                "required_credits_for_next_step",
            )
        elif cancelled:
            status = "cancelled"
            status_code = 499
            error_summary = "request cancelled"
            billing_error_code = None
            public_code = "request_cancelled"
            public_message = "Request cancelled"
            required_credits = None
        elif isinstance(stream_exception, ModelNotPricedError):
            status = "failed"
            status_code = 409
            error_summary = str(stream_exception)
            billing_error_code = "model_not_priced"
            public_code = "model_not_priced"
            public_message = "Selected model is not priced"
            required_credits = None
        elif stream_failure is not None:
            status = stream_failure.status
            status_code = stream_failure.http_status
            error_summary = stream_failure.error_summary
            billing_error_code = None
            public_code = stream_failure.code
            public_message = stream_failure.message
            required_credits = None
        elif stream_exception is not None:
            status = "failed"
            status_code = 500
            error_summary = str(stream_exception)
            billing_error_code = None
            public_code = "request_failed"
            public_message = "Internal server error"
            required_credits = None
        else:
            status = "succeeded"
            status_code = 200
            error_summary = ""
            billing_error_code = None
            public_code = "completed"
            public_message = "Completed"
            required_credits = None
        terminal["status"] = status
        terminal = _canonical_terminal_snapshot(
            terminal,
            http_status=status_code,
            code=public_code,
            message=public_message,
            required_credits=required_credits,
            billing_status=str(terminal.get("billing_status") or "settled"),
        )
        if isinstance(stream_exception, ModelNotPricedError):
            terminal["provider_id"] = stream_exception.provider_id
            terminal["model_key"] = stream_exception.model_key
        execution.begin_finalizing()
        finalize_kwargs = {
            "status": status,
            "status_code": status_code,
            "latency_ms": _latency_ms(stream_started_at),
            "error_summary": error_summary,
            "billing_error_code": billing_error_code,
            "expert_team_run_id": expert_team_run_id or None,
            "terminal_event": terminal,
        }
        repository = billing.open_api_repository
        if no_items:
            updated = repository.finalize_empty_invocation_execution(
                session.invocation_id,
                session.usage_order_id,
                execution_fence,
                **finalize_kwargs,
            )
        else:
            updated = repository.finalize_invocation_execution(
                session.invocation_id,
                execution_fence,
                **finalize_kwargs,
            )
        if updated is None:
            updated = billing.open_api_repository.get_invocation(
                session.invocation_id,
            )
        sealed = (updated or {}).get("terminal_event_json")
        if not isinstance(sealed, dict):
            raise ExecutionLeaseLostError(
                "Open API invocation lease was lost before finalization",
            )
        execution.note_finalized(sealed)
        return sealed

    task = asyncio.create_task(finalize())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Preserve cancellation after the financial/business transition.
        await task
        raise


async def _seal_preproducer_failure(
    billing: Any,
    session: Any,
    execution_fence: OpenApiExecutionFence | None,
    *,
    owns_execution: bool,
    status_code: int,
    message: str,
    started_at: float,
    response_headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Seal a claimed invocation that exits before its producer starts."""
    if not owns_execution:
        invocation = billing.open_api_repository.get_invocation(
            session.invocation_id,
        )
        stored = (invocation or {}).get("terminal_event_json")
        if isinstance(stored, dict):
            return _snapshot_json_response(stored)
        return JSONResponse(
            status_code=503,
            content={"code": "invocation_still_running"},
        )

    no_items = not billing.usage_service.list_items(session.usage_order_id)
    financial = _terminal_billing_payload(billing, session, None)
    public_code = _preproducer_error_code(status_code, message)
    terminal = _canonical_terminal_snapshot(
        {
            "type": "billing.interrupted",
            "status": "failed",
            "invocation_id": session.invocation_id,
            "billing_status": financial.get("billing_status", "settled"),
        },
        http_status=status_code,
        code=public_code,
        message=message if status_code < 500 else "Internal server error",
        required_credits=None,
        billing_status=str(financial.get("billing_status") or "settled"),
    )
    if response_headers:
        terminal["headers"].update(
            {str(key): str(value) for key, value in response_headers.items()},
        )
    if no_items:
        sealed = (
            billing.open_api_repository.finalize_empty_invocation_execution(
                session.invocation_id,
                session.usage_order_id,
                execution_fence,
                status="failed",
                status_code=status_code,
                latency_ms=_latency_ms(started_at),
                error_summary=terminal["message"],
                terminal_event=terminal,
            )
        )
    else:
        sealed = billing.open_api_repository.finalize_invocation_execution(
            session.invocation_id,
            execution_fence,
            status="failed",
            status_code=status_code,
            latency_ms=_latency_ms(started_at),
            error_summary=terminal["message"],
            billing_status=str(financial.get("billing_status") or "settled"),
            terminal_event=terminal,
        )
    if sealed is None:
        await _wait_for_durable_terminal(
            billing.open_api_repository,
            session.invocation_id,
        )
        sealed = billing.open_api_repository.get_invocation(
            session.invocation_id,
        )
    snapshot = (sealed or {}).get("terminal_event_json")
    if not isinstance(snapshot, dict):
        raise HTTPException(
            status_code=503,
            detail="Open API invocation is still finalizing",
        )
    return _snapshot_json_response(snapshot)


async def _execution_heartbeat(
    execution: Any,
    *,
    heartbeat_seconds: float,
    producer_task: asyncio.Task | None,
) -> None:
    consecutive_failures = 0
    while True:
        if execution.finalizing:
            return
        await asyncio.sleep(heartbeat_seconds)
        if execution.finalizing:
            return
        try:
            execution.renew_lease()
        except ExecutionLeaseLostError:
            execution.note_lease_lost()
            active_producer = execution.producer_task or producer_task
            if active_producer is not None:
                active_producer.cancel()
            return
        except Exception:
            consecutive_failures += 1
            logger.exception("Open API execution lease heartbeat failed")
            if consecutive_failures >= 2:
                execution.note_lease_lost()
                active_producer = execution.producer_task or producer_task
                if active_producer is not None:
                    active_producer.cancel()
                return
        else:
            consecutive_failures = 0


async def _cancel_heartbeat(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _canonical_terminal_snapshot(
    terminal: dict[str, Any],
    *,
    http_status: int,
    code: str,
    message: str,
    required_credits: int | None,
    billing_status: str,
) -> dict[str, Any]:
    snapshot = dict(terminal)
    invocation_id = str(snapshot["invocation_id"])
    header_status = (
        "insufficient_credits"
        if code == "insufficient_credits"
        else billing_status
    )
    snapshot.update(
        {
            "http_status": int(http_status),
            "code": code,
            "message": message,
            "required_credits": required_credits,
            "headers": {
                "X-DClaw-Invocation-Id": invocation_id,
                "X-DClaw-Billing-Status": header_status,
            },
        },
    )
    return snapshot


def _snapshot_json_response(snapshot: dict[str, Any]) -> JSONResponse:
    headers = snapshot.get("headers")
    return JSONResponse(
        status_code=int(snapshot.get("http_status") or 200),
        content=snapshot,
        headers=(
            {str(key): str(value) for key, value in headers.items()}
            if isinstance(headers, dict)
            else None
        ),
    )


def _preproducer_error_code(status_code: int, message: str) -> str:
    if status_code == 429:
        return "task_limit_exceeded"
    if status_code == 404 and "target" in message.lower():
        return "open_target_unavailable"
    if status_code == 404:
        return "not_found"
    if status_code == 400:
        return "invalid_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    return "request_failed"


def _positive_seconds_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(0.01, value)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(1, value)


def _get_open_api_wait_queue(app: Any) -> _OpenApiWaitQueue:
    queue = getattr(app.state, "open_api_wait_queue", None)
    if queue is None:
        queue = _OpenApiWaitQueue()
        app.state.open_api_wait_queue = queue
    return queue


async def _acquire_open_api_permit(
    app: Any,
    *,
    publication_id: str,
    api_key_id: str,
) -> _OpenApiTaskPermit | None:
    limiter = get_task_limiter(app)
    queue = _get_open_api_wait_queue(app)
    publication_limit = _positive_int_env(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION",
        30,
    )
    api_key_limit = _positive_int_env(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY",
        20,
    )
    global_limit = _positive_int_env(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_GLOBAL",
        8,
    )
    agent_key = f"openapi-publication:{publication_id}"
    user_key = f"openapi-api-key:{api_key_id}"

    async def try_acquire():
        if not await queue.try_acquire_execution_slot(global_limit):
            return None
        try:
            permit = await limiter.try_acquire(
                agent_id=agent_key,
                user_id=user_key,
                max_per_agent=publication_limit,
                max_per_user=api_key_limit,
                record_rejection=False,
            )
        except Exception:
            await queue.release_execution_slot()
            raise
        if permit is None:
            await queue.release_execution_slot()
        return permit

    permit = await try_acquire()
    if permit is not None:
        return _OpenApiTaskPermit(permit, queue)

    ticket = await queue.try_join(
        publication_id,
        api_key_id,
        max_per_publication=_positive_int_env(
            "DCLAW_OPEN_API_MAX_WAITING_PER_PUBLICATION",
            200,
        ),
        max_per_api_key=_positive_int_env(
            "DCLAW_OPEN_API_MAX_WAITING_PER_API_KEY",
            100,
        ),
    )
    if ticket is None:
        await _note_limiter_rejection(limiter)
        return None

    deadline = time.monotonic() + _positive_seconds_env(
        "DCLAW_OPEN_API_WAIT_TIMEOUT_SECONDS",
        120.0,
    )
    poll_seconds = _positive_seconds_env(
        "DCLAW_OPEN_API_WAIT_POLL_SECONDS",
        0.25,
    )
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await _note_limiter_rejection(limiter)
                return None
            await queue.wait_for_slot(min(poll_seconds, remaining))
            permit = await try_acquire()
            if permit is not None:
                return _OpenApiTaskPermit(permit, queue)
    finally:
        await ticket.release()


async def _note_limiter_rejection(limiter: Any) -> None:
    note_rejection = getattr(limiter, "note_rejection", None)
    if callable(note_rejection):
        await note_rejection()


async def _attach_tracker_queue(tracker: Any, run_key: str) -> Any | None:
    attach = getattr(tracker, "attach", None)
    if not callable(attach):
        return None
    return await attach(run_key)


async def _wait_for_durable_terminal(repo: Any, invocation_id: str) -> None:
    try:
        wait_seconds = float(
            os.environ.get("DCLAW_OPEN_API_REPLAY_WAIT_SECONDS", "300"),
        )
    except ValueError:
        wait_seconds = 300.0
    deadline = time.monotonic() + max(0.1, wait_seconds)
    while time.monotonic() < deadline:
        invocation = repo.get_invocation(invocation_id) or {}
        if isinstance(invocation.get("terminal_event_json"), dict):
            return
        await asyncio.sleep(0.02)
    raise HTTPException(
        status_code=503,
        detail="Open API invocation is still running",
    )


def _streaming_response(
    tracker: Any,
    queue: Any,
    run_key: str,
    prepared: PreparedOpenRun,
    invocation_id: str,
    expert_team_run_id: str,
    invocation: dict[str, Any],
    *,
    initial_event: Any | None = None,
) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        stream_it = tracker.stream_from_queue(queue, run_key)
        try:
            if initial_event is not None:
                yield initial_event
            async for event in stream_it:
                yield event
        finally:
            await stream_it.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-QwenPaw-Chat-Id": prepared.chat_id,
            "X-QwenPaw-Session-Id": prepared.session_id,
            "X-QwenPaw-Open-Invocation-Id": invocation_id,
            "X-QwenPaw-Expert-Team-Run-Id": expert_team_run_id,
            "X-DClaw-Invocation-Id": invocation_id,
            "X-DClaw-Billing-Status": str(
                invocation.get("billing_status") or "reconciling",
            ),
        },
    )


def _is_insufficient_terminal_event(event: Any) -> bool:
    if not isinstance(event, (str, bytes)):
        return False
    text_event = event.decode("utf-8") if isinstance(event, bytes) else event
    for line in text_event.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[5:].strip())
        except (json.JSONDecodeError, TypeError):
            continue
        return bool(
            isinstance(payload, dict)
            and payload.get("type") == "billing.interrupted"
            and payload.get("code") == "insufficient_credits",
        )
    return False


def _sse(payload: dict[str, Any]) -> str:
    return (
        "data: "
        + json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n\n"
    )


async def _tracker_is_running(tracker: Any, run_key: str) -> bool:
    getter = getattr(tracker, "get_status", None)
    if not callable(getter):
        return False
    return await getter(run_key) == "running"


async def _detach_tracker_queue(
    tracker: Any,
    run_key: str,
    queue: Any,
) -> None:
    detach = getattr(tracker, "detach_subscriber", None)
    if callable(detach):
        await detach(run_key, queue)


def _record_failed_invocation(
    repo: Any,
    *,
    invocation_id: str,
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
    prepared: PreparedOpenRun | None,
    status_code: int,
    started_at: float,
    error_summary: str,
) -> None:
    try:
        updated = repo.update_invocation_status(
            invocation_id,
            status="failed",
            status_code=status_code,
            latency_ms=_latency_ms(started_at),
            error_summary=error_summary,
        )
        if updated is not None:
            return
        repo.create_invocation(
            _invocation_row(
                invocation_id=invocation_id,
                request=request,
                publication=publication,
                payload=payload,
                chat_id=prepared.chat_id if prepared else None,
                status="failed",
                status_code=status_code,
                latency_ms=_latency_ms(started_at),
                error_summary=error_summary,
            ),
        )
    except Exception:
        logger.exception("Failed to record Open API invocation failure")


def _update_invocation_status(
    repo: Any,
    *,
    invocation_id: str,
    status: str,
    status_code: int,
    latency_ms: int,
    error_summary: str,
) -> None:
    try:
        repo.update_invocation_status(
            invocation_id,
            status=status,
            status_code=status_code,
            latency_ms=latency_ms,
            error_summary=error_summary,
        )
    except Exception:
        logger.exception("Failed to update Open API invocation status")


def _extract_stream_failure(event_data: str) -> _OpenApiStreamFailure | None:
    for raw_line in event_data.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        error = payload.get("error")
        if isinstance(error, str):
            return _OpenApiStreamFailure(
                status="failed",
                code="request_failed",
                message="Request failed",
                http_status=500,
                error_summary=error,
            )
        if isinstance(error, dict):
            error_code = str(error.get("code") or "")
            known = _DIRECT_AGENT_FAILURES.get(error_code)
            if known is not None:
                http_status, safe_message = known
                return _OpenApiStreamFailure(
                    status="failed",
                    code=error_code,
                    message=safe_message,
                    http_status=http_status,
                    error_summary=f"{error_code}: {safe_message}",
                )
            return _OpenApiStreamFailure(
                status="failed",
                code="request_failed",
                message="Request failed",
                http_status=500,
                error_summary=json.dumps(error, ensure_ascii=False),
            )
        run = payload.get("run")
        if isinstance(run, dict):
            state = run.get("state")
            if state == "failed":
                summary = run.get("error")
                rendered = str(summary or "Expert team run failed")
                return _OpenApiStreamFailure(
                    status="failed",
                    code="request_failed",
                    message="Request failed",
                    http_status=500,
                    error_summary=rendered,
                )
            if state == "cancelled":
                summary = run.get("error")
                rendered = str(summary or "Expert team run cancelled")
                return _OpenApiStreamFailure(
                    status="cancelled",
                    code="request_cancelled",
                    message="Request cancelled",
                    http_status=499,
                    error_summary=rendered,
                )
    return None


def _stream_failure_status_code(status: str) -> int:
    return 499 if status == "cancelled" else 500


async def _request_is_disconnected(request: Request) -> bool:
    try:
        return bool(await request.is_disconnected())
    except Exception:
        return False


async def _get_tracker_payload(tracker: Any, run_key: str) -> Any | None:
    getter = getattr(tracker, "get_payload", None)
    if not callable(getter):
        return None
    try:
        return await getter(run_key)
    except Exception:
        logger.exception("Failed to read active Open API run payload")
        return None


def _invocation_row(
    *,
    invocation_id: str,
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
    chat_id: str | None,
    status: str,
    status_code: int,
    latency_ms: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "id": invocation_id,
        "app_id": str(request.state.open_app_id),
        "publication_id": str(publication["id"]),
        "api_key_id": str(request.state.open_api_key_id),
        "target_type": str(publication["target_type"]),
        "target_id": str(publication["target_id"]),
        "chat_id": chat_id,
        "external_session_id": payload.external_session_id or "default",
        "external_user_id": payload.external_user_id,
        "status": status,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "token_summary": {},
        "error_summary": error_summary,
    }


def _latency_ms(started_at: float) -> int:
    return max(0, int((time.monotonic() - started_at) * 1000))
