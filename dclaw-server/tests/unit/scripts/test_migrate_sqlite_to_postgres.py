# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select

from qwenpaw.app.storage.schema import chats, create_all, messages, session_states, users
from scripts.db.migrate_sqlite_to_postgres import (
    MigrationError,
    migrate_sqlite_to_target,
)


def _source_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE chats (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            agent_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            channel TEXT DEFAULT 'default',
            name TEXT DEFAULT 'New Chat',
            status TEXT DEFAULT 'idle',
            task_status TEXT DEFAULT 'pending',
            pinned BOOLEAN DEFAULT 0,
            meta TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT,
            meta TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(
        """
        INSERT INTO users (id, username, password_hash, password_salt, role)
        VALUES (1, 'alice', 'hash', 'salt', 'user')
        """,
    )
    conn.execute(
        """
        INSERT INTO chats (
            id, user_id, agent_id, session_id, channel, name,
            status, task_status, pinned, meta
        ) VALUES (
            'chat-1', 1, 'agent-a', 'session-1', 'console', 'Chat 1',
            'idle', 'pending', 0, '{}'
        )
        """,
    )
    conn.execute(
        """
        INSERT INTO messages (id, chat_id, role, name, content, meta)
        VALUES ('msg-1', 'chat-1', 'user', 'user', 'hello', '{}')
        """,
    )
    conn.commit()
    conn.close()


def _target_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _target_counts(path: Path) -> dict[str, int]:
    engine = create_engine(_target_url(path), future=True)
    with engine.connect() as conn:
        return {
            "users": int(conn.execute(select(func.count()).select_from(users)).scalar_one()),
            "chats": int(conn.execute(select(func.count()).select_from(chats)).scalar_one()),
            "messages": int(conn.execute(select(func.count()).select_from(messages)).scalar_one()),
        }


def test_dry_run_reports_counts_without_writing(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _source_db(source)

    result = migrate_sqlite_to_target(
        sqlite_path=source,
        target_url=_target_url(target),
        dry_run=True,
        execute=False,
    )

    assert result["mode"] == "dry-run"
    assert result["source_counts"]["users"] == 1
    assert result["source_counts"]["chats"] == 1
    assert result["source_counts"]["messages"] == 1
    assert result["target_reachable"] is True
    assert "inserted_counts" not in result


def test_execute_copies_rows_to_empty_target(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _source_db(source)

    result = migrate_sqlite_to_target(
        sqlite_path=source,
        target_url=_target_url(target),
        dry_run=False,
        execute=True,
    )

    assert result["mode"] == "execute"
    assert result["inserted_counts"]["users"] == 1
    assert result["inserted_counts"]["chats"] == 1
    assert result["inserted_counts"]["messages"] == 1
    assert _target_counts(target) == {"users": 1, "chats": 1, "messages": 1}


def test_execute_refuses_non_empty_target_without_override(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _source_db(source)

    engine = create_engine(_target_url(target), future=True)
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            users.insert().values(
                id=99,
                username="existing",
                password_hash="hash",
                password_salt="salt",
                role="user",
            ),
        )

    with pytest.raises(MigrationError, match="target is not empty"):
        migrate_sqlite_to_target(
            sqlite_path=source,
            target_url=_target_url(target),
            dry_run=False,
            execute=True,
        )


def test_execute_allows_non_empty_target_with_override(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _source_db(source)

    engine = create_engine(_target_url(target), future=True)
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            users.insert().values(
                id=99,
                username="existing",
                password_hash="hash",
                password_salt="salt",
                role="user",
            ),
        )

    result = migrate_sqlite_to_target(
        sqlite_path=source,
        target_url=_target_url(target),
        dry_run=False,
        execute=True,
        allow_non_empty_target=True,
    )

    assert result["inserted_counts"]["users"] == 1
    assert _target_counts(target)["users"] == 2


def test_execute_skips_session_states_without_parent_chat(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _source_db(source)

    conn = sqlite3.connect(source)
    conn.executescript(
        """
        CREATE TABLE session_states (
            chat_id TEXT PRIMARY KEY,
            state_json TEXT
        );
        INSERT INTO session_states (chat_id, state_json)
        VALUES ('chat-1', '{"ok": true}');
        INSERT INTO session_states (chat_id, state_json)
        VALUES ('missing-chat', '{"orphan": true}');
        """
    )
    conn.commit()
    conn.close()

    result = migrate_sqlite_to_target(
        sqlite_path=source,
        target_url=_target_url(target),
        dry_run=False,
        execute=True,
    )

    engine = create_engine(_target_url(target), future=True)
    with engine.connect() as conn:
        migrated_states = conn.execute(
            select(session_states.c.chat_id).order_by(session_states.c.chat_id),
        ).scalars().all()

    assert result["inserted_counts"]["session_states"] == 1
    assert result["skipped_counts"]["session_states"] == 1
    assert migrated_states == ["chat-1"]
