from __future__ import annotations

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = PROJECT_ROOT / "agent"


def test_manifest_is_minimal_super_expert_without_local_assistant() -> None:
    manifest = json.loads((PROJECT_ROOT / "manifest.template.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 3
    assert manifest["agent_type"] == "sealed"
    assert manifest["scope"] == "global"
    assert manifest["package_type"] == "super_expert"
    assert manifest["entrypoint"] == "agent/agent.json"
    capabilities = {item["capability_id"] for item in manifest["capabilities"]}
    assert capabilities == {
        "workspace.turn.orchestrate/1",
        "agent.execute",
        "session.context",
        "runtime.trace",
        "runtime.complete",
        "runtime.fail",
    }
    assert not any(capability.startswith("local.") for capability in capabilities)


def test_release_workspace_has_no_server_or_business_plugin_dependency() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(AGENT_ROOT.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".md", ".json"}
    )
    assert "qwenpaw" not in source
    assert "route_private_message_jev" not in source
    assert "TYPESAFE_API_KEY" not in source
    assert "local_task_" not in source


def test_release_workspace_contains_no_obvious_secret_assignment() -> None:
    pattern = re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|private[_-]?key|password)"
        r"\s*[:=]\s*[\"'][^\"']{8,}[\"']"
    )
    for path in [*AGENT_ROOT.rglob("*"), PROJECT_ROOT / "manifest.template.json"]:
        if path.is_file() and path.suffix in {".py", ".md", ".json"}:
            assert pattern.search(path.read_text(encoding="utf-8")) is None, path


def test_entrypoint_files_exist() -> None:
    profile = json.loads((AGENT_ROOT / "agent.json").read_text(encoding="utf-8"))
    assert profile["orchestration"]["entrypoint"] == "runtime.py:create_runtime"
    assert (AGENT_ROOT / "runtime.py").is_file()
    assert (AGENT_ROOT / "VERSION.json").is_file()
