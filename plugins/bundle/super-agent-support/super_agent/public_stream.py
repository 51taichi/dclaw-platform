"""Opt-in public text streaming for transparent workspace Agent calls."""

import asyncio
from copy import deepcopy

from agentscope.message import Msg


def public_text_model(model):
    """Override inherited JSON-object defaults for this public-text call only."""
    current = model
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        defaults = getattr(current, "generate_kwargs", None)
        if isinstance(defaults, dict) and defaults.get("response_format") == {
            "type": "json_object",
        }:
            from openai import NOT_GIVEN

            class PublicTextModel:
                def __getattr__(self, name):
                    return getattr(model, name)

                async def __call__(self, *args, **kwargs):
                    kwargs.setdefault("response_format", NOT_GIVEN)
                    return await model(*args, **kwargs)

            return PublicTextModel()
        current = getattr(current, "_inner", None) or getattr(
            current,
            "_model",
            None,
        )
    return model


def public_snapshot(message):
    if not isinstance(message, Msg) or message.role != "assistant":
        return None
    blocks = message.content
    if isinstance(blocks, list) and any(
        b.get("type") in {"tool_use", "tool_result"} for b in blocks
    ):
        return None
    text = message.get_text_content()
    if not text or not text.strip():
        return None
    # Legacy model envelopes are decoded by the runtime at completion.
    # Do not flash raw JSON fragments before that decoding happens.
    if text.lstrip().startswith(("{", "[", "```json")):
        return None
    result = deepcopy(message)
    result.content = [{"type": "text", "text": text}]
    result.metadata = None
    return result


async def execute_public_agent(agent, messages, on_public_message):
    queue = asyncio.Queue()
    previous_queue = getattr(agent, "msg_queue", None)
    previous_enabled = not getattr(agent, "_disable_msg_queue", True)
    previous_model = getattr(agent, "model", None)
    if previous_model is not None:
        agent.model = public_text_model(previous_model)
    agent.set_msg_queue_enabled(True, queue)
    task = asyncio.create_task(agent(messages))
    end = object()
    task.add_done_callback(lambda _: queue.put_nowait(end))
    try:
        while True:
            item = await queue.get()
            if item is end:
                break
            snapshot = public_snapshot(item[0])
            if snapshot is not None:
                await on_public_message(snapshot)
        return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        agent.set_msg_queue_enabled(previous_enabled, previous_queue)
        if previous_model is not None:
            agent.model = previous_model


async def stream_workspace_turn(*, run_turn=None, **kwargs):
    """Yield tagged progress and exactly one authoritative completion."""
    from .orchestration import run_workspace_orchestration_turn

    run_turn = run_turn or run_workspace_orchestration_turn
    queue = asyncio.Queue()
    end = object()

    async def publish(message):
        await queue.put(message)

    task = asyncio.create_task(
        run_turn(
            **kwargs,
            on_public_message=publish,
        ),
    )
    task.add_done_callback(lambda _: queue.put_nowait(end))
    try:
        while True:
            item = await queue.get()
            if item is end:
                break
            yield False, item
        yield True, await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
