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


class AigcWorkflowCreateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: AigcTaskScope
    event_id: str = Field(min_length=1)
    workflow: WorkflowBlueprint


_EVENT_TYPES = {
    "card.create": "card.created",
    "card.update": "card.updated",
    "aigc.task.create": "aigc.task.created",
    "aigc.task.create/2": "aigc.task.created",
    "aigc.workflow.create/1": "aigc.task.created",
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

    def workflow_node_execution_binding(
        self,
        *,
        canvas_id: str,
        node_id: str,
    ) -> tuple[str, str, str] | None:
        task = self.task_repository.find_workflow_task_for_node(
            canvas_id=canvas_id,
            node_id=node_id,
        )
        if task is None or task.workflow is None:
            return None
        logical_id = next(
            (
                candidate
                for candidate, physical in task.binding.node_bindings.items()
                if physical == node_id
            ),
            None,
        )
        semantic_node = next(
            (
                candidate
                for candidate in task.workflow.blueprint.nodes
                if candidate.node_id == logical_id
            ),
            None,
        )
        if semantic_node is None:
            return ("", "", "")
        return (
            semantic_node.provider_id or "",
            semantic_node.model_id or "",
            semantic_node.capability or "",
        )

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
        asset_validator: Callable[[AigcTaskBinding, str, Any], Awaitable[None]]
        | None = None,
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
            elif capability == "aigc.workflow.create/1":
                result, binding = await self._create_bound_aigc_workflow(
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
                if capability == "aigc.asset.submit" and asset_validator is not None:
                    asset_id = str(arguments.get("asset_id") or "")
                    current_task = self.task_repository.get(binding.material_task_id)
                    if not asset_id or current_task is None:
                        raise SuperExpertPlatformError("submitted asset is unavailable")
                    if current_task.status == AigcTaskStatus.IN_PROGRESS:
                        await asset_validator(binding, asset_id, current_task)
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
                    include=set(AigcTaskScope.model_fields),
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

    async def _create_bound_aigc_workflow(
        self,
        *,
        installation_id: str,
        user_id: str | None,
        event_id: str,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[dict[str, Any], AigcTaskBinding]:
        if not isinstance(user_id, str) or not user_id.strip():
            raise SuperExpertPlatformError("TASK_OWNER_UNAVAILABLE")
        try:
            request = AigcWorkflowCreateArguments.model_validate(arguments)
        except Exception as exc:
            raise SuperExpertPlatformError("WORKFLOW_SCHEMA_INVALID") from exc
        if request.event_id != event_id:
            raise SuperExpertPlatformError("WORKFLOW_SCHEMA_INVALID")
        if request.scope.installation_id != installation_id:
            raise SuperExpertPlatformError("BINDING_MISMATCH")

        current = self.task_repository.get(request.scope.material_task_id)
        if current is not None:
            current_scope = AigcTaskScope.model_validate(
                current.binding.model_dump(
                    include=set(AigcTaskScope.model_fields),
                    mode="json",
                )
            )
            if current_scope != request.scope:
                raise SuperExpertPlatformError("BINDING_MISMATCH")
            if current.workflow is None or current.workflow.blueprint != request.workflow:
                raise SuperExpertPlatformError("IDEMPOTENCY_CONFLICT")
            task = self.task_repository.apply(
                AigcTaskCommand(
                    action="create",
                    event_id=event_id,
                    binding=current.binding,
                    workflow=current.workflow,
                ),
                idempotency_key=idempotency_key,
            )
            return {
                "task": task,
                "payload": {
                    "workflow_id": current.workflow.workflow_id,
                    "workflow_binding": current.binding.model_dump(mode="json"),
                },
            }, current.binding

        catalog = await _load_workflow_capability_catalog()
        model_capabilities: dict[tuple[str, str], set[str]] = {}
        for model in catalog.available_models:
            model_capabilities.setdefault(
                (model.provider_id, model.model_id),
                set(),
            ).add(model.capability)
        available_models = tuple(
            AvailableWorkflowModel(
                provider_id=provider_id,
                model_id=model_id,
                capabilities=frozenset(capabilities),
            )
            for (provider_id, model_id), capabilities in model_capabilities.items()
        )

        from .aigc_studio import (
            discard_super_expert_aigc_workspace,
            provision_blank_super_expert_aigc_workspace,
            provision_super_expert_aigc_workflow,
            resolve_owned_asset_for_workflow,
        )

        id_factory = lambda prefix: f"{prefix}-{uuid.uuid4()}"
        provisioned_canvas_id: str | None = None
        try:
            compiled = compile_workflow(
                request.workflow,
                available_models=available_models,
                id_factory=id_factory,
                asset_resolver=lambda asset_id: resolve_owned_asset_for_workflow(
                    user_id,
                    asset_id,
                ),
            )
        except WorkflowCompileError as exc:
            if not (
                exc.manual_fallback_allowed
                and request.workflow.fallback_policy
                == "MANUAL_BUILD_IF_UNSUPPORTED"
            ):
                raise SuperExpertPlatformError(exc.code) from exc
            manual = plan_manual_workflow(
                request.workflow,
                available_models=available_models,
                id_factory=id_factory,
                asset_resolver=lambda asset_id: resolve_owned_asset_for_workflow(
                    user_id,
                    asset_id,
                ),
            )
            workflow_id = manual.workflow_id
            canvas = provision_blank_super_expert_aigc_workspace(
                owner_user_id=user_id,
                material_task_id=request.scope.material_task_id,
                workflow_id=workflow_id,
                title=request.workflow.title,
            )
            provisioned_canvas_id = canvas.id
            binding = AigcTaskBinding(
                **request.scope.model_dump(mode="json"),
                canvas_id=canvas.id,
                node_id=manual.output_node_id,
                workflow_id=workflow_id,
                execution_mode="MANUAL_BUILD",
                node_bindings=manual.bindings,
                output_node_id=manual.output_node_id,
                workflow_revision=1,
                guide_revision=1,
            )
            workflow = AigcWorkflowDefinition(
                workflow_id=workflow_id,
                schema_version=1,
                execution_mode="MANUAL_BUILD",
                workflow_revision=1,
                guide_revision=1,
                blueprint=request.workflow,
                guide_steps=manual.guide_steps,
                manual_reason=exc.code,
            )
        else:
            canvas = provision_super_expert_aigc_workflow(
                owner_user_id=user_id,
                material_task_id=request.scope.material_task_id,
                compiled=compiled,
            )
            provisioned_canvas_id = canvas.id
            binding = AigcTaskBinding(
                **request.scope.model_dump(mode="json"),
                canvas_id=canvas.id,
                node_id=compiled.output_node_id,
                workflow_id=compiled.workflow_id,
                execution_mode="PREBUILT_WORKFLOW",
                node_bindings=compiled.bindings,
                output_node_id=compiled.output_node_id,
                workflow_revision=1,
                guide_revision=1,
            )
            workflow = AigcWorkflowDefinition(
                workflow_id=compiled.workflow_id,
                schema_version=1,
                execution_mode="PREBUILT_WORKFLOW",
                workflow_revision=1,
                guide_revision=1,
                blueprint=request.workflow,
                guide_steps=compiled.guide_steps,
            )
        try:
            task = self.task_repository.apply(
                AigcTaskCommand(
                    action="create",
                    event_id=event_id,
                    binding=binding,
                    workflow=workflow,
                ),
                idempotency_key=idempotency_key,
            )
        except Exception:
            if provisioned_canvas_id is not None:
                discard_super_expert_aigc_workspace(
                    owner_user_id=user_id,
                    material_task_id=request.scope.material_task_id,
                    canvas_id=provisioned_canvas_id,
                )
            raise
        return {
            "task": task,
            "payload": {
                "workflow_id": workflow.workflow_id,
                "workflow_binding": binding.model_dump(mode="json"),
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
            if current.workflow is None:
                return {
                    "task": current,
                    "payload": dict(arguments.get("guide") or {}),
                }
            guide = arguments.get("guide")
            if not isinstance(guide, dict):
                raise SuperExpertPlatformError("workflow guide event is invalid")
            try:
                guide_event = AigcWorkflowGuideEvent.model_validate(
                    {"event_id": event_id, **guide}
                )
            except Exception as exc:
                raise SuperExpertPlatformError(
                    "workflow guide event is invalid"
                ) from exc
            task = self.task_repository.apply(
                AigcTaskCommand(
                    action="guide_update",
                    event_id=event_id,
                    binding=binding,
                    guide_event=guide_event,
                ),
                idempotency_key=idempotency_key,
            )
            return {"task": task, "payload": guide_event.model_dump(mode="json")}
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


async def _load_workflow_capability_catalog():
    from ...providers.provider_manager import ProviderManager
    from ..aigc.capability_service import build_workflow_capability_catalog

    return await build_workflow_capability_catalog(ProviderManager.get_instance())


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
    from .aigc_studio import load_super_expert_aigc_workflow_context

    canvas, jobs = load_super_expert_aigc_workflow_context(
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
            from .aigc_studio import resolve_owned_asset_for_agent_review

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
        from .aigc_studio import resolve_owned_asset_for_agent_review

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
