# -*- coding: utf-8 -*-
"""Mindspace search and document reading tools for agents."""

from __future__ import annotations

from pathlib import Path

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
