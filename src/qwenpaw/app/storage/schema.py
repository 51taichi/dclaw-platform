# -*- coding: utf-8 -*-
"""SQLAlchemy Core schema for QwenPaw durable app data."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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
    insert,
    select,
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
Index(
    "uq_user_connections_user_connector",
    user_connections.c.user_id,
    user_connections.c.connector_key,
    unique=True,
)

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
    Column(
        "capability_id",
        String,
        ForeignKey("capability_registry.id"),
        nullable=False,
    ),
    Column("enabled", Boolean, server_default=true()),
    Column("credentials", Text),
    Column("preferences", Text),
    Column(
        "subscribed_at",
        DateTime(timezone=True),
        server_default=func.now(),
    ),
)
Index(
    "uq_user_capabilities_user_capability",
    user_capabilities.c.user_id,
    user_capabilities.c.capability_id,
    unique=True,
)

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
    Column(
        "leader_agent_id",
        String,
        nullable=False,
        server_default="default",
    ),
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
    Column(
        "team_id",
        String,
        ForeignKey("expert_team_templates.id"),
        nullable=False,
    ),
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
    Column(
        "run_id",
        String,
        ForeignKey("expert_team_runs.id"),
        nullable=False,
    ),
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
    Column(
        "app_id",
        String,
        ForeignKey("open_api_external_apps.id"),
        nullable=False,
    ),
    Column(
        "publication_id",
        String,
        ForeignKey("open_api_publications.id"),
        nullable=False,
    ),
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
    Column(
        "app_id",
        String,
        ForeignKey("open_api_external_apps.id"),
        nullable=False,
    ),
    Column(
        "publication_id",
        String,
        ForeignKey("open_api_publications.id"),
        nullable=False,
    ),
    Column(
        "api_key_id",
        String,
        ForeignKey("open_api_keys.id"),
        nullable=False,
    ),
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
    Column(
        "billing_usage_order_id",
        String,
        ForeignKey(
            "billing_usage_orders.id",
            name="fk_open_api_invocations_billing_usage_order",
        ),
    ),
    Column(
        "billing_status", String, nullable=False, server_default="unbilled"
    ),
    Column("quoted_credits", BigInteger, nullable=False, server_default="0"),
    Column("captured_credits", BigInteger, nullable=False, server_default="0"),
    Column("released_credits", BigInteger, nullable=False, server_default="0"),
    Column("billing_error_code", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "quoted_credits >= 0",
        name="ck_open_api_invocations_quoted_nonnegative",
    ),
    CheckConstraint(
        "captured_credits >= 0",
        name="ck_open_api_invocations_captured_nonnegative",
    ),
    CheckConstraint(
        "released_credits >= 0",
        name="ck_open_api_invocations_released_nonnegative",
    ),
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
    Column(
        "chunk_id",
        String,
        ForeignKey("knowledge_chunks.id"),
        nullable=False,
    ),
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

billing_wallets = Table(
    "billing_wallets",
    metadata,
    Column("id", String, primary_key=True),
    Column("owner_type", String, nullable=False),
    Column("owner_id", String, nullable=False),
    Column("status", String, nullable=False, server_default="active"),
    Column(
        "available_credits",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column("held_credits", BigInteger, nullable=False, server_default="0"),
    Column(
        "purchased_credits",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column(
        "promotional_credits",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column("package_credits", BigInteger, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "available_credits >= 0",
        name="ck_billing_wallets_available_nonnegative",
    ),
    CheckConstraint(
        "held_credits >= 0",
        name="ck_billing_wallets_held_nonnegative",
    ),
    CheckConstraint(
        "purchased_credits >= 0",
        name="ck_billing_wallets_purchased_nonnegative",
    ),
    CheckConstraint(
        "promotional_credits >= 0",
        name="ck_billing_wallets_promotional_nonnegative",
    ),
    CheckConstraint(
        "package_credits >= 0",
        name="ck_billing_wallets_package_nonnegative",
    ),
)

billing_credit_lots = Table(
    "billing_credit_lots",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "wallet_id",
        String,
        ForeignKey("billing_wallets.id"),
        nullable=False,
    ),
    Column(
        "source_ledger_entry_id",
        String,
        ForeignKey("billing_ledger_entries.id"),
    ),
    Column("credit_type", String, nullable=False),
    Column("status", String, nullable=False, server_default="active"),
    Column("granted_credits", BigInteger, nullable=False),
    Column("available_credits", BigInteger, nullable=False),
    Column("held_credits", BigInteger, nullable=False, server_default="0"),
    Column("expires_at", DateTime(timezone=True)),
    Column("metadata_json", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "granted_credits >= 0",
        name="ck_billing_credit_lots_granted_nonnegative",
    ),
    CheckConstraint(
        "available_credits >= 0",
        name="ck_billing_credit_lots_available_nonnegative",
    ),
    CheckConstraint(
        "held_credits >= 0",
        name="ck_billing_credit_lots_held_nonnegative",
    ),
    CheckConstraint(
        "credit_type != 'purchased' OR expires_at IS NULL",
        name="ck_billing_credit_lots_purchased_no_expiry",
    ),
)

billing_ledger_entries = Table(
    "billing_ledger_entries",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "wallet_id",
        String,
        ForeignKey("billing_wallets.id"),
        nullable=False,
    ),
    Column("event_type", String, nullable=False),
    Column("status", String, nullable=False, server_default="committed"),
    Column("credit_delta", BigInteger, nullable=False),
    Column("cash_delta_fen", BigInteger, nullable=False, server_default="0"),
    Column("business_type", String, nullable=False),
    Column("business_key", String, nullable=False),
    Column("idempotency_key", String, nullable=False),
    Column("actor_type", String, nullable=False, server_default="system"),
    Column("actor_id", String),
    Column("reason", Text),
    Column("metadata_json", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

billing_ledger_allocations = Table(
    "billing_ledger_allocations",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "ledger_entry_id",
        String,
        ForeignKey("billing_ledger_entries.id"),
        nullable=False,
    ),
    Column(
        "credit_lot_id",
        String,
        ForeignKey("billing_credit_lots.id"),
        nullable=False,
    ),
    Column("credits", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "credits > 0",
        name="ck_billing_ledger_allocations_credits_positive",
    ),
)

billing_price_catalogs = Table(
    "billing_price_catalogs",
    metadata,
    Column("id", String, primary_key=True),
    Column("version", String, nullable=False),
    Column("status", String, nullable=False, server_default="draft"),
    Column("effective_at", DateTime(timezone=True)),
    Column("published_at", DateTime(timezone=True)),
    Column("created_by", String),
    Column("metadata_json", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

billing_price_rules = Table(
    "billing_price_rules",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "catalog_id",
        String,
        ForeignKey("billing_price_catalogs.id"),
        nullable=False,
    ),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("capability", String, nullable=False),
    Column("unit_type", String, nullable=False),
    Column("status", String, nullable=False, server_default="active"),
    Column("priority", Integer, nullable=False, server_default="0"),
    Column("unit_size", Integer, nullable=False, server_default="1"),
    Column("credits_per_unit", Integer, nullable=False, server_default="0"),
    Column(
        "input_credits_per_1k",
        Integer,
        nullable=False,
        server_default="0",
    ),
    Column(
        "output_credits_per_1k",
        Integer,
        nullable=False,
        server_default="0",
    ),
    Column("parameter_match_json", Text, nullable=False, server_default="{}"),
    Column("metadata_json", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "priority >= 0",
        name="ck_billing_price_rules_priority_nonnegative",
    ),
    CheckConstraint(
        "unit_size > 0",
        name="ck_billing_price_rules_unit_size_positive",
    ),
    CheckConstraint(
        "credits_per_unit >= 0",
        name="ck_billing_price_rules_credits_nonnegative",
    ),
    CheckConstraint(
        "input_credits_per_1k >= 0",
        name="ck_billing_price_rules_input_credits_nonnegative",
    ),
    CheckConstraint(
        "output_credits_per_1k >= 0",
        name="ck_billing_price_rules_output_credits_nonnegative",
    ),
)

billing_usage_orders = Table(
    "billing_usage_orders",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "wallet_id",
        String,
        ForeignKey("billing_wallets.id"),
        nullable=False,
    ),
    Column(
        "catalog_id",
        String,
        ForeignKey("billing_price_catalogs.id"),
        nullable=False,
    ),
    Column("price_rule_id", String, ForeignKey("billing_price_rules.id")),
    Column("business_key", String, nullable=False),
    Column("source_type", String),
    Column("source_id", String),
    Column("status", String, nullable=False, server_default="quoted"),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("capability", String, nullable=False),
    Column("quoted_credits", BigInteger, nullable=False, server_default="0"),
    Column("budget_credits", BigInteger, nullable=False, server_default="0"),
    Column("held_credits", BigInteger, nullable=False, server_default="0"),
    Column("captured_credits", BigInteger, nullable=False, server_default="0"),
    Column("released_credits", BigInteger, nullable=False, server_default="0"),
    Column(
        "reconciling_credits",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column("request_snapshot_json", Text, nullable=False, server_default="{}"),
    Column("price_snapshot_json", Text, nullable=False, server_default="{}"),
    Column("supplier_reference", String),
    Column(
        "supplier_evidence_json",
        Text,
        nullable=False,
        server_default="{}",
    ),
    Column("billability", String, nullable=False, server_default="unknown"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("submitted_at", DateTime(timezone=True)),
    Column("settled_at", DateTime(timezone=True)),
    CheckConstraint(
        "quoted_credits >= 0",
        name="ck_billing_usage_orders_quoted_nonnegative",
    ),
    CheckConstraint(
        "held_credits >= 0",
        name="ck_billing_usage_orders_held_nonnegative",
    ),
    CheckConstraint(
        "captured_credits >= 0",
        name="ck_billing_usage_orders_captured_nonnegative",
    ),
    CheckConstraint(
        "budget_credits >= 0",
        name="ck_billing_usage_orders_budget_nonnegative",
    ),
    CheckConstraint(
        "released_credits >= 0",
        name="ck_billing_usage_orders_released_nonnegative",
    ),
    CheckConstraint(
        "reconciling_credits >= 0",
        name="ck_billing_usage_orders_reconciling_nonnegative",
    ),
    CheckConstraint(
        "billability IN ('unknown', 'billable', 'not_billable')",
        name="ck_billing_usage_orders_billability",
    ),
)

billing_usage_items = Table(
    "billing_usage_items",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "usage_order_id",
        String,
        ForeignKey("billing_usage_orders.id"),
        nullable=False,
    ),
    Column("price_rule_id", String, ForeignKey("billing_price_rules.id")),
    Column("item_key", String),
    Column("status", String, nullable=False, server_default="quoted"),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("capability", String, nullable=False),
    Column("supplier_reference", String),
    Column("input_tokens", BigInteger, nullable=False, server_default="0"),
    Column("output_tokens", BigInteger, nullable=False, server_default="0"),
    Column("quantity", BigInteger, nullable=False, server_default="0"),
    Column("quoted_credits", BigInteger, nullable=False, server_default="0"),
    Column("charged_credits", BigInteger, nullable=False, server_default="0"),
    Column(
        "supplier_cost_fen",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column("usage_snapshot_json", Text, nullable=False, server_default="{}"),
    Column("price_snapshot_json", Text, nullable=False, server_default="{}"),
    Column(
        "supplier_evidence_json",
        Text,
        nullable=False,
        server_default="{}",
    ),
    Column("billability", String, nullable=False, server_default="unknown"),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "input_tokens >= 0",
        name="ck_billing_usage_items_input_nonnegative",
    ),
    CheckConstraint(
        "output_tokens >= 0",
        name="ck_billing_usage_items_output_nonnegative",
    ),
    CheckConstraint(
        "quantity >= 0",
        name="ck_billing_usage_items_quantity_nonnegative",
    ),
    CheckConstraint(
        "charged_credits >= 0",
        name="ck_billing_usage_items_charged_nonnegative",
    ),
    CheckConstraint(
        "quoted_credits >= 0",
        name="ck_billing_usage_items_quoted_nonnegative",
    ),
    CheckConstraint(
        "supplier_cost_fen >= 0",
        name="ck_billing_usage_items_supplier_cost_nonnegative",
    ),
    CheckConstraint(
        "billability IN ('unknown', 'billable', 'not_billable')",
        name="ck_billing_usage_items_billability",
    ),
)

Index(
    "idx_chats_user_agent_updated",
    chats.c.user_id,
    chats.c.agent_id,
    chats.c.updated_at.desc(),
)
Index(
    "idx_chats_session_user_channel_agent",
    chats.c.session_id,
    chats.c.user_id,
    chats.c.channel,
    chats.c.agent_id,
)
Index(
    "idx_messages_chat_timestamp",
    messages.c.chat_id,
    messages.c.timestamp.asc(),
)
Index("idx_session_states_chat_id", session_states.c.chat_id)
Index(
    "idx_expert_team_runs_user_state_updated",
    expert_team_runs.c.user_id,
    expert_team_runs.c.state,
    expert_team_runs.c.updated_at.desc(),
)
Index(
    "idx_expert_team_member_runs_run_state",
    expert_team_member_runs.c.run_id,
    expert_team_member_runs.c.state,
)
Index(
    "idx_open_api_publications_target",
    open_api_publications.c.target_type,
    open_api_publications.c.target_id,
)
Index(
    "idx_open_api_external_apps_owner_status",
    open_api_external_apps.c.owner_user_id,
    open_api_external_apps.c.status,
)
Index(
    "idx_open_api_keys_app_publication",
    open_api_keys.c.app_id,
    open_api_keys.c.publication_id,
)
Index(
    "idx_open_api_invocations_publication_created",
    open_api_invocations.c.publication_id,
    open_api_invocations.c.created_at.desc(),
)
Index(
    "idx_knowledge_docs_scope_owner_updated",
    knowledge_docs.c.scope,
    knowledge_docs.c.owner_user_id,
    knowledge_docs.c.updated_at.desc(),
)
Index("idx_knowledge_docs_status", knowledge_docs.c.status)
Index("idx_knowledge_assets_doc", knowledge_assets.c.doc_id)
Index("idx_knowledge_chunks_doc", knowledge_chunks.c.doc_id)
Index(
    "idx_knowledge_chunks_scope_owner",
    knowledge_chunks.c.scope,
    knowledge_chunks.c.owner_user_id,
)
Index("idx_knowledge_embeddings_chunk", knowledge_embeddings.c.chunk_id)
Index(
    "idx_knowledge_wiki_scope_owner_concept",
    knowledge_wiki.c.scope,
    knowledge_wiki.c.owner_user_id,
    knowledge_wiki.c.concept,
)
Index("idx_knowledge_wiki_doc", knowledge_wiki.c.doc_id)
Index(
    "uq_billing_wallets_owner",
    billing_wallets.c.owner_type,
    billing_wallets.c.owner_id,
    unique=True,
)
Index(
    "idx_billing_credit_lots_wallet_expiry",
    billing_credit_lots.c.wallet_id,
    billing_credit_lots.c.expires_at.asc(),
)
Index(
    "idx_billing_credit_lots_wallet_status",
    billing_credit_lots.c.wallet_id,
    billing_credit_lots.c.status,
)
Index(
    "uq_billing_ledger_entries_idempotency",
    billing_ledger_entries.c.idempotency_key,
    unique=True,
)
Index(
    "idx_billing_ledger_entries_wallet_created",
    billing_ledger_entries.c.wallet_id,
    billing_ledger_entries.c.created_at.desc(),
)
Index(
    "idx_billing_ledger_entries_business",
    billing_ledger_entries.c.business_type,
    billing_ledger_entries.c.business_key,
)
Index(
    "uq_billing_ledger_allocations_entry_lot",
    billing_ledger_allocations.c.ledger_entry_id,
    billing_ledger_allocations.c.credit_lot_id,
    unique=True,
)
Index(
    "idx_billing_ledger_allocations_lot",
    billing_ledger_allocations.c.credit_lot_id,
)
Index(
    "uq_billing_price_catalogs_version",
    billing_price_catalogs.c.version,
    unique=True,
)
Index(
    "idx_billing_price_catalogs_status_effective",
    billing_price_catalogs.c.status,
    billing_price_catalogs.c.effective_at.desc(),
)
Index(
    "idx_billing_price_rules_catalog_lookup",
    billing_price_rules.c.catalog_id,
    billing_price_rules.c.provider_id,
    billing_price_rules.c.model_key,
    billing_price_rules.c.capability,
)
Index(
    "uq_billing_usage_orders_business",
    billing_usage_orders.c.business_key,
    unique=True,
)
Index(
    "uq_billing_usage_orders_source",
    billing_usage_orders.c.source_type,
    billing_usage_orders.c.source_id,
    unique=True,
)
Index(
    "idx_billing_usage_orders_wallet_status",
    billing_usage_orders.c.wallet_id,
    billing_usage_orders.c.status,
    billing_usage_orders.c.created_at.desc(),
)
Index(
    "idx_billing_usage_orders_supplier_reference",
    billing_usage_orders.c.supplier_reference,
)
Index("idx_billing_usage_items_order", billing_usage_items.c.usage_order_id)
Index(
    "uq_billing_usage_items_order_item_key",
    billing_usage_items.c.usage_order_id,
    billing_usage_items.c.item_key,
    unique=True,
)


def create_all(engine: Engine) -> None:
    """Create all known durable tables and indexes."""
    metadata.create_all(engine)
    _ensure_open_api_publication_binding_columns(engine)
    _ensure_knowledge_metadata_columns(engine)
    _ensure_billing_usage_order_columns(engine)
    _ensure_open_api_billing_columns(engine)
    _ensure_billing_bigint_columns(engine)
    _ensure_billing_constraints(engine)
    _backfill_personal_wallets(engine)


def _backfill_personal_wallets(engine: Engine) -> None:
    """Create the empty personal wallet required for every durable user."""
    with engine.begin() as conn:
        user_ids = conn.execute(select(users.c.id)).scalars().all()
        existing = set(
            conn.execute(
                select(billing_wallets.c.owner_id).where(
                    billing_wallets.c.owner_type == "user",
                ),
            ).scalars(),
        )
        for user_id in user_ids:
            owner_id = str(user_id)
            if owner_id not in existing:
                values = {
                    "id": str(uuid4()),
                    "owner_type": "user",
                    "owner_id": owner_id,
                }
                if engine.dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import (
                        insert as pg_insert,
                    )

                    statement = pg_insert(billing_wallets).values(**values)
                    statement = statement.on_conflict_do_nothing(
                        index_elements=["owner_type", "owner_id"],
                    )
                elif engine.dialect.name == "sqlite":
                    from sqlalchemy.dialects.sqlite import (
                        insert as sqlite_insert,
                    )

                    statement = sqlite_insert(billing_wallets).values(**values)
                    statement = statement.on_conflict_do_nothing(
                        index_elements=["owner_type", "owner_id"],
                    )
                else:
                    statement = insert(billing_wallets).values(**values)
                conn.execute(statement)


def _ensure_billing_bigint_columns(engine: Engine) -> None:
    """Upgrade existing PostgreSQL accounting quantities to BIGINT."""
    if engine.dialect.name != "postgresql":
        return
    columns = {
        "billing_wallets": (
            "available_credits",
            "held_credits",
            "purchased_credits",
            "promotional_credits",
            "package_credits",
        ),
        "billing_credit_lots": (
            "granted_credits",
            "available_credits",
            "held_credits",
        ),
        "billing_ledger_entries": ("credit_delta", "cash_delta_fen"),
        "billing_ledger_allocations": ("credits",),
        "billing_usage_orders": (
            "quoted_credits",
            "budget_credits",
            "held_credits",
            "captured_credits",
            "released_credits",
            "reconciling_credits",
        ),
        "billing_usage_items": (
            "input_tokens",
            "output_tokens",
            "quantity",
            "quoted_credits",
            "charged_credits",
            "supplier_cost_fen",
        ),
    }
    with engine.begin() as conn:
        for table_name, column_names in columns.items():
            for column_name in column_names:
                conn.execute(
                    text(
                        f'ALTER TABLE "{table_name}" ALTER COLUMN '
                        f'"{column_name}" TYPE BIGINT',
                    ),
                )


def _ensure_billing_usage_order_columns(engine: Engine) -> None:
    """Backfill settlement evidence columns on existing installations."""
    inspector = inspect(engine)
    if "billing_usage_orders" not in inspector.get_table_names():
        return
    existing = {
        column["name"]
        for column in inspector.get_columns("billing_usage_orders")
    }
    if "billability" not in existing:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE billing_usage_orders ADD COLUMN "
                    "billability VARCHAR NOT NULL DEFAULT 'unknown'",
                ),
            )


def _ensure_open_api_billing_columns(engine: Engine) -> None:
    """Upgrade OpenAPI billing data without changing ledger or token rows."""
    datetime_type = str(
        DateTime(timezone=True).compile(dialect=engine.dialect)
    )
    additions = {
        "open_api_invocations": {
            "billing_usage_order_id": (
                "ALTER TABLE open_api_invocations ADD COLUMN "
                "billing_usage_order_id VARCHAR"
            ),
            "billing_status": (
                "ALTER TABLE open_api_invocations ADD COLUMN billing_status "
                "VARCHAR NOT NULL DEFAULT 'unbilled'"
            ),
            "quoted_credits": (
                "ALTER TABLE open_api_invocations ADD COLUMN quoted_credits "
                "BIGINT NOT NULL DEFAULT 0"
            ),
            "captured_credits": (
                "ALTER TABLE open_api_invocations ADD COLUMN captured_credits "
                "BIGINT NOT NULL DEFAULT 0"
            ),
            "released_credits": (
                "ALTER TABLE open_api_invocations ADD COLUMN released_credits "
                "BIGINT NOT NULL DEFAULT 0"
            ),
            "billing_error_code": (
                "ALTER TABLE open_api_invocations ADD COLUMN "
                "billing_error_code VARCHAR"
            ),
        },
        "billing_usage_orders": {
            "source_type": (
                "ALTER TABLE billing_usage_orders ADD COLUMN source_type VARCHAR"  # noqa: E501
            ),
            "source_id": (
                "ALTER TABLE billing_usage_orders ADD COLUMN source_id VARCHAR"
            ),
            "budget_credits": (
                "ALTER TABLE billing_usage_orders ADD COLUMN budget_credits "
                "BIGINT NOT NULL DEFAULT 0"
            ),
            "released_credits": (
                "ALTER TABLE billing_usage_orders ADD COLUMN released_credits "
                "BIGINT NOT NULL DEFAULT 0"
            ),
            "reconciling_credits": (
                "ALTER TABLE billing_usage_orders ADD COLUMN "
                "reconciling_credits BIGINT NOT NULL DEFAULT 0"
            ),
        },
        "billing_usage_items": {
            "item_key": (
                "ALTER TABLE billing_usage_items ADD COLUMN item_key VARCHAR"
            ),
            "billability": (
                "ALTER TABLE billing_usage_items ADD COLUMN billability "
                "VARCHAR NOT NULL DEFAULT 'unknown'"
            ),
            "quoted_credits": (
                "ALTER TABLE billing_usage_items ADD COLUMN quoted_credits "
                "BIGINT NOT NULL DEFAULT 0"
            ),
            "price_snapshot_json": (
                "ALTER TABLE billing_usage_items ADD COLUMN "
                "price_snapshot_json TEXT NOT NULL DEFAULT '{}'"
            ),
            "started_at": (
                "ALTER TABLE billing_usage_items ADD COLUMN started_at "
                f"{datetime_type}"
            ),
            "finished_at": (
                "ALTER TABLE billing_usage_items ADD COLUMN finished_at "
                f"{datetime_type}"
            ),
        },
    }
    inspector = inspect(engine)
    existing_table_names = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table_name, columns in additions.items():
            if table_name not in existing_table_names:
                continue
            existing = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    conn.execute(text(ddl))

    _validate_open_api_billing_history(engine)
    if (
        engine.dialect.name == "sqlite"
        and _sqlite_open_api_billing_rebuild_required(engine)
    ):
        _rebuild_sqlite_open_api_billing_tables(engine)
    elif engine.dialect.name == "postgresql":
        _ensure_postgresql_open_api_billing_constraints(engine)
    _ensure_open_api_billing_indexes(engine)


def _validate_open_api_billing_history(engine: Engine) -> None:
    """Reject unsafe legacy values before adding financial constraints."""
    violations = {
        "open_api_invocations": (
            "quoted_credits IS NULL OR quoted_credits < 0 OR "
            "captured_credits IS NULL OR captured_credits < 0 OR "
            "released_credits IS NULL OR released_credits < 0"
        ),
        "billing_usage_orders": (
            "quoted_credits IS NULL OR quoted_credits < 0 OR "
            "budget_credits IS NULL OR budget_credits < 0 OR "
            "held_credits IS NULL OR held_credits < 0 OR "
            "captured_credits IS NULL OR captured_credits < 0 OR "
            "released_credits IS NULL OR released_credits < 0 OR "
            "reconciling_credits IS NULL OR reconciling_credits < 0 OR "
            "billability IS NULL OR billability NOT IN "
            "('unknown', 'billable', 'not_billable')"
        ),
        "billing_usage_items": (
            "input_tokens IS NULL OR input_tokens < 0 OR "
            "output_tokens IS NULL OR output_tokens < 0 OR "
            "quantity IS NULL OR quantity < 0 OR "
            "quoted_credits IS NULL OR quoted_credits < 0 OR "
            "charged_credits IS NULL OR charged_credits < 0 OR "
            "supplier_cost_fen IS NULL OR supplier_cost_fen < 0 OR "
            "billability IS NULL OR billability NOT IN "
            "('unknown', 'billable', 'not_billable')"
        ),
    }
    existing_table_names = set(inspect(engine).get_table_names())
    with engine.connect() as conn:
        for table_name, condition in violations.items():
            if table_name not in existing_table_names:
                continue
            invalid = conn.scalar(
                text(
                    f"SELECT 1 FROM {table_name} WHERE {condition} LIMIT 1",
                ),
            )
            if invalid is not None:
                raise ValueError(
                    f"invalid historical billing data in {table_name}",
                )


def _rebuild_sqlite_open_api_billing_tables(engine: Engine) -> None:
    """Rebuild SQLite bridge tables so existing rows gain FKs and CHECKs."""
    source_tables = (
        billing_usage_orders,
        billing_usage_items,
        open_api_invocations,
    )
    temporary_tables: dict[str, Table] = {}
    with engine.connect() as conn:
        foreign_keys_enabled = bool(
            conn.scalar(text("PRAGMA foreign_keys")),
        )
        conn.commit()
        if foreign_keys_enabled:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            conn.commit()
        transaction = conn.begin()
        try:
            for source_table in source_tables:
                temporary_tables[source_table.name] = _sqlite_table_copy(
                    conn,
                    source_table,
                )
            for source_table in source_tables:
                temporary_table = temporary_tables[source_table.name]
                existing = {
                    column["name"]
                    for column in inspect(conn).get_columns(source_table.name)
                }
                columns = [
                    column.name
                    for column in temporary_table.columns
                    if column.name in existing
                ]
                quoted_columns = ", ".join(f'"{column}"' for column in columns)
                select_columns = ", ".join(
                    f"COALESCE(\"{column}\", '{{}}')"
                    if column
                    in {
                        "request_snapshot_json",
                        "price_snapshot_json",
                        "supplier_evidence_json",
                        "token_summary",
                        "usage_snapshot_json",
                    }
                    else f'"{column}"'
                    for column in columns
                )
                conn.execute(
                    text(
                        f'INSERT INTO "{temporary_table.name}" '
                        f"({quoted_columns}) SELECT {select_columns} "
                        f'FROM "{source_table.name}"',
                    ),
                )
            for source_table in reversed(source_tables):
                conn.execute(text(f'DROP TABLE "{source_table.name}"'))
            for source_table in source_tables:
                temporary_table = temporary_tables[source_table.name]
                conn.execute(
                    text(
                        f'ALTER TABLE "{temporary_table.name}" RENAME TO '
                        f'"{source_table.name}"',
                    ),
                )
            transaction.commit()
        except Exception:
            transaction.rollback()
            raise
        finally:
            if foreign_keys_enabled:
                conn.execute(text("PRAGMA foreign_keys = ON"))


def _sqlite_open_api_billing_rebuild_required(engine: Engine) -> bool:
    """Return whether legacy SQLite tables are missing bridge constraints."""
    required_checks = {
        "open_api_invocations": {
            "ck_open_api_invocations_quoted_nonnegative",
            "ck_open_api_invocations_captured_nonnegative",
            "ck_open_api_invocations_released_nonnegative",
        },
        "billing_usage_orders": {
            "ck_billing_usage_orders_quoted_nonnegative",
            "ck_billing_usage_orders_held_nonnegative",
            "ck_billing_usage_orders_captured_nonnegative",
            "ck_billing_usage_orders_budget_nonnegative",
            "ck_billing_usage_orders_released_nonnegative",
            "ck_billing_usage_orders_reconciling_nonnegative",
            "ck_billing_usage_orders_billability",
        },
        "billing_usage_items": {
            "ck_billing_usage_items_input_nonnegative",
            "ck_billing_usage_items_output_nonnegative",
            "ck_billing_usage_items_quantity_nonnegative",
            "ck_billing_usage_items_charged_nonnegative",
            "ck_billing_usage_items_quoted_nonnegative",
            "ck_billing_usage_items_supplier_cost_nonnegative",
            "ck_billing_usage_items_billability",
        },
    }
    inspector = inspect(engine)
    for table_name, expected in required_checks.items():
        actual = {
            check["name"]
            for check in inspector.get_check_constraints(table_name)
        }
        if not expected <= actual:
            return True
    invocation_targets = {
        foreign_key["referred_table"]
        for foreign_key in inspector.get_foreign_keys("open_api_invocations")
    }
    return "billing_usage_orders" not in invocation_targets


def _sqlite_table_copy(conn, source_table: Table) -> Table:
    """Create an unindexed SQLite clone with the current table constraints."""
    clone_metadata = MetaData()
    for foreign_key in source_table.foreign_keys:
        foreign_key.column.table.to_metadata(clone_metadata)
    temporary_table = source_table.to_metadata(
        clone_metadata,
        name=f"{source_table.name}__billing_rebuild",
    )
    temporary_table.indexes.clear()
    temporary_table.create(conn)
    return temporary_table


def _ensure_open_api_billing_indexes(engine: Engine) -> None:
    """Create the bridge indexes after fresh creation or a legacy rebuild."""
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_open_api_invocations_publication_created "  # noqa: E501
        "ON open_api_invocations (publication_id, created_at DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_usage_orders_business "
        "ON billing_usage_orders (business_key)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_usage_orders_source "
        "ON billing_usage_orders (source_type, source_id)",
        "CREATE INDEX IF NOT EXISTS idx_billing_usage_orders_wallet_status "
        "ON billing_usage_orders (wallet_id, status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_billing_usage_orders_supplier_reference "  # noqa: E501
        "ON billing_usage_orders (supplier_reference)",
        "CREATE INDEX IF NOT EXISTS idx_billing_usage_items_order "
        "ON billing_usage_items (usage_order_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_usage_items_order_item_key "  # noqa: E501
        "ON billing_usage_items (usage_order_id, item_key)",
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _ensure_postgresql_open_api_billing_constraints(engine: Engine) -> None:
    """Add missing bridge constraints with relation-scoped guards."""
    constraints = (
        (
            "open_api_invocations",
            "ck_open_api_invocations_quoted_nonnegative",
            "c",
            "CHECK (quoted_credits >= 0)",
        ),
        (
            "open_api_invocations",
            "ck_open_api_invocations_captured_nonnegative",
            "c",
            "CHECK (captured_credits >= 0)",
        ),
        (
            "open_api_invocations",
            "ck_open_api_invocations_released_nonnegative",
            "c",
            "CHECK (released_credits >= 0)",
        ),
        (
            "billing_usage_orders",
            "ck_billing_usage_orders_quoted_nonnegative",
            "c",
            "CHECK (quoted_credits >= 0)",
        ),
        (
            "billing_usage_orders",
            "ck_billing_usage_orders_held_nonnegative",
            "c",
            "CHECK (held_credits >= 0)",
        ),
        (
            "billing_usage_orders",
            "ck_billing_usage_orders_captured_nonnegative",
            "c",
            "CHECK (captured_credits >= 0)",
        ),
        (
            "billing_usage_orders",
            "ck_billing_usage_orders_budget_nonnegative",
            "c",
            "CHECK (budget_credits >= 0)",
        ),
        (
            "billing_usage_orders",
            "ck_billing_usage_orders_released_nonnegative",
            "c",
            "CHECK (released_credits >= 0)",
        ),
        (
            "billing_usage_orders",
            "ck_billing_usage_orders_reconciling_nonnegative",
            "c",
            "CHECK (reconciling_credits >= 0)",
        ),
        (
            "billing_usage_orders",
            "ck_billing_usage_orders_billability",
            "c",
            "CHECK (billability IN ('unknown', 'billable', 'not_billable'))",
        ),
        (
            "billing_usage_items",
            "ck_billing_usage_items_input_nonnegative",
            "c",
            "CHECK (input_tokens >= 0)",
        ),
        (
            "billing_usage_items",
            "ck_billing_usage_items_output_nonnegative",
            "c",
            "CHECK (output_tokens >= 0)",
        ),
        (
            "billing_usage_items",
            "ck_billing_usage_items_quantity_nonnegative",
            "c",
            "CHECK (quantity >= 0)",
        ),
        (
            "billing_usage_items",
            "ck_billing_usage_items_charged_nonnegative",
            "c",
            "CHECK (charged_credits >= 0)",
        ),
        (
            "billing_usage_items",
            "ck_billing_usage_items_quoted_nonnegative",
            "c",
            "CHECK (quoted_credits >= 0)",
        ),
        (
            "billing_usage_items",
            "ck_billing_usage_items_supplier_cost_nonnegative",
            "c",
            "CHECK (supplier_cost_fen >= 0)",
        ),
        (
            "billing_usage_items",
            "ck_billing_usage_items_billability",
            "c",
            "CHECK (billability IN ('unknown', 'billable', 'not_billable'))",
        ),
        (
            "open_api_invocations",
            "fk_open_api_invocations_billing_usage_order",
            "f",
            "FOREIGN KEY (billing_usage_order_id) "
            "REFERENCES billing_usage_orders (id)",
        ),
    )
    with engine.begin() as conn:
        for table_name, name, constraint_type, definition in constraints:
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM "
                    "pg_constraint AS pc JOIN pg_class AS relation "
                    "ON relation.oid = pc.conrelid JOIN pg_namespace "
                    "AS namespace ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = current_schema() AND "
                    f"relation.relname = '{table_name}' AND "
                    "pc.conrelid = relation.oid AND "
                    f"pc.conname = '{name}' AND "
                    f"pc.contype = '{constraint_type}') THEN "
                    f"ALTER TABLE {table_name} ADD CONSTRAINT {name} "
                    f"{definition}; END IF; END $$",
                ),
            )


def _ensure_billing_constraints(engine: Engine) -> None:
    """Enforce invariants that runtime upgrades must not bypass."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM "
                    "pg_constraint AS pc JOIN pg_class AS relation "
                    "ON relation.oid = pc.conrelid JOIN pg_namespace "
                    "AS namespace ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = current_schema() AND "
                    "relation.relname = 'billing_credit_lots' AND "
                    "pc.conrelid = relation.oid AND "
                    "pc.conname = "
                    "'ck_billing_credit_lots_purchased_no_expiry' AND "
                    "pc.contype = 'c') THEN "
                    "ALTER TABLE billing_credit_lots ADD CONSTRAINT "
                    "ck_billing_credit_lots_purchased_no_expiry CHECK "
                    "(credit_type <> 'purchased' OR expires_at IS NULL) "
                    "NOT VALID; END IF; END $$",
                ),
            )
            conn.execute(
                text(
                    "ALTER TABLE billing_credit_lots VALIDATE CONSTRAINT "
                    "ck_billing_credit_lots_purchased_no_expiry",
                ),
            )
        return
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS "
                "ck_billing_credit_lots_purchased_no_expiry_insert "
                "BEFORE INSERT ON billing_credit_lots "
                "WHEN NEW.credit_type = 'purchased' "
                "AND NEW.expires_at IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT, "
                "'purchased credits cannot expire'); END",
            ),
        )
        conn.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS "
                "ck_billing_credit_lots_purchased_no_expiry_update "
                "BEFORE UPDATE ON billing_credit_lots "
                "WHEN NEW.credit_type = 'purchased' "
                "AND NEW.expires_at IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT, "
                "'purchased credits cannot expire'); END",
            ),
        )


def _ensure_open_api_publication_binding_columns(engine: Engine) -> None:
    """Backfill runtime-user and knowledge-base publication bindings."""
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
                    "ADD COLUMN bound_user_id VARCHAR",
                ),
            )
        if "knowledge_base_id" not in existing:
            conn.execute(
                text(
                    "ALTER TABLE open_api_publications "
                    "ADD COLUMN knowledge_base_id VARCHAR",
                ),
            )
        conn.execute(
            text(
                "UPDATE open_api_publications "
                "SET bound_user_id = owner_user_id "
                "WHERE bound_user_id IS NULL OR bound_user_id = ''",
            ),
        )
        conn.execute(
            text(
                "UPDATE open_api_publications "
                "SET knowledge_base_id = 'openapi-' || id "
                "WHERE knowledge_base_id IS NULL OR knowledge_base_id = ''",
            ),
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_open_api_publications_knowledge_base "
                "ON open_api_publications (knowledge_base_id)",
            ),
        )


def _ensure_knowledge_metadata_columns(engine: Engine) -> None:
    """Add knowledge metadata columns to older databases."""
    inspector = inspect(engine)
    if "knowledge_docs" not in inspector.get_table_names():
        return
    existing = {
        column["name"] for column in inspector.get_columns("knowledge_docs")
    }
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
