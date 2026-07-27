# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app.mobile.service import (
    derive_mobile_display_status,
    serialize_artifact_summary,
    serialize_pending_confirmation,
)


def test_running_status_wins_over_artifacts() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="running",
            task_status="completed",
            pending_confirmation_count=0,
            artifact_count=2,
        )
        == "running"
    )


def test_pending_confirmation_wins_over_idle() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="idle",
            task_status=None,
            pending_confirmation_count=1,
            artifact_count=0,
        )
        == "pending_confirmation"
    )


def test_completed_can_be_derived_from_artifacts() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="idle",
            task_status=None,
            pending_confirmation_count=0,
            artifact_count=1,
        )
        == "completed"
    )


def test_completed_can_be_derived_from_assistant_response() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="idle",
            task_status="pending",
            pending_confirmation_count=0,
            artifact_count=0,
            has_assistant_response=True,
        )
        == "completed"
    )


def test_artifact_serialization_classifies_generated_images() -> None:
    payload = serialize_artifact_summary(
        SimpleNamespace(
            filename="海报结果.png",
            path="outputs/海报结果.png",
            size=1024,
            modified_time="2026-07-07T12:00:00+00:00",
        ),
    )

    assert payload.kind == "image"
    assert payload.name == "海报结果.png"
    assert payload.path == "outputs/海报结果.png"


def test_failed_task_status_is_preserved() -> None:
    assert (
        derive_mobile_display_status(
            runtime_status="idle",
            task_status="failed",
            pending_confirmation_count=0,
            artifact_count=0,
        )
        == "failed"
    )


def test_approval_serialization_preserves_tool_guard_fields() -> None:
    approval = SimpleNamespace(
        request_id="req-1",
        session_id="child-session",
        root_session_id="root-session",
        owner_agent_id="default",
        agent_id="default",
        tool_name="workspace.export",
        severity="MEDIUM",
        findings_count=2,
        result_summary="包含业务数据，需本人确认",
        created_at=1718600000.0,
        timeout_seconds=300,
        extra={
            "tool_call": {
                "input": {
                    "file": "sales_analysis.xlsx",
                    "scope": "全部数据",
                },
            },
        },
    )

    payload = serialize_pending_confirmation(approval)

    assert payload.request_id == "req-1"
    assert payload.root_session_id == "root-session"
    assert payload.tool_name == "workspace.export"
    assert payload.severity == "MEDIUM"
    assert payload.findings_summary == "包含业务数据，需本人确认"
    assert payload.tool_params == {
        "file": "sales_analysis.xlsx",
        "scope": "全部数据",
    }
