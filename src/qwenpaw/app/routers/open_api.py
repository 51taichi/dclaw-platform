# -*- coding: utf-8 -*-
"""External Open API message runtime routes."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import JSONResponse, StreamingResponse

from ..billing.open_api import (
    CatalogNotReadyError,
    OpenApiBillingCommand,
    OpenApiPublicationNotFoundError,
)
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
    OpenMessageRequest,
    PreparedOpenRun,
    create_open_api_billing_runtime,
    open_api_billing_context,
    prepare_open_agent_chat,
    prepare_open_expert_team_chat,
)
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

    invocation_id = billing_session.invocation_id

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
            expert_team_run_id = str(uuid.uuid4())
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

        billing.open_api_repository.update_billing_invocation(
            invocation_id,
            chat_id=prepared.chat_id,
        )

        tracker = prepared.workspace.task_tracker
        run_key = f"open-api:{invocation_id}"
        if billing_session.replayed and not await _tracker_is_running(
            tracker,
            run_key,
        ):
            return _terminal_replay_response(
                billing,
                billing_session,
                prepared,
                expert_team_run_id,
            )

        permit = None
        if not billing_session.replayed:
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

        execution = billing.execution()

        async def limited_stream_fn(stream_payload):
            stream_started_at = time.monotonic()
            stream_failure: tuple[str, str] | None = None
            stream_exception: Exception | None = None
            with open_api_billing_context(billing_session, execution.meter):
                try:
                    async for item in stream_fn(stream_payload):
                        execution.note_stream_ready()
                        if stream_failure is None:
                            stream_failure = _extract_stream_failure(item)
                        yield item
                except InsufficientUsageCreditsError as exc:
                    execution.note_insufficient(exc)
                except Exception as exc:
                    stream_exception = exc
                    billing.open_api_repository.update_billing_invocation(
                        invocation_id,
                        status="failed",
                        status_code=500,
                        latency_ms=_latency_ms(stream_started_at),
                        error_summary=str(exc),
                    )
                    yield _sse({"error": "internal server error"})
                finally:
                    execution.note_stream_ready()

            terminal = _terminal_billing_payload(
                billing,
                billing_session,
                execution.insufficient,
            )
            if execution.insufficient is not None:
                final_status = (
                    "partially_completed"
                    if terminal["completed_steps"]
                    else "failed"
                )
                billing.open_api_repository.update_billing_invocation(
                    invocation_id,
                    status=final_status,
                    status_code=409,
                    latency_ms=_latency_ms(stream_started_at),
                    error_summary="insufficient credits",
                    billing_error_code="insufficient_credits",
                )
            elif stream_exception is not None:
                # The exception status was written above.  Keep it while still
                # delivering the sealed billing terminal event.
                pass
            elif stream_failure is not None:
                status, error_summary = stream_failure
                billing.open_api_repository.update_billing_invocation(
                    invocation_id,
                    status=status,
                    status_code=_stream_failure_status_code(status),
                    latency_ms=_latency_ms(stream_started_at),
                    error_summary=error_summary,
                )
            else:
                billing.open_api_repository.update_billing_invocation(
                    invocation_id,
                    status="succeeded",
                    status_code=200,
                    latency_ms=_latency_ms(stream_started_at),
                    error_summary="",
                )
            yield _sse(terminal)

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
        billing.open_api_repository.update_billing_invocation(
            invocation_id,
            status="running",
            status_code=202,
            latency_ms=_latency_ms(started_at),
            error_summary="",
        )
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
            except InsufficientUsageCreditsError as exc:
                await _detach_tracker_queue(tracker, run_key, queue)
                return JSONResponse(
                    status_code=409,
                    content={
                        "code": "insufficient_credits",
                        "remaining_credits": exc.available,
                        "required_credits": exc.required,
                        "invocation_id": invocation_id,
                    },
                    headers={
                        "X-DClaw-Invocation-Id": invocation_id,
                        "X-DClaw-Billing-Status": "insufficient_credits",
                    },
                )
    except HTTPException as exc:
        billing.open_api_repository.update_billing_invocation(
            invocation_id,
            status="failed",
            status_code=exc.status_code,
            latency_ms=_latency_ms(started_at),
            error_summary=str(exc.detail),
        )
        raise
    except Exception as exc:
        billing.open_api_repository.update_billing_invocation(
            invocation_id,
            status="failed",
            status_code=500,
            latency_ms=_latency_ms(started_at),
            error_summary=str(exc),
        )
        raise

    async def event_generator() -> AsyncGenerator[str, None]:
        stream_it = tracker.stream_from_queue(queue, run_key)
        try:
            async for event_data in stream_it:
                yield event_data
        finally:
            await stream_it.aclose()

    current = billing.open_api_repository.get_invocation(invocation_id) or {}

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
                current.get("billing_status") or "quoted",
            ),
        },
    )


def _terminal_replay_response(
    billing: Any,
    session: Any,
    prepared: PreparedOpenRun,
    expert_team_run_id: str,
) -> StreamingResponse | JSONResponse:
    invocation = (
        billing.open_api_repository.get_invocation(
            session.invocation_id,
        )
        or {}
    )
    if invocation.get("billing_error_code") == "insufficient_credits":
        balance = billing.repository.balance(session.wallet_id)
        return JSONResponse(
            status_code=409,
            content={
                "code": "insufficient_credits",
                "remaining_credits": balance.available,
                "invocation_id": session.invocation_id,
            },
            headers={
                "X-DClaw-Invocation-Id": session.invocation_id,
                "X-DClaw-Billing-Status": "insufficient_credits",
            },
        )
    payload = _terminal_billing_payload(billing, session, None)

    async def replay_event() -> AsyncGenerator[str, None]:
        yield _sse(payload)

    return StreamingResponse(
        replay_event(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-QwenPaw-Chat-Id": prepared.chat_id,
            "X-QwenPaw-Session-Id": prepared.session_id,
            "X-QwenPaw-Open-Invocation-Id": session.invocation_id,
            "X-QwenPaw-Expert-Team-Run-Id": expert_team_run_id,
            "X-DClaw-Invocation-Id": session.invocation_id,
            "X-DClaw-Billing-Status": str(
                invocation.get("billing_status") or "reconciling",
            ),
        },
    )


def _terminal_billing_payload(
    billing: Any,
    session: Any,
    insufficient: InsufficientUsageCreditsError | None,
) -> dict[str, Any]:
    items = billing.usage_service.list_items(session.usage_order_id)
    if not items:
        # No supplier call exists. Seal the bridge order without inventing an
        # item or touching the ledger; this includes initial reserve failure.
        from datetime import datetime, timezone

        from sqlalchemy import update

        from ..storage.schema import billing_usage_orders, open_api_invocations

        now = datetime.now(timezone.utc)
        with billing.repository.engine.begin() as conn:
            conn.execute(
                update(billing_usage_orders)
                .where(
                    billing_usage_orders.c.id == session.usage_order_id,
                    billing_usage_orders.c.status == "quoted",
                )
                .values(status="settled", settled_at=now, updated_at=now),
            )
            conn.execute(
                update(open_api_invocations)
                .where(open_api_invocations.c.id == session.invocation_id)
                .values(billing_status="settled"),
            )
    order = billing.usage_service.get_order(session.usage_order_id)
    balance = billing.repository.balance(session.wallet_id)
    completed = sum(
        1 for item in items if item["status"] in {"captured", "released"}
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
    billing_status = str(order["status"])
    if billing_status == "settled" and int(order["captured_credits"]):
        billing_status = "captured"
    return {
        "type": "billing.completed",
        "invocation_id": session.invocation_id,
        "credits_used": int(order["captured_credits"]),
        "credits_remaining": balance.available,
        "billing_status": billing_status,
    }


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
