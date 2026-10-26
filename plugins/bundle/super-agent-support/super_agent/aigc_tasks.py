"""Atomic state machine for strongly bound AIGC material tasks."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import (
    AigcMaterialTask,
    AigcReviewAsset,
    AigcTaskBinding,
    AigcTaskEvent,
    AigcTaskStatus,
    AigcWorkflowDefinition,
    AigcWorkflowGuideEvent,
)


class AigcTaskError(ValueError):
    """A public-safe AIGC task state failure."""


class AigcTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal[
        "create",
        "start",
        "pause",
        "resume",
        "submit",
        "review",
        "request_revision",
        "accept",
        "cancel",
        "invalidate",
        "guide_update",
    ]
    event_id: str = Field(min_length=1)
    binding: AigcTaskBinding
    asset_id: str | None = Field(default=None, min_length=1)
    review_assets: tuple[AigcReviewAsset, ...] = ()
    operation_id: str | None = Field(default=None, min_length=1)
    operation_version: str | None = Field(default=None, min_length=1)
    operation_arguments: dict[str, Any] = Field(default_factory=dict)
    workflow: AigcWorkflowDefinition | None = None
    guide_event: AigcWorkflowGuideEvent | None = None


class _IdempotencyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_digest: str
    result: AigcMaterialTask


class _TaskDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    tasks: dict[str, AigcMaterialTask] = Field(default_factory=dict)
    idempotency: dict[str, _IdempotencyRecord] = Field(default_factory=dict)
    event_ids: set[str] = Field(default_factory=set)
    dismissed_task_ids: set[str] = Field(default_factory=set)


_TRANSITIONS = {
    (AigcTaskStatus.WAITING_TO_START, "start"): AigcTaskStatus.IN_PROGRESS,
    (AigcTaskStatus.IN_PROGRESS, "pause"): AigcTaskStatus.PAUSED,
    (AigcTaskStatus.PAUSED, "resume"): AigcTaskStatus.IN_PROGRESS,
    (AigcTaskStatus.IN_PROGRESS, "submit"): AigcTaskStatus.SUBMITTED,
    (AigcTaskStatus.SUBMITTED, "review"): AigcTaskStatus.REVIEWING,
    (
        AigcTaskStatus.REVIEWING,
        "request_revision",
    ): AigcTaskStatus.REVISION_REQUIRED,
    (AigcTaskStatus.REVISION_REQUIRED, "resume"): AigcTaskStatus.IN_PROGRESS,
    (AigcTaskStatus.REVIEWING, "accept"): AigcTaskStatus.ACCEPTED,
}

_TERMINAL = {
    AigcTaskStatus.ACCEPTED,
    AigcTaskStatus.CANCELLED,
    AigcTaskStatus.INVALIDATED,
}


def _command_digest(command: AigcTaskCommand) -> str:
    payload = command.model_dump(mode="json")
    if not payload.get("review_assets"):
        payload.pop("review_assets", None)
    if payload.get("workflow") and not payload["workflow"]["blueprint"].get(
        "review_node_ids",
    ):
        payload["workflow"]["blueprint"].pop("review_node_ids", None)
    # These timestamps are assigned by the trusted domain models when callers
    # omit them. They describe when DClaw accepted the object, not command
    # identity, so a retried semantic command must not receive a new digest.
    workflow = payload.get("workflow")
    if isinstance(workflow, dict):
        workflow.pop("created_at", None)
    guide_event = payload.get("guide_event")
    if isinstance(guide_event, dict):
        guide_event.pop("occurred_at", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AigcTaskRepository:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.path = self.root / "aigc_material_tasks.json"
        self._lock = threading.RLock()

    def apply(
        self,
        command: AigcTaskCommand,
        idempotency_key: str,
    ) -> AigcMaterialTask:
        if not idempotency_key:
            raise AigcTaskError("idempotency key is required")
        digest = _command_digest(command)
        with self._lock:
            document = self._read()
            replay = document.idempotency.get(idempotency_key)
            if replay is not None:
                if replay.command_digest != digest:
                    raise AigcTaskError("idempotency key was reused")
                return replay.result
            if command.event_id in document.event_ids:
                raise AigcTaskError("event id was already used")
            task = self._apply_new_command(document, command)
            document.tasks[command.binding.material_task_id] = task
            document.event_ids.add(command.event_id)
            document.idempotency[idempotency_key] = _IdempotencyRecord(
                command_digest=digest,
                result=task,
            )
            self._write(document)
            return task

    def get(self, material_task_id: str) -> AigcMaterialTask | None:
        with self._lock:
            return self._read().tasks.get(material_task_id)

    def list_for_conversations(
        self,
        conversation_ids: set[str],
    ) -> tuple[AigcMaterialTask, ...]:
        """Read task snapshots for an already authorized chat and its aliases."""
        with self._lock:
            document = self._read()
            return tuple(
                task
                for task_id, task in document.tasks.items()
                if task.binding.conversation_id in conversation_ids
                and task_id not in document.dismissed_task_ids
            )

    def dismiss(self, material_task_id: str) -> bool:
        """Hide a task card without deleting its workflow, canvas, or audit history."""
        with self._lock:
            document = self._read()
            if material_task_id not in document.tasks:
                return False
            if material_task_id not in document.dismissed_task_ids:
                document.dismissed_task_ids.add(material_task_id)
                self._write(document)
            return True

    def find_workflow_task_for_node(
        self,
        *,
        canvas_id: str,
        node_id: str,
    ) -> AigcMaterialTask | None:
        """Find the immutable workflow task owning one physical canvas node."""
        with self._lock:
            for task in self._read().tasks.values():
                if (
                    task.workflow is not None
                    and task.binding.canvas_id == canvas_id
                    and node_id in task.binding.node_bindings.values()
                ):
                    return task
        return None

    def find_tasks_for_node(
        self,
        *,
        canvas_id: str,
        node_id: str,
    ) -> tuple[AigcMaterialTask, ...]:
        """Return every matching immutable binding; callers must reject ambiguity."""
        with self._lock:
            return tuple(
                task
                for task in self._read().tasks.values()
                if task.binding.canvas_id == canvas_id
                and (
                    task.binding.node_id == node_id
                    or node_id in task.binding.node_bindings.values()
                )
            )

    def _apply_new_command(
        self,
        document: _TaskDocument,
        command: AigcTaskCommand,
    ) -> AigcMaterialTask:
        material_task_id = command.binding.material_task_id
        current = document.tasks.get(material_task_id)
        if command.action == "create":
            if current is not None:
                raise AigcTaskError("task already exists")
            if command.asset_id is not None:
                raise AigcTaskError("asset cannot be bound before submission")
            if command.guide_event is not None:
                raise AigcTaskError(
                    "guide event is not valid for task creation",
                )
            self._validate_workflow_creation(command)
            event = AigcTaskEvent(
                event_id=command.event_id,
                action=command.action,
                from_status=None,
                to_status=AigcTaskStatus.WAITING_TO_START,
            )
            return AigcMaterialTask(
                binding=command.binding,
                status=AigcTaskStatus.WAITING_TO_START,
                version=1,
                events=(event,),
                operation_id=command.operation_id,
                operation_version=command.operation_version,
                operation_arguments=command.operation_arguments,
                workflow=command.workflow,
            )
        if current is None:
            raise AigcTaskError("task transition requires an existing task")
        if current.binding != command.binding:
            raise AigcTaskError("task binding mismatch")
        if current.status in _TERMINAL:
            raise AigcTaskError("illegal task transition from terminal state")

        if command.action == "guide_update":
            return self._apply_guide_update(current, command)
        if command.workflow is not None or command.guide_event is not None:
            raise AigcTaskError(
                "workflow data is not valid for this transition",
            )

        if command.action in {"cancel", "invalidate"}:
            target = (
                AigcTaskStatus.CANCELLED
                if command.action == "cancel"
                else AigcTaskStatus.INVALIDATED
            )
        else:
            target = _TRANSITIONS.get((current.status, command.action))
            if target is None:
                raise AigcTaskError("illegal task transition")

        review_assets = current.review_assets
        asset_id = current.asset_id
        if (
            command.action == "resume"
            and current.status == AigcTaskStatus.REVISION_REQUIRED
        ):
            # A revision cycle deliberately opens a fresh asset slot while the
            # immutable event history retains the previously reviewed asset.
            asset_id = None
            review_assets = ()
        elif command.action == "submit":
            if not command.asset_id:
                raise AigcTaskError("submitted task requires an asset")
            if (
                current.status != AigcTaskStatus.REVISION_REQUIRED
                and asset_id is not None
                and asset_id != command.asset_id
            ):
                raise AigcTaskError("asset binding mismatch")
            asset_id = command.asset_id
            review_assets = command.review_assets
        elif command.asset_id is not None:
            raise AigcTaskError("asset is not valid for this transition")
        event = AigcTaskEvent(
            event_id=command.event_id,
            action=command.action,
            from_status=current.status,
            to_status=target,
        )
        return current.model_copy(
            update={
                "status": target,
                "asset_id": asset_id,
                "review_assets": review_assets,
                "version": current.version + 1,
                "events": (*current.events, event),
                "updated_at": event.occurred_at,
            },
        )

    @staticmethod
    def _validate_workflow_creation(command: AigcTaskCommand) -> None:
        binding = command.binding
        workflow = command.workflow
        if workflow is None:
            if (
                binding.workflow_id is not None
                or binding.execution_mode != "LEGACY"
                or binding.node_bindings
                or binding.output_node_id is not None
                or binding.workflow_revision is not None
                or binding.guide_revision is not None
            ):
                raise AigcTaskError("workflow definition is required")
            return
        if binding.workflow_id != workflow.workflow_id:
            raise AigcTaskError("workflow binding mismatch")
        if binding.execution_mode != workflow.execution_mode:
            raise AigcTaskError("workflow execution mode mismatch")
        if binding.workflow_revision != workflow.workflow_revision:
            raise AigcTaskError("workflow revision mismatch")
        if binding.guide_revision != workflow.guide_revision:
            raise AigcTaskError("guide revision mismatch")
        if (
            not binding.output_node_id
            or binding.node_id != binding.output_node_id
        ):
            raise AigcTaskError("output binding mismatch")
        if workflow.execution_mode == "PREBUILT_WORKFLOW":
            logical_ids = {node.node_id for node in workflow.blueprint.nodes}
            if set(binding.node_bindings) != logical_ids:
                raise AigcTaskError("workflow node binding mismatch")
            if workflow.blueprint.output_node_id not in binding.node_bindings:
                raise AigcTaskError("output binding mismatch")
            if (
                binding.node_bindings[workflow.blueprint.output_node_id]
                != binding.output_node_id
            ):
                raise AigcTaskError("output binding mismatch")
            for step in workflow.guide_steps:
                physical_id = binding.node_bindings.get(step.logical_node_id)
                if physical_id != step.node_id:
                    raise AigcTaskError("workflow guide binding mismatch")

    @staticmethod
    def _apply_guide_update(
        current: AigcMaterialTask,
        command: AigcTaskCommand,
    ) -> AigcMaterialTask:
        workflow = current.workflow
        guide_event = command.guide_event
        if workflow is None or guide_event is None:
            raise AigcTaskError("workflow guide update requires a workflow")
        if command.workflow is not None:
            raise AigcTaskError(
                "workflow cannot be replaced by a guide update",
            )
        if guide_event.event_id != command.event_id:
            raise AigcTaskError("guide event id mismatch")
        if guide_event.workflow_id != workflow.workflow_id:
            raise AigcTaskError("workflow binding mismatch")
        if guide_event.guide_revision != workflow.guide_revision:
            raise AigcTaskError("guide revision mismatch")
        step = next(
            (
                candidate
                for candidate in workflow.guide_steps
                if candidate.step_id == guide_event.step_id
            ),
            None,
        )
        if step is None:
            raise AigcTaskError("workflow guide step not found")
        if not step.optional:
            raise AigcTaskError("only optional guide steps can be skipped")
        if (
            step.logical_node_id != guide_event.logical_node_id
            or step.node_id != guide_event.node_id
            or current.binding.node_bindings.get(guide_event.logical_node_id)
            != guide_event.node_id
        ):
            raise AigcTaskError("workflow guide binding mismatch")
        if any(
            existing.step_id == guide_event.step_id
            and existing.action == guide_event.action
            for existing in current.guide_events
        ):
            raise AigcTaskError("workflow guide step was already skipped")
        event = AigcTaskEvent(
            event_id=command.event_id,
            action=command.action,
            from_status=current.status,
            to_status=current.status,
            occurred_at=guide_event.occurred_at,
        )
        return current.model_copy(
            update={
                "version": current.version + 1,
                "events": (*current.events, event),
                "guide_events": (*current.guide_events, guide_event),
                "updated_at": event.occurred_at,
            },
        )

    def _read(self) -> _TaskDocument:
        if not self.path.exists():
            return _TaskDocument()
        try:
            return _TaskDocument.model_validate_json(
                self.path.read_text(encoding="utf-8"),
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise AigcTaskError("AIGC task repository is invalid") from exc

    def _write(self, document: _TaskDocument) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                document.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
