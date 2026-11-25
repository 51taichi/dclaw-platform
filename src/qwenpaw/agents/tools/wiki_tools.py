# -*- coding: utf-8 -*-
"""Wiki reading and searching tools for agents."""

from pathlib import Path
from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ...mindspace import MindspaceScope, MindspaceService
from ...mindspace.models import normalize_mindspace_scope


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
    try:
        return MindspaceService(
            global_root=_global_root(),
            agent_workspace=workspace,
            agent_id=workspace.name,
            user_id=knowledge_base_id or user_id,
            exclusive_personal=bool(knowledge_base_id),
        )
    except Exception:
        return None


def _normalize_concept(concept: str) -> str:
    value = concept.strip()
    if value.endswith(".md"):
        return value[:-3]
    return value


def _text_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


def _read_mindspace_wiki(
    service: MindspaceService,
    concept: str,
    scope: str | None,
) -> str | None:
    normalized = _normalize_concept(concept)
    resolved_scope = _parse_scope(scope)
    if resolved_scope is not None:
        return service.read_wiki(normalized, resolved_scope)

    for item in service.list_wiki(scope=None):
        if item["concept"] != normalized:
            continue
        item_scope = _parse_scope(item.get("scope"))
        if item_scope is None:
            continue
        return service.read_wiki(normalized, item_scope)
    return None


def _search_mindspace_wiki(
    service: MindspaceService,
    keyword: str,
    scope: str | None,
) -> list[dict[str, str]]:
    normalized = keyword.strip().lower()
    concepts = service.list_wiki(scope=_parse_scope(scope))
    if not normalized:
        return concepts
    return [
        item
        for item in concepts
        if normalized in item["concept"].lower()
        or normalized in item.get("name", "").lower()
    ]


def read_wiki_page(concept: str, scope: str = "all") -> ToolResponse:
    """
    Read the full content of a specific LLM-Wiki page by its concept name.
    
    Use this tool when you need deep, structured knowledge about a specific
    concept mentioned in the context (usually represented as [[Concept Name]]).

    Args:
        concept (`str`): The name of the concept to read (without .md extension).
        scope (`str`): enterprise, personal, global, agent, or all.

    Returns:
        `ToolResponse`: The markdown content of the wiki page.
    """
    workspace_dir = get_current_workspace_dir()
    if not workspace_dir:
        return _text_response("Error: No active workspace found.")

    service = _service()
    if service is None:
        return _text_response("Error: No authenticated user context found.")
    content = _read_mindspace_wiki(service, concept, scope)
    if content is not None:
        return _text_response(content)

    normalized_concept = _normalize_concept(concept)
    wiki_path = Path(workspace_dir) / "memory" / "wiki" / f"{normalized_concept}.md"
    if not wiki_path.exists():
        return _text_response(
            f"Wiki page for '{normalized_concept}' not found.",
        )
        
    try:
        with open(wiki_path, "r", encoding="utf-8") as f:
            content = f.read()
        return _text_response(content)
    except Exception as e:
        return _text_response(f"Error reading wiki page: {e}")


def search_wiki(keyword: str, scope: str = "all") -> ToolResponse:
    """
    Search for all available Wiki pages related to the given keyword.
    
    Returns a list of matching wiki page names.

    Args:
        keyword (`str`): The keyword to search for in wiki titles.
        scope (`str`): enterprise, personal, global, agent, or all.

    Returns:
        `ToolResponse`: A list of matching concept names.
    """
    workspace_dir = get_current_workspace_dir()
    if not workspace_dir:
        return _text_response("Error: No active workspace found.")

    service = _service()
    if service is None:
        return _text_response("Error: No authenticated user context found.")
    results = _search_mindspace_wiki(service, keyword, scope)
    if results:
        names = [f"{item['concept']} ({item['scope']})" for item in results]
        return _text_response(
            f"Found {len(results)} pages: " + ", ".join(names),
        )

    wiki_dir = Path(workspace_dir) / "memory" / "wiki"
    if not wiki_dir.exists():
        return _text_response("No wiki directory found.")

    results = []
    try:
        for md_file in wiki_dir.glob("*.md"):
            name = md_file.stem
            if keyword.lower() in name.lower():
                results.append(name)
        if not results:
            return _text_response("No matching wiki pages found.")
        return _text_response(
            f"Found {len(results)} pages: " + ", ".join(results),
        )
    except Exception as e:
        return _text_response(f"Error searching wiki: {e}")
