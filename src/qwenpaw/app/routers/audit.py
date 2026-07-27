# -*- coding: utf-8 -*-
"""Admin API for auditing and monitoring."""

from fastapi import APIRouter, Query, Request, HTTPException
import json
from pathlib import Path

from ...config import load_config
from ..runner.session import _safe_json_loads, sanitize_filename
from ..storage.repos.audit_repo import get_audit_repository

router = APIRouter(prefix="/audit", tags=["audit"])

@router.get("/chats")
async def get_audit_chats(
    request: Request,
    user_id: str | None = Query(None, description="Filter by user ID"),
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    limit: int = Query(50, description="Max results"),
    offset: int = Query(0, description="Offset"),
) -> list[dict]:
    """Get all chats for audit purposes (admin only)."""
    role = getattr(request.state, "role", "user")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
        
    rows = get_audit_repository().list_chats(
        user_id=user_id,
        agent_id=agent_id,
        limit=limit,
        offset=offset,
    )
    
    chats = []
    for row in rows:
        chat = dict(row)
        if chat.get("meta"):
            try:
                chat["meta"] = json.loads(chat["meta"])
            except:
                pass
        chats.append(chat)
        
    return chats

@router.get("/chats/{chat_id}/messages")
async def get_audit_chat_messages(
    request: Request,
    chat_id: str,
) -> list[dict]:
    """Get messages for a specific chat for audit purposes (admin only)."""
    role = getattr(request.state, "role", "user")
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
        
    row = get_audit_repository().get_chat_identity(chat_id)
    
    if not row:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    agent_id = row["agent_id"]
    session_id = row["session_id"]
    uid = str(row["user_id"])
    channel = row["channel"]
    
    config = load_config()
    agent_ref = config.agents.profiles.get(agent_id)
    if not agent_ref:
        raise HTTPException(status_code=404, detail="Agent profile not found")
        
    workspace_dir = Path(agent_ref.workspace_dir).expanduser()
    
    # Reconstruct SafeJSONSession path
    save_dir = workspace_dir / "sessions"
    safe_sid = sanitize_filename(session_id)
    safe_uid = sanitize_filename(uid)
    filename = f"{safe_uid}_{safe_sid}.json" if safe_uid else f"{safe_sid}.json"
    
    if channel and channel != "default":
        safe_channel = sanitize_filename(channel)
        file_path = save_dir / safe_channel / filename
    else:
        file_path = save_dir / filename
        
    if not file_path.exists():
        # Check fallback without channel
        fallback_path = save_dir / filename
        if fallback_path.exists():
            file_path = fallback_path
        else:
            return []
            
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        states = _safe_json_loads(content, str(file_path))
        
    # AgentScope format
    memories = states.get("agent", {}).get("memory", {}).get("memories", [])
    if not memories:
        memories = states.get("agent", {}).get("memory", {}).get("content", [])
        
    # Flatten if needed
    messages = []
    for item in memories:
        if isinstance(item, list) and len(item) > 0:
            messages.append(item[0])
        elif isinstance(item, dict):
            messages.append(item)
            
    return messages
