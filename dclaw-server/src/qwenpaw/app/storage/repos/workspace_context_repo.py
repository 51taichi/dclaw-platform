# -*- coding: utf-8 -*-
"""Repositories for workspace chat/session context lookups."""
from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ... import db
from ..engine import get_app_engine
from ..schema import chats, session_states
from ..settings import get_storage_settings


class WorkspaceContextRepository(Protocol):
    def get_session_id_for_chat_id(self, chat_id: str) -> str | None:
        ...

    def list_chat_identity_rows(self, chat_id_or_session_id: str) -> list[dict[str, str]]:
        ...

    def get_session_state_texts(self, chat_ids: list[str]) -> list[str]:
        ...


class SqlAlchemyWorkspaceContextRepository:
    """SQLAlchemy implementation for Postgres and SQLAlchemy-backed tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def get_session_id_for_chat_id(self, chat_id: str) -> str | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(chats.c.session_id).where(chats.c.id == chat_id),
            ).first()
        return str(row[0]) if row and row[0] else None

    def list_chat_identity_rows(self, chat_id_or_session_id: str) -> list[dict[str, str]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(chats.c.id, chats.c.session_id).where(
                    (chats.c.id == chat_id_or_session_id)
                    | (chats.c.session_id == chat_id_or_session_id),
                ),
            ).mappings().all()
        return [
            {"id": str(row["id"]), "session_id": str(row["session_id"])}
            for row in rows
        ]

    def get_session_state_texts(self, chat_ids: list[str]) -> list[str]:
        if not chat_ids:
            return []
        result: list[str] = []
        with self.engine.connect() as conn:
            for chat_id in chat_ids:
                row = conn.execute(
                    select(session_states.c.state_json).where(
                        session_states.c.chat_id == chat_id,
                    ),
                ).first()
                if row and row[0]:
                    result.append(str(row[0]))
        return result


class SqliteWorkspaceContextRepository:
    """SQLite compatibility implementation using the existing sqlite3 module."""

    def get_session_id_for_chat_id(self, chat_id: str) -> str | None:
        row = db.get_db().execute(
            "SELECT session_id FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        return str(row["session_id"]) if row and row["session_id"] else None

    def list_chat_identity_rows(self, chat_id_or_session_id: str) -> list[dict[str, str]]:
        rows = db.get_db().execute(
            """
            SELECT id, session_id
            FROM chats
            WHERE id = ? OR session_id = ?
            """,
            (chat_id_or_session_id, chat_id_or_session_id),
        ).fetchall()
        return [
            {"id": str(row["id"]), "session_id": str(row["session_id"])}
            for row in rows
        ]

    def get_session_state_texts(self, chat_ids: list[str]) -> list[str]:
        result: list[str] = []
        conn = db.get_db()
        for chat_id in chat_ids:
            row = conn.execute(
                "SELECT state_json FROM session_states WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row and row["state_json"]:
                result.append(str(row["state_json"]))
        return result


def get_workspace_context_repository() -> WorkspaceContextRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyWorkspaceContextRepository(get_app_engine())
    return SqliteWorkspaceContextRepository()
