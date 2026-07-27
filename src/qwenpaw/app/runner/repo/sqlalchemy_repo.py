# -*- coding: utf-8 -*-
"""SQLAlchemy-backed chat repository for Postgres-ready storage."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine

from .base import BaseChatRepository
from ..models import ChatSpec, ChatsFile
from ...channels.schema import DEFAULT_CHANNEL
from ...storage.schema import chats, messages, session_states

logger = logging.getLogger(__name__)


class SqlAlchemyChatRepository(BaseChatRepository):
    """Chat repository backed by SQLAlchemy Core."""

    def __init__(self, agent_id: str, engine: Engine) -> None:
        self.agent_id = agent_id
        self.engine = engine

    async def load(self) -> ChatsFile:
        raise NotImplementedError("SqlAlchemyChatRepository does not support full load()")

    async def save(self, chats_file: ChatsFile) -> None:
        raise NotImplementedError("SqlAlchemyChatRepository does not support full save()")

    async def list_chats(self) -> list[ChatSpec]:
        return await self.filter_chats()

    async def get_chat(self, chat_id: str) -> Optional[ChatSpec]:
        stmt = select(chats).where(
            chats.c.id == chat_id,
            chats.c.agent_id == self.agent_id,
        )
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return self._row_to_spec(row) if row else None

    async def get_chat_by_id(
        self,
        session_id: str,
        user_id: str,
        channel: str = DEFAULT_CHANNEL,
    ) -> Optional[ChatSpec]:
        stmt = select(chats).where(
            chats.c.session_id == session_id,
            chats.c.user_id == str(user_id),
            chats.c.channel == channel,
            chats.c.agent_id == self.agent_id,
        )
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return self._row_to_spec(row) if row else None

    async def upsert_chat(self, spec: ChatSpec) -> None:
        values = {
            "id": spec.id,
            "user_id": str(spec.user_id),
            "agent_id": self.agent_id,
            "session_id": spec.session_id,
            "channel": spec.channel,
            "name": spec.name,
            "status": spec.status,
            "task_status": spec.task_status,
            "pinned": bool(spec.pinned),
            "meta": json.dumps(spec.meta or {}, ensure_ascii=False),
            "created_at": spec.created_at,
            "updated_at": spec.updated_at,
        }
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(chats.c.id).where(
                    chats.c.id == spec.id,
                    chats.c.agent_id == self.agent_id,
                ),
            ).first()
            if existing:
                conn.execute(
                    update(chats)
                    .where(
                        chats.c.id == spec.id,
                        chats.c.agent_id == self.agent_id,
                    )
                    .values(**values),
                )
            else:
                conn.execute(insert(chats).values(**values))

    async def delete_chats(self, chat_ids: list[str]) -> bool:
        if not chat_ids:
            return False
        with self.engine.begin() as conn:
            scoped_chat_ids = [
                row.id
                for row in conn.execute(
                    select(chats.c.id).where(
                        chats.c.id.in_(chat_ids),
                        chats.c.agent_id == self.agent_id,
                    ),
                )
            ]
            if not scoped_chat_ids:
                return False
            conn.execute(
                delete(messages).where(messages.c.chat_id.in_(scoped_chat_ids)),
            )
            conn.execute(
                delete(session_states).where(
                    session_states.c.chat_id.in_(scoped_chat_ids),
                ),
            )
            result = conn.execute(
                delete(chats).where(
                    chats.c.id.in_(scoped_chat_ids),
                    chats.c.agent_id == self.agent_id,
                ),
            )
        return bool(result.rowcount and result.rowcount > 0)

    async def filter_chats(
        self,
        user_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> list[ChatSpec]:
        stmt = select(chats).where(chats.c.agent_id == self.agent_id)
        if user_id is not None:
            stmt = stmt.where(chats.c.user_id == str(user_id))
        if channel is not None:
            stmt = stmt.where(chats.c.channel == channel)
        stmt = stmt.order_by(chats.c.updated_at.desc())

        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [self._row_to_spec(row) for row in rows]

    async def count_messages(self, chat_id: str) -> int:
        stmt = select(func.count()).select_from(messages).where(
            messages.c.chat_id == chat_id,
        )
        with self.engine.connect() as conn:
            return int(conn.execute(stmt).scalar_one())

    async def get_chat_id_by_session(
        self,
        session_id: str,
        channel: str,
        user_id: Optional[str] = None,
    ) -> str | None:
        stmt = select(chats.c.id).where(
            chats.c.session_id == session_id,
            chats.c.channel == channel,
            chats.c.agent_id == self.agent_id,
        )
        if user_id is not None:
            stmt = stmt.where(chats.c.user_id == str(user_id))
        stmt = stmt.order_by(chats.c.updated_at.desc()).limit(1)

        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
        return str(row[0]) if row else None

    def _row_to_spec(self, row) -> ChatSpec:
        meta = {}
        raw_meta = row.get("meta") if row else None
        if raw_meta:
            try:
                meta = json.loads(raw_meta)
            except json.JSONDecodeError:
                logger.debug("Invalid chat meta JSON for chat %s", row.get("id"))

        if "agent_id" not in meta:
            meta["agent_id"] = row["agent_id"]

        return ChatSpec(
            id=row["id"],
            user_id=str(row["user_id"]),
            session_id=row["session_id"],
            channel=row["channel"] or DEFAULT_CHANNEL,
            name=row["name"] or "New Chat",
            status=row["status"] or "idle",
            task_status=row["task_status"] or "pending",
            pinned=bool(row["pinned"]),
            meta=meta,
            created_at=_coerce_datetime(row["created_at"]),
            updated_at=_coerce_datetime(row["updated_at"]),
        )


def _coerce_datetime(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if value is None:
        return datetime.now(timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
