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
    PreparedOpenRun,
    create_open_api_billing_runtime,
    open_api_billing_context,
    prepare_open_agent_chat,
    prepare_open_expert_team_chat,
)
from ..sealed_agents.registry import get_sealed_agent_registry
from ..storage.repos.open_api_repo import get_open_api_repository
from ..task_limits import get_task_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/open/v1", tags=["open-api"])


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

    sealed_target = str(
        publication.get("target_type")
    ) == "agent" and get_sealed_agent_registry().is_sealed(
        str(publication.get("target_id")),
    )
    if sealed_target:
        sealed_record = get_sealed_agent_registry().get_agent(
            str(publication["target_id"]),
        )
        if (
            sealed_record is None
            or not sealed_record.enabled
            or sealed_record.active_release_id is None
        ):
            raise HTTPException(
                status_code=503,
                detail="Sealed agent target is unavailable",
            )

    if payload.stream is False:
        raise HTTPException(
            status_code=400,
            detail="Open API messages currently require stream=true",
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

    billing = create_open_api_billing_runtime()
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
                payload=payload.model_dump(mode="json"),
                idempotency_key=request.headers.get("Idempotency-Key"),
                mode=billing.mode,  # type: ignore[arg-type]
                budget_credits=billing.budget_credits,
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
                    sealed_target=sealed_target,
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
            permit = await get_task_limiter(request.app).try_acquire(
                agent_id=prepared.agent_id,
                user_id=bound_user_id,
            )
            if permit is None:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "Too many running tasks. Please wait for an existing "
                        "task to finish and try again."
                    ),
                )

        assert execution_fence is not None
        assert execution is not None

        async def limited_stream_fn(stream_payload):
            stream_started_at = time.monotonic()
            stream_failure: tuple[str, str] | None = None
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
        sealed_target=sealed_target,
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
    stream_failure: tuple[str, str] | None,
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
        elif stream_exception is not None:
            status = "failed"
            status_code = 500
            error_summary = str(stream_exception)
            billing_error_code = None
            public_code = "request_failed"
            public_message = "Internal server error"
            required_credits = None
        elif stream_failure is not None:
            status, error_summary = stream_failure
            status_code = _stream_failure_status_code(status)
            billing_error_code = None
            public_code = "request_failed"
            public_message = "Request failed"
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
    sealed_target: bool = False,
    initial_event: Any | None = None,
) -> StreamingResponse:
    async def event_generator() -> AsyncGenerator[str, None]:
        stream_it = tracker.stream_from_queue(queue, run_key)
        try:
            if initial_event is not None:
                public_event = _public_stream_event(
                    initial_event,
                    sealed_target=sealed_target,
                )
                if public_event is not None:
                    yield public_event
            async for event in stream_it:
                public_event = _public_stream_event(
                    event,
                    sealed_target=sealed_target,
                )
                if public_event is not None:
                    yield public_event
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


_SEALED_PUBLIC_EVENT_TYPES = {
    "response.started",
    "response.output_text.delta",
    "response.artifact.ready",
    "response.completed",
    "billing.completed",
    "billing.interrupted",
}


def _sealed_failure_event() -> str:
    return (
        "data: "
        + json.dumps(
            {"type": "response.failed", "error": "sealed_agent_failed"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n\n"
    )


def _public_stream_event(
    event: Any,
    *,
    sealed_target: bool,
) -> Any | None:
    if not sealed_target:
        return event
    if isinstance(event, bytes):
        event = event.decode("utf-8", errors="replace")
    if not isinstance(event, str):
        return None
    return _sanitize_sealed_stream_event(event)


def _sanitize_sealed_stream_event(event_data: str) -> str | None:
    """Serialize sealed streams from an allowlist, never a denylist."""
    for raw_line in event_data.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if "error" in payload:
            return _sealed_failure_event()
        if payload.get("type") not in _SEALED_PUBLIC_EVENT_TYPES:
            return None
        return f"data: {raw}\n\n"
    return None


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


def _extract_stream_failure(event_data: str) -> tuple[str, str] | None:
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
            return "failed", error
        if isinstance(error, dict):
            return "failed", json.dumps(error, ensure_ascii=False)
        run = payload.get("run")
        if isinstance(run, dict):
            state = run.get("state")
            if state == "failed":
                summary = run.get("error")
                return "failed", str(summary or "Expert team run failed")
            if state == "cancelled":
                summary = run.get("error")
                return "cancelled", str(summary or "Expert team run cancelled")
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
