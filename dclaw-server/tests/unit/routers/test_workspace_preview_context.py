import json
import io
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers.workspace import (
    _explicit_artifact_files_for_chat,
    download_workspace_file,
    download_workspace_artifacts,
    list_workspace_artifacts,
    MdFileInfo,
    parse_preview_context_path,
    resolve_session_id_for_chat_id,
)
from qwenpaw.app.routers import workspace as workspace_router


def test_parse_preview_context_path_extracts_agent_chat_and_path():
    agent_id, chat_id, preview_path = parse_preview_context_path(
        "__qwenpaw_preview__/fullstack_dev/chat-123/pages/index.html"
    )

    assert agent_id == "fullstack_dev"
    assert chat_id == "chat-123"
    assert preview_path == "pages/index.html"


def test_parse_preview_context_path_leaves_legacy_paths_unchanged():
    agent_id, chat_id, preview_path = parse_preview_context_path("index.html")

    assert agent_id is None
    assert chat_id is None
    assert preview_path == "index.html"


def test_resolve_session_id_for_chat_id_reads_per_user_chat_store(tmp_path):
    chats_dir = tmp_path / "users" / "default"
    chats_dir.mkdir(parents=True)
    (chats_dir / "chats.json").write_text(
        json.dumps(
            {
                "chats": [
                    {
                        "id": "4938c643-7f85-44fc-848d-11892d5223ba",
                        "session_id": "1780133812484",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    assert (
        resolve_session_id_for_chat_id(
            "4938c643-7f85-44fc-848d-11892d5223ba",
            tmp_path,
        )
        == "1780133812484"
    )


def test_resolve_session_id_for_chat_id_uses_workspace_context_repository(monkeypatch, tmp_path):
    class FakeWorkspaceContextRepository:
        def get_session_id_for_chat_id(self, chat_id):
            assert chat_id == "chat-1"
            return "session-1"

    monkeypatch.setattr(
        workspace_router,
        "get_workspace_context_repository",
        lambda: FakeWorkspaceContextRepository(),
    )

    assert resolve_session_id_for_chat_id("chat-1", tmp_path) == "session-1"


def test_explicit_artifact_files_for_chat_uses_workspace_context_repository(
    monkeypatch,
    tmp_path,
):
    (tmp_path / "report.md").write_text("report", encoding="utf-8")
    nested = tmp_path / "sessions_data" / "12345"
    nested.mkdir(parents=True)
    (nested / "extra.md").write_text("extra", encoding="utf-8")
    presentation_dir = nested / "artifacts" / "presentation"
    presentation_dir.mkdir(parents=True)
    (presentation_dir / "deck.pptx").write_bytes(b"pptx")
    (presentation_dir / "deck.pdf").write_bytes(b"pdf")
    (presentation_dir / "deck.presentation.compose.json").write_text(
        "{}",
        encoding="utf-8",
    )

    class FakeWorkspaceContextRepository:
        def list_chat_identity_rows(self, chat_id):
            assert chat_id == "chat-1"
            return [{"id": "chat-1", "session_id": "12345"}]

        def get_session_state_texts(self, chat_ids):
            assert chat_ids == ["chat-1", "12345"]
            return [
                "saved as `report.md`",
                "saved as `sessions_data/12345/extra.md`",
                (
                    "delivery files: "
                    "`sessions_data/12345/artifacts/presentation/deck.pptx`, "
                    "`sessions_data/12345/artifacts/presentation/deck.pdf`, "
                    "`sessions_data/12345/artifacts/presentation/"
                    "deck.presentation.compose.json`"
                ),
            ]

    monkeypatch.setattr(
        workspace_router,
        "get_workspace_context_repository",
        lambda: FakeWorkspaceContextRepository(),
    )

    assert _explicit_artifact_files_for_chat("chat-1", tmp_path) == [
        "report.md",
        "extra.md",
        "artifacts/presentation/deck.pptx",
        "artifacts/presentation/deck.pdf",
    ]


def test_explicit_artifact_files_for_chat_resolves_media_deliverables(
    monkeypatch,
    tmp_path,
):
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "深兆左智企业AI落地共建服务手册.pptx").write_bytes(b"pptx")
    (media_dir / "深兆左智企业AI落地共建服务手册.pdf").write_bytes(b"pdf")
    (media_dir / "深兆左智企业AI落地共建服务手册.presentation.compose.json").write_text(
        "{}",
        encoding="utf-8",
    )

    class FakeWorkspaceContextRepository:
        def list_chat_identity_rows(self, chat_id):
            assert chat_id == "chat-1"
            return [{"id": "chat-1", "session_id": "12345"}]

        def get_session_state_texts(self, chat_ids):
            assert chat_ids == ["chat-1", "12345"]
            return [
                (
                    "生成的文件："
                    "`深兆左智企业AI落地共建服务手册.pptx` "
                    "`深兆左智企业AI落地共建服务手册.pdf` "
                    "`深兆左智企业AI落地共建服务手册.presentation.compose.json`"
                ),
            ]

    monkeypatch.setattr(
        workspace_router,
        "get_workspace_context_repository",
        lambda: FakeWorkspaceContextRepository(),
    )

    assert _explicit_artifact_files_for_chat("chat-1", tmp_path) == [
        "media/深兆左智企业AI落地共建服务手册.pptx",
        "media/深兆左智企业AI落地共建服务手册.pdf",
    ]


def test_explicit_artifact_files_for_chat_allows_structured_video_source_only(
    monkeypatch,
    tmp_path,
):
    media_dir = tmp_path / "aigc_studio" / "canvas-1"
    media_dir.mkdir(parents=True)
    video_path = media_dir / "result.mp4"
    video_path.write_bytes(b"video")
    outside_path = tmp_path.parent / "outside-secret.mp4"
    outside_path.write_bytes(b"secret")

    class FakeWorkspaceContextRepository:
        def list_chat_identity_rows(self, chat_id):
            return [{"id": chat_id, "session_id": "session-1"}]

        def get_session_state_texts(self, chat_ids):
            return [
                json.dumps(
                    {
                        "agent": {
                            "memory": {
                                "content": [
                                    {
                                        "type": "video",
                                        "source": {
                                            "type": "url",
                                            "url": video_path.as_uri(),
                                        },
                                    },
                                    {
                                        "type": "video",
                                        "source": {
                                            "type": "url",
                                            "url": outside_path.as_uri(),
                                        },
                                    },
                                    {"unrelated": video_path.as_uri()},
                                ],
                            },
                        },
                    },
                ),
            ]

    monkeypatch.setattr(
        workspace_router,
        "get_workspace_context_repository",
        lambda: FakeWorkspaceContextRepository(),
    )

    assert _explicit_artifact_files_for_chat("chat-1", tmp_path) == [
        "aigc_studio/canvas-1/result.mp4",
    ]


@pytest.mark.asyncio
async def test_user_artifacts_do_not_fallback_scan_shared_workspace(
    monkeypatch,
    tmp_path,
):
    (tmp_path / "命理学习" / "补充资料").mkdir(parents=True)
    (tmp_path / "命理学习" / "补充资料" / "用户上传.pdf").write_text(
        "uploaded source",
        encoding="utf-8",
    )

    request = SimpleNamespace(
        query_params={"chatId": "chat-bob"},
        headers={},
        state=SimpleNamespace(user_id=2, role="user"),
    )
    workspace = SimpleNamespace(workspace_dir=str(tmp_path), agent_id="default")

    async def fake_get_agent_for_request(_request):
        return workspace

    monkeypatch.setattr(
        workspace_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(workspace_router, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(workspace_router, "is_admin_request", lambda _request: False)
    monkeypatch.setattr(
        workspace_router,
        "ensure_chat_access",
        lambda _request, _chat_id: {
            "id": "chat-bob",
            "session_id": "session-bob",
            "user_id": "2",
        },
    )
    monkeypatch.setattr(
        workspace_router,
        "get_workspace_dir_for_request",
        lambda *_args, **_kwargs: tmp_path,
    )
    monkeypatch.setattr(
        workspace_router,
        "_explicit_artifact_files_for_chat",
        lambda *_args, **_kwargs: [],
    )

    assert await list_workspace_artifacts(request, session_id=None) == []


@pytest.mark.asyncio
async def test_user_artifacts_scan_owned_session_workspace(
    monkeypatch,
    tmp_path,
):
    session_dir = tmp_path / "sessions_data" / "session-bob"
    session_dir.mkdir(parents=True)
    (session_dir / "产品价格表.xlsx").write_bytes(b"xlsx-data")
    (session_dir / "AGENTS.md").write_text("system", encoding="utf-8")

    request = SimpleNamespace(
        query_params={"chatId": "chat-bob"},
        headers={},
        state=SimpleNamespace(user_id=2, role="user"),
    )
    workspace = SimpleNamespace(workspace_dir=str(tmp_path), agent_id="default")

    async def fake_get_agent_for_request(_request):
        return workspace

    monkeypatch.setattr(
        workspace_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(workspace_router, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(workspace_router, "is_admin_request", lambda _request: False)
    monkeypatch.setattr(
        workspace_router,
        "ensure_chat_access",
        lambda _request, _chat_id: {
            "id": "chat-bob",
            "session_id": "session-bob",
            "user_id": "2",
        },
    )
    monkeypatch.setattr(
        workspace_router,
        "get_workspace_dir_for_request",
        lambda *_args, **_kwargs: session_dir,
    )
    monkeypatch.setattr(
        workspace_router,
        "_explicit_artifact_files_for_chat",
        lambda *_args, **_kwargs: [],
    )

    artifacts = await list_workspace_artifacts(request, session_id=None)

    assert [artifact.path for artifact in artifacts] == ["产品价格表.xlsx"]


@pytest.mark.asyncio
async def test_user_artifacts_reject_agent_context_mismatch(
    monkeypatch,
    tmp_path,
):
    request = SimpleNamespace(
        query_params={"chatId": "chat-default"},
        headers={},
        state=SimpleNamespace(user_id=2, role="user"),
    )

    async def fake_get_agent_for_request(*_args, **_kwargs):
        raise AssertionError("workspace should not load for mismatched agent")

    monkeypatch.setattr(
        workspace_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(workspace_router, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(workspace_router, "is_admin_request", lambda _request: False)
    monkeypatch.setattr(
        workspace_router,
        "ensure_chat_access",
        lambda _request, _chat_id: {
            "id": "chat-default",
            "session_id": "session-default",
            "user_id": "2",
            "agent_id": "default",
        },
    )

    with pytest.raises(HTTPException) as exc:
        await list_workspace_artifacts(
            request,
            session_id=None,
            agent_id="legal",
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_download_artifacts_packages_only_listed_artifacts(
    monkeypatch,
    tmp_path,
):
    session_dir = tmp_path / "sessions_data" / "session-1"
    session_dir.mkdir(parents=True)
    (session_dir / "AGENTS.md").write_text("system", encoding="utf-8")
    (session_dir / "deck.pptx").write_bytes(b"pptx-data")
    (session_dir / "slides").mkdir()
    (session_dir / "slides" / "cover.png").write_bytes(b"png-data")

    request = SimpleNamespace(
        query_params={"session_id": "chat-1"},
        headers={},
        state=SimpleNamespace(user_id=2, role="user"),
    )
    workspace = SimpleNamespace(workspace_dir=str(tmp_path), agent_id="default")

    async def fake_get_agent_for_request(_request):
        return workspace

    async def fake_list_workspace_artifacts(_request, session_id=None, agent_id=None):
        assert session_id == "chat-1"
        assert agent_id is None
        return [
            MdFileInfo(
                filename="deck.pptx",
                path="deck.pptx",
                size=9,
                created_time="",
                modified_time="",
            ),
            MdFileInfo(
                filename="slides/cover.png",
                path="slides/cover.png",
                size=8,
                created_time="",
                modified_time="",
            ),
        ]

    monkeypatch.setattr(workspace_router, "get_agent_for_request", fake_get_agent_for_request)
    monkeypatch.setattr(workspace_router, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(workspace_router, "is_admin_request", lambda _request: False)
    monkeypatch.setattr(
        workspace_router,
        "ensure_chat_access",
        lambda _request, _chat_id: {
            "id": "chat-1",
            "session_id": "session-1",
            "user_id": "2",
        },
    )
    monkeypatch.setattr(
        workspace_router,
        "list_workspace_artifacts",
        fake_list_workspace_artifacts,
    )

    response = await download_workspace_artifacts(request, session_id="chat-1")
    body = b"".join([chunk async for chunk in response.body_iterator])
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert archive.namelist() == ["deck.pptx", "slides/cover.png"]
        assert archive.read("deck.pptx") == b"pptx-data"
        assert "AGENTS.md" not in archive.namelist()


@pytest.mark.asyncio
async def test_download_workspace_file_streams_single_file(
    monkeypatch,
    tmp_path,
):
    session_dir = tmp_path / "sessions_data" / "session-1"
    session_dir.mkdir(parents=True)
    target = session_dir / "slides" / "deck.pptx"
    target.parent.mkdir()
    target.write_bytes(b"pptx-data")

    request = SimpleNamespace(
        query_params={"chatId": "chat-1"},
        headers={},
        state=SimpleNamespace(user_id=2, role="user"),
    )
    workspace = SimpleNamespace(workspace_dir=str(tmp_path), agent_id="default")

    async def fake_get_agent_for_request(_request, agent_id=None):
        assert agent_id == "legal"
        return workspace

    monkeypatch.setattr(workspace_router, "get_agent_for_request", fake_get_agent_for_request)
    monkeypatch.setattr(workspace_router, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(workspace_router, "is_admin_request", lambda _request: False)
    monkeypatch.setattr(
        workspace_router,
        "ensure_chat_access",
        lambda _request, _chat_id: {
            "id": "chat-1",
            "session_id": "session-1",
            "user_id": "2",
            "agent_id": "legal",
        },
    )

    response = await download_workspace_file("slides/deck.pptx", request)

    assert response.path == target
    assert "deck.pptx" in response.headers["content-disposition"]
