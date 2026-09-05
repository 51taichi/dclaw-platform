"""Trusted offline legacy-to-core binding migration; never called by core.

Run with application writers stopped and after schema initialization. The
default is read-only. Canvas/task files are never changed, even with apply.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from ..aigc.canvas_service import AigcCanvasService
from ..aigc.resource_store import AigcResourceError, AigcResourceStore
from ..aigc.workflow_execution import WorkflowExecutionBinding
from ..storage.repos.aigc_execution_repo import AigcExecutionRepository
from .aigc_tasks import AigcTaskCommand, AigcTaskError, AigcTaskRepository
from .models import AigcMaterialTask


def _contracts(task: AigcMaterialTask, store: AigcResourceStore) -> list[WorkflowExecutionBinding]:
    binding, workflow = task.binding, task.workflow
    AigcTaskRepository._validate_workflow_creation(AigcTaskCommand(
        action="create", event_id="offline-migration", binding=binding, workflow=workflow,
    ))
    if workflow is None:
        return []  # Only a valid LEGACY task may lack an immutable blueprint.
    if binding.execution_mode != "PREBUILT_WORKFLOW":
        raise ValueError("MANUAL_WORKFLOW_REQUIRES_RECONCILIATION")
    canvas = AigcCanvasService(store).load(binding.canvas_id)
    owner = AigcCanvasService.owner(canvas)
    if not owner or owner != owner.strip():
        raise ValueError("CANVAS_OWNER_MISSING")
    if (canvas.id != binding.canvas_id
            or canvas.meta.get("workflow_id") != workflow.workflow_id
            or canvas.meta.get("super_expert_material_task_id") != binding.material_task_id):
        raise ValueError("CANVAS_BINDING_MISMATCH")
    physical = {node.id: node for node in canvas.nodes}
    if (len(physical) != len(canvas.nodes)
            or len(set(binding.node_bindings.values())) != len(binding.node_bindings)):
        raise ValueError("NODE_BINDING_MISMATCH")
    result = []
    for semantic in workflow.blueprint.nodes:
        node_id = binding.node_bindings.get(semantic.node_id)
        node = physical.get(node_id)
        if node is None or node.type != semantic.kind:
            raise ValueError("NODE_BINDING_MISMATCH")
        # Mutable canvas model data is never the source of an execution grant.
        if semantic.capability:
            result.append(WorkflowExecutionBinding(
                owner_user_id=owner, canvas_id=canvas.id, workflow_id=workflow.workflow_id,
                workflow_revision=workflow.workflow_revision, node_id=node.id,
                logical_node_id=semantic.node_id, provider_id=semantic.provider_id or "",
                model_id=semantic.model_id or "", capability=semantic.capability,
            ))
    return result


def migrate_bindings(*, legacy_root: Path, studio_root: Path, engine: Engine,
                     apply: bool = False) -> dict[str, Any]:
    tables = set(inspect(engine).get_table_names())
    if not {"aigc_operation_journal", "aigc_workflow_execution_bindings"} <= tables:
        raise ValueError("CORE_SCHEMA_NOT_INITIALIZED")
    path = Path(legacy_root) / "aigc_material_tasks.json"
    if not path.is_file():
        raise ValueError("LEGACY_TASK_STORE_MISSING")
    try:
        document = json.loads(path.read_text("utf-8"))
        if (not isinstance(document, dict) or document.get("schema_version") != 1
                or not isinstance(document.get("tasks"), dict)):
            raise ValueError("invalid store")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("LEGACY_TASK_STORE_INVALID") from exc
    tasks = document["tasks"]
    canvas_counts = Counter(
        value.get("binding", {}).get("canvas_id")
        for value in tasks.values()
        if isinstance(value, dict) and isinstance(value.get("binding"), dict)
        and isinstance(value["binding"].get("canvas_id"), str)
    )
    report = {"scanned": len(tasks), "eligible": 0, "migrated": 0,
              "unchanged": 0, "skipped": 0, "conflicts": []}
    repository = AigcExecutionRepository(engine)
    store = AigcResourceStore(studio_root)
    for task_id, raw in sorted(tasks.items()):
        canvas_id = None
        try:
            task = AigcMaterialTask.model_validate(raw)
            canvas_id = task.binding.canvas_id
            if task.binding.material_task_id != task_id or canvas_counts[canvas_id] != 1:
                raise ValueError("TASK_BINDING_CONFLICT")
            contracts = _contracts(task, store)
            if not contracts:
                report["skipped"] += 1
                continue
            status = repository.classify_bindings(contracts)
            if status == "unchanged":
                report["unchanged"] += 1
                continue
            report["eligible"] += 1
            if apply:
                repository.register_bindings(contracts, f"legacy-workflow/{canvas_id}/{task.workflow.workflow_revision}")
                report["migrated"] += 1
        except (ValueError, OSError) as exc:
            # Never include exception text containing prompts, paths, credentials
            # or a complete Pydantic validation payload in the migration report.
            safe_codes = {"MANUAL_WORKFLOW_REQUIRES_RECONCILIATION", "CANVAS_OWNER_MISSING",
                          "CANVAS_BINDING_MISMATCH", "NODE_BINDING_MISMATCH", "TASK_BINDING_CONFLICT",
                          "WORKFLOW_OPERATION_INCOMPLETE", "EXECUTION_BINDING_CONFLICT", "OPERATION_CONFLICT"}
            reason = str(exc) if str(exc) in safe_codes else "LEGACY_TASK_INVALID"
            if isinstance(exc, AigcResourceError):
                reason = exc.code
            elif isinstance(exc, (ValidationError, AigcTaskError)):
                reason = "LEGACY_TASK_INVALID"
            report["conflicts"].append({"material_task_id": task_id, "canvas_id": canvas_id, "reason": reason})
    return report
