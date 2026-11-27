# -*- coding: utf-8 -*-
"""Super-expert application service; independent of HTTP route modules."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable
import uuid

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, ConfigDict, Field
from qwenpaw.aigc.operation_contract import load_operation_catalog
from qwenpaw.aigc.workflow_compiler import (
    AvailableWorkflowModel,
    WorkflowCompileError,
    compile_workflow,
    plan_manual_workflow,
)
from qwenpaw.aigc.workflow_contract import WorkflowBlueprint
from qwenpaw.app.aigc.workflow_execution import AigcWorkflowExecutionService
from qwenpaw.app.runtime.event_bus import RuntimeEvent
from .aigc_adapter import AigcServiceAdapter
from .aigc_tasks import AigcTaskCommand, AigcTaskError, AigcTaskRepository
from .events import SuperExpertEventEnvelope, SuperExpertEventRepository
from .interaction_cards import InteractionError, InteractionService
from .interaction_contract import InteractionCreateRequest
from .interaction_events import InteractionEventEnvelope
from .interaction_receipts import card_receipt

if TYPE_CHECKING:
    from .grants import SuperExpertGrantRepository
from .models import (
    AigcTaskBinding,
    AigcTaskScope,
    AigcTaskStatus,
    AigcWorkflowDefinition,
    AigcWorkflowGuideEvent,
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
        event_session_resolver: Callable[[str], str] | None = None,
        workflow_execution_service: AigcWorkflowExecutionService | None = None,
        aigc_adapter: AigcServiceAdapter | None = None,
        interaction_service: InteractionService | None = None,
    ) -> None:
        self.grant_repository = grant_repository
        self.task_repository = task_repository
        self.event_repository = event_repository
        self.event_bus = event_bus
        self.event_session_resolver = event_session_resolver or (
            lambda value: value
        )
        self.workflow_execution_service = workflow_execution_service
        self.aigc = aigc_adapter
        self.interactions = interaction_service
        self._review_locks: dict[str, asyncio.Lock] = {}
        self._interaction_locks: dict[str, asyncio.Lock] = {}

    def get_task(self, material_task_id: str):
        return self.task_repository.get(material_task_id)

    def latest_task_review(
        self,
        material_task_id: str,
    ) -> dict[str, str] | None:
        """Return the latest persisted review attached to a task transition."""
        task = self.task_repository.get(material_task_id)
        if task is None:
            return None
        for transition in reversed(task.events):
            if transition.action not in {"accept", "request_revision"}:
                continue
            event = self.event_repository.get(transition.event_id)
            if event is None or event.event_type != "aigc.review.completed":
                continue
            assessment = event.payload.get("assessment")
            if not isinstance(assessment, str) or not assessment.strip():
                continue
            return {
                "decision": (
                    "ACCEPTED"
                    if transition.action == "accept"
                    else "REVISION_REQUIRED"
                ),
                "assessment": assessment.strip(),
            }
        return None

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

    def interaction_lock(self, interaction_id: str) -> asyncio.Lock:
        return self._interaction_locks.setdefault(
            interaction_id,
            asyncio.Lock(),
        )

    async def execute_interaction(
        self,
        *,
        tenant_id: str,
        installation_id: str,
        conversation_id: str,
        capability: str,
        contract_version: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        invocation_id: str | None = None,
    ) -> dict[str, Any]:
        """Authorize and execute an Agent-originated interaction operation."""
        decision = self.grant_repository.authorize_capability(
            installation_id,
            capability,
            contract_version,
            tenant_id=tenant_id,
        )
        if not decision.allowed:
            raise SuperExpertPlatformError("capability is not authorized")
        if self.interactions is None:
            raise SuperExpertPlatformError(
                "interaction service is unavailable",
            )
        try:
            if capability == "interaction.card.create/1":
                if set(arguments) != {"request"}:
                    raise InteractionError("INVALID_INTERACTION_REQUEST")
                request = InteractionCreateRequest.model_validate(
                    arguments["request"],
                )
                if request.component_type.value == "file_selector":
                    file_decision = self.grant_repository.authorize_capability(
                        installation_id,
                        "interaction.file.select/1",
                        "1",
                        tenant_id=tenant_id,
                    )
                    if not file_decision.allowed:
                        raise SuperExpertPlatformError(
                            "file selection capability is not authorized",
                        )
                card = self.interactions.create(
                    installation_id=installation_id,
                    conversation_id=conversation_id,
                    request=request,
                    idempotency_key=idempotency_key,
                    invocation_id=invocation_id,
                )
                event_type = "interaction.card.created"
            elif capability == "interaction.card.cancel/1":
                if set(arguments) != {"interaction_id"}:
                    raise InteractionError("INVALID_INTERACTION_REQUEST")
                card = self.interactions.cancel(
                    interaction_id=str(arguments["interaction_id"]),
                    installation_id=installation_id,
                    conversation_id=conversation_id,
                    operation_key=idempotency_key,
                )
                event_type = "interaction.card.cancelled"
            else:
                raise SuperExpertPlatformError("capability is not supported")
        except InteractionError:
            raise
        except SuperExpertPlatformError:
            raise
        except Exception as exc:
            raise SuperExpertPlatformError(
                "interaction request is invalid",
            ) from exc
        if not (
            capability == "interaction.card.create/1"
            and card.status.value != "PENDING"
        ):
            await self.publish_interaction_event(card, event_type=event_type)
        result = {"interaction": card.model_dump(mode="json")}
        if capability == "interaction.card.create/1":
            result["receipt"] = card_receipt(card, "created")
        return result

    async def rollback_interaction_create(
        self,
        *,
        installation_id: str,
        conversation_id: str,
        invocation_id: str,
        interaction_id: str,
        operation_key: str,
    ) -> dict[str, Any]:
        """Compensate only a card created by this failed Host invocation."""
        if self.interactions is None:
            raise SuperExpertPlatformError(
                "interaction service is unavailable",
            )
        cancelled, restored, replayed = self.interactions.rollback_create(
            interaction_id=interaction_id,
            installation_id=installation_id,
            conversation_id=conversation_id,
            invocation_id=invocation_id,
            operation_key=operation_key,
        )
        if not replayed:
            await self.publish_interaction_event(
                cancelled, event_type="interaction.card.cancelled",
            )
            if restored is not None:
                await self.publish_interaction_event(
                    restored, event_type="interaction.card.created",
                )
        return {
            "status": "replayed" if replayed else "cancelled",
            "restored_interaction_id": (
                restored.interaction_id if restored is not None else None
            ),
        }

    def read_interaction(
        self,
        *,
        tenant_id: str,
        installation_id: str,
        conversation_id: str,
        contract_version: str,
        arguments: dict[str, Any],
        compatible_installation_ids: frozenset[str] | None = None,
    ) -> dict[str, Any]:
        """Read one persisted card using only Host-supplied scope."""
        decision = self.grant_repository.authorize_capability(
            installation_id,
            "interaction.card.read/1",
            contract_version,
            tenant_id=tenant_id,
        )
        if not decision.allowed:
            raise SuperExpertPlatformError("capability is not authorized")
        interaction_id = arguments.get("interaction_id")
        if (
            set(arguments) != {"interaction_id"}
            or not isinstance(interaction_id, str)
            or re.fullmatch(r"interaction-[a-f0-9]{32}", interaction_id) is None
        ):
            raise InteractionError(
                "INVALID_INTERACTION_REQUEST", field="interaction_id",
                retryable=False,
            )
        if self.interactions is None:
            raise SuperExpertPlatformError("interaction service is unavailable")
        allowed = compatible_installation_ids or frozenset({installation_id})
        if installation_id not in allowed:
            raise SuperExpertPlatformError("current installation is not authorized")
        card = None
        for owner_installation_id in (installation_id, *sorted(allowed - {installation_id})):
            try:
                card = self.interactions.get_owned(
                    interaction_id,
                    installation_id=owner_installation_id,
                    conversation_id=conversation_id,
                )
                break
            except InteractionError as exc:
                if exc.code != "INTERACTION_NOT_FOUND":
                    raise
        if card is None:
            return {"contract": "interaction.card.read/1", "result": "not_found"}
        submitted = card.status.value == "SUBMITTED"
        return {
            "contract": "interaction.card.read/1",
            "result": "found",
            "interaction_id": card.interaction_id,
            "task_key": card.task_key,
            "interaction_revision": card.interaction_revision,
            "component_type": card.component_type.value,
            "status": card.status.value,
            "version": card.version,
            "answer": (
                card.answer.model_dump(mode="json")
                if submitted and card.answer else None
            ),
            "submission_receipt": card_receipt(card, "submitted") if submitted else None,
        }

    async def publish_interaction_event(
        self,
        card: Any,
        *,
        event_type: str,
    ) -> InteractionEventEnvelope:
        transition = card.transitions[-1]
        envelope = InteractionEventEnvelope(
            event_id=transition.event_id,
            installation_id=card.binding.installation_id,
            conversation_id=card.binding.conversation_id,
            interaction_id=card.interaction_id,
            event_type=event_type,
            interaction=card.model_dump(mode="json"),
        )
        await self.event_bus.publish(
            RuntimeEvent(
                id=envelope.event_id,
                type="super_expert_interaction",
                scope="session",
                session_id=self.event_session_resolver(
                    card.binding.conversation_id,
                ),
                job_id=card.interaction_id,
                status=card.status.value,
                payload={"envelope": envelope.model_dump(mode="json")},
            ),
        )
        return envelope

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
        frontend_workflow_resume: bool = False,
        frontend_asset_submit: bool = False,
    ) -> dict[str, Any]:
        if capability == "aigc.review.complete":
            raise SuperExpertPlatformError("AIGC_REVIEW_RETIRED")
        if capability == "aigc.asset.submit" and not frontend_asset_submit:
            raise SuperExpertPlatformError("AIGC_ASSET_SUBMIT_RETIRED")
        decision = self.grant_repository.authorize_capability(
            installation_id,
            capability,
            contract_version,
            tenant_id=tenant_id,
        )
        if not decision.allowed and frontend_workflow_resume and capability == "aigc.task.resume":
            workflow_decision = self.grant_repository.authorize_capability(
                installation_id,
                "aigc.workflow.create/1",
                "1",
                tenant_id=tenant_id,
            )
            task_binding = arguments.get("binding")
            task = (
                self.task_repository.get(str(task_binding.get("material_task_id") or ""))
                if isinstance(task_binding, dict)
                else None
            )
            if (
                workflow_decision.allowed
                and task is not None
                and task.workflow is not None
                and task.binding.model_dump(mode="json") == task_binding
                and task.binding.installation_id == installation_id
            ):
                decision = workflow_decision
        if (
            not decision.allowed
            and frontend_asset_submit
            and capability == "aigc.asset.submit"
        ):
            grant = self.grant_repository.get(installation_id)
            task_binding = arguments.get("binding")
            task = (
                self.task_repository.get(
                    str(task_binding.get("material_task_id") or ""),
                )
                if isinstance(task_binding, dict)
                else None
            )
            if (
                grant is not None
                and grant.tenant_id == tenant_id
                and task is not None
                and task.binding.model_dump(mode="json") == task_binding
                and task.binding.installation_id == installation_id
            ):
                # Completing a customer-owned material task is a platform UI
                # action, not an Agent capability. The exact persisted task
                # binding and tenant installation remain mandatory, and the
                # router still validates canvas/node/asset ownership.
                decision = decision.model_copy(
                    update={"allowed": True, "reason": "frontend_task_owner"},
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
                    binding = AigcTaskBinding.model_validate(
                        arguments.get("binding"),
                    )
                except Exception as exc:
                    raise SuperExpertPlatformError(
                        "command binding is invalid",
                    ) from exc
                if binding.installation_id != installation_id:
                    raise SuperExpertPlatformError("command binding mismatch")
                if (
                    capability == "aigc.asset.submit"
                    and asset_validator is not None
                ):
                    asset_id = str(arguments.get("asset_id") or "")
                    current_task = self.task_repository.get(
                        binding.material_task_id,
                    )
                    if not asset_id or current_task is None:
                        raise SuperExpertPlatformError(
                            "submitted asset is unavailable",
                        )
                    if current_task.status == AigcTaskStatus.IN_PROGRESS:
                        await asset_validator(binding, asset_id, current_task)
                result = self._apply_capability(
                    capability=capability,
                    binding=binding,
                    event_id=event_id,
                    arguments=arguments,
                    idempotency_key=idempotency_key,
                    complete_asset_submit=frontend_asset_submit,
                )
        except (AigcTaskError, ValueError) as exc:
            raise SuperExpertPlatformError(str(exc)) from exc
        event_id = str(result.pop("_event_id", event_id))
        task = result.get("task")
        asset_id = (
            task.asset_id if task is not None else arguments.get("asset_id")
        )
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
            event_type=(
                "aigc.asset.completed"
                if capability == "aigc.asset.submit" and frontend_asset_submit
                else _EVENT_TYPES[capability]
            ),
            payload=event_payload,
        )
        runtime_session_id = self.event_session_resolver(
            binding.conversation_id,
        )
        if self.event_repository.append(envelope):
            await self.event_bus.publish(
                RuntimeEvent(
                    id=event_id,
                    type="super_expert_event",
                    scope="session",
                    session_id=runtime_session_id,
                    job_id=binding.material_task_id,
                    status=(
                        task.status.value
                        if task is not None
                        else result.get("card_status")
                    ),
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
        if self.aigc is None:
            raise SuperExpertPlatformError("AIGC service is unavailable")
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
            operation = AigcCreateOperation.model_validate(
                arguments.get("operation"),
            )
        except Exception as exc:
            raise SuperExpertPlatformError(
                "create v2 arguments are invalid",
            ) from exc
        if scope.installation_id != installation_id:
            raise SuperExpertPlatformError("command binding mismatch")
        catalog_path = _operation_catalog_path()
        try:
            definition = load_operation_catalog(catalog_path).operation(
                operation.operation_id,
            )
        except KeyError as exc:
            raise SuperExpertPlatformError(
                "AIGC operation is unavailable",
            ) from exc
        if definition.version != operation.operation_version:
            raise SuperExpertPlatformError(
                "AIGC operation version is unavailable",
            )
        try:
            Draft202012Validator(definition.arguments_schema).validate(
                operation.arguments,
            )
        except JsonSchemaValidationError as exc:
            raise SuperExpertPlatformError(
                "AIGC operation arguments are invalid",
            ) from exc

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
            provisioned = self.aigc.provision_workspace(
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
                self.aigc.discard_workspace(
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
        if self.aigc is None:
            raise SuperExpertPlatformError("AIGC service is unavailable")
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
                ),
            )
            if current_scope != request.scope:
                raise SuperExpertPlatformError("BINDING_MISMATCH")
            if (
                current.workflow is None
                or current.workflow.blueprint != request.workflow
            ):
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
                    "workflow_binding": current.binding.model_dump(
                        mode="json",
                    ),
                },
            }, current.binding

        recovered = None
        if self.workflow_execution_service is not None:
            recovered = self.workflow_execution_service.resume(
                user_id,
                f"workflow/{installation_id}/{idempotency_key}",
                command=arguments,
                meta={
                    "super_expert_material_task_id": request.scope.material_task_id,
                },
            )
        if recovered is None:
            catalog = await self.aigc.capability_catalog()
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
                for (
                    provider_id,
                    model_id,
                ), capabilities in model_capabilities.items()
            )

        id_factory = lambda prefix: f"{prefix}-{uuid.uuid4()}"
        provisioned_canvas_id: str | None = None
        try:
            if recovered is not None:
                canvas, compiled = recovered
            else:
                compiled = compile_workflow(
                    request.workflow,
                    available_models=available_models,
                    id_factory=id_factory,
                    asset_resolver=lambda asset_id: self.aigc.resolve_owned_asset(
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
                asset_resolver=lambda asset_id: self.aigc.resolve_owned_asset(
                    user_id,
                    asset_id,
                ),
            )
            workflow_id = manual.workflow_id
            canvas = self.aigc.provision_blank_workspace(
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
            if recovered is not None:
                canvas, compiled = recovered
            elif self.workflow_execution_service is None:
                canvas = self.aigc.provision_workflow(
                    owner_user_id=user_id,
                    material_task_id=request.scope.material_task_id,
                    compiled=compiled,
                )
                provisioned_canvas_id = canvas.id
            else:
                canvas, compiled = self.workflow_execution_service.create(
                    user_id,
                    f"workflow/{installation_id}/{idempotency_key}",
                    command=arguments,
                    compiled=compiled,
                    meta={
                        "super_expert_material_task_id": request.scope.material_task_id,
                    },
                )
                # The core operation is durably APPLIED. A failed outer card
                # write retries that same resource rather than deleting it and
                # leaving an applied execution contract pointing at no canvas.
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
                self.aigc.discard_workspace(
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
        complete_asset_submit: bool = False,
    ) -> dict[str, Any]:
        if capability in {"card.create", "card.update"}:
            current = self.task_repository.get(binding.material_task_id)
            if current is not None and current.binding != binding:
                raise SuperExpertPlatformError("card task binding mismatch")
            card = dict(arguments.get("card") or {})
            if current is None:
                if card.get("card_type") == "aigc_material_task":
                    raise SuperExpertPlatformError("card task is unavailable")
                return {
                    "payload": {
                        key: value
                        for key, value in card.items()
                        if key not in {"task_status", "task_version"}
                    },
                }
            # Card commands do not mutate the material task or start a Job.
            # They carry their own trusted status so an earlier SSE is optional.
            reserved = {"task_status", "task_version"}
            card = {
                key: value
                for key, value in card.items()
                if key not in reserved
            }
            prior = self.event_repository.get(event_id)
            if prior is not None:
                prior_card = {
                    key: value
                    for key, value in prior.payload.items()
                    if key not in reserved
                }
                if (
                    prior_card != card
                    or prior.event_type != _EVENT_TYPES[capability]
                ):
                    raise SuperExpertPlatformError(
                        "card event id is already bound",
                    )
                # Preserve the original event snapshot after task progress.
                # append(envelope) still validates every original binding field.
                return {
                    "payload": dict(prior.payload),
                    "card_status": prior.payload.get("task_status"),
                }
            card.update(
                task_status=current.status.value,
                task_version=current.version,
            )
            return {"payload": card, "card_status": current.status.value}
        current = self.task_repository.get(binding.material_task_id)
        if capability == "aigc.task.create":
            action = "create"
        elif capability == "aigc.task.resume":
            action = (
                "start"
                if current
                and current.status == AigcTaskStatus.WAITING_TO_START
                else "resume"
            )
        elif capability == "aigc.task.cancel":
            action = "cancel"
        elif capability == "aigc.asset.submit":
            action = "complete" if complete_asset_submit else "submit"
            if complete_asset_submit and current is not None:
                supplied_asset = str(arguments.get("asset_id") or "")
                if current.binding != binding:
                    raise SuperExpertPlatformError("task binding mismatch")
                completed_by_same_event = any(
                    transition.action == "complete"
                    and transition.event_id == event_id
                    for transition in current.events
                )
                if current.status in {
                    AigcTaskStatus.SUBMITTED,
                    AigcTaskStatus.REVIEWING,
                } or (
                    current.status == AigcTaskStatus.ACCEPTED
                    and not completed_by_same_event
                ):
                    # Older clients used the unsuffixed keys for the review
                    # submission. Preserve that envelope and write/replay the
                    # direct-completion event under its own stable identity.
                    event_id = f"{event_id}:complete"
                    idempotency_key = f"{idempotency_key}:complete"
                if current.status == AigcTaskStatus.ACCEPTED:
                    if supplied_asset != current.asset_id:
                        raise SuperExpertPlatformError("asset binding mismatch")
                    return {
                        "task": current,
                        "payload": {},
                        "_event_id": event_id,
                    }
                if current.status == AigcTaskStatus.SUBMITTED:
                    if supplied_asset != current.asset_id:
                        raise SuperExpertPlatformError("asset binding mismatch")
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
                raise SuperExpertPlatformError(
                    "workflow guide event is invalid",
                )
            try:
                guide_event = AigcWorkflowGuideEvent.model_validate(
                    {"event_id": event_id, **guide},
                )
            except Exception as exc:
                raise SuperExpertPlatformError(
                    "workflow guide event is invalid",
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
            return {
                "task": task,
                "payload": guide_event.model_dump(mode="json"),
            }
        elif capability == "aigc.review.complete":
            if current is None or current.binding != binding:
                raise SuperExpertPlatformError("task binding mismatch")
            supplied_asset = arguments.get("asset_id")
            if (
                supplied_asset is not None
                and supplied_asset != current.asset_id
            ):
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
                review_assets=(
                    ()
                    if complete_asset_submit
                    else arguments.get("review_assets", ())
                    if capability == "aigc.asset.submit"
                    else ()
                ),
                asset_id=(
                    arguments.get("asset_id")
                    if capability == "aigc.asset.submit"
                    else None
                ),
            ),
            idempotency_key=idempotency_key,
        )
        payload = dict(arguments.get("payload") or {})
        if task.review_assets:
            payload["review_assets"] = [
                item.model_dump(mode="json") for item in task.review_assets
            ]
        return {"task": task, "payload": payload, "_event_id": event_id}


def _operation_catalog_path() -> Path:
    import qwenpaw.aigc

    return (
        Path(qwenpaw.aigc.__file__).resolve().parent
        / "contracts"
        / "aigc-operation-contract-v1.json"
    )
