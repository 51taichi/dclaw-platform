from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from qwenpaw.agents.tools.file_io import _resolve_file_path
from qwenpaw.agents.tools.browser_control import (
    _reject_local_navigation,
    _resolve_output_path as resolve_browser_output_path,
)
from qwenpaw.agents.tools.presentation_builder import (
    _resolve_path as resolve_presentation_path,
)
from qwenpaw.agents.tools.python_sandbox import python_sandbox
from qwenpaw.agents.tools.shell import execute_shell_command
from qwenpaw.agents.tools.view_media import _validate_media_path
from qwenpaw.config.context import (
    set_current_tool_filesystem_root,
    set_current_workspace_dir,
)


def _response_text(response) -> str:
    return "\n".join(
        block.get("text", "")
        for block in response.content
        if block.get("type") == "text"
    )


@pytest.fixture(autouse=True)
def reset_tool_context():
    set_current_workspace_dir(None)
    set_current_tool_filesystem_root(None)
    yield
    set_current_workspace_dir(None)
    set_current_tool_filesystem_root(None)


def test_file_path_rejects_absolute_and_relative_boundary_escapes(tmp_path):
    workspace = tmp_path / "session"
    workspace.mkdir()
    set_current_workspace_dir(workspace)
    set_current_tool_filesystem_root(workspace)

    assert _resolve_file_path("result.txt") == str(
        (workspace / "result.txt").resolve(),
    )
    with pytest.raises(ValueError, match="outside the Agent session"):
        _resolve_file_path(str(tmp_path / "secret.txt"))
    with pytest.raises(ValueError, match="outside the Agent session"):
        _resolve_file_path("../secret.txt")


def test_file_path_rejects_symlink_escape(tmp_path):
    workspace = tmp_path / "session"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    set_current_workspace_dir(workspace)
    set_current_tool_filesystem_root(workspace)

    with pytest.raises(ValueError, match="outside the Agent session"):
        _resolve_file_path("escape/secret.txt")


def test_media_path_rejects_file_outside_boundary(tmp_path):
    workspace = tmp_path / "session"
    workspace.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"not-important")
    set_current_workspace_dir(workspace)
    set_current_tool_filesystem_root(workspace)

    _path, error = _validate_media_path(outside, {".png"}, "image")

    assert error is not None
    assert "outside the Agent session workspace" in _response_text(error)


def test_presentation_and_browser_paths_share_boundary(tmp_path):
    workspace = tmp_path / "session"
    workspace.mkdir()
    set_current_workspace_dir(workspace)
    set_current_tool_filesystem_root(workspace)

    assert resolve_presentation_path("deck.pptx") == (
        workspace / "deck.pptx"
    ).resolve()
    with pytest.raises(ValueError, match="outside the Agent session"):
        resolve_presentation_path(tmp_path / "secret.pptx")
    with pytest.raises(ValueError, match="outside the Agent session"):
        resolve_browser_output_path(str(tmp_path / "capture.png"))
    with pytest.raises(ValueError, match="Local file URLs"):
        _reject_local_navigation("file:///private/release/agent.json")


def test_ordinary_browser_keeps_local_url_behavior():
    set_current_tool_filesystem_root(None)

    _reject_local_navigation("file:///tmp/local.html")


@pytest.mark.asyncio
async def test_shell_rejects_cwd_outside_boundary(tmp_path):
    workspace = tmp_path / "session"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    set_current_workspace_dir(workspace)
    set_current_tool_filesystem_root(workspace)

    response = await execute_shell_command("pwd", cwd=outside)

    assert "outside the Agent session workspace" in _response_text(response)


@pytest.mark.asyncio
async def test_python_sandbox_disables_dynamic_install_for_sealed_runtime(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "session"
    workspace.mkdir()
    set_current_workspace_dir(workspace)
    set_current_tool_filesystem_root(workspace)
    module = __import__(
        "qwenpaw.agents.tools.python_sandbox",
        fromlist=["_install_packages"],
    )
    install = MagicMock(wraps=module._install_packages)
    monkeypatch.setattr(module, "_install_packages", install)

    response = await python_sandbox(
        code="print('ok')",
        install_packages="requests",
    )

    payload = json.loads(_response_text(response))
    assert payload["ok"] is False
    assert "disabled in sealed runtimes" in payload["error"]
    assert install.call_count == 0


@pytest.mark.skipif(
    __import__("sys").platform != "linux",
    reason="Landlock is available only on Linux",
)
def test_landlock_blocks_outside_read_and_allows_workspace_io(tmp_path):
    from qwenpaw.agents.tools.filesystem_sandbox import (
        ensure_landlock_available,
        landlock_preexec,
    )
    import subprocess
    import sys

    workspace = tmp_path / "session"
    workspace.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    ensure_landlock_available()

    blocked = subprocess.run(
        [sys.executable, "-c", f"open({str(secret)!r}).read()"],
        capture_output=True,
        text=True,
        check=False,
        preexec_fn=landlock_preexec(workspace),
    )
    allowed = subprocess.run(
        [
            sys.executable,
            "-c",
            "open('result.txt', 'w').write('ok'); print(open('result.txt').read())",
        ],
        capture_output=True,
        text=True,
        cwd=workspace,
        check=False,
        preexec_fn=landlock_preexec(workspace),
    )
    symlink = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import os; os.symlink({str(secret)!r}, 'escape')",
        ],
        capture_output=True,
        text=True,
        cwd=workspace,
        check=False,
        preexec_fn=landlock_preexec(workspace),
    )

    assert blocked.returncode != 0
    assert "PermissionError" in blocked.stderr
    assert allowed.returncode == 0
    assert allowed.stdout.strip() == "ok"
    assert symlink.returncode != 0
    assert "PermissionError" in symlink.stderr
