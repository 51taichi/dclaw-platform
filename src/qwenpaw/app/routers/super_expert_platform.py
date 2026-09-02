"""Authenticated command boundary for signed super-expert capabilities."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from agentscope.message import Msg
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field

from qwenpaw.constant import WORKING_DIR
from qwenpaw.aigc.operation_contract import load_operation_catalog

from ..billing.context import BillingSource
from ..billing.entrypoint import prepare_user_billing_execution
from ..billing.usage import InsufficientUsageCreditsError
from ..chat_access import ensure_chat_access
from ..runtime.event_bus import RuntimeEvent, get_runtime_event_bus
from ..super_experts.aigc_tasks import (
    AigcTaskCommand,
    AigcTaskError,
    AigcTaskRepository,
)
from ..super_experts.events import (
    SuperExpertEventEnvelope,
    SuperExpertEventRepository,
)
from ..super_experts.grants import SuperExpertGrantRepository
from ..super_experts.models import AigcTaskBinding, AigcTaskScope, AigcTaskStatus

router = APIRouter(
    prefix="/super-expert-platform",
    tags=["super-expert-platform"],
)


class SuperExpertPlatformError(ValueError):
    """A public-safe capability invocation failure."""


class PlatformCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    installation_id: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    arguments: dict[str, Any]


class AigcCreateOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    operation_version: str = Field(min_length=1)
    arguments: dict[str, Any]


_EVENT_TYPES = {
    "card.create": "card.created",
    "card.update": "card.updated",
    "aigc.task.create": "aigc.task.created",
    "aigc.task.create/2": "aigc.task.created",
    "aigc.task.resume": "aigc.task.resumed",
    "aigc.task.cancel": "aigc.task.cancelled",
    "aigc.guide.update": "aigc.guide.updated",
    "aigc.asset.submit": "aigc.asset.submitted",
    "aigc.review.complete": "aigc.review.completed",
}


class SuperExpertPlatformService:
    def __init__(
        self,
        *,
        grant_repository: SuperExpertGrantRepository,
        task_repository: AigcTaskRepository,
        event_repository: SuperExpertEventRepository,
        event_bus: Any,
    ) -> None:
        self.grant_repository = grant_repository
        self.task_repository = task_repository
        self.event_repository = event_repository
        self.event_bus = event_bus
        self._review_locks: dict[str, asyncio.Lock] = {}

    def get_task(self, material_task_id: str):
        return self.task_repository.get(material_task_id)

    def list_session_events(
        self,
        *,
        installation_id: str,
        conversation_id: str,
    ):
        return self.event_repository.list_for_session(
            installation_id=installation_id,
            conversation_id=conversation_id,
        )

    def review_lock(self, event_id: str) -> asyncio.Lock:
        return self._review_locks.setdefault(event_id, asyncio.Lock())

    def get_review_receipt(self, event_id: str) -> dict[str, Any] | None:
        return self.event_repository.get_review_receipt(event_id)

    def save_review_receipt(
        self,
        event_id: str,
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        return self.event_repository.save_review_receipt(event_id, receipt)

    async def execute(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
        installation_id: str,
        capability: str,
        contract_version: str,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        decision = self.grant_repository.authorize_capability(
            installation_id,
            capability,
            contract_version,
            tenant_id=tenant_id,
        )
        if not decision.allowed:
            raise SuperExpertPlatformError("capability is not authorized")
        if capability not in _EVENT_TYPES:
            raise SuperExpertPlatformError("capability is not supported")
        event_id = str(arguments.get("event_id") or "")
        if not event_id:
            raise SuperExpertPlatformError("event id is required")

        try:
            if capability == "aigc.task.create/2":
                result, binding = self._create_bound_aigc_task(
                    installation_id=installation_id,
                    user_id=user_id,
                    event_id=event_id,
                    arguments=arguments,
                    idempotency_key=idempotency_key,
                )
            else:
                try:
                    binding = AigcTaskBinding.model_validate(arguments.get("binding"))
                except Exception as exc:
                    raise SuperExpertPlatformError("command binding is invalid") from exc
                if binding.installation_id != installation_id:
                    raise SuperExpertPlatformError("command binding mismatch")
                result = self._apply_capability(
                    capability=capability,
                    binding=binding,
                    event_id=event_id,
                    arguments=arguments,
                    idempotency_key=idempotency_key,
                )
        except (AigcTaskError, ValueError) as exc:
            raise SuperExpertPlatformError(str(exc)) from exc
        task = result.get("task")
        asset_id = task.asset_id if task is not None else arguments.get("asset_id")
        event_payload = dict(result.get("payload", {}))
        if task is not None:
            event_payload["task_status"] = task.status.value
            event_payload["task_version"] = task.version
        envelope = SuperExpertEventEnvelope(
            event_id=event_id,
            installation_id=binding.installation_id,
            conversation_id=binding.conversation_id,
            agent_task_id=binding.agent_task_id,
            content_revision=binding.content_revision,
            material_task_id=binding.material_task_id,
            canvas_id=binding.canvas_id,
            node_id=binding.node_id,
            asset_id=asset_id,
            event_type=_EVENT_TYPES[capability],
            payload=event_payload,
        )
        if self.event_repository.append(envelope):
            await self.event_bus.publish(
                RuntimeEvent(
                    id=event_id,
                    type="super_expert_event",
                    scope="session",
                    session_id=binding.conversation_id,
                    job_id=binding.material_task_id,
                    status=(task.status.value if task is not None else None),
                    payload={"envelope": envelope.model_dump(mode="json")},
                ),
            )
        response = {"event": envelope.model_dump(mode="json")}
        if task is not None:
            response["task"] = task.model_dump(mode="json")
        else:
            response["card"] = result["payload"]
        return response

    def _create_bound_aigc_task(
        self,
        *,
        installation_id: str,
        user_id: str | None,
        event_id: str,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[dict[str, Any], AigcTaskBinding]:
        if set(arguments) != {"scope", "event_id", "operation"}:
            if "binding" in arguments:
                raise SuperExpertPlatformError(
                    "physical binding must be created by DClaw",
                )
            raise SuperExpertPlatformError("create v2 arguments are invalid")
        if not isinstance(user_id, str) or not user_id.strip():
            raise SuperExpertPlatformError("task owner is unavailable")
        try:
            scope = AigcTaskScope.model_validate(arguments.get("scope"))
            operation = AigcCreateOperation.model_validate(arguments.get("operation"))
        except Exception as exc:
            raise SuperExpertPlatformError("create v2 arguments are invalid") from exc
        if scope.installation_id != installation_id:
            raise SuperExpertPlatformError("command binding mismatch")
        catalog_path = _operation_catalog_path()
        try:
            definition = load_operation_catalog(catalog_path).operation(
                operation.operation_id,
            )
        except KeyError as exc:
            raise SuperExpertPlatformError("AIGC operation is unavailable") from exc
        if definition.version != operation.operation_version:
            raise SuperExpertPlatformError("AIGC operation version is unavailable")
        try:
            Draft202012Validator(definition.arguments_schema).validate(
                operation.arguments,
            )
        except JsonSchemaValidationError as exc:
            raise SuperExpertPlatformError("AIGC operation arguments are invalid") from exc

        current = self.task_repository.get(scope.material_task_id)
        provisioned_canvas_id: str | None = None
        if current is not None:
            current_scope = AigcTaskScope.model_validate(
                current.binding.model_dump(
                    exclude={"canvas_id", "node_id"},
                    mode="json",
                ),
            )
            if current_scope != scope:
                raise SuperExpertPlatformError("task binding mismatch")
            binding = current.binding
        else:
            from .aigc_studio import provision_super_expert_aigc_workspace

            provisioned = provision_super_expert_aigc_workspace(
                owner_user_id=user_id,
                material_task_id=scope.material_task_id,
                operation_id=operation.operation_id,
                arguments=operation.arguments,
            )
            provisioned_canvas_id = provisioned["canvas_id"]
            binding = AigcTaskBinding(
                **scope.model_dump(mode="json"),
                **provisioned,
            )
        try:
            task = self.task_repository.apply(
                AigcTaskCommand(
                    action="create",
                    event_id=event_id,
                    binding=binding,
                    operation_id=operation.operation_id,
                    operation_version=operation.operation_version,
                    operation_arguments=operation.arguments,
                ),
                idempotency_key=idempotency_key,
            )
        except Exception:
            if provisioned_canvas_id is not None:
                from .aigc_studio import discard_super_expert_aigc_workspace

                discard_super_expert_aigc_workspace(
                    owner_user_id=user_id,
                    material_task_id=scope.material_task_id,
                    canvas_id=provisioned_canvas_id,
                )
            raise
        return {
            "task": task,
            "payload": {
                "operation_id": operation.operation_id,
                "operation_version": operation.operation_version,
            },
        }, binding

    def _apply_capability(
        self,
        *,
        capability: str,
        binding: AigcTaskBinding,
        event_id: str,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if capability in {"card.create", "card.update"}:
            return {"payload": dict(arguments.get("card") or {})}
        current = self.task_repository.get(binding.material_task_id)
        if capability == "aigc.task.create":
            action = "create"
        elif capability == "aigc.task.resume":
            action = (
                "start"
                if current and current.status == AigcTaskStatus.WAITING_TO_START
                else "resume"
            )
        elif capability == "aigc.task.cancel":
            action = "cancel"
        elif capability == "aigc.asset.submit":
            action = "submit"
        elif capability == "aigc.guide.update":
            if current is None or current.binding != binding:
                raise SuperExpertPlatformError("task binding mismatch")
            return {"task": current, "payload": dict(arguments.get("guide") or {})}
        elif capability == "aigc.review.complete":
            if current is None or current.binding != binding:
                raise SuperExpertPlatformError("task binding mismatch")
            supplied_asset = arguments.get("asset_id")
            if supplied_asset is not None and supplied_asset != current.asset_id:
                raise SuperExpertPlatformError("asset binding mismatch")
            if current.status == AigcTaskStatus.SUBMITTED:
                current = self.task_repository.apply(
                    AigcTaskCommand(
                        action="review",
                        event_id=f"{event_id}:review",
                        binding=binding,
                    ),
                    idempotency_key=f"{idempotency_key}:review",
                )
            decision = arguments.get("decision")
            action = "accept" if decision == "ACCEPTED" else "request_revision"
        else:
            raise SuperExpertPlatformError("capability is not supported")
        task = self.task_repository.apply(
            AigcTaskCommand(
                action=action,
                event_id=event_id,
                binding=binding,
                asset_id=(
                    arguments.get("asset_id")
                    if capability == "aigc.asset.submit"
                    else None
                ),
            ),
            idempotency_key=idempotency_key,
        )
        return {"task": task, "payload": dict(arguments.get("payload") or {})}


_service: SuperExpertPlatformService | None = None


def _operation_catalog_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "aigc"
        / "contracts"
        / "aigc-operation-contract-v1.json"
    )


def get_super_expert_platform_service() -> SuperExpertPlatformService:
    global _service
    if _service is None:
        root = Path(WORKING_DIR) / "sealed_agents"
        _service = SuperExpertPlatformService(
            grant_repository=SuperExpertGrantRepository(root),
            task_repository=AigcTaskRepository(root / "platform"),
            event_repository=SuperExpertEventRepository(root / "platform"),
            event_bus=get_runtime_event_bus(),
        )
    return _service


@router.get("/tasks/{material_task_id}")
def get_super_expert_task(
    material_task_id: str,
    request: Request,
) -> dict[str, Any]:
    task = get_super_expert_platform_service().get_task(material_task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="AIGC task not found")
    ensure_chat_access(
        request,
        task.binding.conversation_id,
        allow_admin=True,
    )
    return task.model_dump(mode="json")


@router.get("/operations/{operation_id}")
def get_aigc_operation_contract(
    operation_id: str,
    _request: Request,
) -> dict[str, Any]:
    try:
        operation = load_operation_catalog(_operation_catalog_path()).operation(
            operation_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AIGC operation not found") from exc
    return operation.model_dump(mode="json")


@router.post("/commands/{capability}")
async def execute_super_expert_command(
    capability: str,
    command: PlatformCommandRequest,
    request: Request,
) -> dict[str, Any]:
    tenant_id = str(getattr(request.state, "tenant_id", "local") or "local")
    binding = (
        command.arguments.get("scope")
        if capability == "aigc.task.create/2"
        else command.arguments.get("binding")
    )
    conversation_id = (
        str(binding.get("conversation_id") or "")
        if isinstance(binding, dict)
        else ""
    )
    if not conversation_id:
        raise HTTPException(status_code=400, detail="command binding is invalid")
    ensure_chat_access(request, conversation_id, allow_admin=True)
    service = get_super_expert_platform_service()
    try:
        result = await service.execute(
            tenant_id=tenant_id,
            user_id=str(getattr(request.state, "user_id", "") or ""),
            installation_id=command.installation_id,
            capability=capability,
            contract_version=command.contract_version,
            arguments=command.arguments,
            idempotency_key=command.idempotency_key,
        )
        if capability == "aigc.asset.submit":
            submit_event_id = str(command.arguments.get("event_id") or "")
            async with service.review_lock(submit_event_id):
                review = service.get_review_receipt(submit_event_id)
                if review is None:
                    current_task = service.get_task(
                        AigcTaskBinding.model_validate(binding).material_task_id,
                    )
                    if current_task is not None and current_task.status in {
                        AigcTaskStatus.ACCEPTED,
                        AigcTaskStatus.REVISION_REQUIRED,
                    }:
                        review = {
                            "status": "completed",
                            "reply": (
                                "审核已完成，素材已通过，可以返回会话继续。"
                                if current_task.status == AigcTaskStatus.ACCEPTED
                                else "审核已完成，素材需要修改，请按当前任务继续调整。"
                            ),
                        }
                    else:
                        review = await _dispatch_agent_asset_review(
                            request,
                            service=service,
                            installation_id=command.installation_id,
                            binding=AigcTaskBinding.model_validate(binding),
                            asset_id=str(command.arguments.get("asset_id") or ""),
                            request_key=f"{command.idempotency_key}:agent-review",
                        )
                    review = service.save_review_receipt(submit_event_id, review)
                result["agent_review"] = review
            reviewed_task = service.get_task(
                AigcTaskBinding.model_validate(binding).material_task_id,
            )
            if reviewed_task is not None:
                result["task"] = reviewed_task
        return result
    except InsufficientUsageCreditsError as exc:
        raise HTTPException(
            status_code=402,
            detail="insufficient usage credits",
        ) from exc
    except SuperExpertPlatformError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


async def _dispatch_agent_asset_review(
    request: Request,
    *,
    service: SuperExpertPlatformService,
    installation_id: str,
    binding: AigcTaskBinding,
    asset_id: str,
    request_key: str,
) -> dict[str, Any]:
    """Run a generic platform-originated Agent turn while the customer stays in AIGC."""
    grant = service.grant_repository.get(installation_id)
    if grant is None:
        raise SuperExpertPlatformError("installation grant is unavailable")
    if not asset_id:
        raise SuperExpertPlatformError("submitted asset is unavailable")
    try:
        from .aigc_studio import resolve_owned_asset_for_agent_review

        media_block = await resolve_owned_asset_for_agent_review(
            request,
            asset_id,
            canvas_id=binding.canvas_id,
            node_id=binding.node_id,
        )
        manager = request.app.state.multi_agent_manager
        workspace = await manager.get_agent(grant.agent_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise SuperExpertPlatformError("agent review dispatch is unavailable") from exc

    user_id = str(getattr(request.state, "user_id", "platform-user") or "platform-user")
    turn_request = SimpleNamespace(
        session_id=binding.conversation_id,
        user_id=user_id,
        channel="platform:aigc-review",
        tenant_id=grant.tenant_id,
        channel_meta={},
        request_context={"platform_event": "aigc.asset.submitted"},
        root_session_id=binding.conversation_id,
    )
    messages = [
        Msg(
            name="user",
            role="user",
            content=[
                {
                    "type": "text",
                    "text": (
                        "当前绑定的 DClaw AIGC 素材已由客户明确提交。"
                        "请在当前审核阶段读取附件并完成审核；只输出一个当前结论和一个下一步动作。"
                    ),
                },
                media_block,
            ],
        )
    ]
    final_message: Msg | None = None
    prepared = prepare_user_billing_execution(
        user_id,
        BillingSource(
            type="client",
            id=binding.conversation_id,
            expert_id=grant.agent_id,
        ),
        request_key,
        {
            "installation_id": installation_id,
            "conversation_id": binding.conversation_id,
            "material_task_id": binding.material_task_id,
            "asset_id": asset_id,
        },
    )
    try:
        with prepared.activate():
            async for message, is_last in workspace.runner.query_handler(
                messages,
                turn_request,
            ):
                if is_last:
                    final_message = message
    except InsufficientUsageCreditsError:
        prepared.finalize("failed", error_code="INSUFFICIENT_CREDITS")
        raise
    except asyncio.CancelledError:
        prepared.finalize("cancelled", error_code="CANCELLED")
        raise
    except Exception as exc:
        prepared.finalize("failed", error_code="MODEL_ERROR")
        raise SuperExpertPlatformError("agent review dispatch failed") from exc
    if final_message is None:
        prepared.finalize("failed", error_code="MISSING_COMPLETION")
        raise SuperExpertPlatformError("agent review did not complete")
    reply = final_message.get_text_content()
    if not isinstance(reply, str) or not reply.strip():
        prepared.finalize("failed", error_code="INVALID_COMPLETION")
        raise SuperExpertPlatformError("agent review result is invalid")
    prepared.finalize_completed()
    return {"status": "completed", "reply": reply}
