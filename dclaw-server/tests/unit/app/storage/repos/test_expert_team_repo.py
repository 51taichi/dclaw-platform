# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.expert_team_repo import SqlAlchemyExpertTeamRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return engine


@pytest.fixture
def repo(engine):
    return SqlAlchemyExpertTeamRepository(engine)


def _template_row(team_id: str = "team-1", *, enabled: bool = True) -> dict[str, object]:
    return {
        "id": team_id,
        "name": "视频团队",
        "description": "负责视频任务",
        "category": "content",
        "tags": json.dumps(["video"], ensure_ascii=False),
        "icon": "video",
        "enabled": enabled,
        "leader_agent_id": "leader",
        "members": json.dumps(
            [
                {
                    "key": "lead",
                    "agent_id": "leader",
                    "display_name": "负责人",
                    "role": "统筹",
                    "avatar": "",
                },
                {
                    "key": "producer",
                    "agent_id": "producer",
                    "display_name": "制作人",
                    "role": "制作",
                    "avatar": "",
                },
            ],
            ensure_ascii=False,
        ),
        "workflow": json.dumps(
            [{"key": "delivery", "name": "交付", "members": ["lead", "producer"]}],
            ensure_ascii=False,
        ),
        "usage_count": 0,
        "source": "builtin",
        "sort_order": 10,
    }


def test_sqlalchemy_expert_team_repo_preserves_disabled_builtin_when_reseeded(repo):
    repo.seed_builtin_templates([_template_row(enabled=True)])
    repo.upsert_template_row({**_template_row(), "enabled": False})

    repo.seed_builtin_templates([{**_template_row(), "name": "更新后的视频团队"}])

    assert repo.get_template_row("team-1")["enabled"] is False
    assert repo.get_template_row("team-1")["name"] == "更新后的视频团队"
    assert repo.list_template_rows(enabled_only=True) == []


def test_sqlalchemy_expert_team_repo_upserts_lists_and_deletes_templates(repo):
    repo.seed_builtin_templates([_template_row("team-2")])

    repo.upsert_template_row(
        {
            **_template_row("team-2"),
            "name": "自定义团队",
            "enabled": True,
            "source": "custom",
            "sort_order": 1,
        },
    )

    rows = repo.list_template_rows(enabled_only=True)

    assert [row["id"] for row in rows] == ["team-2"]
    assert rows[0]["name"] == "自定义团队"
    assert rows[0]["source"] == "custom"
    assert repo.delete_template("team-2") is True
    assert repo.delete_template("team-2") is False


def test_sqlalchemy_expert_team_repo_tracks_run_and_member_lifecycle(repo):
    repo.seed_builtin_templates([_template_row()])
    repo.create_run(
        team_id="team-1",
        run_row={
            "id": "run-1",
            "team_id": "team-1",
            "root_chat_id": "chat-1",
            "root_session_id": "session-1",
            "user_id": "7",
            "state": "pending",
            "input_text": "做一个短视频",
        },
        member_rows=[
            {
                "id": "member-1",
                "run_id": "run-1",
                "member_key": "lead",
                "agent_id": "leader",
                "display_name": "负责人",
                "role": "统筹",
                "state": "pending",
                "stage_index": 0,
            },
            {
                "id": "member-2",
                "run_id": "run-1",
                "member_key": "producer",
                "agent_id": "producer",
                "display_name": "制作人",
                "role": "制作",
                "state": "pending",
                "stage_index": 1,
            },
        ],
    )

    assert repo.get_latest_run_id_by_chat("chat-1") == "run-1"
    assert repo.get_template_row("team-1")["usage_count"] == 1

    repo.update_run_state("run-1", "running")
    repo.update_member_run_state(
        "run-1",
        "lead",
        "running",
        input_text="做一个短视频",
        task_id="task-1",
    )
    repo.update_member_run_state("run-1", "lead", "completed", output_text="已完成")
    repo.cancel_open_member_runs("run-1")

    run = repo.get_run_row("run-1")
    members = {row["member_key"]: row for row in repo.list_member_run_rows("run-1")}

    assert run["state"] == "running"
    assert members["lead"]["state"] == "completed"
    assert members["lead"]["input_text"] == "做一个短视频"
    assert members["lead"]["task_id"] == "task-1"
    assert members["producer"]["state"] == "cancelled"

    repo.update_run_state("run-1", "failed", error="boom")

    failed = repo.get_run_row("run-1")
    assert failed["state"] == "failed"
    assert failed["error"] == "boom"
    assert failed["finished_at"] is not None


def test_expert_team_pause_and_resume_is_owner_scoped_cas(repo):
    repo.seed_builtin_templates([_template_row()])
    repo.create_run(
        team_id="team-1",
        run_row={
            "id": "run-paused",
            "team_id": "team-1",
            "root_chat_id": "chat-paused",
            "root_session_id": "session-paused",
            "user_id": "7",
            "state": "running",
            "input_text": "继续完成",
            "billing_usage_order_id": "order-1",
        },
        member_rows=[],
    )

    assert repo.pause_for_insufficient_balance(
        "run-paused",
        user_id="7",
        next_member_key="producer",
        required_credits=9,
        billing_usage_order_id="order-1",
    )
    paused = repo.get_run_row("run-paused")
    assert paused["state"] == "paused_insufficient_balance"
    assert paused["next_member_key"] == "producer"
    assert paused["required_credits"] == 9
    assert paused["billing_usage_order_id"] == "order-1"

    assert repo.resume_paused_run("run-paused", user_id="8") is False
    assert repo.resume_paused_run("run-paused", user_id="7") is True
    assert repo.resume_paused_run("run-paused", user_id="7") is False
    resumed = repo.get_run_row("run-paused")
    assert resumed["state"] == "running"
    assert resumed["next_member_key"] == "producer"
