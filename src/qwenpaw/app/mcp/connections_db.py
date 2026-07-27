# -*- coding: utf-8 -*-
"""Database CRUD operations for User Connections (e.g. MCP Connectors)."""
from typing import Optional, List, Dict, Any
from ..storage.repos.capability_repo import get_capability_repository

def add_or_update_connection(user_id: int, connector_key: str, oauth_tokens: Optional[Dict] = None, custom_envs: Optional[Dict] = None) -> int:
    """Add or update a user connection (e.g. MCP auth tokens/envs)."""
    return get_capability_repository().add_or_update_connection(
        user_id,
        connector_key,
        oauth_tokens=oauth_tokens,
        custom_envs=custom_envs,
    )

def get_user_connections(user_id: int) -> List[Dict[str, Any]]:
    """Get all active connections for a user."""
    return get_capability_repository().get_user_connections(user_id)

def disable_connection(user_id: int, connector_key: str) -> None:
    """Disable a user connection."""
    get_capability_repository().disable_connection(user_id, connector_key)
