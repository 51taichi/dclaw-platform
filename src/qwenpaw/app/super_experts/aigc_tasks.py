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
    AigcTaskBinding,
    AigcTaskEvent,
    AigcTaskStatus,
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
    ]
    event_id: str = Field(min_length=1)
    binding: AigcTaskBinding
    asset_id: str | None = Field(default=None, min_length=1)
    operation_id: str | None = Field(default=None, min_length=1)
    operation_version: str | None = Field(default=None, min_length=1)
    operation_arguments: dict[str, Any] = Field(default_factory=dict)


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
    encoded = json.dumps(
        command.model_dump(mode="json"),
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
            )
        if current is None:
            raise AigcTaskError("task transition requires an existing task")
        if current.binding != command.binding:
            raise AigcTaskError("task binding mismatch")
        if current.status in _TERMINAL:
            raise AigcTaskError("illegal task transition from terminal state")

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

        asset_id = current.asset_id
        if (
            command.action == "resume"
            and current.status == AigcTaskStatus.REVISION_REQUIRED
        ):
            # A revision cycle deliberately opens a fresh asset slot while the
            # immutable event history retains the previously reviewed asset.
            asset_id = None
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
                "version": current.version + 1,
                "events": (*current.events, event),
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
