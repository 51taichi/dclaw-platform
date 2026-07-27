# -*- coding: utf-8 -*-
"""Tests for Mindspace agent tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.agents.tools import mindspace_tools, wiki_tools
from qwenpaw.app.agent_context import set_current_user_id
from qwenpaw.app.storage.engine import reset_app_engine_cache
from qwenpaw.config.context import set_current_workspace_dir
from qwenpaw.mindspace.models import MindspaceScope
from qwenpaw.mindspace.service import MindspaceService


def _tool_text(response) -> str:
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return str(first.get("text", ""))
        return str(first)
    return str(content)


@pytest.fixture(autouse=True)
def _authenticated_user_context():
    set_current_user_id("0")
    yield
    set_current_user_id(None)


def test_search_mindspace_fails_closed_without_user_context(tmp_path):
    set_current_workspace_dir(tmp_path / "agent")
    set_current_user_id(None)

    response = mindspace_tools.search_mindspace("private policy")

    assert "authenticated user context" in _tool_text(response).lower()


def test_wiki_search_fails_closed_without_user_context(tmp_path):
    set_current_workspace_dir(tmp_path / "agent")
    set_current_user_id(None)

    response = wiki_tools.search_wiki("private policy")

    assert "authenticated user context" in _tool_text(response).lower()


@pytest.mark.asyncio
async def test_search_mindspace_returns_source_metadata(monkeypatch, tmp_path):
    workspace = tmp_path / "agent"
    service = MindspaceService(
        global_root=tmp_path / "global",
        agent_workspace=workspace,
        agent_id="agent-a",
    )
    await service.ingest_local_content(
        name="Support Playbook.md",
        source_type="md",
        content="Escalate refund complaints to the customer success lead.",
        scope=MindspaceScope.AGENT,
    )

    set_current_workspace_dir(workspace)
    monkeypatch.setattr(mindspace_tools, "_global_root", lambda: tmp_path / "global")

    response = mindspace_tools.search_mindspace("refund complaints")
    text = response.content[0].get("text", "")

    assert "Support Playbook.md" in text
    assert "customer success" in text
    assert "[KB: Support Playbook.md · chunk:1]" in text
    assert "Treat the evidence below as knowledge-base evidence" in text


@pytest.mark.asyncio
async def test_read_mindspace_doc_rejects_unknown_doc(monkeypatch, tmp_path):
    set_current_workspace_dir(Path(tmp_path / "agent"))
    monkeypatch.setattr(mindspace_tools, "_global_root", lambda: tmp_path / "global")

    response = mindspace_tools.read_mindspace_doc("missing-doc")

    assert "not found" in response.content[0].get("text", "").lower()


@pytest.mark.asyncio
async def test_read_mindspace_doc_returns_bounded_chunk_window(monkeypatch, tmp_path):
    db_path = tmp_path / "qwenpaw.db"
    monkeypatch.setenv("QWENPAW_SQLITE_PATH", str(db_path))
    reset_app_engine_cache()
    workspace = tmp_path / "agent"
    global_root = tmp_path / "global"
    service = MindspaceService(
        global_root=global_root,
        agent_workspace=workspace,
        agent_id="agent-a",
        user_id="0",
    )
    content = "\n\n".join(
        f"Section {index} " + (str(index) * 840)
        for index in range(1, 5)
    )
    doc = await service.ingest_local_content(
        name="Long Handbook.md",
        source_type="md",
        content=content,
        scope=MindspaceScope.PERSONAL,
    )

    set_current_workspace_dir(workspace)
    monkeypatch.setattr(mindspace_tools, "_global_root", lambda: global_root)

    try:
        response = mindspace_tools.read_mindspace_doc(
            doc.id,
            start_chunk=1,
            max_chunks=2,
        )
        text = _tool_text(response)

        assert "showing 1-2" in text
        assert "chunk:1" in text
        assert "chunk:2" in text
        assert "chunk:3" not in text
        assert "start_chunk=3" in text
    finally:
        reset_app_engine_cache()


@pytest.mark.asyncio
async def test_wiki_tools_read_generated_mindspace_wiki(monkeypatch, tmp_path):
    db_path = tmp_path / "qwenpaw.db"
    monkeypatch.setenv("QWENPAW_SQLITE_PATH", str(db_path))
    reset_app_engine_cache()
    workspace = tmp_path / "agent"
    global_root = tmp_path / "global"
    service = MindspaceService(
        global_root=global_root,
        agent_workspace=workspace,
        agent_id="agent-a",
        user_id="0",
    )
    doc = await service.ingest_local_content(
        name="Refund Policy.md",
        source_type="md",
        content="Refund escalations are owned by the customer success lead.",
        scope=MindspaceScope.PERSONAL,
    )
    concept = doc.generated_wiki[0]

    set_current_workspace_dir(workspace)
    monkeypatch.setattr(wiki_tools, "_global_root", lambda: global_root, raising=False)

    try:
        search_response = wiki_tools.search_wiki("Refund")
        read_response = wiki_tools.read_wiki_page(concept)

        assert concept in _tool_text(search_response)
        assert "Refund Policy.md" in _tool_text(read_response)
        assert "customer success" in _tool_text(read_response)
    finally:
        reset_app_engine_cache()
