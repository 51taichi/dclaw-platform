"""Trusted AIGC execution contracts, independent of expert installations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from typing import Any, TYPE_CHECKING

from ...aigc.workflow_compiler import CompiledWorkflow
from .canvas_service import AigcCanvasService
from .models import Canvas
from .resource_store import AigcResourceError, AigcResourceStore

if TYPE_CHECKING:
    from ..storage.repos.aigc_execution_repo import AigcExecutionRepository


@dataclass(frozen=True)
class WorkflowExecutionBinding:
    owner_user_id: str
    canvas_id: str
    workflow_id: str
    workflow_revision: int
    node_id: str
    logical_node_id: str
    provider_id: str
    model_id: str
    capability: str

    def __post_init__(self) -> None:
        if type(self.workflow_revision) is not int or self.workflow_revision < 1:
            raise ValueError("INVALID_WORKFLOW_REVISION")
        for field in fields(self):
            if field.name == "workflow_revision":
                continue
            value = getattr(self, field.name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError("INVALID_EXECUTION_BINDING")


def validate_execution(
    binding: WorkflowExecutionBinding, *, provider_id: str, model_id: str,
    capability: str,
) -> None:
    if (provider_id, model_id, capability) != (
        binding.provider_id, binding.model_id, binding.capability,
    ):
        raise ValueError("EXECUTION_BINDING_MISMATCH")


def validate_execution_capability(
    binding: WorkflowExecutionBinding, *, capability: str,
) -> None:
    """Keep the workflow operation fixed while allowing an authorized model choice."""
    if capability != binding.capability:
        raise ValueError("EXECUTION_BINDING_MISMATCH")


class AigcWorkflowExecutionService:
    def __init__(self, store: AigcResourceStore, repository: AigcExecutionRepository):
        self.store = store
        self.repository = repository
        self.canvases = AigcCanvasService(store)

    def create(
        self, owner_user_id: str, operation_id: str, *, command: dict[str, Any],
        compiled: CompiledWorkflow, meta: dict[str, Any] | None = None,
    ) -> tuple[Canvas, CompiledWorkflow]:
        """Persist a stable creation snapshot before touching canvas files.

        Only trusted adapters call this after compiling a validated command.
        Returning the stored compiled graph keeps retry guide/node IDs identical.
        """
        from ..storage.repos.aigc_execution_repo import command_digest

        resumed = self.resume(owner_user_id, operation_id, command=command, meta=meta)
        if resumed is not None:
            return resumed
        candidate = self.canvases.build_compiled(owner_user_id, compiled, meta=meta)
        contracts = []
        for node in compiled.nodes:
            capability = node.data.get("modelCapability")
            if not capability:
                continue
            contracts.append(WorkflowExecutionBinding(
                owner_user_id=owner_user_id, canvas_id=candidate.id,
                workflow_id=compiled.workflow_id, workflow_revision=1,
                node_id=node.physical_node_id, logical_node_id=node.logical_node_id,
                provider_id=node.data.get("providerId", ""),
                model_id=node.data.get("modelId", ""), capability=capability,
            ))
        # Source and output-only workflows may contain no generating nodes.
        if contracts:
            self.repository._validate_group(contracts)
        self.repository.prepare_operation(
            owner_user_id, operation_id, canvas_id=candidate.id,
            digest=command_digest({"command": command, "meta": meta or {}}),
            snapshot={"canvas": candidate.model_dump(mode="json"),
                      "compiled": compiled.model_dump(mode="json"),
                      "bindings": [asdict(binding) for binding in contracts]},
        )
        return self._apply(owner_user_id, operation_id)

    def resume(
        self, owner_user_id: str, operation_id: str, *, command: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> tuple[Canvas, CompiledWorkflow] | None:
        """Recover an accepted command without recompiling against live inputs.

        This restores resources only; generation still checks current policy,
        provider availability and input ownership at its execution boundary.
        """
        from ..storage.repos.aigc_execution_repo import command_digest

        operation = self.repository.get_operation(owner_user_id, operation_id)
        if operation is None:
            return None
        if operation["command_digest"] != command_digest({"command": command, "meta": meta or {}}):
            raise ValueError("OPERATION_CONFLICT")
        return self._apply(owner_user_id, operation_id)

    def _apply(self, owner_user_id: str, operation_id: str) -> tuple[Canvas, CompiledWorkflow]:
        with self.repository.transaction() as connection:
            operation = self.repository._operation(connection, owner_user_id, operation_id)
            if operation is None:
                raise ValueError("WORKFLOW_OPERATION_MISSING")
            snapshot = json.loads(operation["resource_snapshot"])
            canvas = Canvas.model_validate(snapshot["canvas"])
            saved_compiled = CompiledWorkflow.model_validate(snapshot["compiled"])
            if operation["phase"] == "APPLIED":
                return self.canvases.get(owner_user_id, canvas.id), saved_compiled
            file_missing = False
            try:
                existing = self.store.read("canvases", canvas.id)
            except AigcResourceError as exc:
                if exc.code != "RESOURCE_NOT_FOUND":
                    raise
                file_missing = True
            else:
                if existing != snapshot["canvas"]:
                    raise ValueError("WORKFLOW_RESOURCE_CONFLICT")
            bindings = [WorkflowExecutionBinding(**value) for value in snapshot["bindings"]]
            self.repository._insert_bindings(connection, bindings, operation_id)
            # An existing matching snapshot already completed the file step.
            # Do not rewrite it: a user may edit it after the check above.
            if file_missing:
                self.store.write("canvases", canvas.id, canvas.model_dump(mode="json"))
            self.repository.mark_applied(connection, owner_user_id, operation_id)
            return canvas, saved_compiled
