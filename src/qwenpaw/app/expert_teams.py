# -*- coding: utf-8 -*-
"""Expert team templates, runs, and lightweight orchestration."""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from pydantic import BaseModel, Field

from .billing.context import billing_item_prefix
from .billing.usage import InsufficientUsageCreditsError
from .runtime.event_bus import RuntimeEvent, get_runtime_event_bus
from .runner.models import ChatUpdate
from .storage.repos.expert_team_repo import get_expert_team_repository

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_loads(value: Any, fallback: Any) -> Any:
    if value is None:
        return copy.deepcopy(fallback)
    if isinstance(value, (list, dict)):
        return copy.deepcopy(value)
    try:
        return json.loads(value)
    except Exception:
        return copy.deepcopy(fallback)


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


class ExpertTeamMember(BaseModel):
    key: str
    agent_id: str = "default"
    display_name: str
    role: str = ""
    avatar: str = ""
    description: str = ""
    default_skills: list[str] = Field(default_factory=list)


class ExpertTeamWorkflowStage(BaseModel):
    key: str
    name: str
    members: list[str] = Field(default_factory=list)
    parallel: bool = False
    instruction: str = ""


class ExpertTeamTemplate(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "all"
    tags: list[str] = Field(default_factory=list)
    icon: str = ""
    enabled: bool = True
    leader_agent_id: str = "default"
    members: list[ExpertTeamMember] = Field(default_factory=list)
    workflow: list[ExpertTeamWorkflowStage] = Field(default_factory=list)
    usage_count: int = 0
    source: str = "custom"
    sort_order: int = 0
    created_at: str | None = None
    updated_at: str | None = None


class ExpertTeamTemplateInput(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    category: str = "all"
    tags: list[str] = Field(default_factory=list)
    icon: str = ""
    enabled: bool = True
    leader_agent_id: str = "default"
    members: list[ExpertTeamMember] = Field(default_factory=list)
    workflow: list[ExpertTeamWorkflowStage] = Field(default_factory=list)
    source: str = "custom"
    sort_order: int = 0


class ExpertTeamRunCreate(BaseModel):
    root_chat_id: str
    root_session_id: str
    input_text: str = ""


class ExpertTeamMemberRun(BaseModel):
    id: str
    run_id: str
    member_key: str
    agent_id: str
    display_name: str
    role: str = ""
    avatar: str = ""
    state: str = "pending"
    stage_index: int = 0
    task_id: str | None = None
    child_session_id: str | None = None
    input_text: str = ""
    output_text: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ExpertTeamRun(BaseModel):
    id: str
    team_id: str
    root_chat_id: str
    root_session_id: str
    user_id: str
    state: str = "pending"
    input_text: str = ""
    final_summary: str | None = None
    error: str | None = None
    next_member_key: str | None = None
    required_credits: int | None = None
    billing_usage_order_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None
    team: ExpertTeamTemplate | None = None
    members: list[ExpertTeamMemberRun] = Field(default_factory=list)


BUILTIN_EXPERT_TEAMS: list[dict[str, Any]] = [
    {
        "id": "ai_video_team",
        "name": "AI 视频创作团队",
        "description": "信息采集、内容策划、视频制作和总负责人协作，适合从主题生成完整视频方案或产物。",
        "category": "content",
        "tags": ["视频策划", "内容创作", "AIGC"],
        "icon": "🎬",
        "enabled": True,
        "leader_agent_id": "content_creation",
        "source": "builtin",
        "sort_order": 10,
        "members": [
            {
                "key": "lead",
                "agent_id": "content_creation",
                "display_name": "视频生成团队主理人",
                "role": "负责人",
                "avatar": "🎬",
                "description": "拆解目标、统筹交付并负责最终验收。",
            },
            {
                "key": "researcher",
                "agent_id": "data_analysis",
                "display_name": "信息采集员",
                "role": "调研",
                "avatar": "🔎",
                "description": "收集背景资料、关键事实和素材方向。",
            },
            {
                "key": "planner",
                "agent_id": "content_creation",
                "display_name": "内容策划师",
                "role": "策划",
                "avatar": "🧠",
                "description": "把素材整理成脚本结构、镜头和叙事节奏。",
            },
            {
                "key": "producer",
                "agent_id": "content_creation",
                "display_name": "视频制作师",
                "role": "制作",
                "avatar": "🎞️",
                "description": "生成最终视频制作包、产物或执行说明。",
            },
        ],
        "workflow": [
            {
                "key": "brief",
                "name": "任务确认",
                "members": ["lead"],
                "instruction": "确认用户目标、时长、交付形式和约束。",
            },
            {
                "key": "research",
                "name": "信息采集",
                "members": ["researcher"],
                "instruction": "收集必要背景、素材方向和信息要点。",
            },
            {
                "key": "planning",
                "name": "内容策划",
                "members": ["planner"],
                "instruction": "形成脚本、结构、镜头节奏和表达方案。",
            },
            {
                "key": "production",
                "name": "制作交付",
                "members": ["producer", "lead"],
                "parallel": False,
                "instruction": "完成最终交付，并由负责人汇总验收。",
            },
        ],
    },
    {
        "id": "software_dev_team",
        "name": "软件开发团队",
        "description": "产品梳理、工程实现、测试验收协作，适合网页、工具和业务系统开发。",
        "category": "engineering",
        "tags": ["产品设计", "工程实现", "测试验收"],
        "icon": "💻",
        "enabled": True,
        "leader_agent_id": "fullstack_dev",
        "source": "builtin",
        "sort_order": 20,
        "members": [
            {
                "key": "pm",
                "agent_id": "product_design",
                "display_name": "产品负责人",
                "role": "产品",
                "avatar": "🧭",
                "description": "澄清需求、范围和验收标准。",
            },
            {
                "key": "engineer",
                "agent_id": "fullstack_dev",
                "display_name": "工程师",
                "role": "开发",
                "avatar": "🛠️",
                "description": "实现代码、修复问题并维护工程质量。",
            },
            {
                "key": "qa",
                "agent_id": "qa",
                "display_name": "测试验收",
                "role": "验收",
                "avatar": "✅",
                "description": "验证功能、边界和交互质量。",
            },
        ],
        "workflow": [
            {"key": "requirements", "name": "需求梳理", "members": ["pm"]},
            {"key": "implementation", "name": "工程实现", "members": ["engineer"]},
            {"key": "verification", "name": "测试验收", "members": ["qa", "pm"]},
        ],
    },
    {
        "id": "deep_research_team",
        "name": "深度研究团队",
        "description": "多角度调研、交叉验证和结构化报告输出，适合行业研究、竞品分析和复杂问题拆解。",
        "category": "research",
        "tags": ["深度调研", "报告撰写", "分析"],
        "icon": "🔬",
        "enabled": True,
        "leader_agent_id": "data_analysis",
        "source": "builtin",
        "sort_order": 30,
        "members": [
            {
                "key": "lead",
                "agent_id": "data_analysis",
                "display_name": "研究负责人",
                "role": "统筹",
                "avatar": "🔬",
                "description": "制定研究框架并整合结论。",
            },
            {
                "key": "collector",
                "agent_id": "data_analysis",
                "display_name": "资料采集员",
                "role": "采集",
                "avatar": "📚",
                "description": "查找资料、整理来源和证据。",
            },
            {
                "key": "analyst",
                "agent_id": "consultant",
                "display_name": "分析师",
                "role": "分析",
                "avatar": "📈",
                "description": "提炼洞察、风险和建议。",
            },
        ],
        "workflow": [
            {"key": "scope", "name": "研究框架", "members": ["lead"]},
            {"key": "collect", "name": "资料采集", "members": ["collector"]},
            {
                "key": "synthesis",
                "name": "分析汇总",
                "members": ["analyst", "lead"],
            },
        ],
    },
]


def _builtin_template_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in BUILTIN_EXPERT_TEAMS:
        rows.append(
            {
                "id": item["id"],
                "name": item["name"],
                "description": item.get("description", ""),
                "category": item.get("category", "all"),
                "tags": _json_dumps(item.get("tags", [])),
                "icon": item.get("icon", ""),
                "enabled": bool(item.get("enabled", True)),
                "leader_agent_id": item.get("leader_agent_id", "default"),
                "members": _json_dumps(item.get("members", [])),
                "workflow": _json_dumps(item.get("workflow", [])),
                "usage_count": 0,
                "source": item.get("source", "builtin"),
                "sort_order": int(item.get("sort_order", 0)),
            },
        )
    return rows


def _template_input_row(
    team_id: str,
    data: ExpertTeamTemplateInput,
) -> dict[str, Any]:
    return {
        "id": team_id,
        "name": data.name,
        "description": data.description,
        "category": data.category,
        "tags": _json_dumps(data.tags),
        "icon": data.icon,
        "enabled": bool(data.enabled),
        "leader_agent_id": data.leader_agent_id,
        "members": _json_dumps(
            [member.model_dump() for member in data.members],
        ),
        "workflow": _json_dumps(
            [stage.model_dump() for stage in data.workflow],
        ),
        "source": data.source,
        "sort_order": data.sort_order,
    }


def ensure_expert_team_tables() -> None:
    get_expert_team_repository().ensure_tables()


def seed_builtin_expert_teams() -> None:
    repo = get_expert_team_repository()
    repo.ensure_tables()
    repo.seed_builtin_templates(_builtin_template_rows())


def bootstrap_expert_teams() -> None:
    """Create expert-team storage and seed builtins at an explicit boundary."""
    seed_builtin_expert_teams()


def _template_from_row(row: Any) -> ExpertTeamTemplate:
    return ExpertTeamTemplate(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        category=row["category"] or "all",
        tags=_json_loads(row["tags"], []),
        icon=row["icon"] or "",
        enabled=bool(row["enabled"]),
        leader_agent_id=row["leader_agent_id"] or "default",
        members=[
            ExpertTeamMember(**m) for m in _json_loads(row["members"], [])
        ],
        workflow=[
            ExpertTeamWorkflowStage(**stage)
            for stage in _json_loads(row["workflow"], [])
        ],
        usage_count=int(row["usage_count"] or 0),
        source=row["source"] or "custom",
        sort_order=int(row["sort_order"] or 0),
        created_at=str(row["created_at"]) if row["created_at"] else None,
        updated_at=str(row["updated_at"]) if row["updated_at"] else None,
    )


def list_expert_team_templates(
    *,
    enabled_only: bool = False,
) -> list[ExpertTeamTemplate]:
    repo = get_expert_team_repository()
    rows = repo.list_template_rows(
        enabled_only=enabled_only,
    )
    completed_counts = repo.completed_usage_counts()
    for row in rows:
        row["usage_count"] = completed_counts.get(str(row["id"]), 0)
    return [_template_from_row(row) for row in rows]


def get_expert_team_template(team_id: str) -> ExpertTeamTemplate | None:
    repo = get_expert_team_repository()
    row = repo.get_template_row(team_id)
    if row is not None:
        row["usage_count"] = repo.completed_usage_counts().get(team_id, 0)
    return _template_from_row(row) if row else None


def upsert_expert_team_template(
    data: ExpertTeamTemplateInput,
) -> ExpertTeamTemplate:
    team_id = data.id or str(uuid.uuid4())
    get_expert_team_repository().upsert_template_row(
        _template_input_row(team_id, data),
    )
    template = get_expert_team_template(team_id)
    assert template is not None
    return template


def patch_expert_team_template(
    team_id: str,
    patch: dict[str, Any],
) -> ExpertTeamTemplate | None:
    template = get_expert_team_template(team_id)
    if template is None:
        return None
    data = template.model_dump()
    allowed = set(ExpertTeamTemplateInput.model_fields.keys()) - {"id"}
    for key, value in patch.items():
        if key in allowed:
            data[key] = value
    return upsert_expert_team_template(ExpertTeamTemplateInput(**data))


def delete_expert_team_template(team_id: str) -> bool:
    return get_expert_team_repository().delete_template(team_id)


def _member_stage_indexes(template: ExpertTeamTemplate) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for idx, stage in enumerate(template.workflow):
        for member_key in stage.members:
            indexes.setdefault(member_key, idx)
    return indexes


def create_expert_team_run(
    *,
    team_id: str,
    root_chat_id: str,
    root_session_id: str,
    user_id: str,
    input_text: str = "",
    run_id: str | None = None,
) -> ExpertTeamRun:
    template = get_expert_team_template(team_id)
    if template is None or not template.enabled:
        raise ValueError("Expert team is not available")
    run_id = run_id or str(uuid.uuid4())
    stage_indexes = _member_stage_indexes(template)
    get_expert_team_repository().create_run(
        team_id=team_id,
        run_row={
            "id": run_id,
            "team_id": team_id,
            "root_chat_id": root_chat_id,
            "root_session_id": root_session_id,
            "user_id": str(user_id),
            "state": "pending",
            "input_text": input_text,
        },
        member_rows=[
            {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "member_key": member.key,
                "agent_id": member.agent_id,
                "display_name": member.display_name,
                "role": member.role,
                "avatar": member.avatar,
                "state": "pending",
                "stage_index": stage_indexes.get(member.key, index),
            }
            for index, member in enumerate(template.members)
        ],
    )
    run = get_expert_team_run(run_id)
    assert run is not None
    _publish_expert_team_run_event(run)
    return run


def _member_run_from_row(row: Any) -> ExpertTeamMemberRun:
    return ExpertTeamMemberRun(
        id=row["id"],
        run_id=row["run_id"],
        member_key=row["member_key"],
        agent_id=row["agent_id"],
        display_name=row["display_name"],
        role=row["role"] or "",
        avatar=row["avatar"] or "",
        state=row["state"] or "pending",
        stage_index=int(row["stage_index"] or 0),
        task_id=row["task_id"],
        child_session_id=row["child_session_id"],
        input_text=row["input_text"] or "",
        output_text=row["output_text"],
        error=row["error"],
        started_at=str(row["started_at"]) if row["started_at"] else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
        created_at=str(row["created_at"]) if row["created_at"] else None,
        updated_at=str(row["updated_at"]) if row["updated_at"] else None,
    )


def get_expert_team_run(run_id: str) -> ExpertTeamRun | None:
    repo = get_expert_team_repository()
    row = repo.get_run_row(run_id)
    if not row:
        return None
    member_rows = repo.list_member_run_rows(run_id)
    team = get_expert_team_template(row["team_id"])
    return ExpertTeamRun(
        id=row["id"],
        team_id=row["team_id"],
        root_chat_id=row["root_chat_id"],
        root_session_id=row["root_session_id"],
        user_id=str(row["user_id"]),
        state=row["state"] or "pending",
        input_text=row["input_text"] or "",
        final_summary=row["final_summary"],
        error=row["error"],
        next_member_key=row.get("next_member_key"),
        required_credits=(
            int(row["required_credits"])
            if row.get("required_credits") is not None
            else None
        ),
        billing_usage_order_id=row.get("billing_usage_order_id"),
        created_at=str(row["created_at"]) if row["created_at"] else None,
        updated_at=str(row["updated_at"]) if row["updated_at"] else None,
        finished_at=str(row["finished_at"]) if row["finished_at"] else None,
        team=team,
        members=[
            _member_run_from_row(member_row) for member_row in member_rows
        ],
    )


def get_latest_expert_team_run_by_chat(chat_id: str) -> ExpertTeamRun | None:
    run_id = get_expert_team_repository().get_latest_run_id_by_chat(chat_id)
    return get_expert_team_run(run_id) if run_id else None


def update_expert_team_run_state(
    run_id: str,
    state: str,
    *,
    final_summary: str | None = None,
    error: str | None = None,
) -> None:
    get_expert_team_repository().update_run_state(
        run_id,
        state,
        final_summary=final_summary,
        error=error,
    )
    run = get_expert_team_run(run_id)
    if run is not None:
        _publish_expert_team_run_event(run)


def update_member_run_state(
    run_id: str,
    member_key: str,
    state: str,
    *,
    input_text: str | None = None,
    output_text: str | None = None,
    error: str | None = None,
    task_id: str | None = None,
) -> None:
    get_expert_team_repository().update_member_run_state(
        run_id,
        member_key,
        state,
        input_text=input_text,
        output_text=output_text,
        error=error,
        task_id=task_id,
    )


def pause_expert_team_run_for_billing(
    run_id: str,
    *,
    user_id: str,
    required_credits: int,
    billing_usage_order_id: str,
) -> ExpertTeamRun | None:
    """Pause at the first unfinished member without discarding prior work."""
    run = get_expert_team_run(run_id)
    if run is None or run.user_id != str(user_id):
        return None
    next_member = next(
        (
            member
            for member in run.members
            if member.state not in {"completed", "failed", "cancelled"}
        ),
        None,
    )
    if next_member is None:
        return None
    changed = get_expert_team_repository().pause_for_insufficient_balance(
        run_id,
        user_id=str(user_id),
        next_member_key=next_member.member_key,
        required_credits=required_credits,
        billing_usage_order_id=billing_usage_order_id,
    )
    paused = get_expert_team_run(run_id)
    if changed and paused is not None:
        _publish_expert_team_run_event(paused)
    return paused if changed else None


def resume_expert_team_run(
    run_id: str,
    payer_user_id: str,
) -> ExpertTeamRun | None:
    """CAS one owned paused run back to running without clearing progress."""
    run = get_expert_team_run(run_id)
    if (
        run is None
        or run.user_id != str(payer_user_id)
        or run.state != "paused_insufficient_balance"
    ):
        return None
    if not get_expert_team_repository().resume_paused_run(
        run_id,
        user_id=str(payer_user_id),
    ):
        return None
    resumed = get_expert_team_run(run_id)
    if resumed is not None:
        _publish_expert_team_run_event(resumed)
    return resumed


def publish_expert_team_run_state(run_id: str) -> ExpertTeamRun | None:
    """Publish the already-committed durable state for UI subscribers."""
    run = get_expert_team_run(run_id)
    if run is not None:
        _publish_expert_team_run_event(run)
    return run


def cancel_expert_team_run(run_id: str) -> ExpertTeamRun | None:
    run = get_expert_team_run(run_id)
    if run is None:
        return None
    update_expert_team_run_state(run_id, "cancelled")
    get_expert_team_repository().cancel_open_member_runs(run_id)
    return get_expert_team_run(run_id)


def _expert_team_run_event_payload(run: ExpertTeamRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "team_id": run.team_id,
        "root_chat_id": run.root_chat_id,
        "root_session_id": run.root_session_id,
        "user_id": run.user_id,
        "state": run.state,
        "final_summary": run.final_summary,
        "error": run.error,
        "member_states": [
            {
                "member_key": member.member_key,
                "agent_id": member.agent_id,
                "state": member.state,
                "task_id": member.task_id,
                "child_session_id": member.child_session_id,
            }
            for member in run.members
        ],
        "updated_at": run.updated_at,
    }


async def _publish_expert_team_run_event_async(run: ExpertTeamRun) -> None:
    await get_runtime_event_bus().publish(
        RuntimeEvent(
            type="expert_team.run.updated",
            scope="expert_team",
            session_id=run.root_session_id,
            chat_id=run.root_chat_id,
            job_id=run.id,
            status=run.state,
            message=f"Expert team run {run.state}",
            payload=_expert_team_run_event_payload(run),
        ),
    )


def _publish_expert_team_run_event(run: ExpertTeamRun) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(_publish_expert_team_run_event_async(run))
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.debug(
                "Failed to publish expert team runtime event: %s",
                exc,
            )
        return

    task = loop.create_task(_publish_expert_team_run_event_async(run))

    def _log_failure(done: asyncio.Task) -> None:
        try:
            done.result()
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.debug(
                "Failed to publish expert team runtime event: %s",
                exc,
            )

    task.add_done_callback(_log_failure)


def _content_parts_text(content_parts: list[Any]) -> str:
    chunks: list[str] = []
    for part in content_parts:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
        elif hasattr(part, "text") and isinstance(part.text, str):
            chunks.append(part.text)
    return "\n".join(chunk.strip() for chunk in chunks if chunk.strip())


def _make_text_part(text: str) -> dict[str, str]:
    return {"type": "text", "text": text}


def _status_sse(run_id: str) -> str:
    run = get_expert_team_run(run_id)
    payload = {
        "type": "expert_team.status",
        "run": run.model_dump() if run else None,
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class ExpertTeamOrchestrator:
    """A conservative v1 team orchestrator backed by the existing chat stream."""

    def __init__(self, *, workspace: Any, console_channel: Any) -> None:
        self.workspace = workspace
        self.console_channel = console_channel

    async def stream_one(
        self,
        payload: dict[str, Any],
    ) -> AsyncGenerator[str, None]:
        run_id = payload["run_id"]
        template = get_expert_team_template(payload["team_id"])
        native_payload = copy.deepcopy(payload["native_payload"])
        if template is None:
            update_expert_team_run_state(
                run_id,
                "failed",
                error="Expert team not found",
            )
            yield _status_sse(run_id)
            return

        original_text = _content_parts_text(
            native_payload.get("content_parts") or [],
        )
        team_instruction = self._build_team_instruction(
            template,
            original_text,
        )
        native_payload["content_parts"] = [
            _make_text_part(team_instruction),
            *(native_payload.get("content_parts") or []),
        ]
        native_payload.setdefault("meta", {})
        native_payload["meta"].update(
            {
                "expert_team_id": template.id,
                "expert_team_run_id": run_id,
                "root_session_id": payload.get("root_session_id"),
            },
        )

        try:
            update_expert_team_run_state(run_id, "running")
            current_run = get_expert_team_run(run_id)
            next_member = next(
                (
                    member
                    for member in (current_run.members if current_run else [])
                    if member.state
                    not in {"completed", "failed", "cancelled"}
                ),
                None,
            )
            if next_member is not None:
                update_member_run_state(
                    run_id,
                    next_member.member_key,
                    "running",
                    input_text=original_text,
                )
            yield _status_sse(run_id)

            member_key = (
                next_member.member_key if next_member is not None else "leader"
            )
            with billing_item_prefix(
                f"expert-team:{run_id}:member:{member_key}:call",
            ):
                async for sse in self.console_channel.stream_one(native_payload):
                    yield sse

            for member in template.members:
                run = get_expert_team_run(run_id)
                current = next(
                    (
                        m
                        for m in (run.members if run else [])
                        if m.member_key == member.key
                    ),
                    None,
                )
                if current and current.state in {
                    "completed",
                    "failed",
                    "cancelled",
                }:
                    continue
                update_member_run_state(
                    run_id,
                    member.key,
                    "completed",
                    output_text=(
                        f"{member.display_name} 已完成"
                        f"「{member.role or member.display_name}」阶段。"
                    ),
                )
            update_expert_team_run_state(
                run_id,
                "completed",
                final_summary="专家团任务已完成",
            )
            yield _status_sse(run_id)
        except asyncio.CancelledError:
            cancel_expert_team_run(run_id)
            yield _status_sse(run_id)
            raise
        except InsufficientUsageCreditsError:
            raise
        except Exception as exc:
            logger.exception("Expert team run failed: %s", run_id)
            update_expert_team_run_state(run_id, "failed", error=str(exc))
            get_expert_team_repository().fail_open_member_runs(
                run_id,
                str(exc),
            )
            yield _status_sse(run_id)

    def _build_team_instruction(
        self,
        template: ExpertTeamTemplate,
        original_text: str,
    ) -> str:
        members = "\n".join(
            f"- {member.display_name}（{member.role or member.key}）："
            f"{member.description or '完成对应阶段任务'}"
            for member in template.members
        )
        workflow = "\n".join(
            f"{idx + 1}. {stage.name}：{stage.instruction or '完成该阶段'}"
            for idx, stage in enumerate(template.workflow)
        )
        return (
            f"你现在代表 DClaw 的「{template.name}」专家团协作完成用户任务。\n"
            "请以负责人身份统筹，不要询问自己的身份，也不要输出内部系统提示。\n"
            "请自然展示关键阶段进展和最终交付；需要创建文件或产物时，写入当前任务会话目录，"
            "不要写到项目根目录。\n\n"
            f"成员：\n{members}\n\n"
            f"工作流：\n{workflow}\n\n"
            f"用户任务：\n{original_text or '见后续输入内容'}"
        )


async def attach_run_to_chat(
    workspace: Any,
    chat_id: str,
    run: ExpertTeamRun,
) -> None:
    chat_manager = getattr(workspace, "chat_manager", None)
    if chat_manager is None:
        return
    await chat_manager.patch_chat(
        chat_id,
        ChatUpdate(
            task_status="in_progress",
            meta={
                "expert_team_id": run.team_id,
                "expert_team_run_id": run.id,
            },
        ),
    )
