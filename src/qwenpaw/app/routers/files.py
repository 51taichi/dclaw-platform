# -*- coding: utf-8 -*-
from pathlib import Path
from urllib.parse import unquote
from fastapi import APIRouter, HTTPException, Request
from starlette.responses import FileResponse

from ..auth import is_auth_enabled
from ..chat_access import is_admin_request

router = APIRouter(prefix="/files", tags=["files"])


def _is_inside(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


@router.api_route(
    "/preview/{filepath:path}",
    methods=["GET", "HEAD"],
    summary="Preview file",
)
async def preview_file(
    filepath: str,
    request: Request,
):
    """Preview file."""
    normalized = unquote(filepath)

    # Normalize /C:/... to C:/... on Windows.
    if (
        len(normalized) >= 4
        and normalized[0] == "/"
        and normalized[2] == ":"
        and normalized[1].isalpha()
    ):
        normalized = normalized[1:]

    path = Path(normalized)

    from ..agent_context import get_agent_for_request
    from .workspace import (
        _assert_root_fallback_allowed,
        _request_chat_id,
        _require_chat_context_for_user,
        _workspace_dir_for_user_context,
        get_workspace_dir_for_request,
    )

    workspace = await get_agent_for_request(request)
    root_workspace_dir = Path(workspace.workspace_dir).resolve()
    requested_chat_id = _request_chat_id(request)
    user_scoped = is_auth_enabled() and not is_admin_request(request)

    if user_scoped:
        _require_chat_context_for_user(request, requested_chat_id)
        workspace_dir = _workspace_dir_for_user_context(request, root_workspace_dir)
        if path.is_absolute():
            path = path.resolve()
            if not _is_inside(path, workspace_dir):
                if not _is_inside(path, root_workspace_dir):
                    raise HTTPException(status_code=403, detail="Access denied")
                rel_artifact_path = path.relative_to(root_workspace_dir).as_posix()
                _assert_root_fallback_allowed(
                    request,
                    requested_chat_id,
                    rel_artifact_path,
                    root_workspace_dir,
                )
        else:
            path = (workspace_dir / normalized).resolve()
            if not _is_inside(path, workspace_dir):
                raise HTTPException(status_code=403, detail="Path traversal detected")
    else:
        # If the path is not absolute, resolve it relative to the agent's sandboxed workspace.
        if not path.is_absolute():
            try:
                workspace_dir = get_workspace_dir_for_request(request, root_workspace_dir)
                path = (workspace_dir / normalized).resolve()
                if not _is_inside(path, workspace_dir):
                    raise HTTPException(status_code=403, detail="Path traversal detected")
            except HTTPException:
                raise
            except Exception:
                # Fallback to absolute system path for legacy/admin preview behavior.
                if not path.is_absolute():
                    path = Path("/" + normalized).resolve()
        else:
            path = path.resolve()

    # High-robustness smart fallback for folder or missing HTML files
    is_dir = path.is_dir()
    is_missing_html = not path.exists() and (
        path.suffix.lower() == ".html" or path.name.lower() == "index.html"
    )

    if is_dir or is_missing_html:
        search_dir = path if is_dir else path.parent
        if search_dir.exists() and search_dir.is_dir():
            try:
                index_file = search_dir / "index.html"
                if index_file.is_file():
                    path = index_file
                else:
                    html_files = [
                        f for f in search_dir.iterdir()
                        if f.is_file() and f.suffix.lower() == ".html" and f.name.lower() != "index.html"
                    ]
                    if html_files:
                        # Sort by modification time descending (newest first)
                        html_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                        
                        # Prioritize game/play/app/main patterns
                        game_file = None
                        for f in html_files:
                            fname_lower = f.name.lower()
                            if any(k in fname_lower for k in ["game", "play", "app", "main"]):
                                game_file = f
                                break
                        
                        path = game_file if game_file else html_files[0]
            except Exception:
                pass

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, filename=path.name)
