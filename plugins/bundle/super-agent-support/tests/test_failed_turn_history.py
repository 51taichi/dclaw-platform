from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import Msg

from super_agent import orchestration


@pytest.mark.asyncio
async def test_preflight_failure_remains_in_chat_history(monkeypatch, tmp_path):
    recorded = []

    class Memory:
        async def add(self, message):
            recorded.append(message)

    def reject_release(**_):
        raise orchestration.WorkspaceOrchestrationError("orchestration_error")

    monkeypatch.setattr(
        orchestration, "resolve_active_workspace_authorization", reject_release,
    )
    incoming = Msg(name="user", role="user", content="continue")
    result = [
        item async for item in orchestration.handle_workspace_turn(
            agent=SimpleNamespace(memory=Memory()),
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
    assert recorded == [incoming, response]
    assert "本轮处理未能安全完成" in response.get_text_content()
