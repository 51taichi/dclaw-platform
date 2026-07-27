# -*- coding: utf-8 -*-
"""Repositories for cross-agent chat list queries."""
from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine

from ... import db
from ..engine import get_app_engine
from ..schema import chats, messages
from ..settings import get_storage_settings


class ChatListRepository(Protocol):
    def cleanup_empty_ghost_chats(
        self,
        *,
        enabled_agent_ids: list[str],
        user_id: str,
    ) -> int:
        ...

    def list_recent_chats(
        self,
        *,
        enabled_agent_ids: list[str],
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        ...


class SqlAlchemyChatListRepository:
    """SQLAlchemy implementation for Postgres and SQLAlchemy-backed tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def cleanup_empty_ghost_chats(
        self,
        *,
        enabled_agent_ids: list[str],
        user_id: str,
    ) -> int:
        if not enabled_agent_ids:
            return 0
        has_messages = select(messages.c.id).where(messages.c.chat_id == chats.c.id).exists()
        stmt = delete(chats).where(
            chats.c.agent_id.in_(enabled_agent_ids),
            chats.c.user_id == str(user_id),
            chats.c.name == "New Chat",
            func.coalesce(chats.c.status, "idle") != "running",
            ~has_messages,
        )
        with self.engine.begin() as conn:
            result = conn.execute(stmt)
        return int(result.rowcount or 0)

    def list_recent_chats(
        self,
        *,
        enabled_agent_ids: list[str],
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not enabled_agent_ids:
            return []
        candidate_chats = (
            select(chats)
            .where(
                chats.c.agent_id.in_(enabled_agent_ids),
                chats.c.user_id == str(user_id),
                ~chats.c.session_id.like("open:%"),
                ~func.coalesce(chats.c.channel, "").like("open:%"),
            )
            .order_by(chats.c.updated_at.desc())
            .limit(limit)
            .subquery("candidate_chats")
        )
        message_counts = (
            select(
                messages.c.chat_id.label("chat_id"),
                func.count(messages.c.id).label("message_count"),
            )
            .where(messages.c.chat_id.in_(select(candidate_chats.c.id)))
            .group_by(messages.c.chat_id)
            .subquery()
        )
        stmt = (
            select(
                candidate_chats,
                func.coalesce(message_counts.c.message_count, 0).label(
                    "message_count",
                ),
            )
            .outerjoin(
                message_counts,
                message_counts.c.chat_id == candidate_chats.c.id,
            )
            .order_by(candidate_chats.c.updated_at.desc())
        )
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_normalize_chat_row(row) for row in rows]


class SqliteChatListRepository:
    """SQLite compatibility implementation using the existing sqlite3 module."""

    def cleanup_empty_ghost_chats(
        self,
        *,
        enabled_agent_ids: list[str],
        user_id: str,
    ) -> int:
        if not enabled_agent_ids:
            return 0
        placeholders = ",".join(["?"] * len(enabled_agent_ids))
        cursor = db.get_db().cursor()
        cursor.execute(
            f"""
            DELETE FROM chats
            WHERE agent_id IN ({placeholders})
              AND user_id = ?
              AND name = 'New Chat'
              AND COALESCE(status, 'idle') != 'running'
              AND NOT EXISTS (
                  SELECT 1 FROM messages WHERE messages.chat_id = chats.id
              )
            """,
            [*enabled_agent_ids, user_id],
        )
        deleted = int(cursor.rowcount or 0)
        db.get_db().commit()
        return deleted

    def list_recent_chats(
        self,
        *,
        enabled_agent_ids: list[str],
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not enabled_agent_ids:
            return []
        placeholders = ",".join(["?"] * len(enabled_agent_ids))
        rows = db.get_db().execute(
            f"""
            WITH candidate_chats AS (
                SELECT *
                FROM chats
                WHERE agent_id IN ({placeholders})
                  AND user_id = ?
                  AND session_id NOT LIKE 'open:%'
                  AND COALESCE(channel, '') NOT LIKE 'open:%'
                ORDER BY updated_at DESC
                LIMIT ?
            )
            SELECT candidate_chats.*, COUNT(messages.id) AS message_count
            FROM candidate_chats
            LEFT JOIN messages ON messages.chat_id = candidate_chats.id
            GROUP BY candidate_chats.id
            ORDER BY candidate_chats.updated_at DESC
            """,
            [*enabled_agent_ids, user_id, limit],
        ).fetchall()
        return [_normalize_chat_row(dict(row)) for row in rows]


def get_chat_list_repository() -> ChatListRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyChatListRepository(get_app_engine())
    return SqliteChatListRepository()


def _normalize_chat_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": str(row["user_id"]),
        "agent_id": row["agent_id"],
        "session_id": row["session_id"],
        "channel": row["channel"],
        "name": row["name"],
        "status": row["status"] or "idle",
        "task_status": row["task_status"] or "pending",
        "pinned": bool(row["pinned"]),
        "meta": row.get("meta") or "{}",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "message_count": int(row["message_count"] or 0),
    }
