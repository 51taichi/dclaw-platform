"""Server-authoritative projection for super-expert AIGC workflow guides."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .models import AigcMaterialTask, AigcTaskStatus


GuideStepStatus = Literal[
    "LOCKED",
    "READY",
    "RUNNING",
    "FAILED",
    "COMPLETED",
    "SKIPPED",
    "BLOCKED",
]


class AigcGuideRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["RETRY_NODE", "RESTORE_BOUND_CANVAS", "RELOAD_TASK"]
    code: str


class AigcGuideStepProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str
    kind: Literal["INSPECT", "GENERATE", "SUBMIT", "MANUAL_BUILD"]
    title: str
    instruction: str
    logical_node_id: str | None
    node_id: str | None
    control_id: str | None
    optional: bool
    status: GuideStepStatus
    recovery: AigcGuideRecovery | None = None


class AigcTaskSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    material_task_id: str
    status: AigcTaskStatus
    asset_id: str | None
    task_version: int


class AigcGuideProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str
    workflow_revision: int
    guide_revision: int
    execution_mode: Literal["PREBUILT_WORKFLOW", "MANUAL_BUILD"]
    current_step_id: str | None
    current_step: AigcGuideStepProjection | None
    steps: tuple[AigcGuideStepProjection, ...]
    task_summary: AigcTaskSummary


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _latest_jobs(jobs: list[Any]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for job in jobs:
        node_id = str(getattr(job, "node_id", "") or "")
        if not node_id:
            continue
        current = latest.get(node_id)
        if current is None or _timestamp(getattr(job, "updated_at")) > _timestamp(
            getattr(current, "updated_at")
        ):
            latest[node_id] = job
    return latest


def _job_success_time(job: Any | None) -> datetime | None:
    if job is None or str(getattr(job, "status", "")) != "succeeded":
        return None
    if not list(getattr(job, "outputs", []) or []):
        return None
    return _timestamp(getattr(job, "updated_at"))


def _summary(task: AigcMaterialTask) -> AigcTaskSummary:
    return AigcTaskSummary(
        material_task_id=task.binding.material_task_id,
        status=task.status,
        asset_id=task.asset_id,
        task_version=task.version,
    )


def _blocked_projection(
    task: AigcMaterialTask,
    *,
    code: str,
) -> AigcGuideProjection:
    workflow = task.workflow
    assert workflow is not None
    step = AigcGuideStepProjection(
        step_id="workflow.blocked",
        kind="MANUAL_BUILD",
        title="恢复当前任务",
        instruction="当前任务绑定的画布不可用，请恢复该画布后继续。",
        logical_node_id=None,
        node_id=None,
        control_id=None,
        optional=False,
        status="BLOCKED",
        recovery=AigcGuideRecovery(
            action="RESTORE_BOUND_CANVAS",
            code=code,
        ),
    )
    return AigcGuideProjection(
        workflow_id=workflow.workflow_id,
        workflow_revision=workflow.workflow_revision,
        guide_revision=workflow.guide_revision,
        execution_mode=workflow.execution_mode,
        current_step_id=step.step_id,
        current_step=step,
        steps=(step,),
        task_summary=_summary(task),
    )


def project_aigc_guide(
    *,
    task: AigcMaterialTask,
    canvas: Any | None,
    jobs: list[Any],
    now: datetime | None = None,
) -> AigcGuideProjection:
    """Derive guide progress exclusively from persisted workflow and AIGC facts."""
    _ = now
    workflow = task.workflow
    if workflow is None:
        raise ValueError("LEGACY_TASK_GUIDE_REQUIRED")
    if canvas is None or str(getattr(canvas, "id", "")) != task.binding.canvas_id:
        return _blocked_projection(task, code="BOUND_CANVAS_MISSING")

    if workflow.execution_mode == "MANUAL_BUILD":
        step = AigcGuideStepProjection(
            step_id="workflow.manual-build",
            kind="MANUAL_BUILD",
            title="手动搭建工作流",
            instruction="从空白画布开始，按向导逐步添加并连接所需节点。",
            logical_node_id=None,
            node_id=None,
            control_id="aigc.canvas.add-node",
            optional=False,
            status="READY",
        )
        return AigcGuideProjection(
            workflow_id=workflow.workflow_id,
            workflow_revision=workflow.workflow_revision,
            guide_revision=workflow.guide_revision,
            execution_mode=workflow.execution_mode,
            current_step_id=step.step_id,
            current_step=step,
            steps=(step,),
            task_summary=_summary(task),
        )

    canvas_node_ids = {
        str(getattr(node, "id", "") or "")
        for node in list(getattr(canvas, "nodes", []) or [])
    }
    if not set(task.binding.node_bindings.values()).issubset(canvas_node_ids):
        return _blocked_projection(task, code="BOUND_NODE_MISSING")

    latest_jobs = _latest_jobs(
        [
            job
            for job in jobs
            if str(getattr(job, "canvas_id", "") or "") == task.binding.canvas_id
            and str(getattr(job, "node_id", "") or "") in canvas_node_ids
        ]
    )
    dependencies: dict[str, set[str]] = {
        node.node_id: set() for node in workflow.blueprint.nodes
    }
    for edge in workflow.blueprint.edges:
        dependencies[edge.target].add(edge.source)
    skipped = {
        event.step_id
        for event in task.guide_events
        if event.workflow_id == workflow.workflow_id
        and event.guide_revision == workflow.guide_revision
        and event.action == "SKIP_OPTIONAL"
    }
    statuses: dict[str, GuideStepStatus] = {}
    success_times: dict[str, datetime] = {}
    projected: list[AigcGuideStepProjection] = []
    logical_status: dict[str, GuideStepStatus] = {}

    for definition in workflow.guide_steps:
        recovery = None
        if definition.kind == "SUBMIT":
            output_status = logical_status.get(definition.logical_node_id, "LOCKED")
            if task.status in {
                AigcTaskStatus.SUBMITTED,
                AigcTaskStatus.REVIEWING,
                AigcTaskStatus.REVISION_REQUIRED,
                AigcTaskStatus.ACCEPTED,
            }:
                status: GuideStepStatus = "COMPLETED"
            elif output_status in {"COMPLETED", "SKIPPED"}:
                status = "READY"
            else:
                status = "LOCKED"
        elif definition.step_id in skipped and definition.optional:
            status = "SKIPPED"
            logical_status[definition.logical_node_id] = status
        elif definition.kind == "INSPECT":
            status = "COMPLETED"
            logical_status[definition.logical_node_id] = status
        else:
            upstream_ids = dependencies.get(definition.logical_node_id, set())
            upstream_ready = all(
                logical_status.get(logical_id) in {"COMPLETED", "SKIPPED"}
                for logical_id in upstream_ids
            )
            if not upstream_ready:
                status = "LOCKED"
            else:
                job = latest_jobs.get(definition.node_id)
                job_status = str(getattr(job, "status", "") or "")
                if job is None:
                    status = "READY"
                elif job_status in {"queued", "running"}:
                    status = "RUNNING"
                elif job_status in {"failed", "cancelled"}:
                    status = "FAILED"
                    recovery = AigcGuideRecovery(
                        action="RETRY_NODE",
                        code="NODE_JOB_FAILED",
                    )
                else:
                    succeeded_at = _job_success_time(job)
                    upstream_times = [
                        success_times[logical_id]
                        for logical_id in upstream_ids
                        if logical_id in success_times
                    ]
                    if succeeded_at is None:
                        status = "FAILED"
                        recovery = AigcGuideRecovery(
                            action="RETRY_NODE",
                            code="NODE_OUTPUT_MISSING",
                        )
                    elif upstream_times and succeeded_at < max(upstream_times):
                        status = "READY"
                    else:
                        status = "COMPLETED"
                        success_times[definition.logical_node_id] = succeeded_at
            logical_status[definition.logical_node_id] = status
        statuses[definition.step_id] = status
        projected.append(
            AigcGuideStepProjection(
                step_id=definition.step_id,
                kind=definition.kind,
                title=definition.title,
                instruction=definition.instruction,
                logical_node_id=definition.logical_node_id,
                node_id=definition.node_id,
                control_id=definition.control_id,
                optional=definition.optional,
                status=status,
                recovery=recovery,
            )
        )

    current = next(
        (
            step
            for step in projected
            if step.status not in {"COMPLETED", "SKIPPED"}
        ),
        None,
    )
    return AigcGuideProjection(
        workflow_id=workflow.workflow_id,
        workflow_revision=workflow.workflow_revision,
        guide_revision=workflow.guide_revision,
        execution_mode=workflow.execution_mode,
        current_step_id=current.step_id if current else None,
        current_step=current,
        steps=tuple(projected),
        task_summary=_summary(task),
    )

