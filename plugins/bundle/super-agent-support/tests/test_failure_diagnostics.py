from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from jsonschema import validate
from qwenpaw.app.sealed_agents.package import SealedPackageManifest

from super_agent.failure_diagnostics import (
    FailureDiagnosticsUnauthorized,
    FailureDiagnosticsUnavailable,
    read_latest_failure,
    read_owner_failures,
    read_invocation_failure,
    read_developer_failure_by_reference,
    read_developer_failure_by_reference_v2,
    read_developer_failure_by_reference_v3,
    read_developer_invocation_by_reference_v4,
    read_developer_invocation_by_reference_v5,
    search_developer_failures,
    classify_interaction_failure,
)
from super_agent.interaction_cards import InteractionError
from super_agent.interaction_contract import InteractionCreateRequest, InteractionValidationError
from pydantic import ValidationError
from super_agent.capabilities import compute_capability_set_digest, validate_super_expert_manifest
from super_agent.orchestration import WorkspaceOrchestrationError, WorkspaceRuntimeHost
from super_agent.publication import PublisherPublication
from super_agent.router import _memory_message_ids
from super_agent.trust import SuperExpertTrustStore
from devkit import runtime_diagnostics_api_demo
from store import StateStore


NOW = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
SCHEMAS = Path(__file__).parents[1] / "devkit" / "schemas" / "runtime-failure-v1"


def _grant(installation: str, release: str, agent: str = "comic", tenant: str = "local"):
    return SimpleNamespace(
        installation_id=installation, release_id=release,
        agent_id=agent, tenant_id=tenant,
    )


def _grants():
    items = [
        _grant("old", "0.2.3"), _grant("new", "0.2.4"),
        _grant("other-tenant", "1.0", tenant="elsewhere"),
        _grant("other-agent", "1.0", agent="another"),
    ]
    return SimpleNamespace(
        get=lambda installation: next((x for x in items if x.installation_id == installation), None),
        list_grants=lambda: items,
    )


def _trace(root: Path, installation: str, session: str, rows: list[dict]) -> Path:
    scope = lambda value: hashlib.sha256(value.encode()).hexdigest()
    path = root / "traces" / scope(installation) / f"{scope(session)}.ndjson"
    path.parent.mkdir(parents=True)
    path.write_text("".join(json.dumps({
        "installation_id": installation, "session_id": session, **row,
    }) + "\n" for row in rows), encoding="utf-8")
    return path


def _failure(invocation: str, when: datetime, *, text: str = "private model text") -> list[dict]:
    timestamp = lambda offset: (when + timedelta(seconds=offset)).isoformat()
    return [
        {"timestamp": timestamp(0), "invocation_id": invocation,
         "event_type": "orchestration.started", "payload": {}},
        {"timestamp": timestamp(1), "invocation_id": invocation,
         "event_type": "runtime.trace", "payload": {"payload": {
             "event": "agent.turn.failure", "phase": "model_validation",
             "category": "model_response_shape", "attempt": 1,
             "model_text": text,
         }}},
        {"timestamp": timestamp(2), "invocation_id": invocation,
         "event_type": "orchestration.failed", "payload": {
             "error_code": "INVALID_TURN_RESULT", "diagnostic_ref": text,
         }},
    ]


def _args(root: Path, grants=None, owner=None):
    return {
        "storage_root": root,
        "grants": grants or _grants(),
        "installation_id": "new",
        "release_id": "0.2.4",
        "agent_id": "comic",
        "user_id": "57",
        "session_id": "task",
        "owner_resolver": owner or (lambda _: {
            "user_id": "57", "agent_id": "comic", "tenant_id": "local",
        }),
        "now": NOW,
    }


def test_v4_reads_committed_business_block_without_exposing_payload(tmp_path):
    invocation = "e" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": when.isoformat(), "invocation_id": invocation,
         "event_type": "orchestration.started", "payload": {}},
        {"timestamp": (when + timedelta(seconds=1)).isoformat(),
         "invocation_id": invocation, "event_type": "interaction.operation.completed",
         "payload": {"capability": "interaction.card.read/1"}},
        {"timestamp": (when + timedelta(seconds=2)).isoformat(),
         "invocation_id": invocation, "event_type": "host.operation.started",
         "payload": {"capability": "aigc.task.assets.localize/1", "secret": "private"}},
        {"timestamp": (when + timedelta(seconds=3)).isoformat(),
         "invocation_id": invocation, "event_type": "host.operation.completed",
         "payload": {"capability": "aigc.task.assets.localize/1",
                     "status": "rejected", "error_code": "LOCAL_GATEWAY.DEVICE_NOT_READY",
                     "task_accepted": False, "duration_ms": 15,
                     "secret": "private"}},
        {"timestamp": (when + timedelta(seconds=4)).isoformat(),
         "invocation_id": invocation, "event_type": "runtime.trace",
         "payload": {"origin": "agent", "payload": {
             "event": "agent.turn.failure", "phase": "aigc_asset_localize",
             "category": "host_or_input", "attempt": 0,
             "secret": "private"}}},
        {"timestamp": (when + timedelta(seconds=5)).isoformat(),
         "invocation_id": invocation, "event_type": "runtime.trace",
         "payload": {"origin": "host", "payload": {"event": "runtime.complete.accepted"}}},
        {"timestamp": (when + timedelta(seconds=6)).isoformat(),
         "invocation_id": invocation, "event_type": "runtime.trace",
         "payload": {"origin": "host", "payload": {"event": "transaction.committed"}}},
        {"timestamp": (when + timedelta(seconds=7)).isoformat(),
         "invocation_id": invocation, "event_type": "orchestration.completed", "payload": {}},
    ])
    result = read_developer_invocation_by_reference_v4(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic", "tenant_id": "local"},
        now=NOW,
    )
    assert result["runtime_outcome"] == "completed"
    assert result["transaction_status"] == "committed"
    assert result["task_acceptance"] == "not_accepted"
    assert result["task_evidence"] == "not_recorded"
    assert result["first_failure"] == {"phase": "aigc_asset_localize", "category": "host_or_input", "attempt": 0}
    assert result["host_operations"][1]["error_code"] == "LOCAL_GATEWAY.DEVICE_NOT_READY"
    assert "private" not in json.dumps(result)
    validate(result, json.loads((SCHEMAS.parent / "runtime-diagnostics-v4" / "by-reference-response.schema.json").read_text()))
    blocker = read_developer_invocation_by_reference_v5(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic", "tenant_id": "local"},
        now=NOW,
    )["blocker"]
    assert blocker["responsibility"] == "environment"
    assert blocker["recovery_action"] == "reconnect_helper"


def test_v4_history_without_host_trace_reports_unknown_acceptance(tmp_path):
    invocation = "f" * 32
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": (NOW - timedelta(minutes=1, seconds=1)).isoformat(), "invocation_id": invocation,
         "event_type": "runtime.trace", "payload": {"origin": "agent", "payload": {
             "event": "transaction.committed",
         }}},
        {"timestamp": (NOW - timedelta(minutes=1)).isoformat(), "invocation_id": invocation,
         "event_type": "orchestration.completed", "payload": {}},
    ])
    result = read_developer_invocation_by_reference_v4(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic", "tenant_id": "local"},
        now=NOW,
    )
    assert result["status"] == "found"
    assert result["task_acceptance"] == "not_recorded"
    assert result["transaction_status"] == "not_recorded"
    assert result["task_evidence"] == "not_recorded"


def test_v5_exposes_only_recorded_host_blocker(tmp_path):
    invocation = "b" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": when.isoformat(), "invocation_id": invocation,
         "event_type": "orchestration.started", "payload": {}},
        {"timestamp": (when + timedelta(seconds=1)).isoformat(),
         "invocation_id": invocation, "event_type": "host.operation.failed",
         "payload": {"capability": "aigc.task.assets.localize/1",
                     "category": "host_rejected", "host_stage": "asset_validation",
                     "error_code": "INVALID_ASSET_SELECTION", "field_path": "assets",
                     "constraint": "SELECTION_INVALID", "responsibility": "developer",
                     "recovery_action": "correct_request", "secret": "private asset"}},
        {"timestamp": (when + timedelta(seconds=2)).isoformat(),
         "invocation_id": invocation, "event_type": "orchestration.completed",
         "payload": {}},
    ])
    kwargs = dict(storage_root=tmp_path, grants=_grants(), agent_id="comic",
                  tenant_id="local", invocation_id=invocation,
                  owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic",
                                            "tenant_id": "local"},
                  task_lookup=lambda **_: [], now=NOW)
    result = read_developer_invocation_by_reference_v5(**kwargs)
    assert result["blocker"] == {
        "phase": "asset_validation", "error_code": "INVALID_ASSET_SELECTION",
        "field_path": "assets", "constraint": "SELECTION_INVALID",
        "responsibility": "developer", "recovery_action": "correct_request",
        "evidence": "recorded",
    }
    assert result["first_failure_source"] == "host_stage"
    assert result["task_acceptance"] == "not_accepted"
    assert "private asset" not in json.dumps(result)
    validate(result, json.loads((SCHEMAS.parent / "runtime-diagnostics-v5"
                                 / "by-reference-response.schema.json").read_text()))
    with pytest.raises(FailureDiagnosticsUnauthorized):
        read_developer_invocation_by_reference_v5(
            **{**kwargs, "owner_resolver": lambda _: {"user_id": "customer",
                "agent_id": "comic", "tenant_id": "elsewhere"}})


def test_v5_historical_host_exception_keeps_root_unknown(tmp_path):
    invocation = "c" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": when.isoformat(), "invocation_id": invocation,
         "event_type": "host.operation.failed", "payload": {
             "capability": "aigc.task.assets.localize/1",
             "category": "host_exception", "error_code": None}},
        {"timestamp": (when + timedelta(seconds=1)).isoformat(),
         "invocation_id": invocation, "event_type": "orchestration.completed", "payload": {}},
    ])
    result = read_developer_invocation_by_reference_v5(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic",
                                  "tenant_id": "local"},
        task_lookup=lambda **_: [], now=NOW,
    )
    assert result["blocker"]["evidence"] == "historical_detail_not_recorded"
    assert result["blocker"]["error_code"] is None
    assert result["blocker"]["responsibility"] == "undetermined"
    validate(result, json.loads((SCHEMAS.parent / "runtime-diagnostics-v5"
                                 / "by-reference-response.schema.json").read_text()))
    no_record = read_developer_invocation_by_reference_v5(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id="d" * 32,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic",
                                  "tenant_id": "local"},
        task_lookup=lambda **_: [], now=NOW,
    )
    assert no_record == {"contract": "developer.runtime.diagnostics.by-reference/5",
                         "status": "no_record", "retention_days": 30}
    validate(no_record, json.loads((SCHEMAS.parent / "runtime-diagnostics-v5"
                                    / "by-reference-response.schema.json").read_text()))


def test_v5_maps_recorded_runtime_isolation_failure_to_platform(tmp_path):
    invocation = "9" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": when.isoformat(), "invocation_id": invocation,
         "event_type": "orchestration.started", "payload": {}},
        {"timestamp": (when + timedelta(milliseconds=17)).isoformat(),
         "invocation_id": invocation, "event_type": "runtime.trace",
         "payload": {"origin": "host", "payload": {
             "event": "transaction.discarded",
         }}},
        {"timestamp": (when + timedelta(milliseconds=18)).isoformat(),
         "invocation_id": invocation, "event_type": "orchestration.failed",
         "payload": {
             "error_code": "orchestration_error",
             "diagnostic_ref": "runtime_isolation_unavailable",
         }},
    ])
    result = read_developer_invocation_by_reference_v5(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic",
                                  "tenant_id": "local"},
        task_lookup=lambda **_: [], now=NOW,
    )
    assert result["first_failure"] == {
        "phase": "runtime_isolation",
        "category": "platform_runtime_unavailable",
        "attempt": None,
    }
    assert result["first_failure_source"] == "host_stage"
    assert result["blocker"] == {
        "phase": "runtime_isolation",
        "error_code": "RUNTIME_ISOLATION_UNAVAILABLE",
        "field_path": "not_recorded",
        "constraint": "SANDBOX_RUNTIME_UNAVAILABLE",
        "responsibility": "platform",
        "recovery_action": "retry_after_platform_recovery",
        "evidence": "recorded",
    }
    validate(result, json.loads((SCHEMAS.parent / "runtime-diagnostics-v5"
                                 / "by-reference-response.schema.json").read_text()))


def test_v5_does_not_expose_unknown_orchestration_diagnostic(tmp_path):
    invocation = "8" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [{
        "timestamp": when.isoformat(), "invocation_id": invocation,
        "event_type": "orchestration.failed", "payload": {
            "error_code": "orchestration_error",
            "diagnostic_ref": "private_internal_detail",
        },
    }])
    result = read_developer_invocation_by_reference_v5(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic",
                                  "tenant_id": "local"},
        task_lookup=lambda **_: [], now=NOW,
    )
    assert result["first_failure_source"] == "not_recorded"
    assert result["blocker"]["evidence"] == "historical_detail_not_recorded"
    assert "private_internal_detail" not in json.dumps(result)


def test_v4_reads_scoped_live_task_terminal_state(tmp_path):
    invocation = "e" * 32
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": (NOW - timedelta(minutes=1)).isoformat(), "invocation_id": invocation,
         "event_type": "orchestration.completed", "payload": {}},
    ])
    seen = []

    def lookup(**scope):
        seen.append(scope)
        return [{"task_id_sha256": "a" * 64,
                 "capability": "aigc.task.assets.localize/1", "status": "failed",
                 "error_code": "DEVICE_NOT_READY", "result_sha256": None,
                 "secret": "private"}]

    result = read_developer_invocation_by_reference_v4(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic", "tenant_id": "local"},
        task_lookup=lookup, now=NOW,
    )
    assert seen == [{"tenant_id": "local", "user_id": "customer", "agent_id": "comic",
                     "session_id": "customer-task", "installation_id": "old",
                     "invocation_id": invocation}]
    assert result["task_acceptance"] == "accepted"
    assert result["tasks"][0]["status"] == "failed"
    assert "private" not in json.dumps(result)
    validate(result, json.loads((SCHEMAS.parent / "runtime-diagnostics-v4" / "by-reference-response.schema.json").read_text()))


def test_invocation_task_evidence_is_scoped_and_redacted(tmp_path):
    store = StateStore(tmp_path / "tasks.sqlite3")
    task, _ = store.create_task(
        user_id="customer", agent_id="comic", agent_name="comic",
        invocation_id="e" * 32, capability_id="aigc.task.assets.localize/1",
        task_input={"secret": "private input"}, idempotency_key="key",
        device_id="device", max_concurrency=4, tenant_id="local",
        session_id="customer-task", installation_id="old", release_id="release",
    )
    store.update_task(task["task_id"], status="failed",
                      error={"code": "DEVICE_NOT_READY", "message": "private error"})
    scope = dict(tenant_id="local", user_id="customer", agent_id="comic",
                 session_id="customer-task", installation_id="old", invocation_id="e" * 32)
    found = store.invocation_task_summaries(**scope)
    assert len(found) == 1
    assert found[0]["error_code"] == "DEVICE_NOT_READY"
    assert "private" not in json.dumps(found)
    for field in ("tenant_id", "user_id", "agent_id", "session_id", "installation_id", "invocation_id"):
        assert store.invocation_task_summaries(**{**scope, field: "foreign"}) == []


def test_v4_rejects_foreign_task_and_tenant(tmp_path):
    invocation = "a" * 32
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": (NOW - timedelta(minutes=1)).isoformat(), "invocation_id": invocation,
         "event_type": "orchestration.completed", "payload": {}},
    ])
    params = dict(storage_root=tmp_path, grants=_grants(), agent_id="comic",
                  tenant_id="local", invocation_id=invocation, now=NOW)
    with pytest.raises(FailureDiagnosticsUnauthorized):
        read_developer_invocation_by_reference_v4(
            **params, owner_resolver=lambda _: {"agent_id": "comic", "tenant_id": "elsewhere"},
        )
    assert read_developer_invocation_by_reference_v4(
        **{**params, "tenant_id": "elsewhere"},
        owner_resolver=lambda _: {"agent_id": "comic", "tenant_id": "local"},
    )["status"] == "no_record"


def test_reads_latest_cross_installation_failure_without_raw_payload(tmp_path):
    _trace(tmp_path, "old", "task", _failure("old-failure", NOW - timedelta(minutes=5)))
    _trace(tmp_path, "new", "task", _failure("new-failure", NOW - timedelta(minutes=2)))
    _trace(tmp_path, "other-tenant", "task", _failure("foreign", NOW - timedelta(minutes=1)))
    result = read_latest_failure(**_args(tmp_path))

    assert result["status"] == "found"
    assert result["invocation_id"] == "new-failure"
    assert result["release_id"] == "0.2.4"
    assert result["transaction_status"] == "discarded"
    assert result["first_failure"] == {
        "phase": "model_validation", "category": "model_response_shape", "attempt": 1,
    }
    assert result["first_failure_source"] == "agent_trace"
    assert result["error_code"] == "INVALID_TURN_RESULT"
    validate(result, json.loads((SCHEMAS / "response.schema.json").read_text()))
    assert "private model text" not in json.dumps(result)
    assert read_latest_failure(**_args(tmp_path), exclude_invocation_id="new-failure")["invocation_id"] == "old-failure"


def test_stage_projection_omits_candidate_and_preserves_first_failure(tmp_path):
    rows = _failure("one", NOW - timedelta(minutes=1))
    rows.insert(1, {
        "timestamp": (NOW - timedelta(minutes=1) + timedelta(milliseconds=100)).isoformat(),
        "invocation_id": "one", "event_type": "agent.execute.safe_started",
        "payload": {"call_number": 1, "execution_mode": "candidate", "response_format": "json_object"},
    })
    rows.insert(2, {
        "timestamp": (NOW - timedelta(minutes=1) + timedelta(milliseconds=900)).isoformat(),
        "invocation_id": "one", "event_type": "agent.execute.safe_completed",
        "payload": {"call_number": 1, "duration_ms": 800, "has_text": True,
                    "text_length": 4200, "complete_json_object": False,
                    "text": "private model text"},
    })
    rows.insert(3, {
        "timestamp": (NOW - timedelta(minutes=1) + timedelta(milliseconds=950)).isoformat(),
        "invocation_id": "one", "event_type": "runtime.trace",
        "payload": {"origin": "agent", "payload": {
            "event": "transaction.committed", "model_text": "private model text",
        }},
    })
    _trace(tmp_path, "new", "task", rows)
    result = read_owner_failures(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        user_id="57", session_id="task", owner_resolver=_args(tmp_path)["owner_resolver"],
        now=NOW,
    )
    failure = result["failures"][0]
    assert failure["first_failure"]["category"] == "model_response_shape"
    assert failure["stages"][0]["source"] == "host"
    assert failure["stages"][2]["source"] == "host"
    assert failure["stages"][2]["complete_json_object"] is False
    assert failure["stages"][3]["event"] == "transaction.committed"
    assert failure["stages"][3]["source"] == "agent"
    assert "private model text" not in json.dumps(result)
    schema = json.loads((
        Path(__file__).parents[1] / "devkit" / "schemas"
        / "runtime-diagnostics-v1" / "response.schema.json"
    ).read_text())
    validate(result | {"history_readback": {"messages_table_count": 0, "agent_memory_count": 0}}, schema)
    assert read_invocation_failure(
        storage_root=tmp_path, installation_id="new", session_id="task",
        invocation_id="one",
    )["first_failure"]["phase"] == "model_validation"


def test_host_candidate_exception_is_labeled_as_host_stage(tmp_path):
    rows = _failure("one", NOW - timedelta(minutes=1))
    rows = [row for row in rows if row["event_type"] != "runtime.trace"]
    rows.insert(1, {
        "timestamp": (NOW - timedelta(minutes=1) + timedelta(seconds=1)).isoformat(),
        "invocation_id": "one", "event_type": "agent.execute.safe_failed",
        "payload": {"call_number": 2, "duration_ms": 800,
                    "category": "TimeoutError"},
    })
    _trace(tmp_path, "new", "task", rows)
    result = read_latest_failure(**_args(tmp_path))
    assert result["first_failure"] == {
        "phase": "agent_execute", "category": "TimeoutError", "attempt": 2,
    }
    assert result["first_failure_source"] == "host_stage"
    validate(result, json.loads((SCHEMAS / "response.schema.json").read_text()))


def test_no_record_and_retention_window(tmp_path):
    result = read_latest_failure(**_args(tmp_path))
    assert result == {
        "contract": "runtime.failure.read/1", "status": "no_record",
        "reason": "no_failure_in_retention_window",
    }
    validate(result, json.loads((SCHEMAS / "response.schema.json").read_text()))
    _trace(tmp_path, "old", "task", _failure("expired", NOW - timedelta(days=31)))
    assert read_latest_failure(**_args(tmp_path))["status"] == "no_record"


def test_preflight_failure_is_readable_without_runtime_invocation(tmp_path):
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "new", "task", [{
        "timestamp": when.isoformat(),
        "invocation_id": "preflight-one",
        "event_type": "orchestration.preflight_failed",
        "payload": {
            "started_at": (when - timedelta(seconds=1)).isoformat(),
            "phase": "release_authorization",
            "category": "release_digest_mismatch",
            "error_code": "orchestration_error",
        },
    }, {
        "timestamp": (when + timedelta(milliseconds=1)).isoformat(),
        "invocation_id": "preflight-one",
        "event_type": "orchestration.message_staged",
        "payload": {"assistant_message_id": "reply-one"},
    }])
    result = read_latest_failure(**_args(tmp_path))
    assert result["first_failure_source"] == "platform_preflight"
    assert result["first_failure"] == {
        "phase": "release_authorization",
        "category": "release_digest_mismatch",
        "attempt": None,
    }
    validate(result, json.loads((SCHEMAS / "response.schema.json").read_text()))
    history = read_owner_failures(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        user_id="57", session_id="task", owner_resolver=_args(tmp_path)["owner_resolver"],
        now=NOW, persisted_message_ids={"reply-one"},
    )
    assert history["status"] == "found"
    assert history["failures"][0]["invocation_id"] == "preflight-one"
    assert history["failures"][0]["message_status"] == "persisted"
    missing = read_owner_failures(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        user_id="57", session_id="task", owner_resolver=_args(tmp_path)["owner_resolver"],
        now=NOW, persisted_message_ids=set(),
    )
    assert missing["failures"][0]["message_status"] == "missing"
    history["history_readback"] = {
        "messages_table_count": 0, "agent_memory_count": 60,
    }
    developer_schema = SCHEMAS.parent / "runtime-diagnostics-v1" / "response.schema.json"
    validate(history, json.loads(developer_schema.read_text()))


def test_developer_history_rejects_other_owner(tmp_path):
    with pytest.raises(FailureDiagnosticsUnauthorized):
        read_owner_failures(
            storage_root=tmp_path, grants=_grants(), agent_id="comic",
            user_id="58", session_id="task", owner_resolver=_args(tmp_path)["owner_resolver"],
            now=NOW,
        )


def test_developer_can_resolve_customer_reference_only_within_owned_expert(tmp_path):
    invocation = "a" * 32
    _trace(tmp_path, "old", "customer-task", _failure(invocation, NOW - timedelta(minutes=1)))
    owner = lambda session: {
        "user_id": "customer", "agent_id": "comic", "tenant_id": "local",
    } if session == "customer-task" else None
    result = read_developer_failure_by_reference(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=owner, now=NOW,
    )
    assert result["status"] == "found"
    assert result["task_id"] == "customer-task"
    assert result["release_id"] == "0.2.3"
    assert result["first_failure"]["category"] == "model_response_shape"
    assert "private model text" not in json.dumps(result)
    validate(result, json.loads((
        SCHEMAS.parent / "runtime-diagnostics-v1" / "by-reference-response.schema.json"
    ).read_text()))
    assert read_developer_failure_by_reference(
        storage_root=tmp_path, grants=_grants(), agent_id="another",
        tenant_id="local", invocation_id=invocation,
        owner_resolver=owner, now=NOW,
    )["status"] == "no_record"
    with pytest.raises(FailureDiagnosticsUnauthorized):
        read_developer_failure_by_reference(
            storage_root=tmp_path, grants=_grants(), agent_id="comic",
            tenant_id="local", invocation_id=invocation,
            owner_resolver=lambda _: {**owner("customer-task"), "tenant_id": "elsewhere"},
            now=NOW,
        )


def test_reference_v2_identifies_terminal_host_failure_after_recovered_json_error(tmp_path):
    invocation = "b" * 32
    when = NOW - timedelta(minutes=1)
    rows = _failure(invocation, when)
    rows.insert(2, {
        "timestamp": (when + timedelta(milliseconds=1500)).isoformat(),
        "invocation_id": invocation, "event_type": "agent.execute.safe_completed",
        "payload": {"call_number": 3, "duration_ms": 500},
    })
    rows.insert(3, {
        "timestamp": (when + timedelta(milliseconds=1700)).isoformat(),
        "invocation_id": invocation, "event_type": "agent.execute.safe_failed",
        "payload": {"call_number": 4, "duration_ms": 1000, "category": "BadRequestError",
                    "status_code": 400, "provider_code": "invalid_request_error",
                    "provider_param": "response_format", "error": "private model text"},
    })
    rows.insert(4, {
        "timestamp": (when + timedelta(milliseconds=1800)).isoformat(),
        "invocation_id": invocation, "event_type": "runtime.trace",
        "payload": {"origin": "agent", "payload": {
            "event": "agent.turn.failure", "phase": "card_receipt_read",
            "category": "host_or_input", "attempt": 0,
        }},
    })
    _trace(tmp_path, "old", "customer-task", rows)
    owner = lambda _: {"user_id": "customer", "agent_id": "comic", "tenant_id": "local"}
    result = read_developer_failure_by_reference_v2(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation, owner_resolver=owner, now=NOW,
    )
    assert result["first_failure"]["category"] == "model_response_shape"
    assert [event["outcome"] for event in result["failure_events"]] == [
        "recovered", "terminal", "not_recorded",
    ]
    assert result["final_blocker"] == {
        "status": "recorded", "phase": "agent_execute", "category": "BadRequestError",
        "attempt": 4, "responsibility": "model_provider",
        "reason": "provider_rejected_request",
    }
    assert result["failure_events"][1]["provider_param"] == "response_format"
    assert "private model text" not in json.dumps(result)
    validate(result, json.loads((
        SCHEMAS.parent / "runtime-diagnostics-v2" / "by-reference-response.schema.json"
    ).read_text()))
    assert read_developer_failure_by_reference_v2(
        storage_root=tmp_path, grants=_grants(), agent_id="another",
        tenant_id="local", invocation_id=invocation, owner_resolver=owner, now=NOW,
    )["status"] == "no_record"


def test_v3_reports_safe_host_rejection_without_changing_v2(tmp_path):
    invocation = "e" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": when.isoformat(), "invocation_id": invocation,
         "event_type": "orchestration.started", "payload": {}},
        {"timestamp": (when + timedelta(seconds=1)).isoformat(),
         "invocation_id": invocation, "event_type": "interaction.operation.failed",
         "payload": {"capability": "interaction.card.create/1", "category": "InteractionError",
                     "error_code": "IDEMPOTENCY_CONFLICT", "field_path": "task_key",
                     "constraint": "IDEMPOTENCY_CONFLICT",
                     "recovery_action": "correct_request_or_resolve_conflict",
                     "contract": "interaction.card.create/1", "request_body": "private"}},
        {"timestamp": (when + timedelta(seconds=2)).isoformat(),
         "invocation_id": invocation, "event_type": "orchestration.failed",
         "payload": {"error_code": "INVALID_TURN_RESULT"}},
    ])
    kwargs = dict(storage_root=tmp_path, grants=_grants(), agent_id="comic",
                  tenant_id="local", invocation_id=invocation,
                  owner_resolver=lambda _: {"tenant_id": "local", "agent_id": "comic"}, now=NOW)
    v2 = read_developer_failure_by_reference_v2(**kwargs)
    validate(v2, json.loads((
        SCHEMAS.parent / "runtime-diagnostics-v2" / "by-reference-response.schema.json"
    ).read_text()))
    assert "error_code" not in v2["failure_events"][0]
    v3 = read_developer_failure_by_reference_v3(**kwargs)
    assert v3["host_failure_detail"] == {
        "status": "recorded", "error_code": "IDEMPOTENCY_CONFLICT",
        "field_path": "task_key", "constraint": "IDEMPOTENCY_CONFLICT",
        "recovery_action": "correct_request_or_resolve_conflict",
        "contract": "interaction.card.create/1",
    }
    assert "private" not in json.dumps(v3)
    validate(v3, json.loads((
        SCHEMAS.parent / "runtime-diagnostics-v3" / "by-reference-response.schema.json"
    ).read_text()))


def test_v3_historic_host_failure_does_not_invent_details(tmp_path):
    invocation = "f" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": when.isoformat(), "invocation_id": invocation,
         "event_type": "interaction.operation.failed",
         "payload": {"capability": "interaction.card.create/1", "category": "InteractionError"}},
        {"timestamp": (when + timedelta(seconds=1)).isoformat(),
         "invocation_id": invocation, "event_type": "orchestration.failed",
         "payload": {"error_code": "INVALID_TURN_RESULT"}},
    ])
    result = read_developer_failure_by_reference_v3(
        storage_root=tmp_path, grants=_grants(), agent_id="comic", tenant_id="local",
        invocation_id=invocation,
        owner_resolver=lambda _: {"tenant_id": "local", "agent_id": "comic"}, now=NOW,
    )
    assert result["host_failure_detail"]["status"] == "not_recorded"
    assert result["host_failure_detail"]["error_code"] is None


def test_interaction_failure_classifier_never_serializes_untrusted_values():
    rejection = InteractionError("IDEMPOTENCY_CONFLICT", field="task_key", retryable=False)
    assert classify_interaction_failure(rejection, "interaction.card.create/1")["error_code"] == "IDEMPOTENCY_CONFLICT"
    assert classify_interaction_failure(rejection, "interaction.card.create/1")["recovery_action"] == "correct_request_or_resolve_conflict"
    assert classify_interaction_failure(
        InteractionError("INVALID_INTERACTION_REQUEST"), "interaction.card.create/1",
    )["recovery_action"] == "correct_request"
    assert classify_interaction_failure(
        InteractionError("INVALID_SELECTION", field="answers.PRIVATE_SECRET"),
        "interaction.card.create/1",
    )["field_path"] == "not_recorded"
    private = "customer private material"
    assert private not in json.dumps(classify_interaction_failure(RuntimeError(private), "interaction.card.create/1"))
    validation = InteractionValidationError("INVALID_CARD", [{"field": "card.options[0].text", "code": "FIELD_REQUIRED"}])
    assert classify_interaction_failure(validation, "interaction.card.create/1")["field_path"] == "card.options[0].text"
    try:
        InteractionCreateRequest.model_validate({"task_key": private})
    except ValidationError as exc:
        result = classify_interaction_failure(exc, "interaction.card.create/1")
        assert result["error_code"] == "INVALID_INTERACTION_REQUEST"
        assert private not in json.dumps(result)


def test_developer_window_search_is_bounded_and_scoped(tmp_path):
    when = NOW - timedelta(minutes=5)
    _trace(tmp_path, "old", "customer-task", _failure("a" * 32, when))
    _trace(tmp_path, "other-tenant", "foreign-task", _failure("b" * 32, when))
    _trace(tmp_path, "other-agent", "agent-task", _failure("c" * 32, when))
    kwargs = dict(storage_root=tmp_path, grants=_grants(), agent_id="comic",
                  tenant_id="local", start=NOW-timedelta(hours=1), end=NOW,
                  owner_resolver=lambda task: {"tenant_id": "local", "agent_id": "comic"}
                  if task == "customer-task" else None, now=NOW)
    result = search_developer_failures(**kwargs)
    assert [row["invocation_id"] for row in result["failures"]] == ["a" * 32]
    assert "private model text" not in json.dumps(result)
    validate(result, json.loads((SCHEMAS.parent / "runtime-diagnostics-search-v1" / "response.schema.json").read_text()))
    with pytest.raises(ValueError):
        search_developer_failures(**{**kwargs, "start": NOW - timedelta(days=2)})
    with pytest.raises(ValueError):
        search_developer_failures(**{**kwargs, "limit": 51})


def test_developer_window_search_paginates_without_repeating_references(tmp_path):
    rows = []
    for index in range(3):
        rows.extend(_failure(f"{index + 1:032x}", NOW - timedelta(minutes=index + 1)))
    _trace(tmp_path, "old", "customer-task", rows)
    kwargs = dict(storage_root=tmp_path, grants=_grants(), agent_id="comic",
                  tenant_id="local", start=NOW-timedelta(hours=1), end=NOW,
                  owner_resolver=lambda _: {"tenant_id": "local", "agent_id": "comic"},
                  now=NOW, limit=2)
    first = search_developer_failures(**kwargs)
    assert first["has_more"] is True
    assert first["next_cursor"] == first["failures"][-1]["invocation_id"]
    second = search_developer_failures(**kwargs, cursor=first["next_cursor"])
    assert second["has_more"] is False
    assert second["next_cursor"] is None
    assert len({row["invocation_id"] for row in first["failures"] + second["failures"]}) == 3
    with pytest.raises(ValueError):
        search_developer_failures(**kwargs, cursor="0" * 32)


def test_developer_diagnostic_routes_enforce_expert_owner(tmp_path, monkeypatch):
    invocation = "a" * 32
    when = datetime.now(timezone.utc) - timedelta(minutes=3)
    _trace(tmp_path / "workspace_runtime_state", "old", "customer-task",
           _failure(invocation, when))
    monkeypatch.setattr("super_agent.publication.WORKING_DIR", tmp_path)
    monkeypatch.setattr("super_agent.local_host.read_invocation_task_summaries", lambda **_: None)
    monkeypatch.setattr(
        "super_agent.composition.resolve_event_scope",
        lambda _: {"tenant_id": "local", "agent_id": "comic", "user_id": "customer"},
    )
    publication = object.__new__(PublisherPublication)
    publication.repository = SimpleNamespace(
        agent_owner=lambda agent: ("local", "developer") if agent == "comic" else None,
    )
    publication.handler = SimpleNamespace(grant_repository=_grants())
    publication._diagnostic_read_times = {}
    publication.router = APIRouter()
    publication._register_routes()
    app = FastAPI()

    @app.middleware("http")
    async def actor(request, call_next):
        request.state.tenant_id = "local"
        request.state.user_id = "developer"
        return await call_next(request)

    app.include_router(publication.router)
    client = TestClient(app)
    reference = f"/runtime-diagnostics/v3/references/{invocation}"
    assert client.get(reference, params={"agent_id": "foreign"}).status_code == 404
    found = client.get(reference, params={"agent_id": "comic"})
    assert found.status_code == 200
    assert found.json()["host_failure_detail"]["status"] == "not_applicable"
    turn_reference = f"/runtime-diagnostics/v4/references/{invocation}"
    assert client.get(turn_reference, params={"agent_id": "foreign"}).status_code == 404
    turn = client.get(turn_reference, params={"agent_id": "comic"})
    assert turn.status_code == 200
    assert turn.json()["runtime_outcome"] == "failed"
    assert turn.json()["task_acceptance"] == "not_recorded"
    blocker_reference = f"/runtime-diagnostics/v5/references/{invocation}"
    assert client.get(blocker_reference, params={"agent_id": "foreign"}).status_code == 404
    blocker = client.get(blocker_reference, params={"agent_id": "comic"})
    assert blocker.status_code == 200
    assert blocker.json()["blocker"]["evidence"] == "historical_detail_not_recorded"
    searched = client.get("/runtime-diagnostics/v1/search", params={
        "agent_id": "comic", "start": (when - timedelta(minutes=1)).isoformat(),
        "end": (when + timedelta(minutes=1)).isoformat(),
    })
    assert searched.status_code == 200
    assert searched.json()["failures"][0]["invocation_id"] == invocation
    assert client.get("/runtime-diagnostics/v1/search", params={
        "agent_id": "foreign", "start": when.isoformat(), "end": datetime.now(timezone.utc).isoformat(),
    }).status_code == 404


def test_developer_aigc_binding_route_reuses_owner_and_rate_limit(tmp_path, monkeypatch):
    from super_agent import publication as publication_module
    from super_agent import aigc_binding

    monkeypatch.setattr(publication_module, "WORKING_DIR", tmp_path)
    monkeypatch.setattr(publication_module, "get_sealed_agent_service", lambda: SimpleNamespace(
        get_agent=lambda _: SimpleNamespace(active_release=SimpleNamespace(release_id="release")),
    ))
    monkeypatch.setattr(
        "super_agent.composition.get_super_expert_platform_service",
        lambda: SimpleNamespace(
            task_repository=object(), event_repository=object(), aigc=object(),
        ),
    )
    monkeypatch.setattr(
        "super_agent.composition.resolve_event_scope", lambda _: None,
    )
    monkeypatch.setattr(aigc_binding, "read_developer_binding", lambda **_: {
        "contract": "developer.aigc.binding.lookup/1", "status": "not_found",
    })
    publication = object.__new__(PublisherPublication)
    publication.repository = SimpleNamespace(
        agent_owner=lambda agent: ("local", "developer") if agent == "comic" else None,
    )
    publication.handler = SimpleNamespace(grant_repository=SimpleNamespace(
        find_release_grant=lambda *_, **__: SimpleNamespace(installation_id="install"),
    ))
    publication._diagnostic_read_times = {}
    publication.router = APIRouter()
    publication._register_routes()
    app = FastAPI()

    @app.middleware("http")
    async def actor(request, call_next):
        request.state.tenant_id = "local"
        request.state.user_id = "developer"
        return await call_next(request)

    app.include_router(publication.router)
    client = TestClient(app)
    path = "/aigc-tasks/v1/sessions/customer-task/binding"
    assert client.get(path, params={"agent_id": "foreign"}).status_code == 404
    assert client.get(path, params={"agent_id": "comic"}).json() == {
        "contract": "developer.aigc.binding.lookup/1", "status": "not_found",
    }


def test_developer_diagnostic_demo_uses_https_and_closed_schema(monkeypatch):
    requested = []

    def response(request, timeout):
        requested.append((request.full_url, request.get_header("Authorization"), timeout))
        return io.BytesIO(json.dumps({
            "contract": "developer.runtime.diagnostics.by-reference/3",
            "status": "no_record", "retention_days": 30,
        }).encode())

    monkeypatch.setattr(runtime_diagnostics_api_demo, "urlopen", response)
    result = runtime_diagnostics_api_demo.lookup(
        "https://dclaw.example", "comic", "a" * 32, "local-token",
    )
    assert result["status"] == "no_record"
    assert requested[0][0].endswith("/" + "a" * 32 + "?agent_id=comic")
    assert requested[0][1] == "Bearer local-token"
    with pytest.raises(ValueError):
        runtime_diagnostics_api_demo.lookup(
            "http://dclaw.example", "comic", "a" * 32, "local-token",
        )


def test_developer_diagnostic_demo_reads_completed_turn_v4(monkeypatch):
    requested = []

    def response(request, timeout):
        requested.append(request.full_url)
        return io.BytesIO(json.dumps({
            "contract": "developer.runtime.diagnostics.by-reference/4",
            "status": "no_record", "retention_days": 30,
        }).encode())

    monkeypatch.setattr(runtime_diagnostics_api_demo, "urlopen", response)
    result = runtime_diagnostics_api_demo.lookup_turn(
        "https://dclaw.example", "comic", "a" * 32, "local-token",
    )
    assert result["status"] == "no_record"
    assert "/runtime-diagnostics/v4/references/" in requested[0]


def test_developer_diagnostic_demo_reads_blocker_v5(monkeypatch):
    requested = []

    def response(request, timeout):
        requested.append(request.full_url)
        return io.BytesIO(json.dumps({
            "contract": "developer.runtime.diagnostics.by-reference/5",
            "status": "no_record", "retention_days": 30,
        }).encode())

    monkeypatch.setattr(runtime_diagnostics_api_demo, "urlopen", response)
    result = runtime_diagnostics_api_demo.lookup_turn_blocker(
        "https://dclaw.example", "comic", "a" * 32, "local-token",
    )
    assert result["status"] == "no_record"
    assert "/runtime-diagnostics/v5/references/" in requested[0]


def test_reference_v2_rate_limit_is_actor_scoped():
    publication = object.__new__(PublisherPublication)
    publication._diagnostic_read_times = {}
    for _ in range(30):
        publication._limit_diagnostic_reads("tenant", "developer")
    with pytest.raises(HTTPException) as error:
        publication._limit_diagnostic_reads("tenant", "developer")
    assert error.value.status_code == 429
    publication._limit_diagnostic_reads("tenant", "another-developer")
    publication._limit_diagnostic_reads("another-tenant", "developer")


def test_reference_v2_reports_card_validation_field_without_request_body(tmp_path):
    invocation = "c" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": when.isoformat(), "invocation_id": invocation,
         "event_type": "orchestration.started", "payload": {}},
        {"timestamp": (when + timedelta(seconds=1)).isoformat(),
         "invocation_id": invocation, "event_type": "interaction.tool.rejected",
         "payload": {"capability": "interaction.card.create/1",
                     "category": "INVALID_INTERACTION_REQUEST",
                     "field_path": "interaction_revision", "constraint": "INVALID_VALUE",
                     "secret": "private"}},
        {"timestamp": (when + timedelta(seconds=2)).isoformat(),
         "invocation_id": invocation, "event_type": "orchestration.failed",
         "payload": {"error_code": "INVALID_TURN_RESULT"}},
    ])
    owner = lambda _: {"user_id": "customer", "agent_id": "comic", "tenant_id": "local"}
    result = read_developer_failure_by_reference_v2(
        storage_root=tmp_path, grants=_grants(), agent_id="comic",
        tenant_id="local", invocation_id=invocation, owner_resolver=owner, now=NOW,
    )
    assert result["final_blocker"] == {
        "status": "recorded", "phase": "interaction_tool_validation",
        "category": "INVALID_INTERACTION_REQUEST", "attempt": None,
        "responsibility": "request_validation", "reason": "request_rejected",
        "field_path": "interaction_revision", "constraint": "INVALID_VALUE",
        "contract": "interaction.card.create/1",
    }
    assert "private" not in json.dumps(result)
    validate(result, json.loads((
        SCHEMAS.parent / "runtime-diagnostics-v2" / "by-reference-response.schema.json"
    ).read_text()))


def test_reference_v2_uses_later_agent_failure_after_recoverable_tool_rejection(tmp_path):
    invocation = "d" * 32
    when = NOW - timedelta(minutes=1)
    _trace(tmp_path, "old", "customer-task", [
        {"timestamp": when.isoformat(), "invocation_id": invocation,
         "event_type": "interaction.tool.rejected", "payload": {
             "capability": "interaction.card.create/1",
             "category": "INVALID_INTERACTION_REQUEST",
             "field_path": "card.options[0].text", "constraint": "FIELD_REQUIRED",
         }},
        {"timestamp": (when + timedelta(seconds=1)).isoformat(),
         "invocation_id": invocation, "event_type": "runtime.trace",
         "payload": {"origin": "agent", "payload": {
             "event": "agent.turn.failure", "phase": "model_validation",
             "category": "json_parse", "attempt": 2,
         }}},
        {"timestamp": (when + timedelta(seconds=2)).isoformat(),
         "invocation_id": invocation, "event_type": "orchestration.failed",
         "payload": {"error_code": "INVALID_TURN_RESULT"}},
    ])
    result = read_developer_failure_by_reference_v2(
        storage_root=tmp_path, grants=_grants(), agent_id="comic", tenant_id="local",
        invocation_id=invocation,
        owner_resolver=lambda _: {"user_id": "customer", "agent_id": "comic", "tenant_id": "local"},
        now=NOW,
    )
    assert result["final_blocker"]["phase"] == "model_validation"
    assert [event["outcome"] for event in result["failure_events"]] == [
        "not_recorded", "terminal",
    ]
    assert result["unrecorded_fields"] == []


def test_memory_message_ids_supports_persisted_agent_format():
    assert _memory_message_ids([
        [{"id": "user-one"}, []],
        [{"id": "reply-one"}, []],
        {"id": "direct-message"},
    ]) == {"user-one", "reply-one", "direct-message"}


def test_host_failure_without_agent_trace_does_not_invent_phase(tmp_path):
    _trace(tmp_path, "old", "task", [{
        "timestamp": (NOW - timedelta(minutes=1)).isoformat(),
        "invocation_id": "host-failure", "event_type": "orchestration.failed",
        "payload": {"error_code": "orchestration_error"},
    }])
    result = read_latest_failure(**_args(tmp_path))
    assert result["first_failure_source"] == "not_recorded"
    assert result["first_failure"] == {
        "phase": None, "category": None, "attempt": None,
    }
    assert result["transaction_status"] == "discarded"
    validate(result, json.loads((SCHEMAS / "response.schema.json").read_text()))


def test_optional_capability_preserves_required_host_closure():
    fixture = Path(__file__).parents[4] / "tests" / "fixtures" / "super_expert" / "generic-orchestration-v1" / "manifest.template.json"
    manifest = json.loads(fixture.read_text())
    required = list(manifest["orchestration"]["required_host_capabilities"])
    manifest["capabilities"].append({
        "capability_id": "runtime.failure.read/1", "contract_version": "1",
    })
    manifest["content_digest"] = "sha256:" + "0" * 64
    manifest["capability_digest"] = compute_capability_set_digest(manifest)
    validated = validate_super_expert_manifest(
        SealedPackageManifest.model_validate(manifest),
        SuperExpertTrustStore(official_signer_ids=frozenset({"official-test"})),
    )
    assert list(validated.orchestration.required_host_capabilities) == required


@pytest.mark.parametrize("owner", [
    {"user_id": "58", "agent_id": "comic", "tenant_id": "local"},
    {"user_id": "57", "agent_id": "another", "tenant_id": "local"},
    {"user_id": "57", "agent_id": "comic", "tenant_id": "elsewhere"},
    None,
])
def test_rejects_wrong_owner(tmp_path, owner):
    with pytest.raises(FailureDiagnosticsUnauthorized):
        read_latest_failure(**_args(tmp_path, owner=lambda _: owner))


def test_rejects_corrupt_or_unsafe_trace(tmp_path):
    path = _trace(tmp_path, "old", "task", _failure("one", NOW - timedelta(minutes=2)))
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(FailureDiagnosticsUnavailable):
        read_latest_failure(**_args(tmp_path))
    path.unlink()
    path.symlink_to(tmp_path / "elsewhere")
    with pytest.raises(FailureDiagnosticsUnavailable):
        read_latest_failure(**_args(tmp_path))


@pytest.mark.asyncio
async def test_host_requires_declared_grant_and_empty_request(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "super_agent.orchestration._composition.get_super_expert_platform_service",
        lambda: SimpleNamespace(grant_repository=_grants()),
    )
    monkeypatch.setattr(
        "super_agent.orchestration._composition.resolve_event_scope",
        lambda _: {"user_id": "57", "agent_id": "comic", "tenant_id": "local"},
    )
    request = SimpleNamespace(
        invocation_id="current", installation_id="new", release_id="0.2.4",
        agent_id="comic", user_id="57", session_id="task",
        transaction_root=tmp_path / "transactions" / "current",
        granted_capabilities={"runtime.failure.read/1": "1"},
    )
    host = WorkspaceRuntimeHost(
        request=request, execute_agent=lambda _: None, session_context=lambda: None,
    )
    # The Host uses the current wall clock, so provide a recent trace here.
    _trace(tmp_path, "old", "task", _failure("prior", datetime.now(timezone.utc) - timedelta(minutes=2)))
    assert (await host.call("runtime.failure.read/1", {}))["invocation_id"] == "prior"
    with pytest.raises(WorkspaceOrchestrationError):
        await host.call("runtime.failure.read/1", {"session_id": "another"})
    request.granted_capabilities = {}
    with pytest.raises(WorkspaceOrchestrationError) as error:
        await host.call("runtime.failure.read/1", {})
    assert error.value.error_code == "unauthorized_capability"


@pytest.mark.asyncio
async def test_host_stages_are_correlated_without_context_or_message_body():
    request = SimpleNamespace(
        invocation_id="one", agent_id="comic", session_id="task",
        granted_capabilities={
            "session.context": "1", "runtime.fail": "1",
        },
    )
    stages = []
    host = WorkspaceRuntimeHost(
        request=request, execute_agent=lambda _: None,
        session_context=lambda: {"private": "customer content"},
        trace_sink=lambda item: stages.append(item),
    )
    assert (await host.call("session.context", {}))["private"] == "customer content"
    await host.call("runtime.fail", {
        "invocation_id": "one", "error_code": "INVALID_TURN_RESULT",
    })
    assert [item["payload"]["event"] for item in stages] == [
        "session.context.completed", "runtime.fail.accepted",
    ]
    assert all(item["invocation_id"] == "one" for item in stages)
    assert "customer content" not in json.dumps(stages)
