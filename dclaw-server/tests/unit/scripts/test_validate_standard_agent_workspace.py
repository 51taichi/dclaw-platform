from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "validate_standard_agent_workspace.py"


def _run(workspace: Path, agent_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(workspace),
            "--agent-id",
            agent_id,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_validates_realistic_standard_workspace(tmp_path):
    workspace = tmp_path / "agent"
    workspace.mkdir()
    (workspace / "agent.json").write_text(
        '{"id":"luyu_traffic_operator","name":"陆羽"}',
        encoding="utf-8",
    )

    result = _run(workspace, "luyu_traffic_operator")

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "status": "valid",
        "agent_id": "luyu_traffic_operator",
        "workspace": str(workspace.resolve()),
    }
    assert result.stderr == ""


def test_cli_reports_only_stable_error_for_invalid_workspace(tmp_path):
    workspace = tmp_path / "agent"
    workspace.mkdir()
    (workspace / "agent.json").write_text("{", encoding="utf-8")

    result = _run(workspace, "luyu_traffic_operator")

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "status": "invalid",
        "agent_id": "luyu_traffic_operator",
        "error_code": "agent_config_invalid",
    }
    assert str(workspace) not in result.stdout
    assert result.stderr == ""
