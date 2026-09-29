# -*- coding: utf-8 -*-
"""User, auth, and chat-access repositories."""
from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import delete, desc, func, insert, select, update
from sqlalchemy.engine import Engine

from ... import db
from ..engine import get_app_engine
from ..schema import (
    chats,
    credit_alert_events,
    credit_alert_preferences,
    credit_alert_states,
    messages,
    session_states,
    token_usage_logs,
    user_capabilities,
    user_connections,
    users,
)
from ..settings import get_storage_settings


class UserRepository(Protocol):
    def count_users(self) -> int:
        ...

    def count_admins(self) -> int:
        ...

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        ...

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        ...

    def get_user_credentials(self, username: str) -> dict[str, str] | None:
        ...

    def ensure_user(
        self,
        *,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
    ) -> dict[str, Any] | None:
        ...

    def update_user_credentials(
        self,
        *,
        old_username: str,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
    ) -> dict[str, Any] | None:
        ...

    def list_users(self) -> list[dict[str, Any]]:
        ...

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
        display_name: str | None = None,
        phone_number_e164: str | None = None,
    ) -> dict[str, Any]:
        ...

    def update_user_password(
        self,
        user_id: int,
        password_hash: str,
        password_salt: str,
    ) -> bool:
        ...

    def update_user_phone(
        self,
        user_id: int,
        phone_number_e164: str,
    ) -> dict[str, Any] | None:
        ...

    def delete_user_cascade(self, user_id: int) -> bool:
        ...

    def find_chat_access_rows(self, chat_id_or_session_id: str) -> list[dict[str, Any]]:
        ...


class SqlAlchemyUserRepository:
    """SQLAlchemy implementation for Postgres and SQLAlchemy-backed tests."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def count_users(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(users)).scalar() or 0)

    def count_admins(self) -> int:
        with self.engine.connect() as conn:
            return int(
                conn.execute(
                    select(func.count()).select_from(users).where(users.c.role == "admin"),
                ).scalar()
                or 0,
            )

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users.c.id, users.c.username, users.c.role, users.c.display_name, users.c.phone_number_e164, users.c.created_at).where(
                    users.c.id == user_id,
                ),
            ).mappings().first()
            return _dict_or_none(row)

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users.c.id, users.c.username, users.c.role, users.c.display_name, users.c.phone_number_e164).where(
                    users.c.username == username,
                ),
            ).mappings().first()
            return _dict_or_none(row)

    def get_user_credentials(self, username: str) -> dict[str, str] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(users.c.password_hash, users.c.password_salt).where(
                    users.c.username == username,
                ),
            ).mappings().first()
            return _dict_or_none(row)

    def ensure_user(
        self,
        *,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
    ) -> dict[str, Any] | None:
        existing = self.get_user_by_username(username)
        if existing:
            return existing
        return self.create_user(
            username=username,
            password_hash=password_hash,
            password_salt=password_salt,
            role=role,
        )

    def update_user_credentials(
        self,
        *,
        old_username: str,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
    ) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            result = conn.execute(
                update(users)
                .where(users.c.username == old_username)
                .values(
                    username=username,
                    password_hash=password_hash,
                    password_salt=password_salt,
                    role=role,
                ),
            )
        if result.rowcount == 0:
            return self.ensure_user(
                username=username,
                password_hash=password_hash,
                password_salt=password_salt,
                role=role,
            )
        return self.get_user_by_username(username)

    def list_users(self) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(users.c.id, users.c.username, users.c.role, users.c.display_name, users.c.phone_number_e164, users.c.created_at).order_by(
                    desc(users.c.created_at),
                ),
            ).mappings().all()
            return [dict(row) for row in rows]

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
        display_name: str | None = None,
        phone_number_e164: str | None = None,
    ) -> dict[str, Any]:
        with self.engine.begin() as conn:
            result = conn.execute(
                insert(users).values(
                    username=username,
                    password_hash=password_hash,
                    password_salt=password_salt,
                    role=role,
                    display_name=display_name,
                    phone_number_e164=phone_number_e164,
                ),
            )
            user_id = int(result.inserted_primary_key[0])
        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("created user row could not be loaded")
        return user

    def update_user_password(
        self,
        user_id: int,
        password_hash: str,
        password_salt: str,
    ) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(password_hash=password_hash, password_salt=password_salt),
            )
            return bool(result.rowcount)

    def update_user_phone(
        self,
        user_id: int,
        phone_number_e164: str,
    ) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            result = conn.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(phone_number_e164=phone_number_e164),
            )
        if not result.rowcount:
            return None
        return self.get_user_by_id(user_id)

    def delete_user_cascade(self, user_id: int) -> bool:
        if self.get_user_by_id(user_id) is None:
            return False
        user_id_str = str(user_id)
        with self.engine.begin() as conn:
            chat_ids = [
                str(row[0])
                for row in conn.execute(
                    select(chats.c.id).where(chats.c.user_id == user_id_str),
                ).all()
            ]
            if chat_ids:
                conn.execute(
                    delete(session_states).where(
                        session_states.c.chat_id.in_(chat_ids),
                    ),
                )
                conn.execute(delete(messages).where(messages.c.chat_id.in_(chat_ids)))
            conn.execute(delete(user_capabilities).where(user_capabilities.c.user_id == user_id))
            conn.execute(delete(user_connections).where(user_connections.c.user_id == user_id))
            conn.execute(delete(chats).where(chats.c.user_id == user_id_str))
            conn.execute(delete(token_usage_logs).where(token_usage_logs.c.user_id == user_id))
            conn.execute(delete(credit_alert_events).where(credit_alert_events.c.user_id == user_id))
            conn.execute(delete(credit_alert_states).where(credit_alert_states.c.user_id == user_id))
            conn.execute(delete(credit_alert_preferences).where(credit_alert_preferences.c.user_id == user_id))
            conn.execute(delete(users).where(users.c.id == user_id))
        return True

    def find_chat_access_rows(self, chat_id_or_session_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(
                    chats.c.id,
                    chats.c.user_id,
                    chats.c.agent_id,
                    chats.c.session_id,
                    chats.c.channel,
                    chats.c.meta,
                ).where(
                    (chats.c.id == chat_id_or_session_id)
                    | (chats.c.session_id == chat_id_or_session_id),
                ),
            ).mappings().all()
            return [_normalize_chat_row(dict(row)) for row in rows]


class SqliteUserRepository:
    """SQLite compatibility implementation using the existing sqlite3 module."""

    def count_users(self) -> int:
        return int(db.get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0])

    def count_admins(self) -> int:
        row = db.get_db().execute("SELECT COUNT(*) as count FROM users WHERE role = 'admin'").fetchone()
        return int(row["count"])

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return _sqlite_user_dict(row)

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        row = db.get_db().execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return _sqlite_user_dict(row)

    def get_user_credentials(self, username: str) -> dict[str, str] | None:
        row = db.get_db().execute(
            "SELECT password_hash, password_salt FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return _dict_or_none(row)

    def ensure_user(
        self,
        *,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
    ) -> dict[str, Any] | None:
        existing = self.get_user_by_username(username)
        if existing:
            return existing
        return self.create_user(
            username=username,
            password_hash=password_hash,
            password_salt=password_salt,
            role=role,
        )

    def update_user_credentials(
        self,
        *,
        old_username: str,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
    ) -> dict[str, Any] | None:
        conn = db.get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE users
            SET username = ?, password_hash = ?, password_salt = ?, role = ?
            WHERE username = ?
            """,
            (username, password_hash, password_salt, role, old_username),
        )
        if cursor.rowcount == 0:
            conn.commit()
            return self.ensure_user(
                username=username,
                password_hash=password_hash,
                password_salt=password_salt,
                role=role,
            )
        conn.commit()
        return self.get_user_by_username(username)

    def list_users(self) -> list[dict[str, Any]]:
        rows = db.get_db().execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [_sqlite_user_dict(row) for row in rows]

    def create_user(
        self,
        *,
        username: str,
        password_hash: str,
        password_salt: str,
        role: str,
        display_name: str | None = None,
        phone_number_e164: str | None = None,
    ) -> dict[str, Any]:
        conn = db.get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, password_salt, role, display_name, phone_number_e164)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, password_hash, password_salt, role, display_name, phone_number_e164),
        )
        conn.commit()
        user = self.get_user_by_id(int(cursor.lastrowid))
        if user is None:
            raise RuntimeError("created user row could not be loaded")
        return user

    def update_user_password(
        self,
        user_id: int,
        password_hash: str,
        password_salt: str,
    ) -> bool:
        conn = db.get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
            (password_hash, password_salt, user_id),
        )
        conn.commit()
        return cursor.rowcount > 0

    def update_user_phone(
        self,
        user_id: int,
        phone_number_e164: str,
    ) -> dict[str, Any] | None:
        conn = db.get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET phone_number_e164 = ? WHERE id = ?",
            (phone_number_e164, user_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        return self.get_user_by_id(user_id)

    def delete_user_cascade(self, user_id: int) -> bool:
        if self.get_user_by_id(user_id) is None:
            return False
        conn = db.get_db()
        cursor = conn.cursor()
        for table in ("credit_alert_events", "credit_alert_states", "credit_alert_preferences"):
            exists = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,),
            ).fetchone()
            if exists:
                cursor.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM user_capabilities WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM user_connections WHERE user_id = ?", (user_id,))
        cursor.execute("SELECT id FROM chats WHERE user_id = ?", (str(user_id),))
        chat_rows = cursor.fetchall()
        has_session_states = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'session_states'",
        ).fetchone()
        for row in chat_rows:
            if has_session_states:
                cursor.execute("DELETE FROM session_states WHERE chat_id = ?", (row["id"],))
            cursor.execute("DELETE FROM messages WHERE chat_id = ?", (row["id"],))
        cursor.execute("DELETE FROM chats WHERE user_id = ?", (str(user_id),))
        cursor.execute("DELETE FROM token_usage_logs WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return True

    def find_chat_access_rows(self, chat_id_or_session_id: str) -> list[dict[str, Any]]:
        rows = db.get_db().execute(
            """
            SELECT id, user_id, agent_id, session_id, channel, meta
            FROM chats
            WHERE id = ? OR session_id = ?
            """,
            (chat_id_or_session_id, chat_id_or_session_id),
        ).fetchall()
        return [_normalize_chat_row(dict(row)) for row in rows]


def get_user_repository() -> UserRepository:
    settings = get_storage_settings()
    if settings.database_backend == "postgres":
        return SqlAlchemyUserRepository(get_app_engine())
    return SqliteUserRepository()


def _dict_or_none(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _sqlite_user_dict(row: Any) -> dict[str, Any] | None:
    value = _dict_or_none(row)
    if value is not None:
        value.setdefault("display_name", None)
        value.setdefault("phone_number_e164", None)
    return value


def _normalize_chat_row(row: dict[str, Any]) -> dict[str, Any]:
    row["user_id"] = str(row.get("user_id"))
    return row
