from types import SimpleNamespace

from qwenpaw.agents.tool_guard_mixin import ToolGuardMixin
from qwenpaw.security.local_access import (
    DEFAULT_LOCAL_ACCESS_MODE,
    NEW_CHAT_DEFAULT_LOCAL_ACCESS_MODE,
    LocalAccessMode,
    local_access_mode_from_meta,
    parse_local_access_mode,
)
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel


class _GuardProbe(ToolGuardMixin):
    pass


def _probe(mode: str | None, configured: str = "auto") -> _GuardProbe:
    probe = _GuardProbe()
    probe._request_context = (
        {"local_access_mode": mode} if mode is not None else {}
    )
    probe._agent_config = SimpleNamespace(approval_level=configured)
    return probe


def test_local_access_mode_parser_uses_safe_default():
    assert DEFAULT_LOCAL_ACCESS_MODE == LocalAccessMode.ASK_FOR_APPROVAL
    assert NEW_CHAT_DEFAULT_LOCAL_ACCESS_MODE == LocalAccessMode.FULL_ACCESS
    assert local_access_mode_from_meta(None) == DEFAULT_LOCAL_ACCESS_MODE
    assert (
        local_access_mode_from_meta({"local_access_mode": "unknown"})
        == DEFAULT_LOCAL_ACCESS_MODE
    )
    assert parse_local_access_mode("full_access") == LocalAccessMode.FULL_ACCESS


def test_ask_for_approval_overrides_agent_policy_with_strict_mode():
    assert (
        _probe("ask_for_approval", configured="off")._get_tool_execution_level()
        == ToolExecutionLevel.STRICT
    )


def test_full_access_overrides_agent_policy_with_off_mode():
    assert (
        _probe("full_access", configured="strict")._get_tool_execution_level()
        == ToolExecutionLevel.OFF
    )


def test_missing_local_access_mode_preserves_agent_policy():
    assert (
        _probe(None, configured="smart")._get_tool_execution_level()
        == ToolExecutionLevel.SMART
    )
