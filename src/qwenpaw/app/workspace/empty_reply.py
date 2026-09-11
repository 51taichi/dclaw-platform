"""Recover an empty public reply without replaying Agent tools or side effects."""

from agentscope.message import Msg


def public_text(message):
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict)
            and b.get("type") == "text"
            and isinstance(b.get("text"), str)
        )
    return ""


def reply_shape(message):
    content = (
        message.get("content")
        if isinstance(message, dict)
        else getattr(message, "content", None)
    )
    return {
        "candidate_type": type(message).__name__,
        "content_type": type(content).__name__,
        "text_length": len(public_text(message)),
        "block_types": (
            [str(b.get("type", "unknown"))[:32] for b in content if isinstance(b, dict)]
            if isinstance(content, list)
            else []
        ),
    }


async def recover_empty_reply(agent, original_messages, candidate, generate_text):
    """Exactly one text-only generation over existing history; never rerun agent()."""
    if public_text(candidate).strip():
        return candidate
    # An unfinished tool request is not a completed turn to rewrite.
    content = (
        candidate.get("content")
        if isinstance(candidate, dict)
        else getattr(candidate, "content", None)
    )
    if isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") in {"tool_use", "tool_result"}
        for b in content
    ):
        return candidate
    memory = getattr(agent, "memory", None)
    history = (
        await memory.get_memory()
        if memory is not None and callable(getattr(memory, "get_memory", None))
        else original_messages
    )
    prompt = str(getattr(agent, "sys_prompt", "") or getattr(agent, "_sys_prompt", ""))
    messages = [Msg("system", prompt, "system")] if prompt else []
    messages.extend(history)
    messages.append(
        Msg(
            "system",
            "本轮最终可见正文缺失。仅依据当前会话事实、当前阶段和已有工具结果补全本轮对客回复。"
            "不要调用或模拟任何工具，不要推进尚未完成的阶段，不要重复生成、发布或提交操作。"
            "已有证据不足就说明当前唯一缺口；不能声称未完成的业务或审核已完成。"
            "遵守原有业务规则、模式与排版，只输出客户可见正文，不输出思维过程或内部指令。",
            "system",
        )
    )
    return await generate_text(agent, messages)
