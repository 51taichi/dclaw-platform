from qwenpaw.security.tool_guard.engine import ToolGuardEngine
from qwenpaw.security.tool_guard.guardians.rule_guardian import (
    RuleBasedToolGuardian,
)
from qwenpaw.security.tool_guard import utils as guard_utils


def test_default_guarded_tools_include_destructive_file_tools(monkeypatch):
    monkeypatch.delenv("QWENPAW_TOOL_GUARD_TOOLS", raising=False)
    monkeypatch.setattr(guard_utils, "_load_config_tool_guard", lambda: None)

    guarded = guard_utils.resolve_guarded_tools()
    engine = ToolGuardEngine(guardians=[RuleBasedToolGuardian()], enabled=True)

    assert guarded is not None
    assert "delete_file" in guarded
    assert engine.is_guarded("delete_file") is True
    assert engine.is_guarded("remove_file") is True
    assert engine.is_guarded("move_file") is True
    assert engine.is_guarded("rename_file") is True


def test_delete_file_tool_requires_approval_rule():
    engine = ToolGuardEngine(guardians=[RuleBasedToolGuardian()], enabled=True)

    result = engine.guard("delete_file", {"file_path": "index.html"})

    assert result is not None
    assert any(
        finding.rule_id == "TOOL_FILE_DESTRUCTIVE_DELETE"
        for finding in result.findings
    )


def test_rename_file_tool_requires_approval_rule():
    engine = ToolGuardEngine(guardians=[RuleBasedToolGuardian()], enabled=True)

    result = engine.guard(
        "rename_file",
        {"source_path": "old.md", "target_path": "new.md"},
    )

    assert result is not None
    assert any(
        finding.rule_id == "TOOL_FILE_DESTRUCTIVE_MOVE"
        for finding in result.findings
    )


def test_skill_artifact_shell_operations_are_auto_denied(monkeypatch):
    monkeypatch.delenv("QWENPAW_TOOL_GUARD_AUTO_DENIED_RULES", raising=False)
    monkeypatch.setattr(guard_utils, "_load_config_tool_guard", lambda: None)

    engine = ToolGuardEngine(guardians=[RuleBasedToolGuardian()], enabled=True)

    result = engine.guard(
        "execute_shell_command",
        {
            "command": (
                "cd /app/working/workspaces/default && "
                "mv SKILL.md SKILL.md.bak"
            )
        },
    )

    assert result is not None
    assert any(
        finding.rule_id == "TOOL_CMD_SKILL_ARTIFACT_SHELL_OP"
        for finding in result.findings
    )
    assert engine.should_auto_deny_result(result) is True
