from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app import agent_context
from qwenpaw.config.config import AgentProfileRef, Config


@pytest.mark.asyncio
async def test_disabled_agent_is_rejected_before_workspace_lookup(monkeypatch):
    config = Config()
    config.agents.profiles = {
        "disabled-luyu": AgentProfileRef(
            id="disabled-luyu",
            workspace_dir="/tmp/disabled-luyu",
            enabled=False,
        ),
    }

    class Manager:
        async def get_agent(self, agent_id, user_id="default"):
            raise AssertionError("disabled agent reached workspace lookup")

    request = SimpleNamespace(
        state=SimpleNamespace(user_id="user-1"),
        headers={},
        query_params={},
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=Manager()),
        ),
    )
    monkeypatch.setattr(agent_context, "load_config", lambda: config)

    with pytest.raises(HTTPException) as exc_info:
        await agent_context.get_agent_for_request(
            request,
            agent_id="disabled-luyu",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Agent 'disabled-luyu' is disabled"
