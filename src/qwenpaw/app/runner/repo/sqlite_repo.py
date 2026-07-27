# -*- coding: utf-8 -*-
"""SQLite-backed chat repository."""
from __future__ import annotations

import json
import logging
from typing import Optional
from .base import BaseChatRepository
from ..models import ChatSpec, ChatsFile
from ...channels.schema import DEFAULT_CHANNEL
from ...db import get_db

logger = logging.getLogger(__name__)


class SqliteChatRepository(BaseChatRepository):
    """SQLite-backed repository for chat specs persistence."""

    def __init__(self, agent_id: str):
        """Initialize SQLite chat repository.

        Args:
            agent_id: The ID of the agent this repository belongs to.
        """
        self.agent_id = agent_id

    async def load(self) -> ChatsFile:
        """Not used for SQLite repo. We override all data-access methods."""
        raise NotImplementedError("SqliteChatRepository does not support full load()")

    async def save(self, chats_file: ChatsFile) -> None:
        """Not used for SQLite repo."""
        raise NotImplementedError("SqliteChatRepository does not support full save()")

    async def list_chats(self) -> list[ChatSpec]:
        """List all chat specifications for this agent."""
        return await self.filter_chats()

    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        """Get chat spec by chat_id (UUID)."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM chats WHERE id = ? AND agent_id = ?",
            (chat_id, self.agent_id)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_spec(row)

    async def get_chat_by_id(
        self,
        session_id: str,
        user_id: str,
        channel: str = DEFAULT_CHANNEL,
    ) -> Optional[ChatSpec]:
        """Get chat spec by session_id and user_id."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM chats 
            WHERE session_id = ? AND user_id = ? AND channel = ? AND agent_id = ?
            """,
            (session_id, user_id, channel, self.agent_id)
        )
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_spec(row)

    async def upsert_chat(self, spec: ChatSpec) -> None:
        """Insert or update a chat spec."""
        conn = get_db()
        cursor = conn.cursor()
        
        meta_json = json.dumps(spec.meta, ensure_ascii=False) if spec.meta else "{}"
        
        cursor.execute(
            """
            INSERT INTO chats (
                id, user_id, agent_id, session_id, channel, name, 
                status, task_status, pinned, meta, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                user_id=excluded.user_id,
                agent_id=excluded.agent_id,
                session_id=excluded.session_id,
                channel=excluded.channel,
                name=excluded.name,
                status=excluded.status,
                task_status=excluded.task_status,
                pinned=excluded.pinned,
                meta=excluded.meta,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at
            """,
            (
                spec.id,
                spec.user_id,
                self.agent_id,
                spec.session_id,
                spec.channel,
                spec.name,
                spec.status,
                spec.task_status,
                1 if spec.pinned else 0,
                meta_json,
                spec.created_at,
                spec.updated_at
            )
        )
        conn.commit()

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        """Delete chats by IDs."""
        if not chat_ids:
            return False
            
        conn = get_db()
        cursor = conn.cursor()
        
        placeholders = ",".join(["?"] * len(chat_ids))
        args = chat_ids + [self.agent_id]
        cursor.execute(
            f"SELECT id FROM chats WHERE id IN ({placeholders}) AND agent_id = ?",
            args,
        )
        scoped_chat_ids = [str(row["id"]) for row in cursor.fetchall()]
        if not scoped_chat_ids:
            return False

        scoped_placeholders = ",".join(["?"] * len(scoped_chat_ids))
        cursor.execute(
            f"DELETE FROM messages WHERE chat_id IN ({scoped_placeholders})",
            scoped_chat_ids,
        )
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_states'",
        )
        if cursor.fetchone():
            cursor.execute(
                f"DELETE FROM session_states WHERE chat_id IN ({scoped_placeholders})",
                scoped_chat_ids,
            )

        # We need to verify if any rows were deleted
        cursor.execute(
            f"DELETE FROM chats WHERE id IN ({scoped_placeholders}) AND agent_id = ?",
            scoped_chat_ids + [self.agent_id],
        )
        deleted = cursor.rowcount > 0
        conn.commit()
        return deleted

    async def filter_chats(
        self,
        user_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> list[ChatSpec]:
        """Filter chats by user_id and/or channel."""
        conn = get_db()
        cursor = conn.cursor()
        
        query = "SELECT * FROM chats WHERE agent_id = ?"
        args = [self.agent_id]
        
        if user_id is not None:
            query += " AND user_id = ?"
            args.append(user_id)
            
        if channel is not None:
            query += " AND channel = ?"
            args.append(channel)
            
        query += " ORDER BY updated_at DESC"
            
        cursor.execute(query, tuple(args))
        rows = cursor.fetchall()
        
        return [self._row_to_spec(row) for row in rows]

    async def count_messages(self, chat_id: str) -> int:
        """Return persisted message count for a chat."""
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE chat_id = ?",
            (chat_id,),
        )
        row = cursor.fetchone()
        return int(row["count"] if row else 0)

    async def get_chat_id_by_session(
        self,
        session_id: str,
        channel: str,
        user_id: Optional[str] = None,
    ) -> str | None:
        """Return most recent chat id for a session using indexed SQL."""
        conn = get_db()
        cursor = conn.cursor()
        query = """
            SELECT id FROM chats
            WHERE session_id = ? AND channel = ? AND agent_id = ?
        """
        args: list[object] = [session_id, channel, self.agent_id]
        if user_id is not None:
            query += " AND user_id = ?"
            args.append(user_id)
        query += " ORDER BY updated_at DESC LIMIT 1"
        cursor.execute(query, tuple(args))
        row = cursor.fetchone()
        return str(row["id"]) if row else None

    def _row_to_spec(self, row) -> ChatSpec:
        """Convert a database row to a ChatSpec."""
        meta = {}
        if row["meta"]:
            try:
                meta = json.loads(row["meta"])
            except json.JSONDecodeError:
                pass
        
        # Inject agent_id so frontend can read it
        if "agent_id" not in meta:
            meta["agent_id"] = row["agent_id"]
                
        return ChatSpec(
            id=row["id"],
            user_id=str(row["user_id"]),
            session_id=row["session_id"],
            channel=row["channel"],
            name=row["name"],
            status=row["status"],
            task_status=row["task_status"],
            pinned=bool(row["pinned"]),
            meta=meta,
            created_at=row["created_at"],
            updated_at=row["updated_at"]
        )
