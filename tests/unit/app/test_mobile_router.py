# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from qwenpaw.app.mobile.models import MobilePendingConfirmation
from qwenpaw.app.runner.models import ChatSpec
from qwenpaw.app.routers import mobile as mobile_router


def test_mobile_router_prefix_is_user_scoped() -> None:
    assert mobile_router.router.prefix == "/mobile"


def test_mobile_message_serialization_merges_adjacent_assistant_parts() -> None:
    messages = [
        {"type": "message", "role": "user", "content": "你好"},
        {"type": "message", "role": "assistant", "content": "你好！我是 DClaw， 你的智能助手。"},
        {"type": "message", "role": "assistant", "content": "我准备好了，可以帮你做什么？"},
        {"type": "message", "role": "user", "content": "总结一下"},
        {"type": "message", "role": "assistant", "content": "可以，我来整理。"},
    ]

    assert mobile_router._serialize_mobile_messages(messages) == [
        {"type": "message", "role": "user", "content": "你好"},
        {
            "type": "message",
            "role": "assistant",
            "content": "你好！我是 DClaw， 你的智能助手。\n\n我准备好了，可以帮你做什么？",
        },
        {"type": "message", "role": "user", "content": "总结一下"},
        {"type": "message", "role": "assistant", "content": "可以，我来整理。"},
    ]


@pytest.mark.asyncio
async def test_mobile_confirmations_filters_inaccessible_approvals(
    monkeypatch,
) -> None:
    accessible = SimpleNamespace(
        request_id="req-visible",
        session_id="root-visible",
        root_session_id="root-visible",
        owner_agent_id="default",
        agent_id="default",
        tool_name="workspace.export",
        severity="LOW",
        findings_count=0,
        result_summary="visible",
        created_at=1718600000.0,
        timeout_seconds=300,
        extra={},
    )
    hidden = SimpleNamespace(
        request_id="req-hidden",
        session_id="root-hidden",
        root_session_id="root-hidden",
        owner_agent_id="default",
        agent_id="default",
        tool_name="workspace.export",
        severity="LOW",
        findings_count=0,
        result_summary="hidden",
        created_at=1718600000.0,
        timeout_seconds=300,
        extra={},
    )

    class FakeApprovalService:
        async def list_all_pending(self):
            return [accessible, hidden]

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        assert allow_admin is False
        if chat_id == "root-hidden":
            from fastapi import HTTPException

            raise HTTPException(status_code=404)
        return {"id": chat_id, "session_id": chat_id}

    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await mobile_router.get_mobile_confirmations(request)

    assert [item.request_id for item in response] == ["req-visible"]
    assert isinstance(response[0], MobilePendingConfirmation)


@pytest.mark.asyncio
async def test_mobile_tasks_derive_counts_from_real_services(
    monkeypatch,
) -> None:
    chat = ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="1",
        channel="console",
        name="生成周报摘要",
        task_status="pending",
        meta={"mode": "task"},
    )

    class FakeChatManager:
        async def list_chats(self, user_id=None, channel=None):
            assert user_id == "1"
            assert channel == "console"
            return [chat]

    class FakeTaskTracker:
        async def get_status(self, chat_id):
            assert chat_id == "chat-1"
            return "idle"

    class FakeApprovalService:
        async def list_all_pending(self):
            return [
                SimpleNamespace(
                    request_id="req-1",
                    root_session_id="session-1",
                ),
            ]

    async def fake_get_agent_for_request(_request):
        return SimpleNamespace(
            chat_manager=FakeChatManager(),
            task_tracker=FakeTaskTracker(),
        )

    async def fake_list_workspace_artifacts(_request, session_id=None):
        assert session_id == "session-1"
        return [
            SimpleNamespace(
                filename="项目进展_周报.md",
                path="项目进展_周报.md",
                size=128,
                modified_time="2026-06-17T08:00:00+00:00",
            ),
        ]

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        assert allow_admin is False
        assert chat_id == "session-1"
        return {"id": "chat-1", "session_id": "session-1"}

    monkeypatch.setattr(
        mobile_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "list_workspace_artifacts",
        fake_list_workspace_artifacts,
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await mobile_router.get_mobile_tasks(request)

    assert len(response) == 1
    assert response[0].id == "chat-1"
    assert response[0].display_status == "pending_confirmation"
    assert response[0].pending_confirmation_count == 1
    assert response[0].artifact_count == 1


@pytest.mark.asyncio
async def test_mobile_tasks_match_web_task_list_across_enabled_agents(
    monkeypatch,
) -> None:
    default_chat = ChatSpec(
        id="default-chat",
        session_id="default-session",
        user_id="2",
        channel="console",
        name="给我讲一个鬼故事500字",
        task_status="pending",
        meta={"mode": "task", "agent_id": "default"},
        created_at=datetime(2026, 6, 18, 7, 55, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 18, 7, 55, tzinfo=timezone.utc),
    )
    legal_chat = ChatSpec(
        id="legal-chat",
        session_id="legal-session",
        user_id="2",
        channel="console",
        name="我们卖槟榔要在小红书上打广告",
        task_status="pending",
        meta={"mode": "task", "agent_id": "legal"},
        created_at=datetime(2026, 6, 18, 8, 38, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 18, 9, 33, tzinfo=timezone.utc),
    )
    rows = [
        {
            "id": legal_chat.id,
            "user_id": "2",
            "agent_id": "legal",
            "session_id": legal_chat.session_id,
            "channel": "console",
            "name": legal_chat.name,
            "status": "idle",
            "task_status": "pending",
            "pinned": False,
            "meta": '{"mode": "task", "agent_id": "legal"}',
            "created_at": legal_chat.created_at,
            "updated_at": legal_chat.updated_at,
            "message_count": 2,
        },
        {
            "id": default_chat.id,
            "user_id": "2",
            "agent_id": "default",
            "session_id": default_chat.session_id,
            "channel": "console",
            "name": default_chat.name,
            "status": "idle",
            "task_status": "pending",
            "pinned": False,
            "meta": '{"mode": "task", "agent_id": "default"}',
            "created_at": default_chat.created_at,
            "updated_at": default_chat.updated_at,
            "message_count": 2,
        },
    ]

    class FakeRepo:
        def list_recent_chats(self, *, enabled_agent_ids, user_id, limit):
            assert enabled_agent_ids == ["default", "legal"]
            assert user_id == "2"
            assert limit == 50
            return rows

    class FakeChatManager:
        def __init__(self, chat):
            self.chat = chat

        async def list_chats(self, user_id=None, channel=None):
            assert user_id == "2"
            assert channel == "console"
            return [self.chat]

        async def get_chat(self, chat_id):
            assert chat_id == self.chat.id
            return self.chat

    class FakeTaskTracker:
        async def get_status(self, _chat_id):
            return "idle"

    class FakeApprovalService:
        async def list_all_pending(self):
            return []

    class FakeWorkspace:
        def __init__(self, agent_id, chat):
            self.agent_id = agent_id
            self.chat_manager = FakeChatManager(chat)
            self.task_tracker = FakeTaskTracker()
            self.runner = SimpleNamespace(session=object())

    class FakeManager:
        async def get_agent(self, agent_id, user_id="default"):
            assert str(user_id) == "2"
            return {
                "default": FakeWorkspace("default", default_chat),
                "legal": FakeWorkspace("legal", legal_chat),
            }[agent_id]

    class FakeApprovalService:
        async def list_all_pending(self):
            return []

    async def fake_list_workspace_artifacts(
        _request,
        session_id=None,
        agent_id=None,
    ):
        assert session_id in {"default-session", "legal-session"}
        assert agent_id in {None, "default", "legal"}
        return []

    async def fake_get_runner_chat(*_args, **_kwargs):
        return SimpleNamespace(
            messages=[
                {"role": "user", "content": "任务"},
                {"role": "assistant", "content": "结果"},
            ],
        )

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        assert allow_admin is False
        return {
            "legal-session": {
                "id": "legal-chat",
                "session_id": "legal-session",
                "agent_id": "legal",
            },
            "default-session": {
                "id": "default-chat",
                "session_id": "default-session",
                "agent_id": "default",
            },
        }[chat_id]

    monkeypatch.setattr(
        mobile_router,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={
                    "default": SimpleNamespace(enabled=True),
                    "legal": SimpleNamespace(enabled=True),
                    "disabled": SimpleNamespace(enabled=False),
                },
            ),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_chat_list_repository",
        lambda: FakeRepo(),
        raising=False,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "list_workspace_artifacts",
        fake_list_workspace_artifacts,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_runner_chat",
        fake_get_runner_chat,
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(
        state=SimpleNamespace(user_id=2, role="user"),
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=FakeManager()),
        ),
        headers={},
        query_params={},
    )
    response = await mobile_router.get_mobile_tasks(request)

    assert [item.name for item in response] == [
        "我们卖槟榔要在小红书上打广告",
        "给我讲一个鬼故事500字",
    ]
    assert [item.agent_id for item in response] == ["legal", "default"]
    assert all(item.display_status == "completed" for item in response)


@pytest.mark.asyncio
async def test_mobile_tasks_hide_archived_chats(monkeypatch) -> None:
    visible_chat = ChatSpec(
        id="visible-chat",
        session_id="visible-session",
        user_id="3",
        channel="console",
        name="保留的任务",
        task_status="completed",
        meta={"mode": "task"},
    )
    archived_chat = ChatSpec(
        id="archived-chat",
        session_id="archived-session",
        user_id="3",
        channel="console",
        name="归档的任务",
        task_status="completed",
        meta={"mode": "task", "archived_at": "2026-07-07T12:00:00+00:00"},
    )

    class FakeChatManager:
        async def list_chats(self, user_id=None, channel=None):
            assert user_id == "3"
            assert channel == "console"
            return [archived_chat, visible_chat]

    class FakeTaskTracker:
        async def get_status(self, _chat_id):
            return "idle"

    class FakeApprovalService:
        async def list_all_pending(self):
            return []

    async def fake_get_agent_for_request(_request):
        return SimpleNamespace(
            chat_manager=FakeChatManager(),
            task_tracker=FakeTaskTracker(),
        )

    async def fake_list_workspace_artifacts(_request, session_id=None):
        assert session_id == "visible-session"
        return []

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        assert allow_admin is False
        return {"id": "visible-chat", "session_id": chat_id}

    monkeypatch.setattr(
        mobile_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "list_workspace_artifacts",
        fake_list_workspace_artifacts,
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=3, role="user"))
    response = await mobile_router.get_mobile_tasks(request)

    assert [item.id for item in response] == ["visible-chat"]


@pytest.mark.asyncio
async def test_archive_mobile_task_marks_chat_archived(monkeypatch) -> None:
    chat = ChatSpec(
        id="chat-archive",
        session_id="session-archive",
        user_id="4",
        channel="console",
        name="需要归档",
        meta={"mode": "task", "agent_id": "default", "keep": True},
    )

    class FakeChatManager:
        def __init__(self):
            self.patch = None

        async def get_chat(self, chat_id):
            assert chat_id == "chat-archive"
            return chat

        async def patch_chat(self, chat_id, patch):
            assert chat_id == "chat-archive"
            self.patch = patch
            return chat.model_copy(
                update={"meta": {**chat.meta, **(patch.meta or {})}},
            )

    manager = FakeChatManager()

    async def fake_get_agent_for_request(_request, agent_id=None):
        assert agent_id == "default"
        return SimpleNamespace(chat_manager=manager)

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        assert chat_id == "session-archive"
        assert allow_admin is False
        return {
            "id": "chat-archive",
            "session_id": "session-archive",
            "agent_id": "default",
        }

    monkeypatch.setattr(
        mobile_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=4, role="user"))
    response = await mobile_router.archive_mobile_task("session-archive", request)

    assert response["archived"] is True
    assert response["id"] == "chat-archive"
    assert manager.patch is not None
    assert manager.patch.meta["keep"] is True
    assert datetime.fromisoformat(manager.patch.meta["archived_at"])


@pytest.mark.asyncio
async def test_delete_mobile_task_removes_accessible_chat(monkeypatch) -> None:
    deleted: list[list[str]] = []

    class FakeChatManager:
        async def delete_chats(self, chat_ids):
            deleted.append(chat_ids)
            return True

    async def fake_get_agent_for_request(_request, agent_id=None):
        assert agent_id == "legal"
        return SimpleNamespace(chat_manager=FakeChatManager())

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        assert chat_id == "session-delete"
        assert allow_admin is False
        return {
            "id": "chat-delete",
            "session_id": "session-delete",
            "agent_id": "legal",
        }

    monkeypatch.setattr(
        mobile_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=5, role="user"))
    response = await mobile_router.delete_mobile_task("session-delete", request)

    assert response == {"deleted": True, "id": "chat-delete"}
    assert deleted == [["chat-delete"]]


@pytest.mark.asyncio
async def test_mobile_tasks_mark_assistant_response_as_completed(
    monkeypatch,
) -> None:
    chat = ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="1",
        channel="console",
        name="给我讲一个鬼故事500字",
        task_status="pending",
        meta={"mode": "task", "agent_id": "default"},
    )

    class FakeChatManager:
        async def list_chats(self, user_id=None, channel=None):
            assert user_id == "1"
            assert channel == "console"
            return [chat]

    class FakeTaskTracker:
        async def get_status(self, chat_id):
            assert chat_id == "chat-1"
            return "idle"

    class FakeApprovalService:
        async def list_all_pending(self):
            return []

    async def fake_get_agent_for_request(_request):
        return SimpleNamespace(
            chat_manager=FakeChatManager(),
            task_tracker=FakeTaskTracker(),
            runner=SimpleNamespace(session=object()),
        )

    async def fake_list_workspace_artifacts(_request, session_id=None):
        assert session_id == "session-1"
        return []

    async def fake_get_runner_chat(*_args, **_kwargs):
        return SimpleNamespace(
            messages=[
                {"role": "user", "content": "给我讲一个鬼故事500字"},
                {"role": "assistant", "content": "电梯门缓缓合上。"},
            ],
        )

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        assert allow_admin is False
        assert chat_id == "session-1"
        return {"id": "chat-1", "session_id": "session-1"}

    monkeypatch.setattr(
        mobile_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "list_workspace_artifacts",
        fake_list_workspace_artifacts,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_runner_chat",
        fake_get_runner_chat,
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await mobile_router.get_mobile_tasks(request)

    assert response[0].display_status == "completed"
    assert response[0].agent_id == "default"


@pytest.mark.asyncio
async def test_mobile_results_use_owned_session_and_serialize_artifacts(
    monkeypatch,
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        calls.append((chat_id, allow_admin))
        return {"id": "chat-1", "session_id": "session-1"}

    async def fake_list_workspace_artifacts(_request, session_id=None):
        assert session_id == "session-1"
        return [
            SimpleNamespace(
                filename="竞品对比报告.md",
                path="reports/竞品对比报告.md",
                size=256,
                modified_time="2026-06-17T08:00:00+00:00",
            ),
        ]

    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )
    monkeypatch.setattr(
        mobile_router,
        "list_workspace_artifacts",
        fake_list_workspace_artifacts,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await mobile_router.get_mobile_results("chat-1", request)

    assert calls == [("chat-1", False)]
    assert response[0].name == "竞品对比报告.md"
    assert response[0].path == "reports/竞品对比报告.md"


@pytest.mark.asyncio
async def test_mobile_approval_action_checks_non_admin_ownership(
    monkeypatch,
) -> None:
    calls: list[tuple[str, bool]] = []
    pending = SimpleNamespace(
        request_id="req-1",
        root_session_id="root-session",
    )
    resolved = SimpleNamespace(tool_name="workspace.export")

    class FakeApprovalService:
        async def get_request(self, request_id):
            assert request_id == "req-1"
            return pending

        async def resolve_request(self, request_id, _decision):
            assert request_id == "req-1"
            return resolved

    def fake_ensure_chat_access(_request, chat_id, allow_admin=False):
        calls.append((chat_id, allow_admin))
        return {"id": "chat-1", "session_id": chat_id}

    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        fake_ensure_chat_access,
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await mobile_router.approve_mobile_confirmation("req-1", request)

    assert calls == [("root-session", False)]
    assert response.success is True
    assert response.tool_name == "workspace.export"


@pytest.mark.asyncio
async def test_mobile_task_detail_includes_serialized_messages(
    monkeypatch,
) -> None:
    chat = ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="1",
        channel="console",
        name="整理周报",
        task_status="pending",
        meta={"mode": "task", "active_mode": "ask"},
    )

    class FakeChatManager:
        async def get_chat(self, chat_id):
            assert chat_id == "chat-1"
            return chat

    class FakeTaskTracker:
        async def get_status(self, chat_id):
            assert chat_id == "chat-1"
            return "idle"

    async def fake_get_agent_for_request(_request):
        return SimpleNamespace(
            chat_manager=FakeChatManager(),
            task_tracker=FakeTaskTracker(),
            runner=SimpleNamespace(session=SimpleNamespace()),
        )

    async def fake_get_runner_chat(_request, chat_id, **_kwargs):
        assert chat_id == "chat-1"
        return SimpleNamespace(
            messages=[
                SimpleNamespace(
                    model_dump=lambda mode="json": {
                        "role": "user",
                        "content": "整理周报",
                    },
                ),
                {"role": "assistant", "content": "好的，已开始整理。"},
            ],
            status="idle",
        )

    class FakeApprovalService:
        async def list_all_pending(self):
            return []

    async def fake_list_workspace_artifacts(_request, session_id=None, agent_id=None):
        assert session_id == "session-1"
        return []

    monkeypatch.setattr(
        mobile_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_runner_chat",
        fake_get_runner_chat,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "list_workspace_artifacts",
        fake_list_workspace_artifacts,
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        lambda _request, _chat_id, allow_admin=False: {
            "id": "chat-1",
            "session_id": "session-1",
        },
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await mobile_router.get_mobile_task_detail("chat-1", request)

    assert response.messages == [
        {"role": "user", "content": "整理周报"},
        {"role": "assistant", "content": "好的，已开始整理。"},
    ]
    assert response.task.active_mode == "ask"


@pytest.mark.asyncio
async def test_mobile_task_detail_hides_reasoning_messages(
    monkeypatch,
) -> None:
    chat = ChatSpec(
        id="chat-1",
        session_id="session-1",
        user_id="1",
        channel="console",
        name="你好",
        task_status="pending",
        meta={"mode": "task", "active_mode": "craft"},
    )

    class FakeChatManager:
        async def get_chat(self, chat_id):
            assert chat_id == "chat-1"
            return chat

    class FakeTaskTracker:
        async def get_status(self, chat_id):
            assert chat_id == "chat-1"
            return "idle"

    async def fake_get_agent_for_request(_request):
        return SimpleNamespace(
            chat_manager=FakeChatManager(),
            task_tracker=FakeTaskTracker(),
            runner=SimpleNamespace(session=SimpleNamespace()),
        )

    async def fake_get_runner_chat(_request, chat_id, **_kwargs):
        assert chat_id == "chat-1"
        return SimpleNamespace(
            messages=[
                {"type": "message", "role": "user", "content": "你好"},
                {
                    "type": "reasoning",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "用户用中文打招呼说\"你好\"。",
                        },
                    ],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "content": "你好！我是 DClaw，有什么可以帮你的？",
                },
            ],
            status="idle",
        )

    async def fake_list_workspace_artifacts(_request, session_id=None, agent_id=None):
        assert session_id == "session-1"
        return []

    class FakeApprovalService:
        async def list_all_pending(self):
            return []

    monkeypatch.setattr(
        mobile_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_runner_chat",
        fake_get_runner_chat,
    )
    monkeypatch.setattr(
        mobile_router,
        "get_approval_service",
        lambda: FakeApprovalService(),
    )
    monkeypatch.setattr(
        mobile_router,
        "list_workspace_artifacts",
        fake_list_workspace_artifacts,
    )
    monkeypatch.setattr(
        mobile_router,
        "ensure_chat_access",
        lambda _request, _chat_id, allow_admin=False: {
            "id": "chat-1",
            "session_id": "session-1",
        },
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await mobile_router.get_mobile_task_detail("chat-1", request)

    assert response.messages == [
        {"type": "message", "role": "user", "content": "你好"},
        {
            "type": "message",
            "role": "assistant",
            "content": "你好！我是 DClaw，有什么可以帮你的？",
        },
    ]
    assert response.task.has_assistant_response is True
