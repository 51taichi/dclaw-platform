# -*- coding: utf-8 -*-
"""Mindspace search and document reading tools for agents."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re

from openpyxl import load_workbook

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ...mindspace import MindspaceScope, MindspaceService
from ...mindspace.models import normalize_knowledge_tags, normalize_mindspace_scope


def _global_root() -> Path:
    return Path(WORKING_DIR) / "mindspace"


def _parse_scope(scope: str | None) -> MindspaceScope | None:
    return normalize_mindspace_scope(scope)


def _service() -> MindspaceService | None:
    workspace_dir = get_current_workspace_dir()
    if not workspace_dir:
        return None
    try:
        from ...app.agent_context import (
            get_current_knowledge_base_id,
            get_current_user_id,
        )

        user_id = get_current_user_id()
        knowledge_base_id = get_current_knowledge_base_id()
    except Exception:
        return None
    if not user_id:
        return None
    workspace = Path(workspace_dir)
    return MindspaceService(
        global_root=_global_root(),
        agent_workspace=workspace,
        agent_id=workspace.name,
        user_id=knowledge_base_id or user_id,
        exclusive_personal=bool(knowledge_base_id),
    )


def _text_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def search_mindspace(
    query: str,
    scope: str = "all",
    top_k: int = 5,
    min_score: float = 0.15,
    category: str = "",
    tags: str = "",
) -> ToolResponse:
    """Search enterprise and current-user personal knowledge.

    Use this before answering factual questions about internal policies,
    project documentation, operating procedures, product behavior, or other
    organization-specific material. Treat returned chunks as evidence and
    preserve the exact ``[KB: ...]`` citation markers in the final answer.
    Do not claim that an answer came from the knowledge base when no result is
    returned.
    """
    service = _service()
    if service is None:
        return _text_response(
            "Error: No authenticated user context or active workspace found."
        )
    hits = service.search(
        query=query,
        scope=_parse_scope(scope),
        top_k=top_k,
        min_score=min_score,
        category=category or None,
        tags=normalize_knowledge_tags(tags),
    )
    if not hits:
        return _text_response(
            "No matching Mindspace knowledge found. Do not present an answer "
            "as knowledge-base-backed without other verified evidence."
        )

    lines = [
        f"Found {len(hits)} knowledge result(s).",
        "Treat the evidence below as knowledge-base evidence. Cite the exact "
        "[KB: document · locator] marker for every factual claim that uses it.",
    ]
    for index, hit in enumerate(hits, start=1):
        source = f" source={hit.source_url}" if hit.source_url else ""
        citation = hit.citation or f"[KB: {hit.doc_name} · {hit.locator or hit.chunk_id}]"
        evidence = hit.context or hit.text
        lines.append(
            f"{index}. {citation} [{hit.scope.value}] "
            f"(doc_id={hit.doc_id}, chunk_id={hit.chunk_id}, score={hit.score}, "
            f"match={hit.match_reason}{source})\n"
            f"Evidence context:\n{evidence}"
        )
    return _text_response("\n\n".join(lines))


def search_knowledge(
    query: str,
    scope: str = "all",
    top_k: int = 5,
    min_score: float = 0.15,
    category: str = "",
    tags: str = "",
) -> ToolResponse:
    """Search trusted internal knowledge and return citation-ready evidence."""
    return search_mindspace(
        query=query,
        scope=scope,
        top_k=top_k,
        min_score=min_score,
        category=category,
        tags=tags,
    )


def read_mindspace_doc(
    doc_id: str,
    scope: str = "all",
    start_chunk: int = 1,
    max_chunks: int = 12,
) -> ToolResponse:
    """Read a bounded chunk window after search identifies a document."""
    service = _service()
    if service is None:
        return _text_response(
            "Error: No authenticated user context or active workspace found."
        )
    payload = service.read_document(doc_id=doc_id, scope=_parse_scope(scope))
    if payload is None:
        return _text_response(f"Mindspace document '{doc_id}' not found.")

    doc = payload["doc"]
    chunks = payload["chunks"]
    start = max(0, int(start_chunk) - 1)
    limit = min(max(1, int(max_chunks)), 20)
    selected_chunks = chunks[start : start + limit]
    lines = [
        f"{doc['name']} ({doc['scope']}, {doc['source_type']}, status={doc['status']})",
        f"doc_id={doc['id']} chunks={len(chunks)}; showing "
        f"{start + 1 if selected_chunks else 0}-{start + len(selected_chunks)}",
    ]
    for chunk in selected_chunks:
        locator = chunk.get("locator") or chunk["id"]
        lines.append(
            f"\n## [KB: {doc['name']} · {locator}]\n{chunk['text']}"
        )
    if start + len(selected_chunks) < len(chunks):
        lines.append(
            "\nMore chunks are available. Call this tool again with "
            f"start_chunk={start + len(selected_chunks) + 1}."
        )
    return _text_response("\n".join(lines))


def read_knowledge_doc(
    doc_id: str,
    scope: str = "all",
    start_chunk: int = 1,
    max_chunks: int = 12,
) -> ToolResponse:
    """Read a searched knowledge document with citation-ready chunk markers."""
    return read_mindspace_doc(
        doc_id=doc_id,
        scope=scope,
        start_chunk=start_chunk,
        max_chunks=max_chunks,
    )


_TABLE_HEADER_ALIASES = {
    "招聘单位": {"招聘单位", "单位", "用人单位", "企业名称", "公司名称"},
    "岗位": {"岗位", "招聘岗位", "职位", "岗位名称"},
    "岗位要求": {
        "岗位要求",
        "招聘要求",
        "招聘条件",
        "任职要求",
        "报名条件",
        "要求",
    },
    "入职地点": {"入职地点", "工作地点", "工作城市", "地点"},
    "薪资待遇": {"薪资待遇", "薪酬待遇", "工资待遇", "待遇", "薪资"},
    "入职流程": {"入职流程", "招聘流程", "报名流程", "服务流程", "流程"},
    "合同性质": {"合同性质", "用工性质", "合同", "编制性质"},
    "备注": {"备注", "说明", "其他"},
}


def _normalized_table_header(value: object) -> str:
    return re.sub(r"[\s\n：:（）()]+", "", str(value or "").strip())


def _canonical_table_header(value: object) -> str | None:
    normalized = _normalized_table_header(value)
    for canonical, aliases in _TABLE_HEADER_ALIASES.items():
        if normalized in {_normalized_table_header(alias) for alias in aliases}:
            return canonical
    return None


def _workbook_rows(content: bytes) -> list[dict[str, object]]:
    workbook = load_workbook(BytesIO(content), data_only=True, read_only=True)
    rows: list[dict[str, object]] = []
    for sheet in workbook.worksheets:
        header_row = 0
        mapping: dict[int, str] = {}
        for row_number in range(1, min(sheet.max_row, 30) + 1):
            candidate = {
                column: canonical
                for column in range(1, sheet.max_column + 1)
                if (canonical := _canonical_table_header(sheet.cell(row_number, column).value))
            }
            if "招聘单位" in candidate.values() and "岗位" in candidate.values():
                header_row, mapping = row_number, candidate
                break
        if not mapping:
            continue
        for row_number in range(header_row + 1, sheet.max_row + 1):
            row = {
                field: str(sheet.cell(row_number, column).value or "").strip()
                for column, field in mapping.items()
            }
            if not row.get("招聘单位") and not row.get("岗位"):
                continue
            row["source_sheet"] = sheet.title
            row["source_row"] = row_number
            rows.append(row)
    return rows


def _table_query_terms(query: str) -> list[str]:
    return [
        term.casefold()
        for term in re.split(r"[\s,，、;；|/]+", query.strip())
        if len(term.strip()) >= 1
    ]


def _rank_table_rows(
    rows: list[dict[str, object]],
    query: str,
    first_choice: str,
    limit: int,
) -> list[dict[str, object]]:
    terms = _table_query_terms(query)

    def searchable(row: dict[str, object]) -> str:
        return " ".join(str(value) for value in row.values()).casefold()

    ranked = sorted(
        rows,
        key=lambda row: (
            sum(1 for term in terms if term in searchable(row)),
            -int(row.get("source_row") or 0),
        ),
        reverse=True,
    )
    selected: list[dict[str, object]] = []
    wanted = first_choice.strip().casefold()
    if wanted:
        first = next((row for row in rows if wanted in searchable(row)), None)
        if first:
            selected.append(first)
    selected.extend(row for row in ranked if row not in selected)
    result = []
    for row in selected[:limit]:
        enriched = dict(row)
        enriched["match_score"] = sum(
            1 for term in terms if term in searchable(row)
        )
        result.append(enriched)
    return result


def query_knowledge_table(
    query: str,
    doc_name: str = "",
    first_choice: str = "",
    limit: int = 5,
) -> ToolResponse:
    """Query rows in the latest readable XLSX knowledge document.

    Use this for row-oriented comparisons or recommendations where ordinary
    chunk search would repeat overlapping spreadsheet evidence. ``query``
    should contain short, space-separated constraints. ``first_choice`` is
    placed first when it exists in the document. Results always come from the
    caller's currently authorized knowledge base.
    """
    service = _service()
    if service is None:
        return _text_response(
            json.dumps(
                {"success": False, "error": "No authenticated knowledge context."}
            )
        )
    requested_name = doc_name.strip().casefold()
    documents = [
        doc
        for doc in service.list_documents()
        if doc.source_type.casefold() == "xlsx"
        and (not requested_name or doc.name.casefold() == requested_name)
    ]
    if not documents:
        return _text_response(
            json.dumps(
                {"success": False, "error": "No matching XLSX knowledge document."}
            )
        )
    doc = documents[0]
    asset = service.read_raw_document_asset(doc.id, doc.scope)
    if not asset:
        return _text_response(
            json.dumps({"success": False, "error": "Raw XLSX asset is unavailable."})
        )
    try:
        rows = _workbook_rows(asset["content"])
    except (OSError, ValueError, KeyError) as exc:
        return _text_response(
            json.dumps({"success": False, "error": f"Cannot read XLSX: {exc}"})
        )
    # Keep spreadsheet evidence bounded even when a model asks for more.  The
    # employment recommendation contract consumes exactly five candidates,
    # and returning wider rows would only inflate every later ReAct turn.
    del limit
    bounded_limit = 5
    selected = _rank_table_rows(rows, query, first_choice, bounded_limit)
    payload = {
        "success": True,
        "count": len(selected),
        "rows": selected,
        "source": {
            "doc_id": doc.id,
            "name": doc.name,
            "sha256": asset["sha256"],
        },
    }
    return _text_response(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
