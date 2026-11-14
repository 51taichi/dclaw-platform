from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.memory import InMemoryMemory
from agentscope.message import Msg

from super_agent import orchestration


def test_failed_turn_notice_uses_safe_category_action_and_invocation_id():
    result = orchestration.WorkspaceTurnResult(
        error_code="INVALID_TURN_RESULT",
        invocation_id="invocation-123",
        diagnostics={"first_failure": {
            "phase": "model_validation", "category": "json_parse", "attempt": 1,
        }},
    )
    notice = orchestration.workspace_result_to_message(result, agent_name="Expert")
    assert "专家输出格式校验失败" in notice.get_text_content()
    assert "联系专家开发者" in notice.get_text_content()
    assert "invocation-123" in notice.get_text_content()
    assert notice.metadata["dclaw_failure"] == {
        "invocation_id": "invocation-123", "error_code": "INVALID_TURN_RESULT",
        "phase": "model_validation", "category": "json_parse", "attempt": 1,
    }


def _allow_state_preflight(monkeypatch):
    from super_agent import state_continuity

    monkeypatch.setattr(
        orchestration, "get_sealed_agent_registry",
        lambda: SimpleNamespace(get_agent=lambda _: SimpleNamespace()),
    )
    monkeypatch.setattr(
        orchestration, "SuperExpertGrantRepository",
        lambda _: SimpleNamespace(get=lambda __: SimpleNamespace()),
    )
    monkeypatch.setattr(
        state_continuity, "ensure_state_continuity", lambda **_: None,
    )


@pytest.mark.asyncio
async def test_preflight_failure_remains_in_chat_history(monkeypatch, tmp_path):
    memory = InMemoryMemory()
    prior = Msg(name="assistant", role="assistant", content="prior reply")
    await memory.add(prior)

    def reject_release(**_):
        raise orchestration.WorkspaceOrchestrationError("orchestration_error")

    monkeypatch.setattr(
        orchestration, "resolve_active_workspace_authorization", reject_release,
    )
    incoming = Msg(name="user", role="user", content="continue")
    result = [
        item async for item in orchestration.handle_workspace_turn(
            agent=SimpleNamespace(memory=memory),
            messages=[incoming],
            request=SimpleNamespace(session_id="task", user_id="user", tenant_id="local"),
            query="continue",
            mission_info=None,
            agent_id="comic",
            agent_name="Comic",
            workspace_root=tmp_path,
            orchestration=SimpleNamespace(),
            standard_stream=None,
        )
    ]

    assert len(result) == 1
    response, last, should_save_session = result[0]
    assert last is True and should_save_session is True
    assert [item[0].id for item in memory.content] == [
        prior.id, incoming.id, response.id,
    ]
    assert "本轮处理未能安全完成" in response.get_text_content()


@pytest.mark.asyncio
async def test_local_host_dispatch_uses_the_turn_invocation_id(monkeypatch, tmp_path):
    from super_agent import aigc_assets, aigc_binding, local_host

    _allow_state_preflight(monkeypatch)
    authorization = SimpleNamespace(
        installation_id="installation", release_id="release",
        granted_capabilities={
            "aigc.task.assets.localize/1": "1",
            "local.task.start/1": "1",
        },
    )
    monkeypatch.setattr(
        orchestration, "resolve_active_workspace_authorization",
        lambda **_: authorization,
    )
    task = SimpleNamespace(binding=SimpleNamespace(installation_id="installation"))
    service = SimpleNamespace(
        list_session_events=lambda **_: [], interactions=None,
        get_task=lambda _: task, aigc=object(),
    )
    monkeypatch.setattr(
        orchestration._composition, "get_super_expert_platform_service",
        lambda: service,
    )
    monkeypatch.setattr(
        orchestration._media_review_context, "current_review_input",
        lambda **_: None,
    )
    monkeypatch.setattr(aigc_binding, "compatible_installations", lambda **_: {"installation"})
    monkeypatch.setattr(aigc_binding, "owned_task", lambda **_: True)
    monkeypatch.setattr(
        aigc_assets, "prepare_owned_aigc_localization",
        lambda **_: [{"asset_id": "asset-1"}],
    )

    async def verified(_):
        return None

    monkeypatch.setattr(aigc_assets, "verify_public_aigc_localization", verified)
    dispatches = []

    async def localize(**kwargs):
        dispatches.append(("aigc", kwargs["invocation_id"]))
        return {"contract": "local.task.receipt/1", "status": "accepted"}

    async def local_task(**kwargs):
        dispatches.append(("local", kwargs["invocation_id"]))
        return {"contract": "local.task.receipt/1", "status": "accepted"}

    monkeypatch.setattr(local_host, "dispatch_aigc_asset_localization", localize)
    monkeypatch.setattr(local_host, "dispatch_local_task", local_task)

    async def stream(**kwargs):
        await kwargs["business_call"]("aigc.task.assets.localize/1", {
            "material_task_id": "material-1", "assets": [{"asset_id": "asset-1"}],
            "idempotency_key": "localize-1",
        })
        await kwargs["business_call"]("local.task.start/1", {})
        yield True, orchestration.WorkspaceTurnResult(
            message={"reply": "accepted"}, invocation_id=kwargs["invocation_id"],
        )

    monkeypatch.setattr(orchestration._public_stream, "stream_workspace_turn", stream)
    result = [item async for item in orchestration.handle_workspace_turn(
        agent=SimpleNamespace(memory=InMemoryMemory()),
        messages=[Msg(name="user", role="user", content="download")],
        request=SimpleNamespace(session_id="task", user_id="user", tenant_id="local"),
        query="download", mission_info=None, agent_id="comic",
        agent_name="Comic", workspace_root=tmp_path,
        orchestration=SimpleNamespace(), standard_stream=None,
    )]
    assert result[-1][0].get_text_content() == "accepted"
    assert len(dispatches) == 2
    assert dispatches[0][1] == dispatches[1][1]
    assert len(dispatches[0][1]) == 32


@pytest.mark.asyncio
async def test_incompatible_state_blocks_runtime_and_records_category(monkeypatch, tmp_path):
    from super_agent import state_continuity

    memory = InMemoryMemory()
    traces = []
    monkeypatch.setattr(
        orchestration, "_append_runtime_trace",
        lambda *_, **payload: traces.append(payload),
    )
    monkeypatch.setattr(
        orchestration, "resolve_active_workspace_authorization",
        lambda **_: SimpleNamespace(installation_id="installation", granted_capabilities={}),
    )
    monkeypatch.setattr(
        orchestration, "get_sealed_agent_registry",
        lambda: SimpleNamespace(get_agent=lambda _: SimpleNamespace(
            active_release=SimpleNamespace(),
        )),
    )
    monkeypatch.setattr(
        orchestration, "SuperExpertGrantRepository",
        lambda _: SimpleNamespace(
            get=lambda __: SimpleNamespace(installation_id="installation"),
            find_release_grant=lambda *_, **__: SimpleNamespace(
                installation_id="installation",
            ),
        ),
    )
    monkeypatch.setattr(
        state_continuity, "ensure_state_continuity",
        lambda **_: (_ for _ in ()).throw(
            state_continuity.StateContinuityError("state_schema_incompatible"),
        ),
    )
    async def no_runtime(**_):
        pytest.fail("incompatible state must block runtime")
        yield
    monkeypatch.setattr(orchestration._public_stream, "stream_workspace_turn", no_runtime)
    result = [item async for item in orchestration.handle_workspace_turn(
        agent=SimpleNamespace(memory=memory),
        messages=[Msg(name="user", role="user", content="continue")],
        request=SimpleNamespace(session_id="task", user_id="user", tenant_id="local"),
        query="continue", mission_info=None, agent_id="comic",
        agent_name="Comic", workspace_root=tmp_path,
        orchestration=SimpleNamespace(), standard_stream=None,
    )]
    assert len(result) == 1
    assert "本轮处理未能安全完成" in result[0][0].get_text_content()
    assert traces[0]["payload"]["category"] == "state_schema_incompatible"


@pytest.mark.asyncio
async def test_missing_legacy_state_contract_falls_back_to_standard_agent(
    monkeypatch,
    tmp_path,
):
    from super_agent import state_continuity

    memory = InMemoryMemory()
    incoming = Msg(name="user", role="user", content="今日话题")
    calls = []

    class Agent:
        def __init__(self):
            self.memory = memory

        async def __call__(self, messages):
            calls.append(messages)

    agent = Agent()
    monkeypatch.setattr(
        orchestration,
        "resolve_active_workspace_authorization",
        lambda **_: SimpleNamespace(
            installation_id="installation", granted_capabilities={},
        ),
    )
    monkeypatch.setattr(
        orchestration, "get_sealed_agent_registry",
        lambda: SimpleNamespace(get_agent=lambda _: SimpleNamespace()),
    )
    monkeypatch.setattr(
        orchestration, "SuperExpertGrantRepository",
        lambda _: SimpleNamespace(get=lambda __: SimpleNamespace()),
    )
    monkeypatch.setattr(
        state_continuity, "ensure_state_continuity",
        lambda **_: (_ for _ in ()).throw(
            state_continuity.StateContinuityError("state_contract_missing"),
        ),
    )

    async def no_super_agent_runtime(**_):
        pytest.fail("legacy compatibility must use the standard Agent path")
        yield

    monkeypatch.setattr(
        orchestration._public_stream,
        "stream_workspace_turn",
        no_super_agent_runtime,
    )

    async def standard_stream(*, agents, coroutine_task):
        assert agents == [agent]
        await coroutine_task
        yield Msg(name="Comic", role="assistant", content="基础专家回复"), True

    result = [item async for item in orchestration.handle_workspace_turn(
        agent=agent,
        messages=[incoming],
        request=SimpleNamespace(
            session_id="legacy-task", user_id="user", tenant_id="local",
        ),
        query="今日话题",
        mission_info=None,
        agent_id="comic",
        agent_name="Comic",
        workspace_root=tmp_path,
        orchestration=SimpleNamespace(),
        standard_stream=standard_stream,
    )]

    assert calls == [[incoming]]
    assert len(result) == 1
    response, last, should_save_session = result[0]
    assert response.get_text_content() == "基础专家回复"
    assert last is True
    assert should_save_session is True


@pytest.mark.asyncio
async def test_failed_runtime_restores_memory_before_persisting_reply(monkeypatch, tmp_path):
    _allow_state_preflight(monkeypatch)
    memory = InMemoryMemory()
    prior = [
        Msg(name="user", role="user", content=f"request {index}")
        for index in range(12)
    ]
    for message in prior:
        await memory.add(message)

    monkeypatch.setattr(
        orchestration,
        "resolve_active_workspace_authorization",
        lambda **_: SimpleNamespace(
            installation_id="installation", granted_capabilities={},
        ),
    )
    monkeypatch.setattr(
        orchestration._composition,
        "get_super_expert_platform_service",
        lambda: SimpleNamespace(list_session_events=lambda **_: []),
    )
    monkeypatch.setattr(
        orchestration._media_review_context,
        "current_review_input", lambda **_: None,
    )

    async def failed_stream(**_):
        memory.content = memory.content[-2:]
        yield True, orchestration.WorkspaceTurnResult(
            error_code="invalid_turn_result",
        )

    monkeypatch.setattr(
        orchestration._public_stream,
        "stream_workspace_turn", failed_stream,
    )
    incoming = Msg(name="user", role="user", content="new request")
    result = [
        item async for item in orchestration.handle_workspace_turn(
            agent=SimpleNamespace(memory=memory),
            messages=[incoming],
            request=SimpleNamespace(session_id="task", user_id="user", tenant_id="local"),
            query="new request",
            mission_info=None,
            agent_id="comic",
            agent_name="Comic",
            workspace_root=tmp_path,
            orchestration=SimpleNamespace(),
            standard_stream=None,
        )
    ]

    response, last, should_save_session = result[0]
    assert last is True and should_save_session is True
    assert [item[0].id for item in memory.content] == [
        *(message.id for message in prior), incoming.id, response.id,
    ]


@pytest.mark.asyncio
async def test_completed_runtime_does_not_persist_internal_candidate(monkeypatch, tmp_path):
    _allow_state_preflight(monkeypatch)
    memory = InMemoryMemory()
    prior = Msg(name="user", role="user", content="prior request")
    await memory.add(prior)
    monkeypatch.setattr(
        orchestration, "resolve_active_workspace_authorization",
        lambda **_: SimpleNamespace(
            installation_id="installation", granted_capabilities={},
        ),
    )
    monkeypatch.setattr(
        orchestration._composition, "get_super_expert_platform_service",
        lambda: SimpleNamespace(list_session_events=lambda **_: []),
    )
    monkeypatch.setattr(
        orchestration._media_review_context, "current_review_input",
        lambda **_: None,
    )

    async def completed_stream(**_):
        await memory.add(Msg(name="workspace_runtime", role="system", content="internal rule"))
        await memory.add(Msg(name="assistant", role="assistant", content='{"candidate": true}'))
        yield True, orchestration.WorkspaceTurnResult(message={
            "role": "assistant", "name": "Comic", "content": "approved reply",
        })

    monkeypatch.setattr(
        orchestration._public_stream, "stream_workspace_turn", completed_stream,
    )
    incoming = Msg(name="user", role="user", content="new request")
    result = [item async for item in orchestration.handle_workspace_turn(
        agent=SimpleNamespace(memory=memory), messages=[incoming],
        request=SimpleNamespace(session_id="task", user_id="user", tenant_id="local"),
        query="new request", mission_info=None, agent_id="comic",
        agent_name="Comic", workspace_root=tmp_path,
        orchestration=SimpleNamespace(), standard_stream=None,
    )]
    response, last, should_save_session = result[0]
    assert last is True and should_save_session is True
    assert [item[0].id for item in memory.content] == [prior.id, incoming.id, response.id]
    assert response.get_text_content() == "approved reply"


@pytest.mark.asyncio
async def test_unhandled_runtime_exception_restores_memory(monkeypatch, tmp_path):
    _allow_state_preflight(monkeypatch)
    memory = InMemoryMemory()
    prior = Msg(name="user", role="user", content="prior request")
    await memory.add(prior)
    monkeypatch.setattr(
        orchestration,
        "resolve_active_workspace_authorization",
        lambda **_: SimpleNamespace(
            installation_id="installation", granted_capabilities={},
        ),
    )
    monkeypatch.setattr(
        orchestration._composition,
        "get_super_expert_platform_service",
        lambda: SimpleNamespace(list_session_events=lambda **_: []),
    )
    monkeypatch.setattr(
        orchestration._media_review_context,
        "current_review_input", lambda **_: None,
    )

    async def broken_stream(**_):
        memory.content.clear()
        raise RuntimeError("runtime failed")
        yield

    monkeypatch.setattr(
        orchestration._public_stream,
        "stream_workspace_turn", broken_stream,
    )
    with pytest.raises(RuntimeError, match="runtime failed"):
        [
            item async for item in orchestration.handle_workspace_turn(
                agent=SimpleNamespace(memory=memory),
                messages=[Msg(name="user", role="user", content="new request")],
                request=SimpleNamespace(session_id="task", user_id="user", tenant_id="local"),
                query="new request",
                mission_info=None,
                agent_id="comic",
                agent_name="Comic",
                workspace_root=tmp_path,
                orchestration=SimpleNamespace(),
                standard_stream=None,
            )
        ]
    assert [item[0].id for item in memory.content] == [prior.id]


@pytest.mark.asyncio
async def test_unrestorable_memory_does_not_run_workspace_turn(monkeypatch, tmp_path):
    monkeypatch.setattr(
        orchestration,
        "resolve_active_workspace_authorization",
        lambda **_: pytest.fail("workspace turn must not start"),
    )
    result = [
        item async for item in orchestration.handle_workspace_turn(
            agent=SimpleNamespace(memory=SimpleNamespace()),
            messages=[Msg(name="user", role="user", content="new request")],
            request=SimpleNamespace(session_id="task", user_id="user", tenant_id="local"),
            query="new request",
            mission_info=None,
            agent_id="comic",
            agent_name="Comic",
            workspace_root=tmp_path,
            orchestration=SimpleNamespace(),
            standard_stream=None,
        )
    ]
    assert len(result) == 1
    response, last, should_save_session = result[0]
    assert last is True and should_save_session is False
    assert "本轮处理未能安全完成" in response.get_text_content()
