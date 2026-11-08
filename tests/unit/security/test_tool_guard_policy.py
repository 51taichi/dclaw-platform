from types import SimpleNamespace

from qwenpaw.agents.tool_guard_mixin import ToolGuardMixin
from qwenpaw.security.tool_guard.execution_level import ToolExecutionLevel


class _GuardProbe(ToolGuardMixin):
    pass


def _probe(configured: str, request_context: dict | None = None) -> _GuardProbe:
    probe = _GuardProbe()
    probe._request_context = request_context or {}
    probe._agent_config = SimpleNamespace(approval_level=configured)
    return probe


def test_tool_execution_level_uses_agent_policy():
    assert _probe("smart")._get_tool_execution_level() == ToolExecutionLevel.SMART


def test_legacy_local_access_metadata_does_not_override_agent_policy():
    probe = _probe("strict", {"local_access_mode": "full_access"})

    assert probe._get_tool_execution_level() == ToolExecutionLevel.STRICT
