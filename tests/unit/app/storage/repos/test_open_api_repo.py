# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest

from qwenpaw.app import db
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.open_api_repo import (
    SqlAlchemyOpenApiRepository,
    SqliteOpenApiRepository,
)
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture(params=["sqlalchemy", "sqlite"])
def repo(request, tmp_path, monkeypatch):
    if request.param == "sqlalchemy":
        settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "sqlalchemy.db")})
        engine = create_engine_from_settings(settings)
        create_all(engine)
        yield SqlAlchemyOpenApiRepository(engine)
    else:
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            delattr(db._local, "conn")
        monkeypatch.setattr(db, "DB_PATH", tmp_path / "sqlite.db")
        sqlite_repo = SqliteOpenApiRepository()
        sqlite_repo.ensure_tables()
        yield sqlite_repo
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            delattr(db._local, "conn")


@pytest.fixture
def sqlalchemy_repo(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return SqlAlchemyOpenApiRepository(engine)


def _publication_row(publication_id: str = "pub-1", *, status: str = "enabled") -> dict[str, object]:
    return {
        "id": publication_id,
        "public_id": "agent_public_1",
        "target_type": "agent",
        "target_id": "agent-1",
        "owner_user_id": "user-1",
        "name": "客服专家",
        "description": "对外客服入口",
        "status": status,
        "allowed_scopes": json.dumps(["messages:create", "messages:read"]),
    }


def test_open_api_repo_upserts_and_fetches_publication(repo):
    created = repo.upsert_publication(_publication_row())
    updated = repo.upsert_publication(
        {
            **_publication_row(),
            "name": "客服专家更新",
            "allowed_scopes": ["messages:create"],
        },
    )

    assert created["public_id"] == "agent_public_1"
    assert updated["name"] == "客服专家更新"
    assert updated["allowed_scopes"] == ["messages:create"]
    assert repo.get_publication("pub-1")["name"] == "客服专家更新"
    assert repo.get_publication_by_public_id("agent_public_1")["id"] == "pub-1"
    assert [row["id"] for row in repo.list_publications(enabled_only=True)] == ["pub-1"]


def test_open_api_repo_enabled_publication_lookup_ignores_disabled(repo):
    repo.upsert_publication(_publication_row(status="disabled"))

    assert repo.get_publication_by_public_id("agent_public_1")["status"] == "disabled"
    assert repo.get_enabled_publication_by_public_id("agent_public_1") is None
    assert repo.list_publications(enabled_only=True) == []


def test_open_api_repo_creates_external_app_api_key_and_usage(repo):
    repo.upsert_publication(_publication_row())

    app = repo.create_external_app(
        {
            "id": "app-1",
            "owner_user_id": "user-1",
            "name": "CRM",
            "status": "enabled",
            "ip_allowlist": json.dumps(["127.0.0.1"]),
            "quota_policy": {"daily": 100},
        },
    )
    key = repo.create_api_key(
        {
            "id": "key-1",
            "app_id": app["id"],
            "publication_id": "pub-1",
            "key_hash": "hash-1",
            "key_prefix": "qwp_live",
            "key_suffix": "abcd",
            "scopes": json.dumps(["messages:create"]),
        },
    )

    repo.mark_api_key_used("key-1", "10.0.0.2")

    app_row = repo.get_external_app("app-1")
    key_row = repo.get_api_key_by_hash("hash-1")

    assert app["ip_allowlist"] == ["127.0.0.1"]
    assert app["quota_policy"] == {"daily": 100}
    assert app_row["name"] == "CRM"
    assert [row["id"] for row in repo.list_external_apps(owner_user_id="user-1")] == ["app-1"]
    assert key["scopes"] == ["messages:create"]
    assert key_row["id"] == "key-1"
    assert key_row["last_used_ip"] == "10.0.0.2"
    assert key_row["last_used_at"] is not None
    assert [row["id"] for row in repo.list_api_keys(app_id="app-1")] == ["key-1"]
    assert [row["id"] for row in repo.list_api_keys(publication_id="pub-1")] == ["key-1"]
    assert key["status"] == "active"
    assert repo.update_api_key_status("key-1", "revoked")["status"] == "revoked"
    with pytest.raises(ValueError):
        repo.update_api_key_status("key-1", "disabled")


def test_open_api_repo_preserves_publication_id_when_upserting_by_public_id(repo):
    created = repo.upsert_publication(_publication_row("pub-original"))
    updated = repo.upsert_publication(
        {
            **_publication_row("pub-replacement"),
            "name": "客服专家更新",
            "allowed_scopes": ["messages:create"],
        },
    )

    assert created["id"] == "pub-original"
    assert updated["id"] == "pub-original"
    assert updated["name"] == "客服专家更新"
    assert repo.get_publication("pub-original")["name"] == "客服专家更新"
    assert repo.get_publication("pub-replacement") is None
    assert repo.get_publication_by_public_id("agent_public_1")["id"] == "pub-original"


def test_open_api_repo_rejects_cross_owner_publication_upsert(repo):
    repo.upsert_publication(_publication_row("pub-original"))

    with pytest.raises(ValueError):
        repo.upsert_publication(
            {
                **_publication_row("pub-takeover"),
                "owner_user_id": "user-2",
            },
        )

    assert repo.get_publication("pub-original")["owner_user_id"] == "user-1"
    assert repo.get_publication("pub-takeover") is None


def test_open_api_repo_rejects_invalid_api_key_status(repo):
    repo.upsert_publication(_publication_row())
    repo.create_external_app(
        {
            "id": "app-1",
            "owner_user_id": "user-1",
            "name": "CRM",
        },
    )

    with pytest.raises(ValueError):
        repo.create_api_key(
            {
                "id": "key-1",
                "app_id": "app-1",
                "publication_id": "pub-1",
                "key_hash": "hash-1",
                "key_prefix": "qp_live",
                "key_suffix": "abcd",
                "scopes": ["messages:create"],
                "status": "disabled",
            },
        )


@pytest.mark.parametrize(
    ("factory", "field", "bad_value"),
    [
        (_publication_row, "allowed_scopes", json.dumps({"scope": "messages:create"})),
        (_publication_row, "allowed_scopes", {"scope": "messages:create"}),
        (_publication_row, "allowed_scopes", "not-json"),
        (
            lambda: {
                "id": "app-1",
                "owner_user_id": "user-1",
                "name": "CRM",
            },
            "ip_allowlist",
            json.dumps({"ip": "127.0.0.1"}),
        ),
        (
            lambda: {
                "id": "app-1",
                "owner_user_id": "user-1",
                "name": "CRM",
            },
            "quota_policy",
            json.dumps(["daily", 100]),
        ),
        (
            lambda: {
                "id": "key-1",
                "app_id": "app-1",
                "publication_id": "pub-1",
                "key_hash": "hash-1",
                "key_prefix": "qwp_live",
                "key_suffix": "abcd",
            },
            "scopes",
            json.dumps({"scope": "messages:create"}),
        ),
        (
            lambda: {
                "id": "inv-1",
                "app_id": "app-1",
                "publication_id": "pub-1",
                "api_key_id": "key-1",
                "target_type": "agent",
                "target_id": "agent-1",
                "status": "succeeded",
            },
            "token_summary",
            json.dumps(["total", 42]),
        ),
    ],
)
def test_open_api_repo_rejects_wrong_json_field_types(repo, factory, field, bad_value):
    row = factory()
    row[field] = bad_value

    if field == "allowed_scopes":
        with pytest.raises(ValueError):
            repo.upsert_publication(row)
    elif field in {"ip_allowlist", "quota_policy"}:
        with pytest.raises(ValueError):
            repo.create_external_app(row)
    elif field == "scopes":
        repo.upsert_publication(_publication_row())
        repo.create_external_app({"id": "app-1", "owner_user_id": "user-1", "name": "CRM"})
        with pytest.raises(ValueError):
            repo.create_api_key(row)
    else:
        repo.upsert_publication(_publication_row())
        repo.create_external_app({"id": "app-1", "owner_user_id": "user-1", "name": "CRM"})
        repo.create_api_key(
            {
                "id": "key-1",
                "app_id": "app-1",
                "publication_id": "pub-1",
                "key_hash": "hash-1",
                "key_prefix": "qwp_live",
                "key_suffix": "abcd",
                "scopes": ["messages:create"],
            },
        )
        with pytest.raises(ValueError):
            repo.create_invocation(row)


def test_open_api_repo_creates_and_lists_invocations(repo):
    repo.upsert_publication(_publication_row())
    repo.create_external_app(
        {
            "id": "app-1",
            "owner_user_id": "user-1",
            "name": "CRM",
        },
    )
    repo.create_api_key(
        {
            "id": "key-1",
            "app_id": "app-1",
            "publication_id": "pub-1",
            "key_hash": "hash-1",
            "key_prefix": "qwp_live",
            "key_suffix": "abcd",
            "scopes": ["messages:create"],
        },
    )

    first = repo.create_invocation(
        {
            "id": "inv-1",
            "app_id": "app-1",
            "publication_id": "pub-1",
            "api_key_id": "key-1",
            "target_type": "agent",
            "target_id": "agent-1",
            "chat_id": "chat-1",
            "external_session_id": "ext-session-1",
            "external_user_id": "ext-user-1",
            "status": "succeeded",
            "status_code": 200,
            "latency_ms": 321,
            "token_summary": json.dumps({"total": 42}),
            "error_summary": "",
        },
    )
    repo.create_invocation(
        {
            "id": "inv-2",
            "app_id": "app-1",
            "publication_id": "pub-1",
            "api_key_id": "key-1",
            "target_type": "agent",
            "target_id": "agent-1",
            "status": "failed",
            "status_code": 500,
            "token_summary": {"total": 0},
            "error_summary": "boom",
        },
    )

    rows = repo.list_invocations(publication_id="pub-1", limit=1, offset=1)

    assert first["token_summary"] == {"total": 42}
    assert len(rows) == 1
    assert rows[0]["id"] == "inv-1"
    assert rows[0]["latency_ms"] == 321
    assert rows[0]["token_summary"] == {"total": 42}


def test_open_api_repo_updates_invocation_status(repo):
    repo.upsert_publication(_publication_row())
    repo.create_external_app(
        {
            "id": "app-1",
            "owner_user_id": "user-1",
            "name": "CRM",
        },
    )
    repo.create_api_key(
        {
            "id": "key-1",
            "app_id": "app-1",
            "publication_id": "pub-1",
            "key_hash": "hash-1",
            "key_prefix": "qwp_live",
            "key_suffix": "abcd",
            "scopes": ["messages:create"],
        },
    )
    repo.create_invocation(
        {
            "id": "inv-accepted",
            "app_id": "app-1",
            "publication_id": "pub-1",
            "api_key_id": "key-1",
            "target_type": "agent",
            "target_id": "agent-1",
            "status": "accepted",
            "status_code": 202,
            "token_summary": {},
            "error_summary": "",
        },
    )

    updated = repo.update_invocation_status(
        "inv-accepted",
        status="succeeded",
        status_code=200,
        latency_ms=123,
        token_summary={"total": 7},
    )

    assert updated["status"] == "succeeded"
    assert updated["status_code"] == 200
    assert updated["latency_ms"] == 123
    assert updated["token_summary"] == {"total": 7}
