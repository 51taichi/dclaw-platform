# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app.mcp import connections_db
from qwenpaw.app.workspace import capabilities_injector


class FakeCapabilityRepository:
    def __init__(self):
        self.connections = []
        self.disabled = []
        self.capabilities = []

    def add_or_update_connection(self, user_id, connector_key, oauth_tokens=None, custom_envs=None):
        self.connections.append((user_id, connector_key, oauth_tokens, custom_envs))
        return 42

    def get_user_connections(self, user_id):
        assert user_id == 1
        return [
            {
                "connector_key": "github",
                "oauth_tokens": {"token": "secret"},
                "custom_envs": {"A": "1"},
            }
        ]

    def disable_connection(self, user_id, connector_key):
        self.disabled.append((user_id, connector_key))

    def list_enabled_user_capabilities(self, user_id):
        assert user_id == 1
        return list(self.capabilities)


def test_connections_db_uses_capability_repository(monkeypatch):
    repo = FakeCapabilityRepository()
    monkeypatch.setattr(connections_db, "get_capability_repository", lambda: repo)

    conn_id = connections_db.add_or_update_connection(
        1,
        "github",
        oauth_tokens={"token": "secret"},
        custom_envs={"A": "1"},
    )
    rows = connections_db.get_user_connections(1)
    connections_db.disable_connection(1, "github")

    assert conn_id == 42
    assert repo.connections == [(1, "github", {"token": "secret"}, {"A": "1"})]
    assert rows[0]["connector_key"] == "github"
    assert repo.disabled == [(1, "github")]


def test_capabilities_injector_uses_capability_repository(monkeypatch):
    repo = FakeCapabilityRepository()
    repo.capabilities = [
        {
            "type": "MCP",
            "manifest": {"github": {"command": "github-mcp", "args": []}},
            "credentials": {"GITHUB_TOKEN": "secret"},
            "preferences": {},
        },
        {
            "type": "SKILL",
            "manifest": {"name": "research"},
            "credentials": {},
            "preferences": {},
        },
        {
            "type": "TOOL",
            "manifest": {"name": "tool-x"},
            "credentials": {},
            "preferences": {},
        },
    ]
    monkeypatch.setattr(
        capabilities_injector,
        "get_capability_repository",
        lambda: repo,
    )
    config = SimpleNamespace(mcp={}, skills=[], tools=[])

    capabilities_injector.inject_user_capabilities("1", config)

    assert config.mcp == {
        "github": {
            "command": "github-mcp",
            "args": [],
            "env": {"GITHUB_TOKEN": "secret"},
        }
    }
    assert config.skills == ["research"]
    assert config.tools == ["tool-x"]
