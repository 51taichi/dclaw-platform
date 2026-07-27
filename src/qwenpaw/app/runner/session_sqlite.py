# -*- coding: utf-8 -*-
"""SQLite-backed session state storage."""

import json
import logging
from typing import Union, Sequence, Dict, Any, Optional
import uuid
from datetime import datetime, timezone

from agentscope.session import SessionBase
from agentscope_runtime.engine.schemas.exception import ConfigurationException
from ...exceptions import AgentStateError
from ..db import get_db

logger = logging.getLogger(__name__)


class SqliteSession(SessionBase):
    """SessionBase subclass that stores memory in a global SQLite database.
    
    It stores `memory` state directly into the `messages` table.
    Any other state modules are currently merged and stored in the database
    as serialized JSON under `session_states` table if needed, or ignored 
    if we only care about memory for now. Wait, let's store other states
    in a `session_states` table just to be fully compatible.
    """

    def __init__(self, agent_id: str) -> None:
        """Initialize the SQLite session class."""
        self.agent_id = agent_id

    def _get_chat_id(self, session_id: str, user_id: str, channel: str) -> str:
        """Helper to find the chat_id for a session."""
        # Wait, if chat is not found, what should we do? 
        # For now, we assume chat_id = session_id + user_id if not strictly found, 
        # but actually we can query the chats table.
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id FROM chats 
            WHERE session_id = ? AND user_id = ? AND channel = ? AND agent_id = ?
            """,
            (session_id, user_id, channel, self.agent_id)
        )
        row = cursor.fetchone()
        if row:
            return row["id"]
        # Fallback if chat is somehow not synced yet: generate a deterministic or temporary one.
        # But we must have a chat_id. Let's just create a dummy chat or use session_id.
        # Actually, let's insert a pending chat.
        chat_id = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO chats (
                id, user_id, agent_id, session_id, channel, name, 
                status, task_status, pinned, meta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (chat_id, user_id or 0, self.agent_id, session_id, channel or 'default', 
             'New Chat', 'idle', 'pending', 0, '{}')
        )
        conn.commit()
        return chat_id

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        **state_modules_mapping,
    ) -> None:
        """Save state modules to SQLite."""
        chat_id = self._get_chat_id(session_id, user_id, channel)
        conn = get_db()
        cursor = conn.cursor()
        
        # 1. Extract memory (messages)
        memory_module = state_modules_mapping.get("memory")
        if memory_module:
            messages = memory_module.state_dict()
            if isinstance(messages, list):
                # Delete existing messages for this chat_id to overwrite, 
                # or we can do upsert. For simplicity, delete and insert.
                # Actually, an append-only approach is better, but state_dict()
                # gives the full list.
                cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
                
                for msg in messages:
                    msg_id = msg.get("id") or str(uuid.uuid4())
                    role = msg.get("role", "unknown")
                    name = msg.get("name", role)
                    content = msg.get("content", "")
                    
                    # Store everything else in meta
                    meta = {k: v for k, v in msg.items() if k not in ("id", "role", "name", "content")}
                    meta_json = json.dumps(meta, ensure_ascii=False)
                    
                    # Convert content to string if it's not
                    if not isinstance(content, str):
                        try:
                            content_str = json.dumps(content, ensure_ascii=False)
                        except:
                            content_str = str(content)
                    else:
                        content_str = content
                        
                    cursor.execute(
                        """
                        INSERT INTO messages (id, chat_id, role, name, content, meta, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (msg_id, chat_id, role, name, content_str, meta_json, datetime.now(timezone.utc))
                    )
        
        # 2. Store other states (if any) in session_states table
        # We need to create a `session_states` table for non-memory state modules.
        # If it doesn't exist, we will create it inline for backward compatibility.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_states (
                chat_id TEXT PRIMARY KEY,
                state_json TEXT
            )
        ''')
        
        other_states = {
            name: module.state_dict()
            for name, module in state_modules_mapping.items()
            if name != "memory"
        }
        
        if other_states:
            state_json = json.dumps(other_states, ensure_ascii=False)
            cursor.execute(
                """
                INSERT INTO session_states (chat_id, state_json)
                VALUES (?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET state_json=excluded.state_json
                """,
                (chat_id, state_json)
            )
            
        conn.commit()
        logger.info(f"Saved session state to SQLite for session {session_id}")

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        """Load state modules from SQLite."""
        chat_id = self._get_chat_id(session_id, user_id, channel)
        conn = get_db()
        cursor = conn.cursor()
        
        # 1. Load memory
        memory_module = state_modules_mapping.get("memory")
        if memory_module:
            cursor.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY timestamp ASC", (chat_id,))
            rows = cursor.fetchall()
            if rows:
                messages = []
                for row in rows:
                    msg = {
                        "id": row["id"],
                        "role": row["role"],
                        "name": row["name"],
                        "content": row["content"]
                    }
                    if row["meta"]:
                        try:
                            meta = json.loads(row["meta"])
                            msg.update(meta)
                        except:
                            pass
                    messages.append(msg)
                memory_module.load_state_dict(messages)
        
        # 2. Load other states
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_states'")
        if cursor.fetchone():
            cursor.execute("SELECT state_json FROM session_states WHERE chat_id = ?", (chat_id,))
            row = cursor.fetchone()
            if row and row["state_json"]:
                try:
                    other_states = json.loads(row["state_json"])
                    for name, module in state_modules_mapping.items():
                        if name != "memory" and name in other_states:
                            module.load_state_dict(other_states[name])
                except json.JSONDecodeError:
                    pass
                    
        logger.info(f"Loaded session state from SQLite for session {session_id}")

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        channel: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        """Update a specific key in the session state."""
        # For simplicity in Phase 6, we'll just fall back to full load-modify-save
        # because update_session_state is rarely used directly for deep keys in sqlite.
        # But wait! If we do full load, we need the state modules. 
        # Actually, `update_session_state` in SafeJSONSession modifies the JSON dict directly.
        # We can implement this for `session_states` table.
        chat_id = self._get_chat_id(session_id, user_id, channel)
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_states'")
        if not cursor.fetchone():
            cursor.execute('CREATE TABLE IF NOT EXISTS session_states (chat_id TEXT PRIMARY KEY, state_json TEXT)')
            
        cursor.execute("SELECT state_json FROM session_states WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        
        if row and row["state_json"]:
            try:
                states = json.loads(row["state_json"])
            except:
                states = {}
        else:
            if not create_if_not_exist:
                raise AgentStateError(
                    session_id=session_id,
                    message=f"Session state for {session_id} does not exist",
                )
            states = {}
            
        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ConfigurationException(config_key="session.key", message="key path is empty")
            
        cur = states
        for k in path[:-1]:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]
        cur[path[-1]] = value
        
        state_json = json.dumps(states, ensure_ascii=False)
        cursor.execute(
            """
            INSERT INTO session_states (chat_id, state_json)
            VALUES (?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET state_json=excluded.state_json
            """,
            (chat_id, state_json)
        )
        conn.commit()

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        """Get the full session state dict."""
        chat_id = self._get_chat_id(session_id, user_id, channel)
        conn = get_db()
        cursor = conn.cursor()
        
        result = {}
        
        # 1. Load messages
        cursor.execute("SELECT * FROM messages WHERE chat_id = ? ORDER BY timestamp ASC", (chat_id,))
        rows = cursor.fetchall()
        if rows:
            messages = []
            for row in rows:
                msg = {
                    "id": row["id"],
                    "role": row["role"],
                    "name": row["name"],
                    "content": row["content"]
                }
                if row["meta"]:
                    try:
                        meta = json.loads(row["meta"])
                        msg.update(meta)
                    except:
                        pass
                messages.append(msg)
            result["memory"] = messages
            
        # 2. Load other states
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='session_states'")
        if cursor.fetchone():
            cursor.execute("SELECT state_json FROM session_states WHERE chat_id = ?", (chat_id,))
            row = cursor.fetchone()
            if row and row["state_json"]:
                try:
                    other_states = json.loads(row["state_json"])
                    result.update(other_states)
                except:
                    pass
                    
        if not result and not allow_not_exist:
            raise AgentStateError(
                session_id=session_id,
                message=f"Failed to get session state for {session_id} because it does not exist",
            )
            
        return result
