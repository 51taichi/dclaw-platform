# -*- coding: utf-8 -*-
"""Tests for Mindspace agent tools."""

from __future__ import annotations

from pathlib import Path
from io import BytesIO
import json

import pytest
from openpyxl import Workbook

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


def _xlsx_bytes(rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


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


def test_query_knowledge_table_returns_five_ranked_rows(monkeypatch, tmp_path):
    db_path = tmp_path / "qwenpaw.db"
    monkeypatch.setenv("QWENPAW_SQLITE_PATH", str(db_path))
    reset_app_engine_cache()
    workspace = tmp_path / "agent"
    global_root = tmp_path / "global"
    service = MindspaceService(
        global_root=global_root,
        agent_workspace=workspace,
        agent_id="agent-a",
        user_id="experience-a",
        exclusive_personal=True,
    )
    headers = ["招聘单位", "岗位", "岗位要求", "入职地点", "薪资待遇", "入职流程", "合同性质", "备注"]
    rows = [headers]
    rows.extend(
        [f"单位{index}", "会计" if index < 6 else "技术", "本科 会计", "长沙", "年薪10万", "面试→入职", "国企直签", ""]
        for index in range(1, 8)
    )
    service.stage_local_bytes(
        name="公司就业项目汇总.xlsx",
        content=_xlsx_bytes(rows),
        scope=MindspaceScope.PERSONAL,
        source_type="xlsx",
    )
    set_current_workspace_dir(workspace)
    monkeypatch.setattr(mindspace_tools, "_global_root", lambda: global_root)
    monkeypatch.setattr(mindspace_tools, "_service", lambda: service)

    try:
        response = mindspace_tools.query_knowledge_table(
            query="本科 会计 长沙",
            doc_name="公司就业项目汇总.xlsx",
            limit=8,
        )
        payload = json.loads(_tool_text(response))

        assert payload["success"] is True
        assert payload["count"] == 5
        assert len(payload["rows"]) == 5
        assert all(row["招聘单位"].startswith("单位") for row in payload["rows"])
        assert payload["source"]["name"] == "公司就业项目汇总.xlsx"
    finally:
        reset_app_engine_cache()


def test_query_knowledge_table_exports_every_row_without_putting_rows_in_response(
    monkeypatch, tmp_path
):
    db_path = tmp_path / "qwenpaw.db"
    monkeypatch.setenv("QWENPAW_SQLITE_PATH", str(db_path))
    reset_app_engine_cache()
    workspace = tmp_path / "agent"
    global_root = tmp_path / "global"
    service = MindspaceService(
        global_root=global_root,
        agent_workspace=workspace,
        agent_id="agent-a",
        user_id="experience-a",
        exclusive_personal=True,
    )
    headers = ["招聘单位", "岗位", "岗位要求", "入职地点"]
    rows = [headers] + [
        [f"单位{index}", "会计", "本科", "长沙"] for index in range(1, 13)
    ]
    service.stage_local_bytes(
        name="公司就业项目汇总.xlsx",
        content=_xlsx_bytes(rows),
        scope=MindspaceScope.PERSONAL,
        source_type="xlsx",
    )
    set_current_workspace_dir(workspace)
    monkeypatch.setattr(mindspace_tools, "_global_root", lambda: global_root)
    monkeypatch.setattr(mindspace_tools, "_service", lambda: service)

    try:
        response = mindspace_tools.query_knowledge_table(
            query="本科 会计 长沙",
            doc_name="公司就业项目汇总.xlsx",
            result_mode="full_index",
        )
        payload = json.loads(_tool_text(response))

        assert payload["success"] is True
        assert payload["count"] == 12
        assert "rows" not in payload
        index_path = Path(payload["index_path"])
        assert index_path.is_file()
        assert index_path.is_relative_to(workspace)
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        assert len(index_payload["rows"]) == 12
        assert index_payload["source"]["sha256"] == payload["source"]["sha256"]
    finally:
        reset_app_engine_cache()


def test_query_knowledge_table_maps_production_header_aliases(monkeypatch, tmp_path):
    db_path = tmp_path / "qwenpaw.db"
    monkeypatch.setenv("QWENPAW_SQLITE_PATH", str(db_path))
    reset_app_engine_cache()
    workspace = tmp_path / "agent"
    global_root = tmp_path / "global"
    service = MindspaceService(
        global_root=global_root,
        agent_workspace=workspace,
        agent_id="agent-a",
        user_id="experience-a",
        exclusive_personal=True,
    )
    service.stage_local_bytes(
        name="公司就业项目汇总.xlsx",
        content=_xlsx_bytes(
            [["项目", "招聘单位", "岗位", "招聘条件", "入职地点", "薪资待遇", "服务流程", "合同性质", "备注"]]
            + [[index, f"单位{index}", "会计", "本科", "长沙", "年薪10万", "面试→入职", "国企直签", ""] for index in range(1, 6)]
        ),
        scope=MindspaceScope.PERSONAL,
        source_type="xlsx",
    )
    monkeypatch.setattr(mindspace_tools, "_service", lambda: service)

    try:
        payload = json.loads(
            _tool_text(mindspace_tools.query_knowledge_table(query="本科 会计", limit=5))
        )
        assert payload["rows"][0]["岗位要求"] == "本科"
        assert payload["rows"][0]["入职流程"] == "面试→入职"
    finally:
        reset_app_engine_cache()


def test_query_knowledge_table_places_first_choice_first(monkeypatch, tmp_path):
    db_path = tmp_path / "qwenpaw.db"
    monkeypatch.setenv("QWENPAW_SQLITE_PATH", str(db_path))
    reset_app_engine_cache()
    workspace = tmp_path / "agent"
    global_root = tmp_path / "global"
    service = MindspaceService(
        global_root=global_root,
        agent_workspace=workspace,
        agent_id="agent-a",
        user_id="experience-a",
        exclusive_personal=True,
    )
    service.stage_local_bytes(
        name="公司就业项目汇总.xlsx",
        content=_xlsx_bytes(
            [["招聘单位", "岗位", "岗位要求", "入职地点"]]
            + [[f"单位{index}", "会计", "本科", "长沙"] for index in range(1, 7)]
            + [["国家电网", "技能岗", "电气专业", "湖南"]]
        ),
        scope=MindspaceScope.PERSONAL,
        source_type="xlsx",
    )
    set_current_workspace_dir(workspace)
    monkeypatch.setattr(mindspace_tools, "_global_root", lambda: global_root)
    monkeypatch.setattr(mindspace_tools, "_service", lambda: service)

    try:
        response = mindspace_tools.query_knowledge_table(
            query="本科 会计 长沙",
            doc_name="公司就业项目汇总.xlsx",
            first_choice="国家电网",
            limit=5,
        )
        payload = json.loads(_tool_text(response))

        assert len(payload["rows"]) == 5
        assert payload["rows"][0]["招聘单位"] == "国家电网"
    finally:
        reset_app_engine_cache()


def test_query_knowledge_table_uses_latest_same_name_upload(monkeypatch, tmp_path):
    db_path = tmp_path / "qwenpaw.db"
    monkeypatch.setenv("QWENPAW_SQLITE_PATH", str(db_path))
    reset_app_engine_cache()
    workspace = tmp_path / "agent"
    global_root = tmp_path / "global"
    service = MindspaceService(
        global_root=global_root,
        agent_workspace=workspace,
        agent_id="agent-a",
        user_id="experience-a",
        exclusive_personal=True,
    )
    for version in ("旧单位", "新单位"):
        service.stage_local_bytes(
            name="公司就业项目汇总.xlsx",
            content=_xlsx_bytes(
                [["招聘单位", "岗位"]]
                + [[f"{version}{index}", "会计"] for index in range(1, 6)]
            ),
            scope=MindspaceScope.PERSONAL,
            source_type="xlsx",
        )
    set_current_workspace_dir(workspace)
    monkeypatch.setattr(mindspace_tools, "_service", lambda: service)

    try:
        payload = json.loads(
            _tool_text(
                mindspace_tools.query_knowledge_table(
                    query="会计",
                    doc_name="公司就业项目汇总.xlsx",
                    limit=5,
                )
            )
        )

        assert len(payload["rows"]) == 5
        assert all(row["招聘单位"].startswith("新单位") for row in payload["rows"])
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
