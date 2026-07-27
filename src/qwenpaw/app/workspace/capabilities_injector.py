# -*- coding: utf-8 -*-
"""Dynamic capability injection for user workspaces."""
import logging
from typing import Any

from ..storage.repos.capability_repo import get_capability_repository

logger = logging.getLogger(__name__)

def inject_user_capabilities(user_id: str, config: Any) -> None:
    """Inject user-subscribed capabilities into the agent runtime config.
    
    Args:
        user_id: The user ID extracted from the workspace path.
        config: The AgentConfig object.
    """
    try:
        # User ID might be "admin" or an int ID. If it's not digit, maybe fallback.
        # But our DB user_id is INTEGER. Let's try to convert or skip.
        try:
            uid = int(user_id)
        except ValueError:
            # Maybe it's a mock user from tests, or "admin".
            # For "admin", we can query user_id = 0 or just fallback.
            uid = 0

        rows = get_capability_repository().list_enabled_user_capabilities(uid)
        
        # Merge into config
        for row in rows:
            cap_type = row["type"]
            manifest = row["manifest"]
            creds = row["credentials"]
            
            if cap_type == "MCP":
                # Inject MCP
                if not hasattr(config, "mcp") or config.mcp is None:
                    config.mcp = {}
                
                # manifest for MCP: {"server_name": {"command": "...", "args": [...]}}
                for server_name, server_config in manifest.items():
                    # Merge credentials as env vars
                    if creds:
                        if "env" not in server_config:
                            server_config["env"] = {}
                        server_config["env"].update(creds)
                    config.mcp[server_name] = server_config
            
            elif cap_type == "SKILL":
                # Inject Skill
                if not hasattr(config, "skills") or config.skills is None:
                    config.skills = []
                # manifest for SKILL: {"name": "..."}
                skill_name = manifest.get("name")
                if skill_name and skill_name not in config.skills:
                    config.skills.append(skill_name)
                    
            elif cap_type == "TOOL":
                # Inject Tool
                if not hasattr(config, "tools") or config.tools is None:
                    config.tools = []
                # manifest for TOOL: {"name": "..."}
                tool_name = manifest.get("name")
                if tool_name and tool_name not in config.tools:
                    config.tools.append(tool_name)
                    
    except Exception as e:
        logger.error(f"Failed to inject user capabilities for user {user_id}: {e}")
