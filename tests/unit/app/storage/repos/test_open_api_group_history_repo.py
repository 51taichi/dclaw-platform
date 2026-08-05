# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from qwenpaw.app import db
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.open_api_group_history_repo import (
    SqlAlchemyOpenApiGroupHistoryRepository,
    SqliteOpenApiGroupHistoryRepository,
)
from qwenpaw.app.storage.repos.open_api_repo import (
    SqlAlchemyOpenApiRepository,
    SqliteOpenApiRepository,
)
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def _publication_row(publication_id: str, public_id: str) -> dict[str, object]:
    return {
        "id": publication_id,
        "public_id": public_id,
        "target_type": "agent",
        "target_id": f"agent-{publication_id}",
        "owner_user_id": "user-1",
        "name": "群任务专家",
        "allowed_scopes": ["messages:create", "messages:read"],
    }


@pytest.fixture(params=["sqlalchemy", "sqlite"])
def repo(request, tmp_path, monkeypatch):
    if request.param == "sqlalchemy":
        settings = get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "sqlalchemy.db")},
        )
        engine = create_engine_from_settings(settings)
        create_all(engine)
        publication_repo = SqlAlchemyOpenApiRepository(engine)
        publication_repo.upsert_publication(_publication_row("pub-1", "agent-public-1"))
        publication_repo.upsert_publication(_publication_row("pub-2", "agent-public-2"))
        yield SqlAlchemyOpenApiGroupHistoryRepository(engine)
        engine.dispose()
        return

    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sqlite.db")
    publication_repo = SqliteOpenApiRepository()
    publication_repo.ensure_tables()
    publication_repo.upsert_publication(_publication_row("pub-1", "agent-public-1"))
    publication_repo.upsert_publication(_publication_row("pub-2", "agent-public-2"))
    yield SqliteOpenApiGroupHistoryRepository()
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")


def _message(
    external_message_id: str,
    occurred_at: str,
    sender_name: str,
    *,
    content: str = "完成了",
) -> dict[str, object]:
    return {
        "external_message_id": external_message_id,
        "occurred_at": occurred_at,
        "sender_id": f"sender-{sender_name}",
        "sender_name": sender_name,
        "participant_role_id": f"role-{sender_name}",
        "direction": "inbound",
        "source": "worktool_local",
        "message_type": "text",
        "content": content,
        "metadata": {"fileName": "", "sequence": external_message_id},
    }


def test_append_is_idempotent_and_preserves_message_fields(repo):
    payload = _message(
        "wt-message-9",
        "2026-08-05T01:00:00+00:00",
        "张三",
        content="今天作业已经完成",
    )

    first = repo.append_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        messages=[payload],
    )
    second = repo.append_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        messages=[payload],
    )

    assert first["inserted"] == 1
    assert first["duplicates"] == 0
    assert second["inserted"] == 0
    assert second["duplicates"] == 1

    page = repo.list_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        from_at=None,
        until_at=None,
        after=None,
        limit=100,
    )
    assert page["has_more"] is False
    assert page["next_cursor"] is None
    assert page["messages"] == [
        {
            "external_message_id": "wt-message-9",
            "occurred_at": datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
            "sender_id": "sender-张三",
            "sender_name": "张三",
            "participant_role_id": "role-张三",
            "direction": "inbound",
            "source": "worktool_local",
            "message_type": "text",
            "content": "今天作业已经完成",
            "metadata": {"fileName": "", "sequence": "wt-message-9"},
        },
    ]


def test_messages_are_ordered_and_keyset_paginated(repo):
    repo.append_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        messages=[
            _message("wt-message-3", "2026-08-05T03:00:00Z", "王五"),
            _message("wt-message-1", "2026-08-05T01:00:00Z", "张三"),
            _message("wt-message-2", "2026-08-05T02:00:00Z", "李四"),
        ],
    )

    first = repo.list_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        from_at=None,
        until_at=None,
        after=None,
        limit=2,
    )
    second = repo.list_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        from_at=None,
        until_at=None,
        after=first["next_cursor"],
        limit=2,
    )

    assert [row["external_message_id"] for row in first["messages"]] == [
        "wt-message-1",
        "wt-message-2",
    ]
    assert first["has_more"] is True
    assert isinstance(first["next_cursor"], str)
    assert [row["external_message_id"] for row in second["messages"]] == [
        "wt-message-3",
    ]
    assert second["has_more"] is False
    assert second["next_cursor"] is None


def test_range_is_closed_and_publication_group_scoped(repo):
    for publication_id, group_id, message_id in [
        ("pub-1", "wtg-abc", "wanted-start"),
        ("pub-1", "wtg-abc", "wanted-end"),
        ("pub-1", "wtg-other", "wrong-group"),
        ("pub-2", "wtg-abc", "wrong-publication"),
    ]:
        repo.append_messages(
            publication_id=publication_id,
            external_group_id=group_id,
            messages=[
                _message(
                    message_id,
                    "2026-08-05T01:00:00Z" if message_id.endswith("start") else "2026-08-05T02:00:00Z",
                    "张三",
                ),
            ],
        )

    page = repo.list_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        from_at="2026-08-05T01:00:00Z",
        until_at="2026-08-05T02:00:00Z",
        after=None,
        limit=100,
    )

    assert [row["external_message_id"] for row in page["messages"]] == [
        "wanted-start",
        "wanted-end",
    ]


def test_cursor_cannot_be_reused_for_another_history(repo):
    repo.append_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        messages=[
            _message("wt-message-1", "2026-08-05T01:00:00Z", "张三"),
            _message("wt-message-2", "2026-08-05T02:00:00Z", "李四"),
        ],
    )
    first = repo.list_messages(
        publication_id="pub-1",
        external_group_id="wtg-abc",
        from_at=None,
        until_at=None,
        after=None,
        limit=1,
    )

    with pytest.raises(ValueError, match="cursor"):
        repo.list_messages(
            publication_id="pub-1",
            external_group_id="wtg-other",
            from_at=None,
            until_at=None,
            after=first["next_cursor"],
            limit=1,
        )


@pytest.mark.parametrize("limit", [0, 501])
def test_list_rejects_invalid_page_limit(repo, limit):
    with pytest.raises(ValueError, match="limit"):
        repo.list_messages(
            publication_id="pub-1",
            external_group_id="wtg-abc",
            from_at=None,
            until_at=None,
            after=None,
            limit=limit,
        )
