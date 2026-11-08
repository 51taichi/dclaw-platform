from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
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
)
from super_agent.capabilities import compute_capability_set_digest, validate_super_expert_manifest
from super_agent.orchestration import WorkspaceOrchestrationError, WorkspaceRuntimeHost
from super_agent.publication import PublisherPublication
from super_agent.router import _memory_message_ids
from super_agent.trust import SuperExpertTrustStore


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
