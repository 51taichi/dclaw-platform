# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest
from sqlalchemy import insert

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.capability_repo import SqlAlchemyCapabilityRepository
from qwenpaw.app.storage.schema import (
    capability_registry,
    create_all,
    user_capabilities,
    users,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(users),
            {
                "id": 1,
                "username": "alice",
                "password_hash": "hash",
                "password_salt": "salt",
                "role": "user",
            },
        )
    return engine


@pytest.fixture
def repo(engine):
    return SqlAlchemyCapabilityRepository(engine)


def test_sqlalchemy_capability_repo_adds_updates_lists_and_disables_connections(repo):
    conn_id = repo.add_or_update_connection(
        user_id=1,
        connector_key="github",
        oauth_tokens={"access_token": "old"},
        custom_envs={"A": "1"},
    )
    assert conn_id == 1

    updated_id = repo.add_or_update_connection(
        user_id=1,
        connector_key="github",
        oauth_tokens={"access_token": "new"},
        custom_envs={"A": "2"},
    )
    assert updated_id == conn_id
    assert repo.get_user_connections(1) == [
        {
            "connector_key": "github",
            "oauth_tokens": {"access_token": "new"},
            "custom_envs": {"A": "2"},
        }
    ]

    repo.disable_connection(1, "github")
    assert repo.get_user_connections(1) == []


def test_sqlalchemy_capability_repo_lists_enabled_user_capabilities(engine, repo):
    with engine.begin() as conn:
        conn.execute(
            insert(capability_registry),
            [
                {
                    "id": "cap-mcp",
                    "type": "MCP",
                    "name": "GitHub MCP",
                    "manifest": json.dumps(
                        {"github": {"command": "github-mcp", "args": []}},
                    ),
                },
                {
                    "id": "cap-skill",
                    "type": "SKILL",
                    "name": "Research",
                    "manifest": json.dumps({"name": "research"}),
                },
                {
                    "id": "cap-tool",
                    "type": "TOOL",
                    "name": "Tool",
                    "manifest": json.dumps({"name": "tool-x"}),
                },
                {
                    "id": "cap-disabled",
                    "type": "SKILL",
                    "name": "Disabled",
                    "manifest": json.dumps({"name": "disabled"}),
                },
            ],
        )
        conn.execute(
            insert(user_capabilities),
            [
                {
                    "id": "uc-mcp",
                    "user_id": 1,
                    "capability_id": "cap-mcp",
                    "enabled": True,
                    "credentials": json.dumps({"GITHUB_TOKEN": "secret"}),
                    "preferences": json.dumps({"region": "cn"}),
                },
                {
                    "id": "uc-skill",
                    "user_id": 1,
                    "capability_id": "cap-skill",
                    "enabled": True,
                    "credentials": None,
                    "preferences": None,
                },
                {
                    "id": "uc-tool",
                    "user_id": 1,
                    "capability_id": "cap-tool",
                    "enabled": True,
                    "credentials": None,
                    "preferences": None,
                },
                {
                    "id": "uc-disabled",
                    "user_id": 1,
                    "capability_id": "cap-disabled",
                    "enabled": False,
                    "credentials": None,
                    "preferences": None,
                },
            ],
        )

    rows = repo.list_enabled_user_capabilities(1)

    assert rows == [
        {
            "type": "MCP",
            "manifest": {"github": {"command": "github-mcp", "args": []}},
            "credentials": {"GITHUB_TOKEN": "secret"},
            "preferences": {"region": "cn"},
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
