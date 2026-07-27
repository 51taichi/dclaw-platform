# -*- coding: utf-8 -*-
"""Tests for expert team template and run persistence."""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import expert_teams as expert_team_router
from qwenpaw.app import expert_teams
from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus
from qwenpaw.app.storage.repos import expert_team_repo
from qwenpaw.app.storage.repos.expert_team_repo import SqliteExpertTeamRepository


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _use_sqlite_repo(monkeypatch, conn: sqlite3.Connection) -> None:
    monkeypatch.setattr(
        expert_teams,
        "get_expert_team_repository",
        lambda: SqliteExpertTeamRepository(),
    )
    monkeypatch.setattr(expert_team_repo.db, "get_db", lambda: conn)


def test_builtin_templates_seed_and_user_list_hides_disabled(monkeypatch):
    conn = _make_db()
    _use_sqlite_repo(monkeypatch, conn)

    templates = expert_teams.list_expert_team_templates(enabled_only=True)

    assert {template.id for template in templates} >= {
        "ai_video_team",
        "software_dev_team",
        "deep_research_team",
    }
    ai_video = next(t for t in templates if t.id == "ai_video_team")
    assert ai_video.members[0].display_name == "视频生成团队主理人"
    assert ai_video.leader_agent_id == "content_creation"
    assert ai_video.workflow[0].members == ["lead"]

    software = next(t for t in templates if t.id == "software_dev_team")
    assert software.leader_agent_id == "fullstack_dev"
    assert {member.agent_id for member in software.members} == {
        "product_design",
        "fullstack_dev",
        "qa",
    }

    conn.execute(
        "UPDATE expert_team_templates SET enabled = 0 WHERE id = ?",
        ("ai_video_team",),
    )
    conn.commit()

    visible = expert_teams.list_expert_team_templates(enabled_only=True)

    assert "ai_video_team" not in {template.id for template in visible}


def test_create_run_initializes_members_and_usage(monkeypatch):
    conn = _make_db()
    _use_sqlite_repo(monkeypatch, conn)
    expert_teams.seed_builtin_expert_teams()

    run = expert_teams.create_expert_team_run(
        team_id="ai_video_team",
        root_chat_id="chat-1",
        root_session_id="session-1",
        user_id="7",
        input_text="做一个 60 秒视频",
    )

    assert run.team_id == "ai_video_team"
    assert run.state == "pending"
    assert [member.member_key for member in run.members] == [
        "lead",
        "researcher",
        "planner",
        "producer",
    ]
    assert {member.state for member in run.members} == {"pending"}
    assert run.members[0].stage_index == 0

    template = expert_teams.get_expert_team_template("ai_video_team")

    assert template is not None
    assert template.usage_count == 1


def test_member_state_updates_and_chat_lookup(monkeypatch):
    conn = _make_db()
    _use_sqlite_repo(monkeypatch, conn)
    expert_teams.seed_builtin_expert_teams()
    run = expert_teams.create_expert_team_run(
        team_id="deep_research_team",
        root_chat_id="chat-2",
        root_session_id="session-2",
        user_id="7",
        input_text="调研茶饮市场",
    )

    expert_teams.update_member_run_state(
        run.id,
        "collector",
        "running",
        input_text="调研茶饮市场",
    )
    expert_teams.update_expert_team_run_state(run.id, "running")

    latest = expert_teams.get_latest_expert_team_run_by_chat("chat-2")

    assert latest is not None
    assert latest.state == "running"
    collector = next(m for m in latest.members if m.member_key == "collector")
    assert collector.state == "running"
    assert collector.input_text == "调研茶饮市场"


@pytest.mark.asyncio
async def test_expert_team_run_state_publishes_runtime_events(monkeypatch):
    conn = _make_db()
    _use_sqlite_repo(monkeypatch, conn)
    bus = MemoryRuntimeEventBus(max_events=20, max_age_seconds=60)
    monkeypatch.setattr(expert_teams, "get_runtime_event_bus", lambda: bus, raising=False)
    expert_teams.seed_builtin_expert_teams()
    run = expert_teams.create_expert_team_run(
        team_id="deep_research_team",
        root_chat_id="chat-2",
        root_session_id="session-2",
        user_id="7",
        input_text="调研茶饮市场",
    )

    expert_teams.update_expert_team_run_state(run.id, "running")
    expert_teams.cancel_expert_team_run(run.id)
    await asyncio.sleep(0)

    events = await bus.replay(session_id="session-2", since_id=None)

    assert [event.type for event in events] == [
        "expert_team.run.updated",
        "expert_team.run.updated",
        "expert_team.run.updated",
    ]
    assert [event.status for event in events] == ["pending", "running", "cancelled"]
    assert {event.job_id for event in events} == {run.id}
    assert events[-1].payload["root_chat_id"] == "chat-2"


def test_user_run_guard_rejects_other_users(monkeypatch):
    conn = _make_db()
    _use_sqlite_repo(monkeypatch, conn)
    expert_teams.seed_builtin_expert_teams()
    run = expert_teams.create_expert_team_run(
        team_id="software_dev_team",
        root_chat_id="chat-3",
        root_session_id="session-3",
        user_id="7",
        input_text="做一个小工具",
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id=8))

    with pytest.raises(HTTPException) as exc:
        expert_team_router._ensure_user_run(run, request)

    assert exc.value.status_code == 404
