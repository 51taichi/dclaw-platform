"""Background startup must gate deployment readiness."""

import json

from qwenpaw.app._app import app, get_readiness


def _state(monkeypatch, *, phase, agents, expected, loaded, hooks=0):
    values = {
        "startup_phase": phase,
        "agent_startup_results": agents,
        "expected_plugin_ids": list(expected),
        "expected_plugin_versions": expected,
        "loaded_plugin_versions": loaded,
        "failed_control_commands": 0,
        "failed_startup_hooks": hooks,
        "knowledge_worker_ready": True,
    }
    for name, value in values.items():
        monkeypatch.setattr(app.state, name, value, raising=False)


def test_loading_is_not_ready(monkeypatch):
    _state(
        monkeypatch,
        phase="loading",
        agents={},
        expected={},
        loaded={},
    )
    response = get_readiness()
    assert response.status_code == 503
    assert json.loads(response.body)["status"] == "loading"


def test_all_agents_and_exact_plugin_versions_are_ready(monkeypatch):
    _state(
        monkeypatch,
        phase="ready",
        agents={"a": True, "b": True},
        expected={"support": "1.18.57"},
        loaded={"support": "1.18.57"},
    )
    response = get_readiness()
    assert response.status_code == 200
    assert json.loads(response.body)["agents_ready"] == 2


def test_plugin_fallback_or_agent_failure_blocks_readiness(monkeypatch):
    _state(
        monkeypatch,
        phase="ready",
        agents={"a": True, "b": False},
        expected={"support": "1.18.57"},
        loaded={"support": "1.18.52"},
    )
    response = get_readiness()
    assert response.status_code == 503
    assert json.loads(response.body)["plugins_ready"] == 0
