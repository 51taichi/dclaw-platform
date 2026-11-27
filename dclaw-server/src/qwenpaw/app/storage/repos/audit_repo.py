# -*- coding: utf-8 -*-
"""Repositories for admin audit queries."""
from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ... import db
from ..engine import get_app_engine
from ..schema import chats
from ..settings import get_storage_settings


class AuditRepository(Protocol):
    def list_chats(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        ...

    def get_chat_identity(self, chat_id: str) -> dict[str, Any] | None:
        ...


class SqlAlchemyAuditRepository:
    """SQLAlchemy implementation for Postgres and SQLAlchemy-backed tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_chats(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        stmt = select(chats)
        if user_id:
            stmt = stmt.where(chats.c.user_id == str(user_id))
        if agent_id:
            stmt = stmt.where(chats.c.agent_id == agent_id)
        stmt = stmt.order_by(chats.c.updated_at.desc()).limit(limit).offset(offset)

        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [_chat_row(row) for row in rows]

    def get_chat_identity(self, chat_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(
                    chats.c.agent_id,
                    chats.c.session_id,
                    chats.c.user_id,
                    chats.c.channel,
                ).where(chats.c.id == chat_id),
            ).mappings().first()
        return _identity_row(row) if row else None


class SqliteAuditRepository:
    """SQLite compatibility implementation using the existing sqlite3 module."""

    def list_chats(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM chats WHERE 1=1"
        params: list[Any] = []
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = db.get_db().execute(query, params).fetchall()
        return [_chat_row(dict(row)) for row in rows]

    def get_chat_identity(self, chat_id: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            """
            SELECT agent_id, session_id, user_id, channel
            FROM chats
            WHERE id = ?
            """,
            (chat_id,),
        ).fetchone()
        return _identity_row(dict(row)) if row else None


def get_audit_repository() -> AuditRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyAuditRepository(get_app_engine())
    return SqliteAuditRepository()


def _chat_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["user_id"] = str(result.get("user_id"))
    return result


def _identity_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": row["agent_id"],
        "session_id": row["session_id"],
        "user_id": str(row["user_id"]),
        "channel": row["channel"],
    }
