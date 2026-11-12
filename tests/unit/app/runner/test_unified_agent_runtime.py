from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import Msg

from qwenpaw.app.runner import runner as runner_module
from qwenpaw.app.runner.runner import AgentRunner
from qwenpaw.config.config import OrchestrationConfig
from qwenpaw.app.workspace import orchestration as orchestration_module
from qwenpaw.app.workspace.orchestration import WorkspaceTurnResult
from qwenpaw.app.super_experts.models import AigcTaskBinding, AigcTaskStatus
from qwenpaw.app.sealed_agents import registry as registry_module
from qwenpaw.plugins.registry import PluginRegistry


@pytest.fixture(autouse=True)
def _registered_workspace_turn_handler():
    registry = PluginRegistry()
    previous = registry._workspace_turn_handlers.copy()
    registry._workspace_turn_handlers.clear()
    registry.register_workspace_turn_handler(
        "test.super-agent-support",
        "workspace.turn.orchestrate/1",
        orchestration_module.handle_workspace_turn,
    )
    try:
        yield
    finally:
        registry._workspace_turn_handlers = previous


def _request():
    return SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )


def _command_message():
    return Msg(name="user", role="user", content="/new")


@pytest.mark.parametrize(
    "capability",
    ["aigc.review.complete", "aigc.asset.submit"],
)
def test_retired_aigc_write_returns_owned_read_only_receipt(capability):
    binding = AigcTaskBinding(
        installation_id="installation-1",
        conversation_id="session-1",
        agent_task_id="content-1",
        content_revision=1,
        material_task_id="material-1",
        canvas_id="canvas-1",
        node_id="output-1",
    )
    task = SimpleNamespace(
        binding=binding,
        status=AigcTaskStatus.IN_PROGRESS,
    )
    service = SimpleNamespace(
        get_task=lambda task_id: task if task_id == "material-1" else None,
    )

    receipt = orchestration_module._retired_aigc_write_receipt(
        capability=capability,
        arguments={"binding": binding.model_dump(mode="json")},
        platform_service=service,
        installation_id="installation-1",
        conversation_id="session-1",
    )

    assert receipt == {
        "contract": capability,
        "status": "IN_PROGRESS",
        "write_applied": False,
        "customer_action_required": True,
        "compatibility_mode": "legacy_read_only",
        "completion_source": None,
        "review_performed": False,
        "material_task_id": "material-1",
        "task_status": "IN_PROGRESS",
    }
    assert task.status == AigcTaskStatus.IN_PROGRESS


@pytest.mark.parametrize(
    "binding_change",
    [
        {"installation_id": "installation-2"},
        {"conversation_id": "session-2"},
        {"canvas_id": "canvas-2"},
    ],
)
def test_retired_aigc_write_does_not_disclose_mismatched_task(binding_change):
    binding = AigcTaskBinding(
        installation_id="installation-1",
        conversation_id="session-1",
        agent_task_id="content-1",
        content_revision=1,
        material_task_id="material-1",
        canvas_id="canvas-1",
        node_id="output-1",
    )
    task = SimpleNamespace(
        binding=binding,
        status=AigcTaskStatus.ACCEPTED,
    )
    candidate = binding.model_dump(mode="json")
    candidate.update(binding_change)

    receipt = orchestration_module._retired_aigc_write_receipt(
        capability="aigc.review.complete",
        arguments={"binding": candidate},
        platform_service=SimpleNamespace(get_task=lambda _task_id: task),
        installation_id="installation-1",
        conversation_id="session-1",
    )

    assert receipt == {
        "contract": "aigc.review.complete",
        "status": "retired",
        "write_applied": False,
        "customer_action_required": True,
    }


def test_retired_aigc_write_does_not_request_action_for_accepted_task():
    binding = AigcTaskBinding(
        installation_id="installation-1",
        conversation_id="session-1",
        agent_task_id="content-1",
        content_revision=1,
        material_task_id="material-1",
        canvas_id="canvas-1",
        node_id="output-1",
    )
    task = SimpleNamespace(binding=binding, status=AigcTaskStatus.ACCEPTED)

    receipt = orchestration_module._retired_aigc_write_receipt(
        capability="aigc.review.complete",
        arguments={"binding": binding.model_dump(mode="json")},
        platform_service=SimpleNamespace(get_task=lambda _task_id: task),
        installation_id="installation-1",
        conversation_id="session-1",
    )

    assert receipt["status"] == "ACCEPTED"
    assert receipt["task_status"] == "ACCEPTED"
    assert receipt["compatibility_mode"] == "legacy_read_only"
    assert receipt["completion_source"] == "customer"
    assert receipt["review_performed"] is False
    assert receipt["write_applied"] is False
    assert receipt["customer_action_required"] is False


@pytest.mark.asyncio
async def test_sealed_agent_uses_the_same_command_path(monkeypatch):
    class SealedRegistry:
        def is_sealed(self, _agent_id):
            return True

    command_result = Msg(
        name="assistant",
        role="assistant",
        content="ordinary command response",
    )

    async def fake_command_path(_request, _messages, _runner):
        yield command_result, True

    monkeypatch.setattr(
        registry_module,
        "get_sealed_agent_registry",
        lambda: SealedRegistry(),
    )
    monkeypatch.setattr(
        runner_module,
        "run_command_path",
        fake_command_path,
    )
    runtime = AgentRunner(agent_id="sealed-agent")

    actual = [
        item
        async for item in runtime.query_handler(
            [_command_message()],
            _request(),
        )
    ]

    assert actual == [(command_result, True)]


@pytest.mark.asyncio
async def test_ordinary_agent_command_never_reads_sealed_registry(monkeypatch):
    def fail_registry_lookup():
        pytest.fail("ordinary Runner must not read sealed Registry")

    command_result = Msg(
        name="assistant",
        role="assistant",
        content="ordinary command response",
    )

    async def fake_command_path(_request, _messages, _runner):
        yield command_result, True

    monkeypatch.setattr(
        registry_module,
        "get_sealed_agent_registry",
        fail_registry_lookup,
    )
    monkeypatch.setattr(
        runner_module,
        "run_command_path",
        fake_command_path,
    )
    runtime = AgentRunner(agent_id="ordinary-agent")

    actual = [
        item
        async for item in runtime.query_handler(
            [_command_message()],
            _request(),
        )
    ]

    assert actual == [(command_result, True)]


@pytest.mark.asyncio
async def test_undeclared_business_turn_uses_exact_standard_agent_path(
    monkeypatch,
    tmp_path,
):
    calls = []

    class Agent:
        async def __call__(self, messages):
            calls.append(messages)
            return Msg(name="assistant", role="assistant", content="standard")

    async def fake_stream(*, agents, coroutine_task):
        assert len(agents) == 1
        yield await coroutine_task, True

    def fail_authorization(**_kwargs):
        pytest.fail(
            "undeclared Agent must not resolve orchestration authorization",
        )

    monkeypatch.setattr(
        runner_module,
        "_stream_printing_messages_interruptible",
        fake_stream,
    )
    monkeypatch.setattr(
        orchestration_module,
        "resolve_active_workspace_authorization",
        fail_authorization,
        raising=False,
    )
    messages = [Msg(name="user", role="user", content="hello")]

    actual = [
        item
        async for item in runner_module._run_standard_or_orchestrated_turn(
            agent=Agent(),
            messages=messages,
            request=_request(),
            query="hello",
            mission_info=None,
            agent_id="ordinary-agent",
            agent_name="Agent",
            workspace_root=tmp_path,
            orchestration=OrchestrationConfig(),
        )
    ]

    assert len(actual) == 1
    assert actual[0][0].content == "standard"
    assert actual[0][1:] == (True, True)
    assert calls == [messages]


@pytest.mark.asyncio
async def test_declared_turn_never_falls_back_to_direct_model_on_failure(
    monkeypatch,
    tmp_path,
):
    class Memory:
        def state_dict(self):
            return {"messages": []}

        def load_state_dict(self, state, *, strict=True):
            assert strict is False
            assert state == {"messages": []}

    class Agent:
        def __init__(self):
            self.memory = Memory()

        async def __call__(self, _messages):
            pytest.fail(
                "Runner must not directly invoke the model as fallback",
            )

    authorization = SimpleNamespace(
        installation_id="installation-1",
        granted_capabilities={},
    )
    monkeypatch.setattr(
        orchestration_module,
        "resolve_active_workspace_authorization",
        lambda **_kwargs: authorization,
        raising=False,
    )
    monkeypatch.setattr(
        orchestration_module,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            get_agent=lambda _agent_id: SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(
        orchestration_module,
        "SuperExpertGrantRepository",
        lambda _root: SimpleNamespace(
            get=lambda _installation_id: SimpleNamespace(),
        ),
    )
    from qwenpaw.app.workspace import orchestration as _workspace_orchestration

    state_continuity = __import__(
        f"{_workspace_orchestration.__package__}.state_continuity",
        fromlist=["ensure_state_continuity"],
    )

    monkeypatch.setattr(
        state_continuity,
        "ensure_state_continuity",
        lambda **_kwargs: None,
    )
    from qwenpaw.app.super_experts import composition as platform_module

    class PlatformService:
        def list_session_events(self, **_kwargs):
            return []

    monkeypatch.setattr(
        platform_module,
        "get_super_expert_platform_service",
        lambda: PlatformService(),
    )

    async def fail_closed(**_kwargs):
        assert callable(_kwargs["business_call"])
        return WorkspaceTurnResult(error_code="orchestration_timeout")

    monkeypatch.setattr(
        orchestration_module,
        "run_workspace_orchestration_turn",
        fail_closed,
        raising=False,
    )
    config = OrchestrationConfig(
        enabled=True,
        contract_version="1",
        entrypoint="runtime.py:create_runtime",
        required_host_capabilities=(
            "agent.execute",
            "session.context",
            "runtime.trace",
            "runtime.complete",
            "runtime.fail",
        ),
    )

    actual = [
        item
        async for item in runner_module._run_standard_or_orchestrated_turn(
            agent=Agent(),
            messages=[Msg(name="user", role="user", content="hello")],
            request=_request(),
            query="hello",
            mission_info=None,
            agent_id="generic-agent",
            agent_name="Generic",
            workspace_root=tmp_path,
            orchestration=config,
        )
    ]

    assert actual[0][0].content == (
        "本轮处理未能安全完成：专家运行失败。请稍后重试；"
        "若再次发生，请联系平台维护人员核查。关联 ID：未生成"
    )
    assert actual[0][1:] == (True, True)


@pytest.mark.asyncio
async def test_declared_turn_passes_loaded_conversation_history_to_runtime(
    monkeypatch,
    tmp_path,
):
    prior_history = [
        Msg(name="user", role="user", content="我是做就业培训的"),
        Msg(name="assistant", role="assistant", content="培训面向哪些人？"),
    ]
    current_messages = [
        Msg(name="user", role="user", content="失业人员，天门市，线下报名"),
    ]

    class Memory:
        def __init__(self):
            self.added = []

        def state_dict(self):
            return {"added": list(self.added)}

        def load_state_dict(self, state, *, strict=True):
            assert strict is False
            self.added = list(state["added"])

        async def get_memory(self, *, prepend_summary=True):
            assert prepend_summary is True
            return prior_history

        async def add(self, message):
            self.added.append(message)

    class Agent:
        def __init__(self):
            self.memory = Memory()

    agent = Agent()

    authorization = SimpleNamespace(
        installation_id="installation-1",
        granted_capabilities={},
    )
    monkeypatch.setattr(
        orchestration_module,
        "resolve_active_workspace_authorization",
        lambda **_kwargs: authorization,
        raising=False,
    )
    monkeypatch.setattr(
        orchestration_module,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            get_agent=lambda _agent_id: SimpleNamespace(),
        ),
    )
    monkeypatch.setattr(
        orchestration_module,
        "SuperExpertGrantRepository",
        lambda _root: SimpleNamespace(
            get=lambda _installation_id: SimpleNamespace(),
        ),
    )
    from qwenpaw.app.workspace import orchestration as _workspace_orchestration

    state_continuity = __import__(
        f"{_workspace_orchestration.__package__}.state_continuity",
        fromlist=["ensure_state_continuity"],
    )

    monkeypatch.setattr(
        state_continuity,
        "ensure_state_continuity",
        lambda **_kwargs: None,
    )
    from qwenpaw.app.super_experts import composition as platform_module

    class PlatformService:
        def list_session_events(self, **_kwargs):
            return []

    monkeypatch.setattr(
        platform_module,
        "get_super_expert_platform_service",
        lambda: PlatformService(),
    )

    async def capture_history(**kwargs):
        assert kwargs["original_messages"] == current_messages
        assert kwargs["conversation_history"] == prior_history
        return WorkspaceTurnResult(
            message={
                "name": "assistant",
                "role": "assistant",
                "content": "继续",
            },
        )

    monkeypatch.setattr(
        orchestration_module,
        "run_workspace_orchestration_turn",
        capture_history,
        raising=False,
    )
    config = OrchestrationConfig(
        enabled=True,
        contract_version="1",
        entrypoint="runtime.py:create_runtime",
        required_host_capabilities=(
            "agent.execute",
            "session.context",
            "runtime.trace",
            "runtime.complete",
            "runtime.fail",
        ),
    )

    actual = [
        item
        async for item in runner_module._run_standard_or_orchestrated_turn(
            agent=agent,
            messages=current_messages,
            request=_request(),
            query="失业人员，天门市，线下报名",
            mission_info=None,
            agent_id="generic-agent",
            agent_name="Generic",
            workspace_root=tmp_path,
            orchestration=config,
        )
    ]

    assert actual[0][0].content == "继续"
    assert actual[0][1:] == (True, True)
    assert agent.memory.added[:1] == current_messages
    assert agent.memory.added[1].role == "assistant"
    assert agent.memory.added[1].content == "继续"


@pytest.mark.asyncio
@pytest.mark.skip(reason="cross-installation Agent review bridge was retired")
async def test_active_release_can_review_a_task_bound_to_its_previous_installation(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.super_experts.models import AigcTaskBinding

    bind_review_input = (
        orchestration_module._media_review_context.bind_review_input
    )

    old_binding = AigcTaskBinding(
        installation_id="old-installation",
        conversation_id="session-1",
        agent_task_id="content-1",
        content_revision=1,
        material_task_id="material-1",
        canvas_id="canvas-1",
        node_id="image-1",
    )
    task = SimpleNamespace(
        binding=old_binding,
        asset_id="asset-1",
        status=SimpleNamespace(value="SUBMITTED"),
        model_dump=lambda **_kwargs: {
            "binding": old_binding.model_dump(mode="json"),
            "asset_id": "asset-1",
            "status": "SUBMITTED",
            "review_assets": [],
        },
    )
    authorization = SimpleNamespace(
        installation_id="active-installation",
        granted_capabilities={"aigc.review.complete": "1"},
    )
    monkeypatch.setattr(
        orchestration_module,
        "resolve_active_workspace_authorization",
        lambda **_kwargs: authorization,
        raising=False,
    )
    calls = []

    class Tasks:
        def get(self, material_task_id):
            return task if material_task_id == "material-1" else None

    class PlatformService:
        task_repository = Tasks()

        def list_session_events(self, **_kwargs):
            return []

        async def execute(self, **kwargs):
            calls.append(kwargs)
            return {"task": task}

    from qwenpaw.app.super_experts import composition as platform_module

    monkeypatch.setattr(
        platform_module,
        "get_super_expert_platform_service",
        lambda: PlatformService(),
    )

    async def exercise_review_bridge(**kwargs):
        review_input = kwargs["safe_metadata"].get("aigcReviewInput")
        assert review_input["binding"]["installation_id"] == "old-installation"
        assert kwargs["read_aigc_task"]("material-1")["asset_id"] == "asset-1"
        await kwargs["business_call"](
            "aigc.review.complete",
            {
                "idempotency_key": "review-1",
                "event_id": "review-1",
                "binding": old_binding.model_dump(mode="json"),
                "asset_id": "asset-1",
                "decision": "ACCEPTED",
                "payload": {"assessment": "可用"},
            },
        )
        return WorkspaceTurnResult(
            message={
                "name": "assistant",
                "role": "assistant",
                "content": "审核完成",
            },
        )

    monkeypatch.setattr(
        orchestration_module,
        "run_workspace_orchestration_turn",
        exercise_review_bridge,
        raising=False,
    )
    config = OrchestrationConfig(
        enabled=True,
        contract_version="1",
        entrypoint="runtime.py:create_runtime",
        required_host_capabilities=(
            "agent.execute",
            "session.context",
            "runtime.trace",
            "runtime.complete",
            "runtime.fail",
        ),
    )
    request = _request()
    request.tenant_id = "local"

    with bind_review_input(
        user_id="user-1",
        binding=old_binding,
        asset_id="asset-1",
        media_block={
            "type": "image",
            "source": {
                "type": "url",
                "url": "https://example.test/review.png",
            },
        },
        runtime_installation_id="active-installation",
    ):
        actual = [
            item
            async for item in runner_module._run_standard_or_orchestrated_turn(
                agent=SimpleNamespace(memory=None),
                messages=[Msg(name="user", role="user", content="审核")],
                request=request,
                query="审核",
                mission_info=None,
                agent_id="expert",
                agent_name="Expert",
                workspace_root=tmp_path,
                orchestration=config,
            )
        ]

    assert actual[0][0].content == "审核完成"
    assert calls[0]["installation_id"] == "old-installation"
