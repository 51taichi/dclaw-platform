from __future__ import annotations

import importlib
import json

import pytest


def _api():
    return importlib.import_module(
        "qwenpaw.app.sealed_agents.standard_workspace",
    )


def _workspace(root, *, agent_id="luyu"):
    root.mkdir(parents=True)
    (root / "agent.json").write_text(
        json.dumps({"id": agent_id, "name": "陆羽"}),
        encoding="utf-8",
    )
    return root


def test_valid_standard_workspace_returns_agent_profile(tmp_path):
    api = _api()
    result = api.validate_standard_workspace(
        "luyu",
        _workspace(tmp_path / "agent"),
    )
    assert result.id == "luyu"
    assert result.name == "陆羽"


@pytest.mark.parametrize(
    ("fixture_name", "error_code"),
    [
        ("missing_config", "agent_config_missing"),
        ("invalid_json", "agent_config_invalid"),
        ("mismatched_id", "agent_id_mismatch"),
    ],
)
def test_invalid_standard_workspace_has_stable_error(
    tmp_path,
    fixture_name,
    error_code,
):
    api = _api()
    root = tmp_path / fixture_name
    root.mkdir(parents=True)
    if fixture_name == "invalid_json":
        (root / "agent.json").write_text("{", encoding="utf-8")
    elif fixture_name == "mismatched_id":
        (root / "agent.json").write_text(
            json.dumps({"id": "other", "name": "其他"}),
            encoding="utf-8",
        )
    with pytest.raises(api.StandardWorkspaceError) as exc_info:
        api.validate_standard_workspace("luyu", root)
    assert exc_info.value.error_code == error_code


def test_missing_workspace_has_stable_error(tmp_path):
    api = _api()
    with pytest.raises(api.StandardWorkspaceError) as exc_info:
        api.validate_standard_workspace("luyu", tmp_path / "missing")
    assert exc_info.value.error_code == "workspace_missing"


def test_agent_config_symlink_is_rejected(tmp_path):
    api = _api()
    source = _workspace(tmp_path / "source") / "agent.json"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "agent.json").symlink_to(source)
    with pytest.raises(api.StandardWorkspaceError) as exc_info:
        api.validate_standard_workspace("luyu", candidate)
    assert exc_info.value.error_code == "unsafe_agent_config"
