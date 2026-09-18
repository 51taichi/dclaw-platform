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
    _agent_execute_instruction,
    _agent_execute_mode,
    _agent_execute_require_interaction,
    _agent_execute_response_format,
    _execute_internal_candidate,
    is_workspace_business_turn,
    resolve_active_workspace_authorization,
    run_workspace_orchestration_turn,
    runtime_trace_path,
    workspace_orchestration_timeout_seconds,
    WorkspaceStateTransaction,
    WorkspaceOrchestrationError,
    WorkspaceTurnOrchestrator,
    WorkspaceTurnResult,
    workspace_result_to_message,
)
from qwenpaw.app.runner.runner import (
    _list_aigc_capabilities_for_workspace,
    _list_aigc_workflow_capabilities_for_workspace,
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


@pytest.mark.asyncio
async def test_workspace_catalog_bridge_reuses_safe_aigc_inventory(monkeypatch):
    expected = {
        "capabilities": [{
            "provider_id": "provider-1",
            "provider_name": "Provider",
            "model_id": "image-1",
            "model_name": "Image",
            "capability": "text_to_image",
            "source": "model_registry",
            "parameter_schema": {"type": "object"},
        }],
    }

    provider_manager = object()

    async def fake_list(actual_manager):
        assert actual_manager is provider_manager
        return SimpleNamespace(model_dump=lambda **_kwargs: expected)

    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: provider_manager,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.aigc_studio.build_capability_list",
        fake_list,
    )

    # Workspace turns carry an AgentRequest-like object, not Starlette Request.
    # The bridge must therefore resolve the provider manager directly instead
    # of dereferencing request.app.state.
    assert await _list_aigc_capabilities_for_workspace(object()) == expected


@pytest.mark.asyncio
async def test_workspace_workflow_catalog_bridge_uses_server_projection(monkeypatch):
    expected = {
        "schema_version": 1,
        "nodes": [{"kind": "video_generate"}],
        "available_models": [{"model_id": "video-1"}],
    }
    provider_manager = object()

    async def fake_list(actual_manager):
        assert actual_manager is provider_manager
        return SimpleNamespace(model_dump=lambda **_kwargs: expected)

    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: provider_manager,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.aigc_studio.build_workflow_capability_catalog",
        fake_list,
    )

    assert (
        await _list_aigc_workflow_capabilities_for_workspace(object())
        == expected
    )


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
        "不得输出面向客户的普通回答或任何前后解释。"
    )


def test_candidate_execution_does_not_override_runtime_ini_format_with_json_rules():
    messages = [
        Msg(
            name="runtime",
            role="system",
            content="只输出 INI-lite。\n[method]\nmethod_id=M01",
        ),
        Msg(name="user", role="user", content="好"),
    ]

    projected = _candidate_execution_messages(messages)
    candidate_instruction = projected[-1].get_text_content()

    assert "只输出 INI-lite" in candidate_instruction
    assert "JSON 类型" not in candidate_instruction
    assert 'JSON null' not in candidate_instruction


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


@pytest.mark.asyncio
async def test_internal_candidate_forwards_validated_json_response_format():
    class Formatter:
        async def format(self, *, msgs):
            return msgs

    class Model:
        stream = False
        model_key = "openai-compatible:test"

        async def __call__(self, prompt, **kwargs):
            assert kwargs["response_format"] == {"type": "json_object"}
            assert kwargs["max_tokens"] == 8192
            return SimpleNamespace(id="json-1", content=[{"type": "text", "text": "{}"}])

    result = await _execute_internal_candidate(
        SimpleNamespace(name="agent", formatter=Formatter(), model=Model()),
        [Msg(name="runtime", role="system", content="Return strict JSON")],
        response_format="json_object",
    )
    assert result.get_text_content() == "{}"


@pytest.mark.asyncio
async def test_fallback_agent_rejects_json_format_instead_of_ignoring_it():
    class FallbackAgent:
        # A self-declared flag is not a trusted host/model API and must not
        # turn a format request into an ordinary prompt-only call.
        supports_json_object_response_format = True

        async def __call__(self, messages):
            raise AssertionError("unsupported fallback must not execute")

    with pytest.raises(WorkspaceOrchestrationError):
        await _execute_internal_candidate(
            FallbackAgent(), [Msg(name="runtime", role="system", content="JSON")],
            response_format="json_object",
        )

    with pytest.raises(WorkspaceOrchestrationError):
        await _execute_internal_candidate(
            SimpleNamespace(name="direct", formatter=object(), model=object()),
            [Msg(name="runtime", role="system", content="JSON")],
            response_format={},
        )


def test_agent_execute_response_format_is_closed_and_does_not_coerce_values():
    assert _agent_execute_response_format({"messages": []}) is None
    assert _agent_execute_response_format({
        "messages": [], "response_format": "json_object",
    }) == "json_object"
    for invalid in (None, False, True, "json", {}, 0):
        with pytest.raises(WorkspaceOrchestrationError):
            _agent_execute_response_format({
                "messages": [], "response_format": invalid,
            })


def test_agent_execute_mode_is_closed_and_defaults_to_internal_candidate():
    assert _agent_execute_mode({"messages": []}) == "candidate"
    assert _agent_execute_mode({
        "messages": [], "execution_mode": "agent_loop",
    }) == "agent_loop"
    for invalid in (None, False, True, "full", {}, 0):
        with pytest.raises(WorkspaceOrchestrationError):
            _agent_execute_mode({
                "messages": [], "execution_mode": invalid,
            })


def test_agent_execute_instruction_is_optional_stripped_and_closed():
    assert _agent_execute_instruction({"messages": []}) is None
    assert _agent_execute_instruction({
        "messages": [], "instruction": "  keep the card  ",
    }) == "keep the card"
    for invalid in (None, "", "   ", 1, True, []):
        with pytest.raises(WorkspaceOrchestrationError):
            _agent_execute_instruction({
                "messages": [], "instruction": invalid,
            })


def test_agent_execute_require_interaction_is_optional_boolean_and_closed():
    assert _agent_execute_require_interaction({"messages": []}) is False
    assert _agent_execute_require_interaction({
        "messages": [], "require_interaction": True,
    }) is True
    assert _agent_execute_require_interaction({
        "messages": [], "require_interaction": False,
    }) is False
    for invalid in (None, 0, 1, "true", []):
        with pytest.raises(WorkspaceOrchestrationError):
            _agent_execute_require_interaction({
                "messages": [], "require_interaction": invalid,
            })


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


def test_interaction_completion_exposes_only_the_card_anchor_in_message_metadata():
    message = workspace_result_to_message(
        WorkspaceTurnResult(
            message={"reply": "请按下方卡片填写。"},
            diagnostics={
                "adapter": "fixed_initial_interaction",
                "interaction_id": "interaction-s0-1",
            },
        ),
        agent_name="陆羽",
    )

    assert message.metadata == {
        "super_expert_interaction_id": "interaction-s0-1",
    }


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


def test_runtime_deadline_is_host_private_not_request_input(tmp_path):
    transaction = WorkspaceStateTransaction.begin(
        tmp_path / "state-store", installation_id="installation-1",
        session_id="session-1", invocation_id="inv-private-deadline",
    )
    request = _request_for(transaction)

    assert "_runtime_deadline_monotonic" not in request.model_dump()
    with pytest.raises(ValidationError):
        WorkspaceTurnRequest(**{
            **request.model_dump(),
            "_runtime_deadline_monotonic": 999999999.0,
        })


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
async def test_configured_runtime_checkpoints_before_host_deadline(tmp_path):
    """A later slow owner must not erase an earlier validated owner commit."""
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)
    for skill in ("interview", "diagnose"):
        path = workspace / "skills" / skill / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {skill}\nUse only supplied evidence.\n")
    definition = {
        "id": "deadline-flow", "version": "3.0.0", "entry_node": "collect", "nodes": [
            {"id": "collect", "goal": "collect", "main_skill": "interview",
             "collect_fields": ["business"],
             "fact_policies": {"business": {"sources": ["customer"], "allow_unknown": False}},
             "required_methods": [], "dimensions": [], "support_skills": [],
             "next_node": "decide", "return_nodes": []},
            {"id": "decide", "goal": "decide", "main_skill": "diagnose",
             "collect_fields": [], "required_methods": [], "dimensions": [],
             "support_skills": [], "next_node": None, "return_nodes": []},
        ],
    }
    (workspace / "config" / "flow.json").write_text(json.dumps(definition))
    _write_runtime(workspace, """
        from pathlib import Path
        import json
        from qwenpaw.app.workspace.flow_runtime import ConfiguredFlowRuntime
        def create_runtime():
            root = Path(__file__).resolve().parent
            definition = json.loads((root / "config" / "flow.json").read_text())
            return ConfiguredFlowRuntime(root, definition, contract_driven=True)
    """)
    transaction = WorkspaceStateTransaction.begin(
        tmp_path / "state-store", installation_id="installation-1",
        session_id="session-1", invocation_id="inv-budget",
    )

    async def execute(arguments):
        payload = json.loads(arguments["messages"][-1]["content"])
        if payload["operation"] == "generate" and payload["node"]["id"] == "decide":
            await asyncio.sleep(1)
        if payload["operation"] == "generate":
            return {"text": json.dumps({"candidate": {
                "reply": "business captured", "facts": {"business": {
                    "value": "English lessons", "source": "customer",
                    "status": "known", "quote": "English lessons"}},
                "outcomes": {}, "node_completed": True,
                "interaction": {"kind": "none"}, "actions": []},
                "methods": {}, "support_requests": []})}
        return {"text": json.dumps({
            "candidate_digest": payload["candidate_digest"], "acceptable": True,
            "context_revision": payload["context"]["revision"],
            "context_node": payload["node"]["id"], "facts_valid": True,
            "reply_valid": True, "dimensions": {}, "issues": []})}

    orchestrator = WorkspaceTurnOrchestrator(
        workspace_root=workspace,
        config=OrchestrationConfig.model_validate(_orchestration()),
        signed_files=frozenset({"runtime.py"}), execute_agent=execute,
        session_context=lambda: {}, timeout_seconds=0.15,
    )
    request = _request_for(transaction, normalized_input={"messages": [{
        "name": "user", "role": "user", "content": "English lessons"}]})

    result = await orchestrator.invoke(request, transaction)

    assert result.error_code is None
    saved = json.loads((transaction.state_root / "configured-flow.json").read_text())
    assert saved["revision"] == 1 and saved["current_node"] == "decide"
    assert saved["recovery"] == {"node_id": "decide", "reason": "turn_budget_exhausted"}


@pytest.mark.asyncio
async def test_one_inbound_turn_automatically_resumes_checkpointed_next_owner(tmp_path):
    workspace = tmp_path / "workspace"
    (workspace / "config").mkdir(parents=True)
    for skill in ("interview", "diagnose"):
        path = workspace / "skills" / skill / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {skill}\nUse only supplied evidence.\n")
    definition = {
        "id": "continuation-flow", "version": "3.0.0", "entry_node": "collect", "nodes": [
            {"id": "collect", "goal": "collect", "main_skill": "interview",
             "collect_fields": ["business"],
             "fact_policies": {"business": {"sources": ["customer"], "allow_unknown": False}},
             "required_methods": [], "dimensions": [], "support_skills": [],
             "next_node": "decide", "return_nodes": []},
            {"id": "decide", "goal": "decide", "main_skill": "diagnose",
             "collect_fields": [], "required_methods": [], "dimensions": [],
             "support_skills": [], "next_node": None, "return_nodes": []},
        ],
    }
    (workspace / "config" / "flow.json").write_text(json.dumps(definition))
    _write_runtime(workspace, """
        from pathlib import Path
        import json
        from qwenpaw.app.workspace.flow_runtime import ConfiguredFlowRuntime
        def create_runtime():
            root = Path(__file__).resolve().parent
            return ConfiguredFlowRuntime(root, json.loads((root / "config" / "flow.json").read_text()), contract_driven=True)
    """)

    class Formatter:
        async def format(self, *, msgs):
            return msgs

    class DirectModel:
        stream = False
        model_key = "openai-compatible:fixture"

        def __init__(self, owner):
            self.owner = owner

        async def __call__(self, prompt, **kwargs):
            message = await self.owner(prompt)
            return SimpleNamespace(id="fixture", content=[{
                "type": "text", "text": message.get_text_content(),
            }])

    class Agent:

        def __init__(self):
            self.slow_calls = 0
            self.decide_customer_texts = []
            self.formatter = Formatter()
            self.model = DirectModel(self)

        async def __call__(self, messages):
            payload = next(json.loads(message.get_text_content()) for message in messages
                           if message.name == "node_context")
            operation = payload["operation"]
            if operation == "generate":
                node_id = payload["node"]["id"]
                if node_id == "decide":
                    self.decide_customer_texts.append(payload["customer_text"])
                    if self.slow_calls == 0:
                        self.slow_calls += 1
                        await asyncio.sleep(1)
                facts = ({"business": {"value": "English lessons", "source": "customer",
                          "status": "known", "quote": "English lessons"}}
                         if node_id == "collect" else {})
                value = {"candidate": {"reply": f"done:{node_id}", "facts": facts,
                    "outcomes": {}, "node_completed": True,
                    "interaction": {"kind": "none"}, "actions": []},
                    "methods": {}, "support_requests": []}
            elif operation == "assess":
                value = {"candidate_digest": payload["candidate_digest"], "acceptable": True,
                    "context_revision": payload["context"]["revision"],
                    "context_node": payload["node"]["id"], "facts_valid": True,
                    "reply_valid": True, "dimensions": {}, "issues": []}
            elif operation == "render":
                value = {"reply": "final decision"}
            else:
                value = {"valid": True, "issues": []}
            return Msg(name="assistant", role="assistant", content=json.dumps(value))

    agent = Agent()
    authorization = AuthorizedWorkspaceRelease(
        installation_id="installation-1", release_id="release-1",
        release_digest=f"sha256:{'a' * 64}",
        granted_capabilities={capability: "1" for capability in HOST_CAPABILITIES_V1},
        signed_workspace_files=frozenset({"runtime.py"}),
    )
    inbound = [Msg(name="user", role="user", content="English lessons")]

    result = await run_workspace_orchestration_turn(
        agent=agent, original_messages=inbound,
        request=SimpleNamespace(session_id="session-1", user_id="user-1", channel="console"),
        agent_id="generic-agent", workspace_root=workspace,
        state_storage_root=tmp_path / "state-store",
        config=OrchestrationConfig.model_validate(_orchestration()),
        authorization=authorization, timeout_seconds=0.15,
    )

    assert result.error_code is None and result.message == {"reply": "final decision"}
    state_files = list((tmp_path / "state-store" / "state").rglob("configured-flow.json"))
    saved = json.loads(state_files[0].read_text())
    assert saved["revision"] == 2 and saved["status"] == "completed"
    assert [item["node_id"] for item in saved["history"]] == ["collect", "decide"]
    assert agent.decide_customer_texts == ["", ""]
    assert inbound[0].get_text_content() == "English lessons"


@pytest.mark.asyncio
async def test_automatic_continuation_does_not_reapply_conversation_reset(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(workspace, """
        import json
        from pathlib import Path
        class Runtime:
            async def handle(self, request, host):
                path = Path(request.transaction_root) / "reset-count.json"
                count = json.loads(path.read_text()) if path.exists() else 0
                if request.safe_metadata.get("conversationReset") is True:
                    count += 1
                path.write_text(json.dumps(count))
                continued = getattr(request, "_runtime_continuation", False)
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": {"reply": (request.safe_metadata.get("platformEvents", [{}])[0].get("event_id", "missing")
                                           if continued else "checkpoint")},
                    "diagnostics": ({} if continued else {"continuation_reason": "turn_budget_exhausted"}),
                })
        def create_runtime(): return Runtime()
    """)
    authorization = AuthorizedWorkspaceRelease(
        installation_id="installation-1", release_id="release-1",
        release_digest=f"sha256:{'a' * 64}",
        granted_capabilities={capability: "1" for capability in HOST_CAPABILITIES_V1},
        signed_workspace_files=frozenset({"runtime.py"}),
    )
    result = await run_workspace_orchestration_turn(
        agent=lambda _: None,
        original_messages=[Msg(name="user", role="user", content="reset and analyze")],
        request=SimpleNamespace(session_id="session-1", user_id="user-1", channel="console"),
        agent_id="generic-agent", workspace_root=workspace,
        state_storage_root=tmp_path / "state-store",
        config=OrchestrationConfig.model_validate(_orchestration()),
        authorization=authorization, safe_metadata={
            "conversationReset": True, "platformEvents": [{"event_id": "evidence-1"}],
        }, timeout_seconds=0.15,
    )
    state_file = next((tmp_path / "state-store" / "state").rglob("reset-count.json"))
    assert result.message == {"reply": "evidence-1"}
    assert json.loads(state_file.read_text()) == 1


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
async def test_runner_adapter_can_opt_into_the_standard_agent_loop(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        class Runtime:
            async def handle(self, request, host):
                candidate = await host.call("agent.execute", {
                    "messages": request.normalized_input["messages"],
                    "execution_mode": "agent_loop",
                })
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": candidate["message"],
                })
        def create_runtime(): return Runtime()
        """,
    )

    class DirectModel:
        model_key = "deepseek:test"

        async def __call__(self, *_args, **_kwargs):
            raise AssertionError("agent_loop must not bypass the Agent")

    class Agent:
        formatter = SimpleNamespace(format=lambda **_kwargs: None)
        model = DirectModel()

        def __init__(self):
            self.calls = []

        async def __call__(self, messages):
            self.calls.append(messages)
            return Msg(
                name="assistant",
                role="assistant",
                content="full agent loop",
            )

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

    assert result.message["content"] == "full agent loop"
    assert len(agent.calls) == 1
    assert agent.calls[0][0].get_text_content() == "hello"


@pytest.mark.asyncio
async def test_agent_loop_applies_runtime_instruction_at_system_authority_and_restores_it(
    tmp_path,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        class Runtime:
            async def handle(self, request, host):
                candidate = await host.call("agent.execute", {
                    "messages": request.normalized_input["messages"],
                    "execution_mode": "agent_loop",
                    "instruction": "KEEP THE EXISTING CARD",
                })
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": candidate["message"],
                })
        def create_runtime(): return Runtime()
        """,
    )
    system = Msg(name="agent", role="system", content="ORIGINAL")

    class Agent:
        formatter = SimpleNamespace(format=lambda **_kwargs: None)
        model = SimpleNamespace(model_key="deepseek:test")

        def __init__(self):
            self._sys_prompt = "ORIGINAL"
            self.memory = SimpleNamespace(content=[(system, None)])
            self.calls = []

        def _build_sys_prompt(self):
            return "ORIGINAL"

        async def __call__(self, messages):
            self._sys_prompt = self._build_sys_prompt()
            assert "KEEP THE EXISTING CARD" in self._sys_prompt
            assert "KEEP THE EXISTING CARD" in system.get_text_content()
            self.calls.append(messages)
            return Msg(name="assistant", role="assistant", content="done")

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

    assert result.message["content"] == "done"
    assert agent._sys_prompt == "ORIGINAL"
    assert system.get_text_content() == "ORIGINAL"
    assert len(agent.calls) == 1
    assert [message.role for message in agent.calls[0]] == ["user"]


@pytest.mark.asyncio
async def test_agent_loop_can_require_a_real_interaction_before_text(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        class Runtime:
            async def handle(self, request, host):
                candidate = await host.call("agent.execute", {
                    "messages": request.normalized_input["messages"],
                    "execution_mode": "agent_loop",
                    "require_interaction": True,
                })
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": candidate["message"],
                })
        def create_runtime(): return Runtime()
        """,
    )
    active_card = None

    class Agent:
        formatter = SimpleNamespace(format=lambda **_kwargs: None)
        model = SimpleNamespace(model_key="deepseek:test")

        def __init__(self):
            self._sys_prompt = "ORIGINAL"
            self.memory = SimpleNamespace(content=[])
            self.reasoning_choices = []

        def _build_sys_prompt(self):
            return "ORIGINAL"

        async def _reasoning(self, tool_choice=None):
            nonlocal active_card
            self.reasoning_choices.append(tool_choice)
            if len(self.reasoning_choices) == 1:
                active_card = {"interaction_id": "interaction-1", "status": "PENDING"}
            return None

        async def __call__(self, _messages):
            await self._reasoning()
            await self._reasoning()
            return Msg(name="assistant", role="assistant", content="card ready")

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
        original_messages=[Msg(name="user", role="user", content="开始")],
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
        read_interaction_card=lambda _interaction_id: active_card,
    )

    assert result.message["content"] == "card ready"
    assert agent.reasoning_choices == ["required", None]
    assert agent._reasoning.__func__ is Agent._reasoning


@pytest.mark.asyncio
async def test_local_raw_model_trace_records_each_agent_execute_request_and_response(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("DCLAW_WORKSPACE_MODEL_TRACE_RAW", "true")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_runtime(
        workspace,
        """
        class Runtime:
            async def handle(self, request, host):
                candidate = await host.call("agent.execute", {
                    "messages": [{"name": "runtime", "role": "system", "content": "Return JSON"}],
                    "response_format": "json_object",
                })
                await host.call("runtime.complete", {
                    "invocation_id": request.invocation_id,
                    "message": {"reply": candidate["text"]},
                })
        def create_runtime(): return Runtime()
        """,
    )

    class Formatter:
        async def format(self, *, msgs):
            return msgs

    class Model:
        stream = False
        model_key = "deepseek:test"

        async def __call__(self, prompt, **kwargs):
            return SimpleNamespace(
                id="response-raw-1",
                content=[{"type": "text", "text": '{"reply":"第一段\\\\n第二段"}'}],
            )

    authorization = AuthorizedWorkspaceRelease(
        installation_id="installation-1",
        release_id="release-1",
        release_digest=f"sha256:{'a' * 64}",
        granted_capabilities={
            capability: "1" for capability in HOST_CAPABILITIES_V1
        },
        signed_workspace_files=frozenset({"runtime.py"}),
    )
    storage = tmp_path / "state-store"

    result = await run_workspace_orchestration_turn(
        agent=SimpleNamespace(
            name="agent", formatter=Formatter(), model=Model(),
        ),
        original_messages=[Msg(name="user", role="user", content="开始")],
        request=SimpleNamespace(
            session_id="session-1", user_id="user-1", channel="console",
        ),
        agent_id="luyu_traffic_operator",
        workspace_root=workspace,
        state_storage_root=storage,
        config=OrchestrationConfig.model_validate(_orchestration()),
        authorization=authorization,
    )

    assert result.message == {"reply": '{"reply":"第一段\\\\n第二段"}'}
    events = [
        json.loads(line)
        for line in runtime_trace_path(
            storage,
            installation_id="installation-1",
            session_id="session-1",
        ).read_text(encoding="utf-8").splitlines()
    ]
    started = next(event for event in events if event["event_type"] == "agent.execute.started")
    completed = next(event for event in events if event["event_type"] == "agent.execute.completed")
    assert started["payload"]["call_number"] == 1
    assert started["payload"]["response_format"] == "json_object"
    assert started["payload"]["model_key"] == "deepseek:test"
    assert started["payload"]["messages"][0]["content"] == "Return JSON"
    assert completed["payload"]["call_id"] == started["payload"]["call_id"]
    assert completed["payload"]["response_id"] == "response-raw-1"
    assert completed["payload"]["text"] == '{"reply":"第一段\\\\n第二段"}'
    assert completed["payload"]["has_text"] is True
    assert completed["payload"]["duration_ms"] >= 0


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
