"""Authenticated command boundary for signed super-expert capabilities."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable
import uuid

from fastapi import APIRouter, HTTPException, Request
from agentscope.message import Msg
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field

from qwenpaw.constant import WORKING_DIR
from qwenpaw.aigc.operation_contract import load_operation_catalog
from qwenpaw.aigc.workflow_compiler import (
    AvailableWorkflowModel,
    WorkflowCompileError,
    compile_workflow,
    plan_manual_workflow,
)
from qwenpaw.aigc.workflow_contract import WorkflowBlueprint, workflow_node_registry

from ..billing.context import BillingSource
from ..aigc.workflow_execution import AigcWorkflowExecutionService
from ..billing.entrypoint import prepare_user_billing_execution
from ..billing.usage import InsufficientUsageCreditsError
from ..chat_access import ensure_chat_access
from ..aigc.resource_store import AigcResourceError
from ..runtime.aigc_media import review_media_source, resource_http_error
from ..super_experts.service import (
    SuperExpertPlatformService, SuperExpertPlatformError, PlatformCommandRequest,
    AigcCreateOperation, AigcWorkflowCreateArguments, _operation_catalog_path,
)
from ..super_experts.aigc_adapter import (
    load_workflow_capability_catalog as _load_workflow_capability_catalog,
)
from ..super_experts.composition import get_super_expert_platform_service
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
from ..super_experts.models import (
    AigcTaskBinding,
    AigcTaskScope,
    AigcTaskStatus,
    AigcWorkflowDefinition,
    AigcWorkflowGuideEvent,
)

router = APIRouter(
    prefix="/super-expert-platform",
    tags=["super-expert-platform"],
)
frontend_read_router = APIRouter(
    prefix="/super-expert-platform",
    tags=["super-expert-platform"],
)




















async def resolve_owned_asset_for_agent_review(
    request: Request, asset_id: str, *, canvas_id: str, node_ids: set[str],
    asset_kinds: set[str] | None = None, service=None,
) -> dict[str, Any]:
    service = service or get_super_expert_platform_service()
    if service.aigc is None:
        raise SuperExpertPlatformError("AIGC service is unavailable")
    assets = service.aigc.assets
    try:
        asset = assets.resolve_owned(str(getattr(request.state, "user_id", "") or ""), asset_id)
    except AigcResourceError as exc:
        if exc.code == "RESOURCE_NOT_FOUND":
            raise HTTPException(status_code=404, detail="Asset not found.") from exc
        raise resource_http_error(exc) from exc
    return await review_media_source(request, assets, asset, canvas_id=canvas_id,
                                     node_ids=node_ids, asset_kinds=asset_kinds)


def _workflow_review_binding(task: Any) -> tuple[set[str], set[str]]:
    """Return the exact physical producers and media kinds allowed for review."""
    binding = task.binding
    workflow = task.workflow
    if workflow is None:
        return {binding.node_id}, {"image", "video", "audio"}

    blueprint = workflow.blueprint
    by_id = {node.node_id: node for node in blueprint.nodes}
    incoming: dict[str, list[str]] = {}
    for edge in blueprint.edges:
        incoming.setdefault(edge.target, []).append(edge.source)

    producer_ids: set[str] = set()

    def collect(logical_node_id: str, visited: set[str]) -> None:
        if logical_node_id in visited:
            return
        visited.add(logical_node_id)
        node = by_id.get(logical_node_id)
        if node is None:
            return
        if node.kind == "output":
            for source in incoming.get(logical_node_id, []):
                collect(source, visited)
            return
        producer_ids.add(logical_node_id)

    collect(blueprint.output_node_id, set())
    physical_ids = {
        binding.node_bindings[logical_id]
        for logical_id in producer_ids
        if logical_id in binding.node_bindings
    }
    if not physical_ids:
        physical_ids = {binding.output_node_id or binding.node_id}

    registry = workflow_node_registry()
    output_types = {
        registry[logical.kind].output_type
        for logical_id in producer_ids
        if (logical := by_id.get(logical_id)) is not None
        and logical.kind in registry
    }
    if not output_types or "asset" in output_types:
        asset_kinds = {"image", "video", "audio"}
    else:
        asset_kinds = output_types & {"image", "video", "audio"}
    return physical_ids, asset_kinds


def _workflow_review_node_ids(task: Any) -> set[str]:
    """Compatibility helper used by tests and review dispatch diagnostics."""
    return _workflow_review_binding(task)[0]




@frontend_read_router.get("/tasks/{material_task_id}")
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


@frontend_read_router.get("/tasks/{material_task_id}/guide")
@router.get("/tasks/{material_task_id}/guide")
def get_super_expert_task_guide(
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
    if task.workflow is None:
        raise HTTPException(status_code=409, detail="LEGACY_TASK_GUIDE_REQUIRED")
    from ..super_experts.aigc_guide import project_aigc_guide
    service = get_super_expert_platform_service()
    if service.aigc is None:
        raise HTTPException(status_code=503, detail="AIGC service is unavailable")

    canvas, jobs = service.aigc.workflow_context(
        canvas_id=task.binding.canvas_id,
        material_task_id=task.binding.material_task_id,
    )
    return project_aigc_guide(
        task=task,
        canvas=canvas,
        jobs=jobs,
    ).model_dump(mode="json")


@frontend_read_router.get("/operations/{operation_id}")
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


@frontend_read_router.get("/workflow-capabilities")
@router.get("/workflow-capabilities")
async def get_workflow_capability_catalog(_request: Request) -> dict[str, Any]:
    catalog = await _load_workflow_capability_catalog()
    return catalog.model_dump(mode="json")


@router.post("/commands/{capability}")
async def execute_super_expert_command(
    capability: str,
    command: PlatformCommandRequest,
    request: Request,
) -> dict[str, Any]:
    tenant_id = str(getattr(request.state, "tenant_id", "local") or "local")
    binding = (
        command.arguments.get("scope")
        if capability in {"aigc.task.create/2", "aigc.workflow.create/1"}
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
        asset_validator = None
        if capability == "aigc.asset.submit":
            async def validate_asset(
                candidate_binding: AigcTaskBinding,
                asset_id: str,
                current_task: Any,
            ) -> None:
                node_ids, asset_kinds = _workflow_review_binding(current_task)
                await resolve_owned_asset_for_agent_review(
                    request,
                    asset_id,
                    canvas_id=candidate_binding.canvas_id,
                    node_ids=node_ids,
                    asset_kinds=asset_kinds,
                    service=service,
                )

            asset_validator = validate_asset
        result = await service.execute(
            tenant_id=tenant_id,
            user_id=str(getattr(request.state, "user_id", "") or ""),
            installation_id=command.installation_id,
            capability=capability,
            contract_version=command.contract_version,
            arguments=command.arguments,
            idempotency_key=command.idempotency_key,
            asset_validator=asset_validator,
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
        task_getter = getattr(service, "get_task", None)
        current_task = (
            task_getter(binding.material_task_id) if callable(task_getter) else None
        )
        node_ids, asset_kinds = (
            _workflow_review_binding(current_task)
            if current_task is not None
            else ({binding.node_id}, {"image", "video", "audio"})
        )
        media_block = await resolve_owned_asset_for_agent_review(
            request,
            asset_id,
            canvas_id=binding.canvas_id,
            node_ids=node_ids,
            asset_kinds=asset_kinds,
            service=service,
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
