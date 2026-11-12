from __future__ import annotations

import json

import pytest

from qwenpaw.aigc.workflow_compiler import WorkflowGuideStepDefinition
from qwenpaw.aigc.workflow_contract import WorkflowBlueprint
from qwenpaw.app.super_experts.aigc_tasks import (
    AigcTaskCommand,
    AigcTaskError,
    AigcTaskRepository,
)
from qwenpaw.app.super_experts.models import (
    AigcTaskBinding,
    AigcTaskStatus,
    AigcWorkflowDefinition,
    AigcWorkflowGuideEvent,
)


def _blueprint() -> WorkflowBlueprint:
    return WorkflowBlueprint.model_validate(
        {
            "schema_version": 1,
            "title": "三节点视频",
            "execution_preference": "CUSTOMER_TRIGGERED",
            "nodes": [
                {
                    "node_id": "clip",
                    "kind": "video_generate",
                    "title": "生成视频",
                    "capability": "text_to_video",
                    "provider_id": "provider-1",
                    "model_id": "video-1",
                    "inputs": {"prompt": "真实课堂"},
                    "parameters": {"duration_seconds": 5},
                    "customer_action": "CLICK_GENERATE",
                    "optional": True,
                }
            ],
            "edges": [],
            "output_node_id": "clip",
            "fallback_policy": "FAIL_CLOSED",
        }
    )


def _step(*, optional: bool = True) -> WorkflowGuideStepDefinition:
    return WorkflowGuideStepDefinition(
        step_id="clip.generate",
        kind="GENERATE",
        title="生成视频",
        instruction="点击生成",
        logical_node_id="clip",
        node_id="video-1",
        control_id="aigc.video.generate-submit",
        optional=optional,
        completion_rule="JOB_SUCCEEDED_WITH_OUTPUT",
    )


def _workflow(*, optional: bool = True) -> AigcWorkflowDefinition:
    return AigcWorkflowDefinition(
        workflow_id="workflow-1",
        schema_version=1,
        execution_mode="PREBUILT_WORKFLOW",
        workflow_revision=1,
        guide_revision=1,
        blueprint=_blueprint(),
        guide_steps=(
            _step(optional=optional),
            WorkflowGuideStepDefinition(
                step_id="workflow.submit",
                kind="SUBMIT",
                title="提交",
                instruction="完成并返回会话",
                logical_node_id="clip",
                node_id="video-1",
                control_id="aigc.workflow.submit",
                optional=False,
                completion_rule="OUTPUT_AVAILABLE",
            ),
        ),
    )


def _binding() -> AigcTaskBinding:
    return AigcTaskBinding(
        installation_id="installation-1",
        conversation_id="conversation-1",
        agent_task_id="agent-task-1",
        content_revision=3,
        material_task_id="material-1",
        canvas_id="canvas-1",
        node_id="video-1",
        workflow_id="workflow-1",
        execution_mode="PREBUILT_WORKFLOW",
        node_bindings={"clip": "video-1"},
        output_node_id="video-1",
        workflow_revision=1,
        guide_revision=1,
    )


def _create_command(*, optional: bool = True) -> AigcTaskCommand:
    return AigcTaskCommand(
        action="create",
        event_id="create-1",
        binding=_binding(),
        workflow=_workflow(optional=optional),
    )


def test_legacy_task_document_loads_without_workflow_fields(tmp_path):
    document = {
        "schema_version": 1,
        "tasks": {
            "material-1": {
                "binding": {
                    "installation_id": "installation-1",
                    "conversation_id": "conversation-1",
                    "agent_task_id": "agent-task-1",
                    "content_revision": 3,
                    "material_task_id": "material-1",
                    "canvas_id": "canvas-1",
                    "node_id": "video-1",
                },
                "status": "WAITING_TO_START",
                "asset_id": None,
                "version": 1,
                "events": [
                    {
                        "event_id": "create-1",
                        "action": "create",
                        "from_status": None,
                        "to_status": "WAITING_TO_START",
                        "occurred_at": "2026-09-04T00:00:00Z",
                    }
                ],
                "operation_id": "aigc.text_to_video.create",
                "operation_version": "1",
                "operation_arguments": {},
                "updated_at": "2026-09-04T00:00:00Z",
            }
        },
        "idempotency": {},
        "event_ids": ["create-1"],
    }
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "aigc_material_tasks.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )

    task = AigcTaskRepository(tmp_path).get("material-1")

    assert task is not None
    assert task.binding.node_id == "video-1"
    assert task.binding.workflow_id is None
    assert task.binding.execution_mode == "LEGACY"
    assert task.workflow is None
    assert task.guide_events == ()


def test_workflow_create_persists_definition_and_output_alias_idempotently(tmp_path):
    repository = AigcTaskRepository(tmp_path)

    first = repository.apply(_create_command(), "workflow-key")
    replay = repository.apply(_create_command(), "workflow-key")

    assert replay == first
    assert first.workflow is not None
    assert first.workflow.workflow_id == "workflow-1"
    assert first.binding.node_id == first.binding.output_node_id == "video-1"
    assert first.binding.node_bindings == {"clip": "video-1"}


def test_workflow_create_rejects_output_alias_mismatch(tmp_path):
    command = _create_command().model_copy(
        update={
            "binding": _binding().model_copy(update={"node_id": "another-node"})
        }
    )

    with pytest.raises(AigcTaskError, match="output binding"):
        AigcTaskRepository(tmp_path).apply(command, "workflow-key")


def test_skip_optional_step_is_revision_bound_and_keeps_task_status(tmp_path):
    repository = AigcTaskRepository(tmp_path)
    created = repository.apply(_create_command(), "workflow-key")
    skipped = repository.apply(
        AigcTaskCommand(
            action="guide_update",
            event_id="skip-1",
            binding=created.binding,
            guide_event=AigcWorkflowGuideEvent(
                event_id="skip-1",
                action="SKIP_OPTIONAL",
                workflow_id="workflow-1",
                guide_revision=1,
                step_id="clip.generate",
                logical_node_id="clip",
                node_id="video-1",
            ),
        ),
        "skip-key",
    )

    assert skipped.status == AigcTaskStatus.WAITING_TO_START
    assert skipped.version == 2
    assert skipped.guide_events[-1].step_id == "clip.generate"
    assert skipped.events[-1].action == "guide_update"


def test_skip_rejects_stale_revision_wrong_node_and_required_step(tmp_path):
    for name, optional, changes, message in (
        ("stale", True, {"guide_revision": 2}, "revision"),
        ("wrong-node", True, {"node_id": "video-other"}, "binding"),
        ("required", False, {}, "optional"),
    ):
        root = tmp_path / name
        repository = AigcTaskRepository(root)
        created = repository.apply(
            _create_command(optional=optional),
            f"create-{name}",
        )
        guide_event = AigcWorkflowGuideEvent(
            event_id=f"skip-{name}",
            action="SKIP_OPTIONAL",
            workflow_id="workflow-1",
            guide_revision=1,
            step_id="clip.generate",
            logical_node_id="clip",
            node_id="video-1",
        ).model_copy(update=changes)

        with pytest.raises(AigcTaskError, match=message):
            repository.apply(
                AigcTaskCommand(
                    action="guide_update",
                    event_id=f"skip-{name}",
                    binding=created.binding,
                    guide_event=guide_event,
                ),
                f"skip-key-{name}",
            )
