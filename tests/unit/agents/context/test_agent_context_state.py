from agentscope.state import AgentState

from qwenpaw.agents.context.agent_context import AgentContext
from qwenpaw.agents.message_compat import Msg
from qwenpaw.agents.utils.estimate_token_counter import EstimatedTokenCounter


def test_load_state_dict_preserves_all_history_when_bound_to_agent_state():
    state = AgentState(context=[])
    context = AgentContext(EstimatedTokenCounter())
    context.bind_agent_state(state)
    messages = [
        Msg(name="user", role="user", content=f"request-{index}")
        if index % 2 == 0
        else Msg(name="assistant", role="assistant", content=f"reply-{index}")
        for index in range(8)
    ]
    saved = {
        "content": [
            [message.model_dump(mode="json"), [f"mark-{index}"]]
            for index, message in enumerate(messages)
        ],
        "_compressed_summary": "earlier summary",
    }

    context.load_state_dict(saved)

    assert [message.id for message, _marks in context.content] == [
        message.id for message in messages
    ]
    assert [marks for _message, marks in context.content] == [
        [f"mark-{index}"] for index in range(8)
    ]
    assert [message.id for message in state.context] == [
        message.id for message in messages
    ]
    assert state.summary == "earlier summary"
