# -*- coding: utf-8 -*-
"""SQLAlchemy-backed session state storage."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

from agentscope.session import SessionBase
from agentscope_runtime.engine.schemas.exception import ConfigurationException
from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from ...exceptions import AgentStateError
from ..channels.schema import DEFAULT_CHANNEL
from ..storage.schema import chats, messages, session_states

logger = logging.getLogger(__name__)


class SqlAlchemySession(SessionBase):
    """SessionBase implementation backed by SQLAlchemy Core."""

    def __init__(self, agent_id: str, engine: Engine) -> None:
        self.agent_id = agent_id
        self.engine = engine

    def _get_chat_id(self, session_id: str, user_id: str, channel: str) -> str:
        normalized_channel = channel or DEFAULT_CHANNEL
        normalized_user_id = str(user_id or "0")
        with self.engine.begin() as conn:
            row = conn.execute(
                select(chats.c.id).where(
                    chats.c.session_id == session_id,
                    chats.c.user_id == normalized_user_id,
                    chats.c.channel == normalized_channel,
                    chats.c.agent_id == self.agent_id,
                ),
            ).first()
            if row:
                return str(row[0])

            chat_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            conn.execute(
                insert(chats).values(
                    id=chat_id,
                    user_id=normalized_user_id,
                    agent_id=self.agent_id,
                    session_id=session_id,
                    channel=normalized_channel,
                    name="New Chat",
                    status="idle",
                    task_status="pending",
                    pinned=False,
                    meta="{}",
                    created_at=now,
                    updated_at=now,
                ),
            )
            return chat_id

    async def save_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        **state_modules_mapping,
    ) -> None:
        chat_id = self._get_chat_id(session_id, user_id, channel)
        memory_module = state_modules_mapping.get("memory")
        other_states = {
            name: module.state_dict()
            for name, module in state_modules_mapping.items()
            if name != "memory"
        }

        with self.engine.begin() as conn:
            if memory_module:
                memory_state = memory_module.state_dict()
                if isinstance(memory_state, list):
                    self._upsert_messages(conn, chat_id, memory_state)

            if other_states:
                self._upsert_session_states(conn, chat_id, other_states)

        logger.info("Saved session state to SQLAlchemy storage for session %s", session_id)

    async def load_session_state(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
        **state_modules_mapping,
    ) -> None:
        _ = allow_not_exist
        chat_id = self._get_chat_id(session_id, user_id, channel)

        with self.engine.connect() as conn:
            memory_rows = conn.execute(
                select(messages)
                .where(messages.c.chat_id == chat_id)
                .order_by(messages.c.timestamp.asc()),
            ).mappings().all()
            state_row = conn.execute(
                select(session_states.c.state_json).where(
                    session_states.c.chat_id == chat_id,
                ),
            ).first()

        memory_module = state_modules_mapping.get("memory")
        if memory_module and memory_rows:
            memory_module.load_state_dict([_message_row_to_dict(row) for row in memory_rows])

        if state_row and state_row[0]:
            try:
                other_states = json.loads(state_row[0])
            except json.JSONDecodeError:
                other_states = {}
            for name, module in state_modules_mapping.items():
                if name != "memory" and name in other_states:
                    module.load_state_dict(other_states[name])

        logger.info("Loaded session state from SQLAlchemy storage for session %s", session_id)

    async def update_session_state(
        self,
        session_id: str,
        key: Union[str, Sequence[str]],
        value,
        user_id: str = "",
        channel: str = "",
        create_if_not_exist: bool = True,
    ) -> None:
        chat_id = self._get_chat_id(session_id, user_id, channel)
        path = key.split(".") if isinstance(key, str) else list(key)
        if not path:
            raise ConfigurationException(
                config_key="session.key",
                message="key path is empty",
            )

        with self.engine.begin() as conn:
            row = conn.execute(
                select(session_states.c.state_json).where(
                    session_states.c.chat_id == chat_id,
                ),
            ).first()
            if row and row[0]:
                try:
                    states = json.loads(row[0])
                except json.JSONDecodeError:
                    states = {}
            else:
                if not create_if_not_exist:
                    raise AgentStateError(
                        session_id=session_id,
                        message=f"Session state for {session_id} does not exist",
                    )
                states = {}

            cur = states
            for item in path[:-1]:
                if item not in cur or not isinstance(cur[item], dict):
                    cur[item] = {}
                cur = cur[item]
            cur[path[-1]] = value
            self._upsert_session_states(conn, chat_id, states)

    async def get_session_state_dict(
        self,
        session_id: str,
        user_id: str = "",
        channel: str = "",
        allow_not_exist: bool = True,
    ) -> dict:
        chat_id = self._get_chat_id(session_id, user_id, channel)

        with self.engine.connect() as conn:
            memory_rows = conn.execute(
                select(messages)
                .where(messages.c.chat_id == chat_id)
                .order_by(messages.c.timestamp.asc()),
            ).mappings().all()
            state_row = conn.execute(
                select(session_states.c.state_json).where(
                    session_states.c.chat_id == chat_id,
                ),
            ).first()

        result: dict = {}
        if memory_rows:
            result["memory"] = [_message_row_to_dict(row) for row in memory_rows]
        if state_row and state_row[0]:
            try:
                result.update(json.loads(state_row[0]))
            except json.JSONDecodeError:
                pass

        if not result and not allow_not_exist:
            raise AgentStateError(
                session_id=session_id,
                message=f"Failed to get session state for {session_id} because it does not exist",
            )
        return result

    def _upsert_messages(self, conn, chat_id: str, memory_state: list[dict]) -> None:
        message_ids: list[str] = []
        normalized_messages = []
        base_ts = datetime.now(timezone.utc)

        for index, msg in enumerate(memory_state):
            msg_id = str(msg.get("id") or uuid.uuid4())
            message_ids.append(msg_id)
            role = str(msg.get("role", "unknown"))
            name = str(msg.get("name", role))
            content = msg.get("content", "")
            content_str = _content_to_string(content)
            meta = {
                k: v
                for k, v in msg.items()
                if k not in ("id", "role", "name", "content")
            }
            normalized_messages.append(
                {
                    "id": msg_id,
                    "chat_id": chat_id,
                    "role": role,
                    "name": name,
                    "content": content_str,
                    "meta": json.dumps(meta, ensure_ascii=False),
                    "timestamp": base_ts + timedelta(microseconds=index),
                },
            )

        if message_ids:
            conn.execute(
                delete(messages).where(
                    messages.c.chat_id == chat_id,
                    messages.c.id.not_in(message_ids),
                ),
            )
        else:
            conn.execute(delete(messages).where(messages.c.chat_id == chat_id))

        if normalized_messages:
            dialect = conn.dialect.name
            if dialect == "sqlite":
                self._bulk_upsert_messages(conn, sqlite_insert, normalized_messages)
            elif dialect == "postgresql":
                self._bulk_upsert_messages(conn, postgres_insert, normalized_messages)
            else:
                self._fallback_upsert_messages(conn, normalized_messages)

    @staticmethod
    def _bulk_upsert_messages(conn, insert_factory, rows: list[dict]) -> None:
        stmt = insert_factory(messages).values(rows)
        update_values = {
            column: getattr(stmt.excluded, column)
            for column in ("chat_id", "role", "name", "content", "meta", "timestamp")
        }
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=[messages.c.id],
                set_=update_values,
            ),
        )

    @staticmethod
    def _fallback_upsert_messages(conn, rows: list[dict]) -> None:
        for row in rows:
            existing = conn.execute(
                select(messages.c.id).where(messages.c.id == row["id"]),
            ).first()
            if existing:
                conn.execute(
                    update(messages).where(messages.c.id == row["id"]).values(**row),
                )
            else:
                conn.execute(insert(messages).values(**row))

    @staticmethod
    def _upsert_session_states(conn, chat_id: str, states: dict) -> None:
        state_json = json.dumps(states, ensure_ascii=False)
        existing = conn.execute(
            select(session_states.c.chat_id).where(session_states.c.chat_id == chat_id),
        ).first()
        if existing:
            conn.execute(
                update(session_states)
                .where(session_states.c.chat_id == chat_id)
                .values(state_json=state_json),
            )
        else:
            conn.execute(
                insert(session_states).values(
                    chat_id=chat_id,
                    state_json=state_json,
                ),
            )


def _content_to_string(content) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)


def _message_row_to_dict(row) -> dict:
    msg = {
        "id": row["id"],
        "role": row["role"],
        "name": row["name"],
        "content": row["content"],
    }
    raw_meta = row.get("meta")
    if raw_meta:
        try:
            msg.update(json.loads(raw_meta))
        except json.JSONDecodeError:
            pass
    return msg
