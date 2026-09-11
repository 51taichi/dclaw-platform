import pytest
from types import SimpleNamespace
from agentscope.message import Msg
from qwenpaw.app.workspace.empty_reply import recover_empty_reply, reply_shape


@pytest.mark.asyncio
async def test_recovery_uses_existing_evidence_once_without_rerunning_tools():
    evidence = Msg(
        "aigc",
        [
            {
                "type": "tool_result",
                "id": "1",
                "name": "aigc_task_status",
                "output": "asset exists",
            }
        ],
        "system",
    )

    class Memory:
        async def get_memory(self):
            return [evidence]

    class Agent:
        memory = Memory()
        sys_prompt = "Existing business and review rules"

        async def __call__(self, *args):
            raise AssertionError("must not replay Agent")

    calls = []

    async def generate(agent, messages):
        calls.append(messages)
        return Msg("assistant", "当前素材已生成，尚未完成审核。", "assistant")

    result = await recover_empty_reply(
        Agent(),
        [],
        Msg("assistant", [{"type": "thinking", "thinking": "private"}], "assistant"),
        generate,
    )
    assert len(calls) == 1 and evidence in calls[0]
    assert "不要调用或模拟任何工具" in calls[0][-1].get_text_content()
    assert result.get_text_content() == "当前素材已生成，尚未完成审核。"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "already complete",
        [{"type": "tool_use", "id": "1", "name": "aigc_workflow_create", "input": {}}],
    ],
)
async def test_existing_text_or_pending_tools_never_triggers_recovery(content):
    message = Msg("assistant", content, "assistant")

    async def generate(*args):
        raise AssertionError("unnecessary generation")

    assert (
        await recover_empty_reply(SimpleNamespace(), [], message, generate) is message
    )


def test_shape_contains_no_customer_text_or_reasoning():
    info = reply_shape(
        Msg("assistant", [{"type": "thinking", "thinking": "secret"}], "assistant")
    )
    assert info["text_length"] == 0 and info["block_types"] == ["thinking"]
    assert "secret" not in str(info)


@pytest.mark.asyncio
async def test_actual_text_generation_path_disables_tools():
    from agentscope.model import ChatResponse
    from qwenpaw.app.workspace.orchestration import _execute_internal_candidate

    calls = []

    class Model:
        stream = False

        async def __call__(self, prompt, **kwargs):
            calls.append(kwargs)
            return ChatResponse(
                content=[{"type": "text", "text": "缺少审核证据，保持当前步骤。"}]
            )

    class Formatter:
        async def format(self, msgs):
            return msgs

    agent = SimpleNamespace(model=Model(), formatter=Formatter(), name="expert")
    result = await recover_empty_reply(
        agent, [], Msg("expert", [], "assistant"), _execute_internal_candidate
    )
    assert result.get_text_content() == "缺少审核证据，保持当前步骤。"
    assert (
        len(calls) == 1
        and calls[0]["tools"] is None
        and calls[0]["tool_choice"] == "none"
    )
