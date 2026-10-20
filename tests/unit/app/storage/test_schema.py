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


def test_schema_upgrades_legacy_users_and_creates_credit_alert_tables(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "legacy-users.db")})
    engine = create_engine_from_settings(settings)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username VARCHAR NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role VARCHAR,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            INSERT INTO users (id, username, password_hash, password_salt, role)
            VALUES (7, 'legacy', 'hash', 'salt', 'user')
        """))

    create_all(engine)
    create_all(engine)

    inspector = inspect(engine)
    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert user_columns["display_name"]["nullable"] is True
    assert user_columns["phone_number_e164"]["nullable"] is True
    assert user_columns["ai_customer_service_url"]["nullable"] is True
    assert {
        "credit_alert_preferences",
        "credit_alert_states",
        "credit_alert_events",
    }.issubset(set(inspector.get_table_names()))
    unique_columns = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("credit_alert_events")
    }
    assert ("user_id", "tier", "cycle_number") in unique_columns
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT username, display_name, phone_number_e164, "
            "ai_customer_service_url FROM users WHERE id = 7"
        )).mappings().one()
    assert dict(row) == {
        "username": "legacy",
        "display_name": None,
        "phone_number_e164": None,
        "ai_customer_service_url": None,
    }
