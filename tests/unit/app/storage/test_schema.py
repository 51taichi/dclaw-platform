# -*- coding: utf-8 -*-
from __future__ import annotations

from sqlalchemy import inspect, text

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all, table_names
from qwenpaw.app.storage.settings import get_storage_settings


def test_schema_creates_expected_tables_and_indexes(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)

    create_all(engine)
    create_all(engine)

    inspector = inspect(engine)
    assert table_names().issubset(set(inspector.get_table_names()))

    chat_indexes = {idx["name"] for idx in inspector.get_indexes("chats")}
    assert "idx_chats_user_agent_updated" in chat_indexes
    assert "idx_chats_session_user_channel_agent" in chat_indexes

    message_indexes = {idx["name"] for idx in inspector.get_indexes("messages")}
    assert "idx_messages_chat_timestamp" in message_indexes

    session_state_indexes = {idx["name"] for idx in inspector.get_indexes("session_states")}
    assert "idx_session_states_chat_id" in session_state_indexes


def test_schema_adds_knowledge_metadata_columns_to_existing_database(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "legacy.db")})
    engine = create_engine_from_settings(settings)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE knowledge_docs (id VARCHAR PRIMARY KEY)"))

    create_all(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("knowledge_docs")}
    assert {"category", "tags"}.issubset(columns)
