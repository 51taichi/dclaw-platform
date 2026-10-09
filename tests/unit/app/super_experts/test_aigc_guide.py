from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from qwenpaw.aigc.workflow_compiler import WorkflowGuideStepDefinition
from qwenpaw.aigc.workflow_contract import WorkflowBlueprint
from qwenpaw.app.super_experts.aigc_guide import project_aigc_guide
from qwenpaw.app.super_experts.models import (
    AigcMaterialTask,
    AigcTaskBinding,
    AigcTaskStatus,
    AigcWorkflowDefinition,
    AigcWorkflowGuideEvent,
)


NOW = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)


def _blueprint() -> WorkflowBlueprint:
    return WorkflowBlueprint.model_validate(
        {
            "schema_version": 1,
            "title": "文案到视频",
            "execution_preference": "CUSTOMER_TRIGGERED",
            "nodes": [
                {
                    "node_id": "copy",
                    "kind": "prompt",
                    "title": "文案",
                    "capability": "storyboard",
                    "inputs": {"text": "开场"},
                    "customer_action": "CLICK_GENERATE",
                },
                {
                    "node_id": "clip",
                    "kind": "video_generate",
                    "title": "视频",
                    "capability": "text_to_video",
                    "provider_id": "provider-1",
                    "model_id": "video-1",
                    "inputs": {"prompt": "课堂"},
                    "customer_action": "CLICK_GENERATE",
                },
            ],
            "edges": [{"source": "copy", "target": "clip", "target_slot": "prompt"}],
            "output_node_id": "clip",
            "fallback_policy": "FAIL_CLOSED",
        }
    )


def _step(logical_id: str, node_id: str) -> WorkflowGuideStepDefinition:
    is_video = logical_id == "clip"
    return WorkflowGuideStepDefinition(
        step_id=f"{logical_id}.generate",
        kind="GENERATE",
        title=logical_id,
        instruction="点击生成",
        logical_node_id=logical_id,
        node_id=node_id,
        control_id=f"aigc.{logical_id}.generate-submit",
        optional=False,
        completion_rule="JOB_SUCCEEDED_WITH_OUTPUT",
        expected_output_type="video" if is_video else "file",
        expected_capability="text_to_video" if is_video else "storyboard",
        expected_provider_id="provider-1",
        expected_model_id="video-1" if is_video else "text-1",
    )


def _task(*, optional_copy: bool = False) -> AigcMaterialTask:
    copy_step = _step("copy", "prompt-1").model_copy(
        update={"optional": optional_copy}
    )
    workflow = AigcWorkflowDefinition(
        workflow_id="workflow-1",
        schema_version=1,
        execution_mode="PREBUILT_WORKFLOW",
        workflow_revision=1,
        guide_revision=1,
        blueprint=_blueprint(),
        guide_steps=(
            copy_step,
            _step("clip", "video-1"),
            WorkflowGuideStepDefinition(
                step_id="workflow.submit",
                kind="SUBMIT",
                title="提交",
                instruction="提交审核",
                logical_node_id="clip",
                node_id="video-1",
                control_id="aigc.workflow.submit",
                optional=False,
                completion_rule="OUTPUT_AVAILABLE",
            ),
        ),
    )
    return AigcMaterialTask(
        binding=AigcTaskBinding(
            installation_id="installation-1",
            conversation_id="conversation-1",
            agent_task_id="agent-task-1",
            content_revision=1,
            material_task_id="material-1",
            canvas_id="canvas-1",
            node_id="video-1",
            workflow_id="workflow-1",
            execution_mode="PREBUILT_WORKFLOW",
            node_bindings={"copy": "prompt-1", "clip": "video-1"},
            output_node_id="video-1",
            workflow_revision=1,
            guide_revision=1,
        ),
        status=AigcTaskStatus.WAITING_TO_START,
        version=1,
        events=(),
        workflow=workflow,
    )


def _canvas():
    return SimpleNamespace(
        id="canvas-1",
        nodes=[SimpleNamespace(id="prompt-1"), SimpleNamespace(id="video-1")],
    )


def _job(
    node_id: str,
    status: str,
    minute: int,
    *,
    outputs: bool = True,
    kind: str = "file",
    capability: str | None = None,
    provider_id: str = "provider-1",
    model_id: str | None = None,
):
    stamp = NOW + timedelta(minutes=minute)
    return SimpleNamespace(
        id=f"job-{node_id}-{minute}",
        canvas_id="canvas-1",
        node_id=node_id,
        status=status,
        created_at=stamp.isoformat(),
        updated_at=stamp.isoformat(),
        outputs=(
            [SimpleNamespace(id=f"asset-{node_id}-{minute}", kind=kind)]
            if outputs
            else []
        ),
        capability=capability or ("text_to_video" if node_id == "video-1" else "storyboard"),
        provider_id=provider_id,
        model_id=model_id or ("video-1" if node_id == "video-1" else "text-1"),
    )


def _status(guide, step_id: str) -> str:
    return next(step.status for step in guide.steps if step.step_id == step_id)


def test_downstream_generate_stays_locked_until_upstream_succeeds():
    guide = project_aigc_guide(task=_task(), canvas=_canvas(), jobs=[])

    assert _status(guide, "copy.generate") == "READY"
    assert _status(guide, "clip.generate") == "LOCKED"
    assert guide.current_step_id == "copy.generate"


def test_failed_job_exposes_retry_and_refresh_reconstructs_same_step():
    jobs = [_job("prompt-1", "failed", 1, outputs=False)]

    first = project_aigc_guide(task=_task(), canvas=_canvas(), jobs=jobs)
    refreshed = project_aigc_guide(task=_task(), canvas=_canvas(), jobs=jobs)

    assert first == refreshed
    assert first.current_step_id == "copy.generate"
    assert first.current_step is not None
    assert first.current_step.status == "FAILED"
    assert first.current_step.recovery is not None
    assert first.current_step.recovery.action == "RETRY_NODE"


def test_regenerated_upstream_invalidates_older_downstream_result():
    jobs = [
        _job("prompt-1", "succeeded", 1),
        _job("video-1", "succeeded", 2, kind="video"),
        _job("prompt-1", "succeeded", 3),
    ]

    guide = project_aigc_guide(task=_task(), canvas=_canvas(), jobs=jobs)

    assert _status(guide, "copy.generate") == "COMPLETED"
    assert _status(guide, "clip.generate") == "READY"
    assert guide.current_step_id == "clip.generate"


def test_wrong_model_capability_or_output_kind_does_not_unlock_step():
    jobs = [
        _job(
            "prompt-1",
            "succeeded",
            1,
            capability="text_to_image",
            model_id="wrong-model",
            kind="image",
        )
    ]

    guide = project_aigc_guide(task=_task(), canvas=_canvas(), jobs=jobs)

    assert _status(guide, "copy.generate") == "FAILED"
    assert guide.current_step is not None
    assert guide.current_step.recovery is not None
    assert guide.current_step.recovery.code == "NODE_JOB_SEMANTICS_MISMATCH"


def test_authorized_model_choice_does_not_change_workflow_semantics():
    jobs = [
        _job(
            "prompt-1",
            "succeeded",
            1,
            model_id="customer-selected-model",
            kind="file",
        )
    ]

    guide = project_aigc_guide(task=_task(), canvas=_canvas(), jobs=jobs)

    assert _status(guide, "copy.generate") == "COMPLETED"
    assert guide.current_step_id == "clip.generate"


def test_optional_skip_is_projected_only_from_durable_bound_event():
    task = _task(optional_copy=True)
    task = task.model_copy(
        update={
            "guide_events": (
                AigcWorkflowGuideEvent(
                    event_id="skip-1",
                    action="SKIP_OPTIONAL",
                    workflow_id="workflow-1",
                    guide_revision=1,
                    step_id="copy.generate",
                    logical_node_id="copy",
                    node_id="prompt-1",
                ),
            )
        }
    )

    guide = project_aigc_guide(task=task, canvas=_canvas(), jobs=[])

    assert _status(guide, "copy.generate") == "SKIPPED"
    assert _status(guide, "clip.generate") == "READY"


def test_missing_bound_canvas_returns_blocked_recovery_not_another_canvas():
    guide = project_aigc_guide(task=_task(), canvas=None, jobs=[])

    assert guide.current_step is not None
    assert guide.current_step.status == "BLOCKED"
    assert guide.current_step.recovery is not None
    assert guide.current_step.recovery.code == "BOUND_CANVAS_MISSING"


def test_manual_fallback_projects_real_node_actions_from_blank_canvas():
    base = _task()
    manual_steps = (
        WorkflowGuideStepDefinition(
            step_id="copy.manual-add",
            kind="MANUAL_BUILD",
            title="添加文案节点",
            instruction="添加",
            logical_node_id="copy",
            node_id="prompt-1",
            control_id="aigc.canvas.add-node.prompt",
            optional=False,
            completion_rule="PRESENT",
            manual_action="ADD_NODE",
            node_kind="prompt",
            manual_node_data={"text": "开场"},
        ),
        WorkflowGuideStepDefinition(
            step_id="clip.manual-add",
            kind="MANUAL_BUILD",
            title="添加视频节点",
            instruction="添加",
            logical_node_id="clip",
            node_id="video-1",
            control_id="aigc.canvas.add-node.video_generate",
            optional=False,
            completion_rule="PRESENT",
            manual_action="ADD_NODE",
            node_kind="video_generate",
            manual_node_data={"text": "课堂"},
        ),
    )
    task = base.model_copy(
        update={
            "binding": base.binding.model_copy(
                update={"execution_mode": "MANUAL_BUILD"}
            ),
            "workflow": base.workflow.model_copy(
                update={"execution_mode": "MANUAL_BUILD", "guide_steps": manual_steps}
            ),
        }
    )
    blank = SimpleNamespace(id="canvas-1", nodes=[], edges=[])

    first = project_aigc_guide(task=task, canvas=blank, jobs=[])
    assert first.current_step_id == "copy.manual-add"
    assert first.current_step.manual_action == "ADD_NODE"
    assert _status(first, "clip.manual-add") == "LOCKED"

    one_node = SimpleNamespace(
        id="canvas-1",
        nodes=[SimpleNamespace(id="prompt-1", type="prompt")],
        edges=[],
    )
    second = project_aigc_guide(task=task, canvas=one_node, jobs=[])
    assert _status(second, "copy.manual-add") == "COMPLETED"
    assert second.current_step_id == "clip.manual-add"
    assert second.current_step.status == "READY"
