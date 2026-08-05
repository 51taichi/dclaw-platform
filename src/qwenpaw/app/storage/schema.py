# -*- coding: utf-8 -*-
"""SQLAlchemy Core schema for QwenPaw durable app data."""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    false,
    func,
    inspect,
    text,
    true,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String, nullable=False, unique=True),
    Column("password_hash", Text, nullable=False),
    Column("password_salt", Text, nullable=False),
    Column("role", String, server_default="user"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

user_connections = Table(
    "user_connections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("connector_key", String, nullable=False),
    Column("oauth_tokens", Text),
    Column("custom_envs", Text),
    Column("is_active", Boolean, server_default=true()),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)
Index("uq_user_connections_user_connector", user_connections.c.user_id, user_connections.c.connector_key, unique=True)

capability_registry = Table(
    "capability_registry",
    metadata,
    Column("id", String, primary_key=True),
    Column("type", String, nullable=False),
    Column("name", String, nullable=False),
    Column("description", Text),
    Column("manifest", Text, nullable=False),
    Column("is_public", Boolean, server_default=true()),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

user_capabilities = Table(
    "user_capabilities",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("capability_id", String, ForeignKey("capability_registry.id"), nullable=False),
    Column("enabled", Boolean, server_default=true()),
    Column("credentials", Text),
    Column("preferences", Text),
    Column("subscribed_at", DateTime(timezone=True), server_default=func.now()),
)
Index("uq_user_capabilities_user_capability", user_capabilities.c.user_id, user_capabilities.c.capability_id, unique=True)

chats = Table(
    "chats",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, nullable=False),
    Column("agent_id", String, nullable=False),
    Column("session_id", String, nullable=False),
    Column("channel", String, server_default="default"),
    Column("name", Text, server_default="New Chat"),
    Column("status", String, server_default="idle"),
    Column("task_status", String, server_default="pending"),
    Column("pinned", Boolean, server_default=false()),
    Column("meta", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

messages = Table(
    "messages",
    metadata,
    Column("id", String, primary_key=True),
    Column("chat_id", String, ForeignKey("chats.id"), nullable=False),
    Column("role", String, nullable=False),
    Column("name", String, nullable=False),
    Column("content", Text),
    Column("meta", Text),
    Column("timestamp", DateTime(timezone=True), server_default=func.now()),
)

session_states = Table(
    "session_states",
    metadata,
    Column("chat_id", String, ForeignKey("chats.id"), primary_key=True),
    Column("state_json", Text),
)

token_usage_logs = Table(
    "token_usage_logs",
    metadata,
    Column("id", String, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("model_name", String, nullable=False),
    Column("prompt_tokens", Integer, server_default="0"),
    Column("completion_tokens", Integer, server_default="0"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

expert_team_templates = Table(
    "expert_team_templates",
    metadata,
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("description", Text, server_default=""),
    Column("category", String, server_default="all"),
    Column("tags", Text, nullable=False, server_default="[]"),
    Column("icon", String, server_default=""),
    Column("enabled", Boolean, server_default=true()),
    Column("leader_agent_id", String, nullable=False, server_default="default"),
    Column("members", Text, nullable=False, server_default="[]"),
    Column("workflow", Text, nullable=False, server_default="[]"),
    Column("usage_count", Integer, server_default="0"),
    Column("source", String, server_default="custom"),
    Column("sort_order", Integer, server_default="0"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

expert_team_runs = Table(
    "expert_team_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("team_id", String, ForeignKey("expert_team_templates.id"), nullable=False),
    Column("root_chat_id", String, nullable=False),
    Column("root_session_id", String, nullable=False),
    Column("user_id", String, nullable=False),
    Column("state", String, server_default="pending"),
    Column("input_text", Text, server_default=""),
    Column("final_summary", Text),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("finished_at", DateTime(timezone=True)),
)

expert_team_member_runs = Table(
    "expert_team_member_runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("run_id", String, ForeignKey("expert_team_runs.id"), nullable=False),
    Column("member_key", String, nullable=False),
    Column("agent_id", String, nullable=False),
    Column("display_name", String, nullable=False),
    Column("role", Text, server_default=""),
    Column("avatar", Text, server_default=""),
    Column("state", String, server_default="pending"),
    Column("stage_index", Integer, server_default="0"),
    Column("task_id", String),
    Column("child_session_id", String),
    Column("input_text", Text, server_default=""),
    Column("output_text", Text),
    Column("error", Text),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_publications = Table(
    "open_api_publications",
    metadata,
    Column("id", String, primary_key=True),
    Column("public_id", String, nullable=False, unique=True),
    Column("target_type", String, nullable=False),
    Column("target_id", String, nullable=False),
    Column("owner_user_id", String, nullable=False),
    Column("bound_user_id", String, nullable=False),
    Column("knowledge_base_id", String, nullable=False, unique=True),
    Column("name", Text, nullable=False),
    Column("description", Text, server_default=""),
    Column("status", String, server_default="enabled"),
    Column("allowed_scopes", Text, nullable=False, server_default="[]"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_external_apps = Table(
    "open_api_external_apps",
    metadata,
    Column("id", String, primary_key=True),
    Column("owner_user_id", String, nullable=False),
    Column("name", Text, nullable=False),
    Column("status", String, server_default="enabled"),
    Column("ip_allowlist", Text, nullable=False, server_default="[]"),
    Column("quota_policy", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_keys = Table(
    "open_api_keys",
    metadata,
    Column("id", String, primary_key=True),
    Column("app_id", String, ForeignKey("open_api_external_apps.id"), nullable=False),
    Column("publication_id", String, ForeignKey("open_api_publications.id"), nullable=False),
    Column("key_hash", String, nullable=False, unique=True),
    Column("key_prefix", String, nullable=False),
    Column("key_suffix", String, nullable=False),
    Column("scopes", Text, nullable=False, server_default="[]"),
    Column("status", String, server_default="active"),
    Column("expires_at", DateTime(timezone=True)),
    Column("last_used_at", DateTime(timezone=True)),
    Column("last_used_ip", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_invocations = Table(
    "open_api_invocations",
    metadata,
    Column("id", String, primary_key=True),
    Column("app_id", String, ForeignKey("open_api_external_apps.id"), nullable=False),
    Column("publication_id", String, ForeignKey("open_api_publications.id"), nullable=False),
    Column("api_key_id", String, ForeignKey("open_api_keys.id"), nullable=False),
    Column("target_type", String, nullable=False),
    Column("target_id", String, nullable=False),
    Column("chat_id", String),
    Column("external_session_id", String),
    Column("external_user_id", String),
    Column("status", String, nullable=False),
    Column("status_code", Integer),
    Column("latency_ms", Integer, server_default="0"),
    Column("token_summary", Text, nullable=False, server_default="{}"),
    Column("error_summary", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_group_histories = Table(
    "open_api_group_histories",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "publication_id",
        String,
        ForeignKey("open_api_publications.id"),
        nullable=False,
    ),
    Column("external_group_id", String, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

open_api_group_history_messages = Table(
    "open_api_group_history_messages",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "history_id",
        String,
        ForeignKey("open_api_group_histories.id"),
        nullable=False,
    ),
    Column("external_message_id", String, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("sender_id", String, nullable=False, server_default=""),
    Column("sender_name", Text, nullable=False),
    Column("participant_role_id", String, nullable=False, server_default=""),
    Column("direction", String, nullable=False),
    Column("source", String, nullable=False),
    Column("message_type", String, nullable=False),
    Column("content", Text, nullable=False, server_default=""),
    Column("metadata", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

knowledge_docs = Table(
    "knowledge_docs",
    metadata,
    Column("id", String, primary_key=True),
    Column("scope", String, nullable=False),
    Column("owner_user_id", String),
    Column("name", Text, nullable=False),
    Column("source_type", String, nullable=False),
    Column("source_url", Text),
    Column("category", String, nullable=False, server_default="uncategorized"),
    Column("tags", Text, nullable=False, server_default="[]"),
    Column("size", String, server_default="0 KB"),
    Column("byte_size", Integer, server_default="0"),
    Column("chunk_count", Integer, server_default="0"),
    Column("status", String, server_default="pending"),
    Column("progress", Integer, server_default="0"),
    Column("failed_stage", String),
    Column("last_error", Text),
    Column("cloud_account_id", String),
    Column("agent_ids", Text, nullable=False, server_default="[]"),
    Column("legacy_agent_id", String),
    Column("generated_wiki", Text, nullable=False, server_default="[]"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

knowledge_assets = Table(
    "knowledge_assets",
    metadata,
    Column("id", String, primary_key=True),
    Column("doc_id", String, ForeignKey("knowledge_docs.id"), nullable=False),
    Column("kind", String, nullable=False, server_default="raw"),
    Column("storage_path", Text, nullable=False),
    Column("mime_type", String),
    Column("sha256", String),
    Column("byte_size", Integer, server_default="0"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

knowledge_chunks = Table(
    "knowledge_chunks",
    metadata,
    Column("id", String, primary_key=True),
    Column("doc_id", String, ForeignKey("knowledge_docs.id"), nullable=False),
    Column("doc_name", Text, nullable=False),
    Column("scope", String, nullable=False),
    Column("owner_user_id", String),
    Column("chunk_index", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("source_url", Text),
    Column("locator", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

knowledge_embeddings = Table(
    "knowledge_embeddings",
    metadata,
    Column("id", String, primary_key=True),
    Column("chunk_id", String, ForeignKey("knowledge_chunks.id"), nullable=False),
    Column("model", String, nullable=False),
    Column("vector", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

knowledge_wiki = Table(
    "knowledge_wiki",
    metadata,
    Column("id", String, primary_key=True),
    Column("doc_id", String, ForeignKey("knowledge_docs.id"), nullable=False),
    Column("scope", String, nullable=False),
    Column("owner_user_id", String),
    Column("concept", String, nullable=False),
    Column("content", Text, nullable=False),
    Column("chunk_ids", Text, nullable=False, server_default="[]"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

Index("idx_chats_user_agent_updated", chats.c.user_id, chats.c.agent_id, chats.c.updated_at.desc())
Index("idx_chats_session_user_channel_agent", chats.c.session_id, chats.c.user_id, chats.c.channel, chats.c.agent_id)
Index("idx_messages_chat_timestamp", messages.c.chat_id, messages.c.timestamp.asc())
Index("idx_session_states_chat_id", session_states.c.chat_id)
Index("idx_expert_team_runs_user_state_updated", expert_team_runs.c.user_id, expert_team_runs.c.state, expert_team_runs.c.updated_at.desc())
Index("idx_expert_team_member_runs_run_state", expert_team_member_runs.c.run_id, expert_team_member_runs.c.state)
Index("idx_open_api_publications_target", open_api_publications.c.target_type, open_api_publications.c.target_id)
Index("idx_open_api_external_apps_owner_status", open_api_external_apps.c.owner_user_id, open_api_external_apps.c.status)
Index("idx_open_api_keys_app_publication", open_api_keys.c.app_id, open_api_keys.c.publication_id)
Index("idx_open_api_invocations_publication_created", open_api_invocations.c.publication_id, open_api_invocations.c.created_at.desc())
Index(
    "uq_open_api_group_histories_publication_group",
    open_api_group_histories.c.publication_id,
    open_api_group_histories.c.external_group_id,
    unique=True,
)
Index(
    "uq_open_api_group_history_messages_external",
    open_api_group_history_messages.c.history_id,
    open_api_group_history_messages.c.external_message_id,
    unique=True,
)
Index(
    "idx_open_api_group_history_messages_time",
    open_api_group_history_messages.c.history_id,
    open_api_group_history_messages.c.occurred_at.asc(),
    open_api_group_history_messages.c.id.asc(),
)
Index("idx_knowledge_docs_scope_owner_updated", knowledge_docs.c.scope, knowledge_docs.c.owner_user_id, knowledge_docs.c.updated_at.desc())
Index("idx_knowledge_docs_status", knowledge_docs.c.status)
Index("idx_knowledge_assets_doc", knowledge_assets.c.doc_id)
Index("idx_knowledge_chunks_doc", knowledge_chunks.c.doc_id)
Index("idx_knowledge_chunks_scope_owner", knowledge_chunks.c.scope, knowledge_chunks.c.owner_user_id)
Index("idx_knowledge_embeddings_chunk", knowledge_embeddings.c.chunk_id)
Index("idx_knowledge_wiki_scope_owner_concept", knowledge_wiki.c.scope, knowledge_wiki.c.owner_user_id, knowledge_wiki.c.concept)
Index("idx_knowledge_wiki_doc", knowledge_wiki.c.doc_id)


def create_all(engine: Engine) -> None:
    """Create all known durable tables and indexes."""
    metadata.create_all(engine)
    _ensure_open_api_publication_binding_columns(engine)
    _ensure_knowledge_metadata_columns(engine)


def _ensure_open_api_publication_binding_columns(engine: Engine) -> None:
    """Backfill runtime-user and dedicated knowledge-base publication bindings."""
    inspector = inspect(engine)
    if "open_api_publications" not in inspector.get_table_names():
        return
    existing = {
        column["name"]
        for column in inspector.get_columns("open_api_publications")
    }
    with engine.begin() as conn:
        if "bound_user_id" not in existing:
            conn.execute(
                text(
                    "ALTER TABLE open_api_publications "
                    "ADD COLUMN bound_user_id VARCHAR"
                ),
            )
        if "knowledge_base_id" not in existing:
            conn.execute(
                text(
                    "ALTER TABLE open_api_publications "
                    "ADD COLUMN knowledge_base_id VARCHAR"
                ),
            )
        conn.execute(
            text(
                "UPDATE open_api_publications "
                "SET bound_user_id = owner_user_id "
                "WHERE bound_user_id IS NULL OR bound_user_id = ''"
            ),
        )
        conn.execute(
            text(
                "UPDATE open_api_publications "
                "SET knowledge_base_id = 'openapi-' || id "
                "WHERE knowledge_base_id IS NULL OR knowledge_base_id = ''"
            ),
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_open_api_publications_knowledge_base "
                "ON open_api_publications (knowledge_base_id)"
            ),
        )


def _ensure_knowledge_metadata_columns(engine: Engine) -> None:
    """Add knowledge metadata columns for databases created before this schema."""
    inspector = inspect(engine)
    if "knowledge_docs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("knowledge_docs")}
    additions = {
        "category": (
            "ALTER TABLE knowledge_docs ADD COLUMN category "
            "VARCHAR NOT NULL DEFAULT 'uncategorized'"
        ),
        "tags": (
            "ALTER TABLE knowledge_docs ADD COLUMN tags "
            "TEXT NOT NULL DEFAULT '[]'"
        ),
    }
    for name, ddl in additions.items():
        if name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(text(ddl))


def table_names() -> set[str]:
    """Return the known table names in this schema module."""
    return set(metadata.tables.keys())
