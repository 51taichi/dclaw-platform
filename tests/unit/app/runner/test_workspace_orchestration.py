from __future__ import annotations

import asyncio
from pathlib import Path
import textwrap
from types import SimpleNamespace

from agentscope.message import Msg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import json

import pytest
from pydantic import ValidationError

from qwenpaw.app.workspace.orchestration_contract import (
    HOST_CAPABILITIES_V1,
    OrchestrationConfig,
    WorkspaceTurnCompletion,
    WorkspaceTurnRequest,
)
from qwenpaw.app.workspace.orchestration import (
    AuthorizedWorkspaceRelease,
    authorize_workspace_release,
    _candidate_execution_messages,
    _execute_internal_candidate,
    is_workspace_business_turn,
    resolve_active_workspace_authorization,
    run_workspace_orchestration_turn,
    runtime_trace_path,
    workspace_orchestration_timeout_seconds,
    WorkspaceStateTransaction,
    WorkspaceOrchestrationError,
    WorkspaceTurnOrchestrator,
)
from qwenpaw.app.sealed_agents.models import SealedAgentRecord, SealedReleaseRecord
from qwenpaw.app.sealed_agents.package import inspect_extracted_payload
from qwenpaw.app.sealed_agents.package import (
    build_signed_package_bytes,
    validate_sealed_package,
)
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.app.sealed_agents.service import SealedAgentService
from qwenpaw.app.sealed_agents.signing import SuperExpertTrustStore
from qwenpaw.app.super_experts.capabilities import (
    compute_capability_set_digest,
    validate_super_expert_manifest,
)
from qwenpaw.app.super_experts.grants import SuperExpertGrantRepository
from qwenpaw.config.config import AgentProfileConfig


def _orchestration(**overrides):
    value = {
        "enabled": True,
        "contract_version": "1",
        "entrypoint": "runtime.py:create_runtime",
        "required_host_capabilities": list(HOST_CAPABILITIES_V1),
    }
    value.update(overrides)
    return value


def test_agent_profile_defaults_to_disabled_orchestration():
    profile = AgentProfileConfig(id="agent-1", name="Agent")

    assert profile.orchestration == OrchestrationConfig()
    assert profile.orchestration.enabled is False


def test_workspace_orchestration_timeout_allows_multi_step_agent_turns(monkeypatch):
    monkeypatch.delenv("DCLAW_WORKSPACE_ORCHESTRATION_TIMEOUT_SECONDS", raising=False)
    assert workspace_orchestration_timeout_seconds() == 180.0


def test_workspace_orchestration_timeout_is_bounded_and_invalid_values_are_safe(monkeypatch):
    monkeypatch.setenv("DCLAW_WORKSPACE_ORCHESTRATION_TIMEOUT_SECONDS", "10")
    assert workspace_orchestration_timeout_seconds() == 30.0
    monkeypatch.setenv("DCLAW_WORKSPACE_ORCHESTRATION_TIMEOUT_SECONDS", "1200")
    assert workspace_orchestration_timeout_seconds() == 900.0
    monkeypatch.setenv("DCLAW_WORKSPACE_ORCHESTRATION_TIMEOUT_SECONDS", "invalid")
    assert workspace_orchestration_timeout_seconds() == 180.0


def test_agent_profile_accepts_the_strict_v1_declaration():
    profile = AgentProfileConfig(
        id="agent-1",
        name="Agent",
        orchestration=_orchestration(),
    )

    assert profile.orchestration.entrypoint == "runtime.py:create_runtime"
    assert profile.orchestration.required_host_capabilities == HOST_CAPABILITIES_V1


def test_resolve_active_authorization_forwards_runtime_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "runtime" / "agent"
    workspace.mkdir(parents=True)
    record = SimpleNamespace(active_release_id="release-1")
    captured = {}

    monkeypatch.setattr(
        "qwenpaw.app.workspace.orchestration.get_sealed_agent_registry",
        lambda: SimpleNamespace(get_agent=lambda agent_id: record),
    )

    def fake_authorize_workspace_release(**kwargs):
        captured.update(kwargs)
        return "authorized"

    monkeypatch.setattr(
        "qwenpaw.app.workspace.orchestration.authorize_workspace_release",
        fake_authorize_workspace_release,
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.orchestration.WORKING_DIR",
        str(tmp_path),
    )

    result = resolve_active_workspace_authorization(
        agent_id="agent-1",
        workspace_root=workspace,
        tenant_id="local",
        config=OrchestrationConfig(**_orchestration()),
    )

    assert result == "authorized"
    assert captured["workspace_root"] == workspace


def test_candidate_execution_projects_runtime_system_instruction_as_last_user_turn():
    messages = [
        Msg(name="runtime", role="system", content="ONLY JSON"),
        Msg(name="user", role="user", content="customer input"),
    ]

    projected = _candidate_execution_messages(messages)

    assert [message.role for message in projected] == ["user", "user"]
    assert "ONLY JSON" in projected[-1].get_text_content()
    assert projected[-1].get_text_content().endswith(
        "禁止用普通字符串或字符串 \"null\" 代替。"
    )


@pytest.mark.asyncio
async def test_internal_candidate_temporarily_raises_runtime_instruction_authority():
    system = Msg(name="agent", role="system", content="ORIGINAL")

    class Agent:
        _sys_prompt = "ORIGINAL"
        memory = SimpleNamespace(content=[(system, None)])

        def _build_sys_prompt(self):
            return "ORIGINAL"

        async def __call__(self, messages):
            self._sys_prompt = self._build_sys_prompt()
            assert "ONLY JSON" in self._sys_prompt
            assert "ONLY JSON" in system.get_text_content()
            return Msg(name="assistant", role="assistant", content="{}")

    result = await _execute_internal_candidate(
        Agent(),
        [Msg(name="runtime", role="system", content="ONLY JSON")],
    )

    assert result.get_text_content() == "{}"
    assert system.get_text_content() == "ORIGINAL"


@pytest.mark.asyncio
async def test_internal_candidate_keeps_latest_nonempty_stream_chunk():
    class Formatter:
        async def format(self, *, msgs):
            return msgs

    class Model:
        stream = True
        model_key = "volcengine-cn:deepseek-v4-flash"

        def __init__(self):
            self.max_tokens = None
            self.extra_body = None

        async def __call__(
            self, prompt, *, tools, tool_choice, max_tokens, extra_body
        ):
            self.max_tokens = max_tokens
            self.extra_body = extra_body
            async def chunks():
                yield SimpleNamespace(
                    id="chunk-1",
                    content=[{"type": "text", "text": '{"response":{}}'}],
                )
                yield SimpleNamespace(
                    id="chunk-2",
                    content=[{"type": "text", "text": ""}],
                )

            return chunks()

    model = Model()
    agent = SimpleNamespace(name="agent", formatter=Formatter(), model=model)

    result = await _execute_internal_candidate(
        agent,
        [Msg(name="runtime", role="system", content="ONLY JSON")],
    )

    assert result.get_text_content() == '{"response":{}}'
    assert result.invocation_id == "chunk-1"
    assert model.max_tokens == 4096
    assert model.extra_body == {"thinking": {"type": "disabled"}}


@pytest.mark.parametrize(
    "orchestration",
    [
        _orchestration(unknown=True),
        _orchestration(contract_version="2"),
        _orchestration(entrypoint="../runtime.py:create_runtime"),
        _orchestration(entrypoint="runtime.py"),
        _orchestration(required_host_capabilities=[*HOST_CAPABILITIES_V1, "x"]),
        _orchestration(
            required_host_capabilities=[
                *HOST_CAPABILITIES_V1,
                HOST_CAPABILITIES_V1[0],
            ],
        ),
    ],
)
def test_invalid_orchestration_declarations_fail_validation(orchestration):
    with pytest.raises(ValidationError):
        AgentProfileConfig(
            id="agent-1",
            name="Agent",
            orchestration=orchestration,
        )


def test_workspace_turn_request_rejects_caller_extensions(tmp_path):
    with pytest.raises(ValidationError):
        WorkspaceTurnRequest(
            invocation_id="inv-1",
            agent_id="agent-1",
            release_id="release-1",
            release_digest=f"sha256:{'a' * 64}",
            installation_id="installation-1",
            session_id="session-1",
            user_id="user-1",
            channel="console",
            normalized_input={"message": "hello"},
            history=[],
            safe_metadata={},
            diagnostics_authorized=False,
            granted_capabilities={"runtime.complete": "1"},
            state_root=tmp_path / "state",
            transaction_root=tmp_path / "transaction",
            caller_stage="S15",
        )


def test_completion_contract_is_render_bound_and_strict():
    completion = WorkspaceTurnCompletion(
        invocation_id="inv-1",
        message={"reply": "done"},
    )

    assert completion.message == {"reply": "done"}
    with pytest.raises(ValidationError):
        WorkspaceTurnCompletion(
            invocation_id="inv-1",
            message={"reply": "done"},
            raw_model_output="leak",
        )


def test_state_paths_must_be_absolute_and_distinct(tmp_path):
    base = {
        "invocation_id": "inv-1",
        "agent_id": "agent-1",
        "release_id": "release-1",
        "release_digest": f"sha256:{'a' * 64}",
        "installation_id": "installation-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "channel": "console",
        "normalized_input": {"message": "hello"},
        "history": [],
        "safe_metadata": {},
        "diagnostics_authorized": False,
        "granted_capabilities": {"runtime.complete": "1"},
    }

    with pytest.raises(ValidationError):
        WorkspaceTurnRequest(
            **base,
            state_root=Path("relative"),
            transaction_root=tmp_path / "transaction",
        )
    with pytest.raises(ValidationError):
        WorkspaceTurnRequest(
            **base,
            state_root=tmp_path / "same",
            transaction_root=tmp_path / "same",
        )


def _write_runtime(workspace, body):
    runtime_path = workspace / "runtime.py"
    runtime_path.write_text(textwrap.dedent(body), encoding="utf-8")
    return runtime_path


def _request_for(transaction, **overrides):
    values = {
        "invocation_id": transaction.invocation_id,
        "agent_id": "generic-agent",
        "release_id": "release-1",
        "release_digest": f"sha256:{'a' * 64}",
        "installation_id": "installation-1",
        "session_id": "session-1",
        "user_id": "user-1",
        "channel": "console",
        "normalized_input": {"message": "hello"},
        "history": [],
        "safe_metadata": {},
        "diagnostics_authorized": False,
        "granted_capabilities": {
            capability: "1" for capability in HOST_CAPABILITIES_V1
        },
        "state_root": transaction.state_root,
        "transaction_root": transaction.transaction_root,
    }
    values.update(overrides)
    return WorkspaceTurnRequest(**values)


def test_state_transaction_commits_or_discards_as_one_unit(tmp_path):
    transaction = WorkspaceStateTransaction.begin(
        tmp_path,
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="inv-1",
    )
    (transaction.transaction_root / "state.txt").write_text("first")
    transaction.commit()
    assert (transaction.state_root / "state.txt").read_text() == "first"

    discarded = WorkspaceStateTransaction.begin(
        tmp_path,
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="inv-2",
    )
    assert (discarded.transaction_root / "state.txt").read_text() == "first"
    (discarded.transaction_root / "state.txt").write_text("uncommitted")
    discarded.discard()

    assert (discarded.state_root / "state.txt").read_text() == "first"
    assert not discarded.transaction_root.exists()


def test_stale_state_transaction_cannot_overwrite_a_newer_commit(tmp_path):
    storage = tmp_path / "state-store"
    seed = WorkspaceStateTransaction.begin(
        storage,
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="seed",
    )
    (seed.transaction_root / "state.txt").write_text("seed")
    seed.commit()
    first = WorkspaceStateTransaction.begin(
        storage,
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="first",
    )
    stale = WorkspaceStateTransaction.begin(
        storage,
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="stale",
    )
    (first.transaction_root / "state.txt").write_text("first")
    (stale.transaction_root / "state.txt").write_text("stale")
    first.commit()

    with pytest.raises(WorkspaceOrchestrationError):
        stale.commit()
    stale.discard()

    assert (first.state_root / "state.txt").read_text() == "first"


@pytest.mark.asyncio
async def test_generic_runtime_candidate_is_internal_and_complete_is_visible(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        from pathlib import Path

        class Runtime:
            async def handle(self, request, host):
                candidate = await host.call("agent.execute", {"prompt": "normalized"})
                Path(request.transaction_root, "state.txt").write_text("committed")
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": {"reply": "generic:" + candidate["text"]},
                })

        def create_runtime():
            return Runtime()
        """,
    )
    transaction = WorkspaceStateTransaction.begin(
        tmp_path / "state-store",
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="inv-1",
    )
    candidate_calls = []

    async def execute(arguments):
        candidate_calls.append(arguments)
        return {"text": "draft-secret"}

    orchestrator = WorkspaceTurnOrchestrator(
        workspace_root=workspace,
        config=OrchestrationConfig.model_validate(_orchestration()),
        signed_files=frozenset({"runtime.py"}),
        execute_agent=execute,
        session_context=lambda: {"session_id": "session-1"},
        timeout_seconds=1,
    )

    result = await orchestrator.invoke(_request_for(transaction), transaction)

    assert result.message == {"reply": "generic:draft-secret"}
    assert result.error_code is None
    assert candidate_calls == [{"prompt": "normalized"}]
    assert (transaction.state_root / "state.txt").read_text() == "committed"


@pytest.mark.asyncio
async def test_runtime_failure_preserves_safe_diagnostic_ref(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        class Runtime:
            async def handle(self, request, host):
                await host.call("runtime.fail", {
                    "invocation_id": request.invocation_id,
                    "error_code": "runtime_failed",
                    "diagnostic_ref": "WorkspaceRuntimeError:CALIBRATION_EVENT_INVALID",
                })
        def create_runtime(): return Runtime()
        """,
    )
    transaction = WorkspaceStateTransaction.begin(
        tmp_path / "state-store",
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="inv-1",
    )
    orchestrator = WorkspaceTurnOrchestrator(
        workspace_root=workspace,
        config=OrchestrationConfig.model_validate(_orchestration()),
        signed_files=frozenset({"runtime.py"}),
        execute_agent=lambda _arguments: {"text": "draft"},
        session_context=lambda: {},
        timeout_seconds=1,
    )

    result = await orchestrator.invoke(_request_for(transaction), transaction)

    assert result.error_code == "runtime_failed"
    assert result.diagnostic_ref == "WorkspaceRuntimeError:CALIBRATION_EVENT_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runtime_body", "expected_error"),
    [
        (
            """
            class Runtime:
                async def handle(self, request, host):
                    open(request.transaction_root / "state.txt", "w").write("leak")
            def create_runtime(): return Runtime()
            """,
            "invalid_completion",
        ),
        (
            """
            class Runtime:
                async def handle(self, request, host):
                    await host.call("runtime.complete", {"invocation_id": request.invocation_id, "message": {"reply": "one"}})
                    await host.call("runtime.complete", {"invocation_id": request.invocation_id, "message": {"reply": "two"}})
            def create_runtime(): return Runtime()
            """,
            "invalid_completion",
        ),
        (
            """
            class Runtime:
                async def handle(self, request, host):
                    await host.call("not.authorized", {})
            def create_runtime(): return Runtime()
            """,
            "unauthorized_capability",
        ),
        (
            """
            class Runtime:
                async def handle(self, request, host):
                    raise RuntimeError("boom")
            def create_runtime(): return Runtime()
            """,
            "orchestration_error",
        ),
        (
            """
            import asyncio
            class Runtime:
                async def handle(self, request, host):
                    await asyncio.sleep(1)
            def create_runtime(): return Runtime()
            """,
            "orchestration_timeout",
        ),
        (
            """
            class Runtime:
                async def handle(self, request, host):
                    open(request.transaction_root / "state.txt", "w").write("leak")
                    await host.call("runtime.complete", {"invocation_id": request.invocation_id, "message": {"not_renderable": True}})
            def create_runtime(): return Runtime()
            """,
            "invalid_completion",
        ),
    ],
)
async def test_every_orchestration_failure_discards_state(
    tmp_path,
    runtime_body,
    expected_error,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(workspace, runtime_body)
    transaction = WorkspaceStateTransaction.begin(
        tmp_path / "state-store",
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="inv-1",
    )
    orchestrator = WorkspaceTurnOrchestrator(
        workspace_root=workspace,
        config=OrchestrationConfig.model_validate(_orchestration()),
        signed_files=frozenset({"runtime.py"}),
        execute_agent=lambda _arguments: {"text": "draft"},
        session_context=lambda: {},
        timeout_seconds=0.01,
    )

    result = await orchestrator.invoke(_request_for(transaction), transaction)

    assert result.message is None
    assert result.error_code == expected_error
    assert not transaction.state_root.exists()
    assert not transaction.transaction_root.exists()


@pytest.mark.asyncio
async def test_cancellation_discards_staged_state_and_propagates_cancel(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        import asyncio
        from pathlib import Path
        class Runtime:
            async def handle(self, request, host):
                Path(request.transaction_root, "state.txt").write_text("staged")
                await asyncio.sleep(60)
        def create_runtime(): return Runtime()
        """,
    )
    transaction = WorkspaceStateTransaction.begin(
        tmp_path / "state-store",
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="inv-cancel",
    )
    orchestrator = WorkspaceTurnOrchestrator(
        workspace_root=workspace,
        config=OrchestrationConfig.model_validate(_orchestration()),
        signed_files=frozenset({"runtime.py"}),
        execute_agent=lambda _arguments: {"text": "draft"},
        session_context=lambda: {},
    )
    task = asyncio.create_task(
        orchestrator.invoke(_request_for(transaction), transaction),
    )
    for _ in range(100):
        if (transaction.transaction_root / "state.txt").exists():
            break
        await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert not transaction.transaction_root.exists()
    assert not transaction.state_root.exists()


@pytest.mark.asyncio
async def test_runner_level_cancellation_records_a_terminal_trace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        import asyncio
        class Runtime:
            async def handle(self, request, host):
                await asyncio.sleep(60)
        def create_runtime(): return Runtime()
        """,
    )
    authorization = AuthorizedWorkspaceRelease(
        installation_id="installation-1",
        release_id="release-1",
        release_digest=f"sha256:{'a' * 64}",
        granted_capabilities={capability: "1" for capability in HOST_CAPABILITIES_V1},
        signed_workspace_files=frozenset({"runtime.py"}),
    )
    storage = tmp_path / "runtime-state"
    task = asyncio.create_task(
        run_workspace_orchestration_turn(
            agent=lambda _messages: None,
            original_messages=[Msg(name="user", role="user", content="hello")],
            request=SimpleNamespace(
                session_id="session-1", user_id="user-1", channel="console",
            ),
            agent_id="generic-agent",
            workspace_root=workspace,
            state_storage_root=storage,
            config=OrchestrationConfig.model_validate(_orchestration()),
            authorization=authorization,
        ),
    )
    trace_path = runtime_trace_path(
        storage,
        installation_id="installation-1",
        session_id="session-1",
    )
    for _ in range(100):
        if trace_path.exists():
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert [event["event_type"] for event in events] == [
        "orchestration.started",
        "orchestration.cancelled",
    ]


@pytest.mark.asyncio
async def test_entrypoint_must_be_a_signed_regular_file_inside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def create_runtime(): pass")
    (workspace / "runtime.py").symlink_to(outside)
    transaction = WorkspaceStateTransaction.begin(
        tmp_path / "state-store",
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="inv-1",
    )
    orchestrator = WorkspaceTurnOrchestrator(
        workspace_root=workspace,
        config=OrchestrationConfig.model_validate(_orchestration()),
        signed_files=frozenset({"runtime.py"}),
        execute_agent=lambda _arguments: {},
        session_context=lambda: {},
    )

    result = await orchestrator.invoke(_request_for(transaction), transaction)

    assert result.error_code == "orchestration_error"
    assert not transaction.transaction_root.exists()


@pytest.mark.asyncio
async def test_signed_runtime_can_import_its_own_signed_modules(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "scripts").mkdir(parents=True)
    (workspace / "scripts" / "helper.py").write_text(
        "def render(): return 'package-local'\n",
        encoding="utf-8",
    )
    _write_runtime(
        workspace,
        """
        from .scripts.helper import render
        class Runtime:
            async def handle(self, request, host):
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": {"reply": render()},
                })
        def create_runtime(): return Runtime()
        """,
    )
    transaction = WorkspaceStateTransaction.begin(
        tmp_path / "state-store",
        installation_id="installation-1",
        session_id="session-1",
        invocation_id="inv-package-import",
    )
    orchestrator = WorkspaceTurnOrchestrator(
        workspace_root=workspace,
        config=OrchestrationConfig.model_validate(_orchestration()),
        signed_files=frozenset({"runtime.py", "scripts/helper.py"}),
        execute_agent=lambda _arguments: {"text": "unused"},
        session_context=lambda: {},
    )

    result = await orchestrator.invoke(_request_for(transaction), transaction)

    assert result.error_code is None
    assert result.message == {"reply": "package-local"}


def test_authorization_binds_active_release_grant_digest_and_workspace(tmp_path):
    release_root = tmp_path / "sealed" / "releases" / "generic-agent" / "release-1"
    workspace = release_root / "agent"
    workspace.mkdir(parents=True)
    (workspace / "agent.json").write_text("{}")
    (workspace / "runtime.py").write_text("def create_runtime(): pass")
    digest, _ = inspect_extracted_payload(release_root)
    release = SealedReleaseRecord(
        release_id="release-1",
        version="1.0.0",
        content_digest=digest,
        signer_id="official",
        package_type="super_expert",
        capability_digest=f"sha256:{'b' * 64}",
        declared_capabilities=tuple(
            (capability, "1") for capability in (
                "workspace.turn.orchestrate/1",
                *HOST_CAPABILITIES_V1,
            )
        ),
        orchestration_capability_id="workspace.turn.orchestrate/1",
        orchestration_contract_version="1",
        orchestration_entrypoint="runtime.py:create_runtime",
        orchestration_required_host_capabilities=HOST_CAPABILITIES_V1,
    )
    record = SealedAgentRecord(
        agent_id="generic-agent",
        name="Generic",
        active_release_id=release.release_id,
        releases=[release.model_copy(update={"state": "active"})],
    )
    grants = SuperExpertGrantRepository(tmp_path / "grants")
    grants.grant_installation(
        grants.preview("generic-agent", release, tenant_id="tenant-a"),
        administrator_id="admin-1",
    )

    runtime_workspace = (
        tmp_path / "sealed" / "runtime_workspaces" / "generic-agent" / "release-1" / "agent"
    )
    runtime_workspace.mkdir(parents=True)
    authorization = authorize_workspace_release(
        record=record,
        workspace_root=runtime_workspace,
        release_root=release_root,
        grant_repository=grants,
        tenant_id="tenant-a",
        config=OrchestrationConfig.model_validate(_orchestration()),
    )

    assert authorization.installation_id
    assert authorization.release_id == "release-1"
    assert authorization.signed_workspace_root == workspace
    assert authorization.signed_workspace_files == frozenset(
        {"agent.json", "runtime.py"},
    )


def test_self_declared_or_tampered_workspace_is_not_authorized(tmp_path):
    release_root = tmp_path / "sealed" / "releases" / "generic-agent" / "release-1"
    workspace = release_root / "agent"
    workspace.mkdir(parents=True)
    (workspace / "agent.json").write_text("{}")
    (workspace / "runtime.py").write_text("def create_runtime(): pass")
    digest, _ = inspect_extracted_payload(release_root)
    release = SealedReleaseRecord(
        release_id="release-1",
        version="1.0.0",
        content_digest=digest,
        signer_id="official",
        package_type="super_expert",
        capability_digest=f"sha256:{'b' * 64}",
        declared_capabilities=tuple(
            (capability, "1") for capability in (
                "workspace.turn.orchestrate/1",
                *HOST_CAPABILITIES_V1,
            )
        ),
        orchestration_capability_id="workspace.turn.orchestrate/1",
        orchestration_contract_version="1",
        orchestration_entrypoint="runtime.py:create_runtime",
        orchestration_required_host_capabilities=HOST_CAPABILITIES_V1,
    )
    record = SealedAgentRecord(
        agent_id="generic-agent",
        name="Generic",
        active_release_id=release.release_id,
        releases=[release.model_copy(update={"state": "active"})],
    )
    grants = SuperExpertGrantRepository(tmp_path / "grants")
    grants.grant_installation(
        grants.preview("generic-agent", release, tenant_id="tenant-a"),
        administrator_id="admin-1",
    )
    (workspace / "runtime.py").write_text("tampered = True")
    runtime_workspace = (
        tmp_path / "sealed" / "runtime_workspaces" / "generic-agent" / "release-1" / "agent"
    )
    runtime_workspace.mkdir(parents=True)

    with pytest.raises(WorkspaceOrchestrationError):
        authorize_workspace_release(
            record=record,
            workspace_root=runtime_workspace,
            release_root=release_root,
            grant_repository=grants,
            tenant_id="tenant-a",
            config=OrchestrationConfig.model_validate(_orchestration()),
        )


def test_business_turn_classification_excludes_platform_control_paths():
    assert is_workspace_business_turn("hello", mission_info=None)
    assert not is_workspace_business_turn("/new", mission_info=None)
    assert not is_workspace_business_turn("continue", mission_info={"phase": 1})


@pytest.mark.asyncio
async def test_runner_adapter_executes_internal_candidate_without_streaming(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        class Runtime:
            async def handle(self, request, host):
                candidate = await host.call("agent.execute", {"messages": [{"name": "user", "role": "user", "content": "internal"}]})
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": {"name": "assistant", "role": "assistant", "content": "final:" + candidate["text"]},
                })
        def create_runtime(): return Runtime()
        """,
    )

    class Agent:
        def __init__(self):
            self.calls = []

        async def __call__(self, messages):
            self.calls.append(messages)
            return Msg(name="assistant", role="assistant", content="draft")

    agent = Agent()
    authorization = AuthorizedWorkspaceRelease(
        installation_id="installation-1",
        release_id="release-1",
        release_digest=f"sha256:{'a' * 64}",
        granted_capabilities={
            capability: "1" for capability in HOST_CAPABILITIES_V1
        },
        signed_workspace_files=frozenset({"runtime.py"}),
    )

    result = await run_workspace_orchestration_turn(
        agent=agent,
        original_messages=[Msg(name="user", role="user", content="hello")],
        request=SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            channel="console",
            channel_meta={},
        ),
        agent_id="generic-agent",
        workspace_root=workspace,
        state_storage_root=tmp_path / "state-store",
        config=OrchestrationConfig.model_validate(_orchestration()),
        authorization=authorization,
    )

    assert result.message["content"] == "final:draft"
    assert len(agent.calls) == 1
    assert agent.calls[0][0].content == "internal"
    trace_events = [
        json.loads(line)
        for line in runtime_trace_path(
            tmp_path / "state-store",
            installation_id="installation-1",
            session_id="session-1",
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event_type"] for event in trace_events] == [
        "orchestration.started",
        "orchestration.completed",
    ]
    assert all(event["invocation_id"] for event in trace_events)


@pytest.mark.asyncio
async def test_server_owned_platform_events_reach_the_workspace_runtime(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        class Runtime:
            async def handle(self, request, host):
                events = request.safe_metadata.get("platformEvents", [])
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": {"reply": events[0]["event_id"]},
                })
        def create_runtime(): return Runtime()
        """,
    )
    authorization = AuthorizedWorkspaceRelease(
        installation_id="installation-1",
        release_id="release-1",
        release_digest=f"sha256:{'a' * 64}",
        granted_capabilities={capability: "1" for capability in HOST_CAPABILITIES_V1},
        signed_workspace_files=frozenset({"runtime.py"}),
    )

    result = await run_workspace_orchestration_turn(
        agent=lambda _messages: None,
        original_messages=[Msg(name="user", role="user", content="continue")],
        request=SimpleNamespace(session_id="session-1", user_id="user-1", channel="console"),
        agent_id="generic-agent",
        workspace_root=workspace,
        state_storage_root=tmp_path / "state-store",
        config=OrchestrationConfig.model_validate(_orchestration()),
        authorization=authorization,
        safe_metadata={"platformEvents": [{"event_id": "event-1"}]},
    )

    assert result.message == {"reply": "event-1"}


@pytest.mark.asyncio
async def test_official_signed_non_luyu_fixture_uses_the_generic_protocol(tmp_path):
    fixture = (
        Path(__file__).parents[3]
        / "fixtures/super_expert/generic-orchestration-v1"
    )
    manifest = json.loads((fixture / "manifest.template.json").read_text())
    manifest["capability_digest"] = compute_capability_set_digest(manifest)
    files = {
        path.relative_to(fixture).as_posix(): path.read_bytes()
        for path in (fixture / "agent").rglob("*")
        if path.is_file()
    }
    private = Ed25519PrivateKey.generate()
    package_bytes = build_signed_package_bytes(manifest, files, private)
    inspected = validate_sealed_package(
        package_bytes,
        trusted_signers={"official-test": private.public_key()},
        staging_root=tmp_path / "inspection",
    )
    validate_super_expert_manifest(
        inspected.manifest,
        SuperExpertTrustStore(
            official_signer_ids=frozenset({"official-test"}),
        ),
    )

    registry = SealedAgentRegistry(tmp_path / "registry")
    service = SealedAgentService(
        root=tmp_path / "sealed",
        registry=registry,
        trusted_signers={"official-test": private.public_key()},
        official_super_expert_signer_ids=frozenset({"official-test"}),
        grant_repository=SuperExpertGrantRepository(tmp_path / "grants"),
    )
    release = service.install(package_bytes)
    await service.validate_release_runtime("generic-orchestration", release.release_id)
    service.grant_installation(
        "generic-orchestration",
        release.release_id,
        tenant_id="tenant-a",
        administrator_id="admin-1",
    )
    record = service.activate(
        "generic-orchestration",
        release.release_id,
        tenant_id="tenant-a",
    )
    signed_workspace = service.release_root(
        "generic-orchestration",
        release.release_id,
    ) / "agent"
    workspace = service.prepare_runtime_workspace(
        "generic-orchestration", release.release_id
    )
    authorization = authorize_workspace_release(
        record=record,
        workspace_root=workspace,
        release_root=service.release_root(
            "generic-orchestration", release.release_id
        ),
        grant_repository=service.grant_repository,
        tenant_id="tenant-a",
        config=AgentProfileConfig.model_validate_json(
            (signed_workspace / "agent.json").read_text(),
        ).orchestration,
    )

    class Agent:
        async def __call__(self, messages):
            return Msg(
                name="assistant",
                role="assistant",
                content=messages[-1].get_text_content().upper(),
            )

    result = await run_workspace_orchestration_turn(
        agent=Agent(),
        original_messages=[Msg(name="user", role="user", content="hello")],
        request=SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            channel="console",
        ),
        agent_id="generic-orchestration",
        workspace_root=workspace,
        state_storage_root=tmp_path / "runtime-state",
        config=AgentProfileConfig.model_validate_json(
            (signed_workspace / "agent.json").read_text(),
        ).orchestration,
        authorization=authorization,
    )

    assert result.message["content"] == "generic:HELLO"
    fixture_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in fixture.rglob("*")
        if path.is_file()
    )
    assert "luyu_traffic_operator" not in fixture_text
    assert "S0-S15" not in fixture_text
