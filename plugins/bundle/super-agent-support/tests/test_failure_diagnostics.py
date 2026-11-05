from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import validate
from qwenpaw.app.sealed_agents.package import SealedPackageManifest

from super_agent.failure_diagnostics import (
    FailureDiagnosticsUnauthorized,
    FailureDiagnosticsUnavailable,
    read_latest_failure,
)
from super_agent.capabilities import compute_capability_set_digest, validate_super_expert_manifest
from super_agent.orchestration import WorkspaceOrchestrationError, WorkspaceRuntimeHost
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


def test_no_record_and_retention_window(tmp_path):
    result = read_latest_failure(**_args(tmp_path))
    assert result == {
        "contract": "runtime.failure.read/1", "status": "no_record",
        "reason": "no_failure_in_retention_window",
    }
    validate(result, json.loads((SCHEMAS / "response.schema.json").read_text()))
    _trace(tmp_path, "old", "task", _failure("expired", NOW - timedelta(days=31)))
    assert read_latest_failure(**_args(tmp_path))["status"] == "no_record"


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
