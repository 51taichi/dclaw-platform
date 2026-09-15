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
from ..agent_context import get_current_chat_model, set_current_chat_model
from ..billing.entrypoint import prepare_user_billing_execution
from ..billing.usage import InsufficientUsageCreditsError
from ..chat_access import ensure_chat_access
from ..aigc.resource_store import AigcResourceError
from ..runtime.aigc_media import review_media_source, resource_http_error
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


def _review_provider_is_configured(provider: Any) -> bool:
    if bool(getattr(provider, "disabled", False)):
        return False
    if bool(getattr(provider, "is_local", False)):
        return True
    if bool(getattr(provider, "is_custom", False)):
        return bool(str(getattr(provider, "base_url", "") or "").strip())
    if getattr(provider, "require_api_key", True) is False:
        return bool(str(getattr(provider, "base_url", "") or "").strip())
    return bool(str(getattr(provider, "api_key", "") or "").strip())


def _review_provider_inventory(manager: Any) -> list[Any]:
    providers: list[Any] = []
    seen: set[str] = set()
    for collection_name in ("builtin_providers", "custom_providers"):
        for provider in getattr(manager, collection_name, {}).values():
            provider_id = str(getattr(provider, "id", "") or "")
            if provider_id and provider_id not in seen:
                providers.append(provider)
                seen.add(provider_id)
    get_provider = getattr(manager, "get_provider", None)
    for provider_id, entry in getattr(manager, "plugin_providers", {}).items():
        provider = (
            get_provider(provider_id)
            if callable(get_provider)
            else (entry.get("provider") if isinstance(entry, dict) else entry)
        )
        resolved_id = str(getattr(provider, "id", "") or provider_id)
        if provider is not None and resolved_id not in seen:
            providers.append(provider)
            seen.add(resolved_id)
    return providers


def _model_slot_values(slot: Any) -> tuple[str, str]:
    if isinstance(slot, dict):
        return (
            str(slot.get("provider_id") or "").strip(),
            str(slot.get("model") or "").strip(),
        )
    return (
        str(getattr(slot, "provider_id", "") or "").strip(),
        str(getattr(slot, "model", "") or "").strip(),
    )


def _select_review_chat_model(
    manager: Any,
    current_slot: Any,
    required_modalities: set[str],
) -> dict[str, str] | None:
    """Select a configured chat model with confirmed media capabilities."""
    providers = _review_provider_inventory(manager)
    provider_by_id = {
        str(getattr(provider, "id", "") or ""): provider
        for provider in providers
    }
    ordered_slots: list[Any] = []

    def append_slot_and_provider_models(slot: Any) -> None:
        provider_id, model_id = _model_slot_values(slot)
        if not provider_id:
            return
        if model_id:
            ordered_slots.append({"provider_id": provider_id, "model": model_id})
        provider = provider_by_id.get(provider_id)
        if provider is None:
            return
        ordered_slots.extend(
            {"provider_id": provider_id, "model": model.id}
            for model in (
                list(getattr(provider, "models", ()) or ())
                + list(getattr(provider, "extra_models", ()) or ())
            )
        )

    append_slot_and_provider_models(current_slot)
    get_active_model = getattr(manager, "get_active_model", None)
    if callable(get_active_model):
        append_slot_and_provider_models(get_active_model())
    ordered_slots.extend(
        {"provider_id": provider_id, "model": model.id}
        for provider_id, provider in provider_by_id.items()
        for model in (
            list(getattr(provider, "models", ()) or ())
            + list(getattr(provider, "extra_models", ()) or ())
        )
    )

    seen: set[tuple[str, str]] = set()
    for slot in ordered_slots:
        provider_id, model_id = _model_slot_values(slot)
        key = (provider_id, model_id)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        provider = provider_by_id.get(provider_id)
        if provider is None or not _review_provider_is_configured(provider):
            continue
        model = next(
            (
                item
                for item in (
                    list(getattr(provider, "models", ()) or ())
                    + list(getattr(provider, "extra_models", ()) or ())
                )
                if str(getattr(item, "id", "") or "") == model_id
            ),
            None,
        )
        if model is None or getattr(model, "model_type", "llm") != "llm":
            continue
        if list(getattr(model, "aigc_capabilities", ()) or ()):
            continue
        if "image" in required_modalities and getattr(
            model,
            "supports_image",
            None,
        ) is not True:
            continue
        if "video" in required_modalities and getattr(
            model,
            "supports_video",
            None,
        ) is not True:
            continue
        return {"provider_id": provider_id, "model": model_id}
    return None


def _replace_review_message_text(message: Any, text: str) -> None:
    if hasattr(message, "content"):
        message.content = text

router = APIRouter(
    prefix="/super-expert-platform",
    tags=["super-expert-platform"],
)
frontend_read_router = APIRouter(
    prefix="/super-expert-platform",
    tags=["super-expert-platform"],
)


from ..super_experts.service import (
    SuperExpertPlatformService, SuperExpertPlatformError, PlatformCommandRequest,
    AigcCreateOperation, AigcWorkflowCreateArguments, _operation_catalog_path,
)
from ..super_experts.aigc_adapter import (
    load_workflow_capability_catalog as _load_workflow_capability_catalog,
)
from ..super_experts.composition import (
    get_super_expert_platform_service, _resolve_runtime_session_id,
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


def _workflow_review_binding(task: Any, logical_node_id: str | None = None) -> tuple[set[str], set[str]]:
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

    collect(logical_node_id or blueprint.output_node_id, set())
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
        asset_kinds = {"image", "video", "audio", "text"}
    else:
        asset_kinds = output_types & {"image", "video", "audio", "text"}
    return physical_ids, asset_kinds


async def _resolve_review_bundle(request, task, entries, *, service):
    """Resolve the declared, ordered submission; ownership stays platform-bound."""
    expected = task.workflow.blueprint.review_node_ids if task.workflow else ()
    physical = [task.binding.node_bindings[node] for node in expected]
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("node_id"), str)
        or not isinstance(entry.get("asset_id"), str) or not entry["asset_id"]
        for entry in entries
    ):
        raise HTTPException(status_code=400, detail="Review submission is invalid.")
    groups = []
    for entry in entries:
        if not groups or groups[-1] != entry["node_id"]:
            groups.append(entry["node_id"])
    if not expected or groups != physical:
        raise HTTPException(status_code=400, detail="Review submission does not match declared nodes.")
    blocks = []
    by_id = {node.node_id: node for node in task.workflow.blueprint.nodes}
    logical_by_physical = dict(zip(physical, expected))
    for entry in entries:
        logical = logical_by_physical[entry["node_id"]]
        node = by_id[logical]
        nodes, kinds = _workflow_review_binding(task, logical)
        block = await resolve_owned_asset_for_agent_review(
            request, str(entry.get("asset_id") or ""), canvas_id=task.binding.canvas_id,
            node_ids=nodes, asset_kinds=kinds, service=service,
        )
        prompt = str((node.inputs or {}).get("prompt") or "").strip()
        requirement = f"；制作要求：{prompt}" if prompt else ""
        blocks.append({
            "type": "text",
            "text": (
                f"提交节点：{node.title}；node_id={entry['node_id']}；"
                f"asset_id={entry['asset_id']}{requirement}"
            ),
        })
        blocks.append(block)
    return blocks


def _workflow_review_node_ids(task: Any) -> set[str]:
    """Compatibility helper used by tests and review dispatch diagnostics."""
    return _workflow_review_binding(task)[0]


@frontend_read_router.get("/conversation-route")
def get_conversation_route(conversation_id: str, request: Request) -> dict[str, str]:
    """Resolve a user's deep link before any agent-scoped chat request."""
    row = ensure_chat_access(request, conversation_id)
    agent_id = str((row or {}).get("agent_id") or "").strip()
    if not agent_id:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"conversation_id": conversation_id, "agent_id": agent_id,
            "chat_id": str(row.get("id") or conversation_id)}


@frontend_read_router.get("/cards")
@router.get("/cards")
def list_super_expert_cards(conversation_id: str, request: Request) -> dict[str, Any]:
    """Restore cards from persisted tasks, independently of the SSE buffer."""
    row = ensure_chat_access(request, conversation_id, allow_admin=True)
    aliases = {conversation_id}
    if isinstance(row, dict):
        aliases.update(str(row[key]) for key in ("id", "session_id") if row.get(key))
    service = get_super_expert_platform_service()
    tenant_id = str(getattr(request.state, "tenant_id", "local") or "local")
    from urllib.parse import quote

    cards = []
    for task in service.task_repository.list_for_conversations(aliases):
        grant = service.grant_repository.get(task.binding.installation_id)
        if grant is None or grant.tenant_id != tenant_id:
            continue
        title = (task.workflow.blueprint.title if task.workflow is not None
                 else task.operation_arguments.get("title")) or "AIGC 素材制作任务"
        cards.append({
            "material_task_id": task.binding.material_task_id,
            "title": title,
            "instruction": "打开已绑定画布，按向导完成当前制作步骤。",
            "status": task.status.value,
            "binding": task.binding.model_dump(mode="json"),
            "href": "/aigc-studio?task=" + quote(task.binding.material_task_id, safe=""),
        })
    return {"cards": cards}


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


@frontend_read_router.post("/commands/{capability:path}")
async def execute_frontend_super_expert_command(
    capability: str,
    command: PlatformCommandRequest,
    request: Request,
) -> dict[str, Any]:
    # The shipped card sends the original seven-field binding. Only enrich
    # this exact shape for resume, after ownership and every supplied field
    # match. Canonical agent commands retain their full-binding requirement.
    binding = command.arguments.get("binding")
    legacy_keys = {"installation_id", "conversation_id", "agent_task_id",
                   "content_revision", "material_task_id", "canvas_id", "node_id"}
    if capability == "aigc.task.resume" and isinstance(binding, dict) and set(binding) == legacy_keys:
        ensure_chat_access(request, str(binding.get("conversation_id") or ""), allow_admin=True)
        current = get_super_expert_platform_service().get_task(str(binding.get("material_task_id") or ""))
        expected = current.binding.model_dump(mode="json") if current is not None else {}
        if current is None or any(expected.get(key) != value for key, value in binding.items()):
            raise HTTPException(status_code=400, detail="card task binding mismatch")
        command = command.model_copy(update={
            "arguments": {**command.arguments, "binding": expected},
        })
    return await execute_super_expert_command(capability, command, request)


@router.post("/commands/{capability:path}")
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
                if current_task.workflow and current_task.workflow.blueprint.review_node_ids:
                    entries = command.arguments.get("review_assets") or []
                    if (not isinstance(entries, list) or not entries or not isinstance(entries[0], dict)
                            or entries[0].get("asset_id") != asset_id):
                        raise HTTPException(status_code=400, detail="Review submission is missing.")
                    await _resolve_review_bundle(request, current_task, entries, service=service)
                    return
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
                            request_key=(
                                f"{command.idempotency_key}:agent-review:"
                                f"{uuid.uuid4().hex}"
                            ),
                        )
                    if review.get("status") == "completed":
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
        review_assets = getattr(current_task, "review_assets", ())
        if review_assets:
            media_blocks = await _resolve_review_bundle(
                request, current_task,
                [entry.model_dump(mode="json") for entry in review_assets], service=service,
            )
        else:
            media_blocks = [await resolve_owned_asset_for_agent_review(
                request, asset_id, canvas_id=binding.canvas_id, node_ids=node_ids,
                asset_kinds=asset_kinds, service=service,
            )]
        media_block = media_blocks[1] if review_assets else media_blocks[0]
        manager = request.app.state.multi_agent_manager
        workspace = await manager.get_agent(grant.agent_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise SuperExpertPlatformError("agent review dispatch is unavailable") from exc

    user_id = str(getattr(request.state, "user_id", "platform-user") or "platform-user")
    # Review continues the bound conversation. Resolve that chat first so its
    # selected model remains the preferred candidate for the review turn.
    resolved_chat_id = binding.conversation_id
    chat = await workspace.chat_manager.get_chat(binding.conversation_id)
    if chat is None:
        chat_id = await workspace.chat_manager.get_chat_id_by_session(
            binding.conversation_id, "console", user_id=user_id,
        )
        if chat_id:
            resolved_chat_id = chat_id
            chat = await workspace.chat_manager.get_chat(chat_id)
    chat_model = (
        chat.meta.get("active_model")
        if chat is not None and str(chat.user_id) == user_id and isinstance(chat.meta, dict)
        else None
    )
    required_modalities = {
        str(block.get("type") or "")
        for block in media_blocks
        if isinstance(block, dict) and block.get("type") in {"image", "video"}
    }
    provider_manager = getattr(request.app.state, "provider_manager", None)
    review_model = chat_model
    if provider_manager is not None and required_modalities:
        review_model = _select_review_chat_model(
            provider_manager,
            chat_model,
            required_modalities,
        )
        if review_model is None:
            names = "、".join(
                "图片" if item == "image" else "视频"
                for item in sorted(required_modalities)
            )
            return {
                "status": "model_required",
                "reply": f"素材已提交，但当前没有已配置且支持{names}识别的模型，暂未完成审核。",
                "required_modalities": sorted(required_modalities),
            }
    turn_request = SimpleNamespace(
        # Continue the exact bound chat on its original channel. Supplying the
        # conversation id with a synthetic platform channel used to create a
        # second chat whose short history then shadowed the original one.
        session_id=str(getattr(chat, "id", None) or resolved_chat_id),
        user_id=user_id,
        channel=str(getattr(chat, "channel", None) or "console"),
        tenant_id=grant.tenant_id,
        channel_meta={},
        request_context={"platform_event": "aigc.asset.submitted"},
        root_session_id=str(getattr(chat, "id", None) or resolved_chat_id),
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
                        f"任务ID：{binding.material_task_id}。"
                        "请在当前审核阶段读取附件并完成审核，并在本轮调用 aigc_task_review。"
                        "只有该工具成功返回且任务状态已经变为 ACCEPTED 或 REVISION_REQUIRED，"
                        "才可以向客户表示审核已经完成；只输出一个当前结论和一个下一步动作。"
                    ),
                },
                *media_blocks,
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
    previous_model = get_current_chat_model()
    set_current_chat_model(review_model)
    from ..workspace.media_review_context import bind_review_input
    review_status = "completed"
    try:
        with prepared.activate(), bind_review_input(
            user_id=user_id, binding=binding, asset_id=asset_id, media_block=media_block,
            review_assets=[entry.model_dump(mode="json") for entry in review_assets],
            media_blocks=media_blocks,
        ):
            async for message, is_last in workspace.runner.query_handler(
                messages,
                turn_request,
            ):
                if is_last:
                    task_getter = getattr(service, "get_task", None)
                    reviewed_task = (
                        task_getter(binding.material_task_id)
                        if callable(task_getter)
                        else None
                    )
                    if callable(task_getter) and (
                        reviewed_task is None
                        or reviewed_task.status
                        not in {
                            AigcTaskStatus.ACCEPTED,
                            AigcTaskStatus.REVISION_REQUIRED,
                        }
                    ):
                        review_status = "review_incomplete"
                        _replace_review_message_text(
                            message,
                            "素材已收到，但审核结果尚未成功写入任务，请重新发起审核。",
                        )
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
    finally:
        set_current_chat_model(previous_model)
    if final_message is None:
        prepared.finalize("failed", error_code="MISSING_COMPLETION")
        raise SuperExpertPlatformError("agent review did not complete")
    reply = final_message.get_text_content()
    if not isinstance(reply, str) or not reply.strip():
        prepared.finalize("failed", error_code="INVALID_COMPLETION")
        raise SuperExpertPlatformError("agent review result is invalid")
    prepared.finalize_completed()
    return {"status": review_status, "reply": reply}
