# -*- coding: utf-8 -*-
from __future__ import annotations

import warnings
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from qwenpaw.app.open_api.models import (
    AppendGroupHistoryRequest,
    GroupHistoryMessageInput,
)
from qwenpaw.app.routers import open_api_group_history
from qwenpaw.app.routers import router as root_router


class FakePublicationRepository:
    def __init__(self, publication: dict[str, Any] | None) -> None:
        self.publication = publication

    def get_enabled_publication_by_public_id(self, public_id: str):
        if self.publication and self.publication["public_id"] == public_id:
            return self.publication
        return None


class FakeGroupHistoryRepository:
    def __init__(self) -> None:
        self.append_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []

    def append_messages(self, **kwargs):
        self.append_calls.append(kwargs)
        return {
            "history_id": "history-1",
            "inserted": len(kwargs["messages"]),
            "duplicates": 0,
        }

    def list_messages(self, **kwargs):
        self.list_calls.append(kwargs)
        return {
            "messages": [
                {
                    "external_message_id": "wt-message-7",
                    "occurred_at": datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc),
                    "sender_id": "user-7",
                    "sender_name": "张三",
                    "participant_role_id": "role-7",
                    "direction": "inbound",
                    "source": "worktool_local",
                    "message_type": "text",
                    "content": "完成了",
                    "metadata": {"fileName": ""},
                },
            ],
            "next_cursor": "cursor-2",
            "has_more": True,
        }


def _request(*, publication_id: str = "pub-1") -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/open/v1/targets/public-agent/group-histories/wtg-1/messages",
            "raw_path": b"/api/open/v1/targets/public-agent/group-histories/wtg-1/messages",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 8088),
            "client": ("127.0.0.1", 12345),
            "app": SimpleNamespace(state=SimpleNamespace()),
        },
    )
    request.state.open_publication_id = publication_id
    return request


def _payload() -> AppendGroupHistoryRequest:
    return AppendGroupHistoryRequest(
        messages=[
            GroupHistoryMessageInput(
                external_message_id="wt-message-7",
                occurred_at="2026-08-05T01:00:00Z",
                sender_id="user-7",
                sender_name="张三",
                participant_role_id="role-7",
                direction="inbound",
                source="worktool_local",
                message_type="text",
                content="完成了",
                metadata={"fileName": ""},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_append_group_history_is_storage_only(monkeypatch):
    publication_repo = FakePublicationRepository(
        {"id": "pub-1", "public_id": "public-agent", "status": "enabled"},
    )
    history_repo = FakeGroupHistoryRepository()
    monkeypatch.setattr(
        open_api_group_history,
        "get_open_api_repository",
        lambda: publication_repo,
    )
    monkeypatch.setattr(
        open_api_group_history,
        "get_open_api_group_history_repository",
        lambda: history_repo,
    )

    response = await open_api_group_history.append_group_history_messages(
        "public-agent",
        "wtg-1",
        _payload(),
        _request(),
    )

    assert response.inserted == 1
    assert response.duplicates == 0
    assert history_repo.append_calls == [
        {
            "publication_id": "pub-1",
            "external_group_id": "wtg-1",
            "messages": [_payload().messages[0].model_dump()],
        },
    ]
    assert not hasattr(_request().app.state, "multi_agent_manager")


@pytest.mark.asyncio
async def test_list_group_history_returns_page_and_forwards_range(monkeypatch):
    publication_repo = FakePublicationRepository(
        {"id": "pub-1", "public_id": "public-agent", "status": "enabled"},
    )
    history_repo = FakeGroupHistoryRepository()
    monkeypatch.setattr(
        open_api_group_history,
        "get_open_api_repository",
        lambda: publication_repo,
    )
    monkeypatch.setattr(
        open_api_group_history,
        "get_open_api_group_history_repository",
        lambda: history_repo,
    )

    response = await open_api_group_history.list_group_history_messages(
        "public-agent",
        "wtg-1",
        _request(),
        from_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        until_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        after="cursor-1",
        limit=20,
    )

    assert response.has_more is True
    assert response.next_cursor == "cursor-2"
    assert response.messages[0].external_message_id == "wt-message-7"
    assert history_repo.list_calls == [
        {
            "publication_id": "pub-1",
            "external_group_id": "wtg-1",
            "from_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
            "until_at": datetime(2026, 8, 5, tzinfo=timezone.utc),
            "after": "cursor-1",
            "limit": 20,
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("publication", "request_publication_id", "status_code"),
    [
        (None, "pub-1", 404),
        ({"id": "pub-1", "public_id": "public-agent"}, "pub-other", 403),
    ],
)
async def test_group_history_route_enforces_publication_binding(
    monkeypatch,
    publication,
    request_publication_id,
    status_code,
):
    monkeypatch.setattr(
        open_api_group_history,
        "get_open_api_repository",
        lambda: FakePublicationRepository(publication),
    )
    monkeypatch.setattr(
        open_api_group_history,
        "get_open_api_group_history_repository",
        lambda: FakeGroupHistoryRepository(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await open_api_group_history.append_group_history_messages(
            "public-agent",
            "wtg-1",
            _payload(),
            _request(publication_id=request_publication_id),
        )

    assert exc_info.value.status_code == status_code


def test_group_history_request_rejects_naive_time_and_oversized_body():
    with pytest.raises(ValidationError, match="timezone"):
        GroupHistoryMessageInput(
            external_message_id="wt-message-7",
            occurred_at="2026-08-05T01:00:00",
            sender_name="张三",
            direction="inbound",
            source="worktool_local",
            message_type="text",
        )

    with pytest.raises(ValidationError, match="1.5 MB"):
        AppendGroupHistoryRequest(
            messages=[
                GroupHistoryMessageInput(
                    external_message_id=f"wt-message-{index}",
                    occurred_at="2026-08-05T01:00:00Z",
                    sender_name="张三",
                    direction="inbound",
                    source="worktool_local",
                    message_type="text",
                    content="文" * 10_000,
                )
                for index in range(60)
            ],
        )


def test_group_history_router_is_mounted_only_at_root_open_prefix():
    app = FastAPI()
    app.include_router(root_router)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        paths = set(app.openapi()["paths"])

    path = "/open/v1/targets/{public_id}/group-histories/{external_group_id}/messages"
    assert path in paths
    assert f"/user{path}" not in paths
    assert f"/admin{path}" not in paths
