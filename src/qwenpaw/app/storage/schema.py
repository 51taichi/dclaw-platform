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
    update,
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
    Column(
        "billing_overdraft_enabled",
        Boolean,
        nullable=False,
        server_default=false(),
    ),
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

aigc_model_policies = Table(
    "aigc_model_policies",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("category", String, nullable=False, unique=True),
    Column("configured", Boolean, nullable=False, server_default=true()),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("updated_by", Integer),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "category IN ('text', 'image', 'video', 'audio')",
        name="ck_aigc_model_policies_category",
    ),
)

aigc_model_policy_items = Table(
    "aigc_model_policy_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "policy_id",
        Integer,
        ForeignKey("aigc_model_policies.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("provider_id", String, nullable=False),
    Column("model_id", String, nullable=False),
    Column("sort_order", Integer, nullable=False),
    Column("is_default", Boolean, nullable=False, server_default=false()),
)
Index(
    "uq_aigc_model_policy_items_model",
    aigc_model_policy_items.c.policy_id,
    aigc_model_policy_items.c.provider_id,
    aigc_model_policy_items.c.model_id,
    unique=True,
)
Index(
    "uq_aigc_model_policy_items_order",
    aigc_model_policy_items.c.policy_id,
    aigc_model_policy_items.c.sort_order,
    unique=True,
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
    Column("next_member_key", String),
    Column("required_credits", BigInteger),
    Column("billing_usage_order_id", String),
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
        "billing_status",
        String,
        nullable=False,
        server_default="unbilled",
    ),
    Column("quoted_credits", BigInteger, nullable=False, server_default="0"),
    Column("captured_credits", BigInteger, nullable=False, server_default="0"),
    Column("released_credits", BigInteger, nullable=False, server_default="0"),
    Column("billing_error_code", String),
    Column("execution_owner_token", String),
    Column(
        "execution_fence_generation",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column("execution_claimed_at", DateTime(timezone=True)),
    Column("execution_lease_expires_at", DateTime(timezone=True)),
    Column("expert_team_run_id", String),
    Column("terminal_event_json", Text),
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
    CheckConstraint(
        "execution_fence_generation >= 0",
        name="ck_open_api_invocations_fence_generation_nonnegative",
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
    Column("debt_credits", BigInteger, nullable=False, server_default="0"),
    Column(
        "held_overdraft_credits",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
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
    CheckConstraint(
        "debt_credits >= 0",
        name="ck_billing_wallets_debt_nonnegative",
    ),
    CheckConstraint(
        "held_overdraft_credits >= 0",
        name="ck_billing_wallets_held_overdraft_nonnegative",
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
    Column("revision", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

billing_cost_snapshots = Table(
    "billing_cost_snapshots",
    metadata,
    Column("id", String, primary_key=True),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("capability", String, nullable=False),
    Column("unit_key", String, nullable=False),
    Column("source_type", String, nullable=False),
    Column("source_reference", Text),
    Column("original_currency", String, nullable=False),
    Column("original_price_decimal", String, nullable=False),
    Column("fx_rate_decimal", String, nullable=False),
    Column("rmb_cost_decimal", String, nullable=False),
    Column("conditions_json", Text, nullable=False, server_default="{}"),
    Column("verification_status", String, nullable=False),
    Column("verified_at", DateTime(timezone=True)),
    Column("valid_until", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

billing_pricing_policies = Table(
    "billing_pricing_policies",
    metadata,
    Column("id", String, primary_key=True),
    Column("scope_type", String, nullable=False),
    Column("scope_key", String, nullable=False),
    Column("multiplier_decimal", String, nullable=False),
    Column("settings_json", Text, nullable=False, server_default="{}"),
    Column("revision", Integer, nullable=False, server_default="0"),
    Column("updated_by", String),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

billing_pricing_imports = Table(
    "billing_pricing_imports",
    metadata,
    Column("id", String, primary_key=True),
    Column("content_sha256", String, nullable=False, unique=True),
    Column("filename", String, nullable=False),
    Column("status", String, nullable=False),
    Column("preview_json", Text, nullable=False, server_default="{}"),
    Column("created_by", String, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

billing_pricing_unlocks = Table(
    "billing_pricing_unlocks",
    metadata,
    Column("id", String, primary_key=True),
    Column("actor_id", String, nullable=False),
    Column("token_hash", String, nullable=False, unique=True),
    Column("credential_fingerprint", String, nullable=False),
    Column("ip_address", String),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

billing_pricing_unlock_attempts = Table(
    "billing_pricing_unlock_attempts",
    metadata,
    Column("id", String, primary_key=True),
    Column("actor_id", String, nullable=False),
    Column("ip_address", String),
    Column("succeeded", Boolean, nullable=False, server_default=false()),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

billing_pricing_audits = Table(
    "billing_pricing_audits",
    metadata,
    Column("id", String, primary_key=True),
    Column("action", String, nullable=False),
    Column("actor_id", String, nullable=False),
    Column("before_json", Text, nullable=False, server_default="{}"),
    Column("after_json", Text, nullable=False, server_default="{}"),
    Column("metadata_json", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

billing_pricing_sync_state = Table(
    "billing_pricing_sync_state",
    metadata,
    Column("state_key", String, primary_key=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)

billing_official_price_candidates = Table(
    "billing_official_price_candidates",
    metadata,
    Column("id", String, primary_key=True),
    Column("content_sha256", String, nullable=False, unique=True),
    Column("provider_id", String, nullable=False),
    Column("official_model_id", String, nullable=False),
    Column("capability", String, nullable=False),
    Column("unit_key", String, nullable=False),
    Column("conditions_digest", String, nullable=False),
    Column("conditions_json", Text, nullable=False, server_default="{}"),
    Column("source_url", Text, nullable=False),
    Column("source_published_at", DateTime(timezone=True)),
    Column("original_currency", String, nullable=False),
    Column("original_price_decimal", String, nullable=False),
    Column("fx_rate_decimal", String, nullable=False),
    Column("rmb_cost_decimal", String, nullable=False),
    Column("verification_status", String, nullable=False),
    Column("registry_version", String, nullable=False),
    Column(
        "evidence_level",
        String,
        nullable=False,
        server_default="official_verified",
    ),
    Column("evidence_excerpt", Text),
    Column("collector_version", String, nullable=False, server_default="bundled"),
    Column("ai_model", String),
    Column("prompt_version", String),
    Column("confidence_decimal", String),
    Column("default_multiplier_decimal", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

billing_pricing_collection_jobs = Table(
    "billing_pricing_collection_jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("inventory_digest", String, nullable=False),
    Column("status", String, nullable=False, server_default="pending"),
    Column("requested_by", String, nullable=False),
    Column("worker_id", String),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("progress_json", Text, nullable=False, server_default="{}"),
    Column("error_summary", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('pending','running','succeeded',"
        "'partially_succeeded','failed')",
        name="ck_billing_pricing_collection_jobs_status",
    ),
)
Index(
    "idx_billing_pricing_collection_jobs_status_lease",
    billing_pricing_collection_jobs.c.status,
    billing_pricing_collection_jobs.c.lease_expires_at,
)
billing_pricing_collection_active_digest_index = Index(
    "uq_billing_pricing_collection_jobs_active_digest",
    billing_pricing_collection_jobs.c.inventory_digest,
    unique=True,
    sqlite_where=billing_pricing_collection_jobs.c.status.in_(
        ("pending", "running")
    ),
    postgresql_where=billing_pricing_collection_jobs.c.status.in_(
        ("pending", "running")
    ),
)

billing_pricing_collection_items = Table(
    "billing_pricing_collection_items",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "job_id",
        String,
        ForeignKey("billing_pricing_collection_jobs.id"),
        nullable=False,
    ),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("pricing_region", String, nullable=False, server_default=""),
    Column("status", String, nullable=False, server_default="pending"),
    Column("candidate_id", String),
    Column("result_json", Text, nullable=False, server_default="{}"),
    Column("error_summary", Text),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
)
Index(
    "uq_billing_pricing_collection_item",
    billing_pricing_collection_items.c.job_id,
    billing_pricing_collection_items.c.provider_id,
    billing_pricing_collection_items.c.model_key,
    billing_pricing_collection_items.c.pricing_region,
    unique=True,
)

billing_pricing_model_decisions = Table(
    "billing_pricing_model_decisions",
    metadata,
    Column("id", String, primary_key=True),
    Column("draft_key", String, nullable=False),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("include_in_publish", Boolean, nullable=False),
    Column("reason", Text),
    Column("updated_by", String, nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)
Index(
    "uq_billing_pricing_model_decision",
    billing_pricing_model_decisions.c.draft_key,
    billing_pricing_model_decisions.c.provider_id,
    billing_pricing_model_decisions.c.model_key,
    unique=True,
)

billing_pricing_model_mappings = Table(
    "billing_pricing_model_mappings",
    metadata,
    Column("id", String, primary_key=True),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("official_provider_id", String, nullable=False),
    Column("official_model_id", String, nullable=False),
    Column("revision", Integer, nullable=False, server_default="0"),
    Column("updated_by", String, nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)
Index(
    "uq_billing_pricing_model_mapping",
    billing_pricing_model_mappings.c.provider_id,
    billing_pricing_model_mappings.c.model_key,
    unique=True,
)

billing_pricing_draft_exclusions = Table(
    "billing_pricing_draft_exclusions",
    metadata,
    Column("id", String, primary_key=True),
    Column("draft_key", String, nullable=False),
    Column("provider_id", String, nullable=False),
    Column("model_key", String, nullable=False),
    Column("excluded", Boolean, nullable=False, server_default=false()),
    Column("reason", Text),
    Column("updated_by", String, nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)
Index(
    "uq_billing_pricing_draft_exclusion",
    billing_pricing_draft_exclusions.c.draft_key,
    billing_pricing_draft_exclusions.c.provider_id,
    billing_pricing_draft_exclusions.c.model_key,
    unique=True,
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

billing_executions = Table(
    "billing_executions",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "usage_order_id",
        String,
        ForeignKey("billing_usage_orders.id"),
        unique=True,
    ),
    Column("payer_user_id", String),
    Column("source_type", String, nullable=False),
    Column("source_id", String, nullable=False),
    Column("request_sha256", String, nullable=False),
    Column("state", String, nullable=False, server_default="accepted"),
    Column("owner_token", String),
    Column("fence_generation", BigInteger, nullable=False, server_default="0"),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("resume_state_json", Text, nullable=False, server_default="{}"),
    Column("exemption_actor", String),
    Column("exemption_reason", String),
    Column("error_code", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "state IN ('accepted', 'running', "
        "'paused_insufficient_balance', 'succeeded', 'failed', "
        "'cancelled', 'reconciling')",
        name="ck_billing_executions_state",
    ),
    CheckConstraint(
        "fence_generation >= 0",
        name="ck_billing_executions_fence_generation_nonnegative",
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
    Column("reconciliation_id", String),
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
    Column(
        "execution_outcome",
        String,
        nullable=False,
        server_default="pending",
    ),
    Column("would_pass", Boolean),
    Column("would_block_reason", String),
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
    CheckConstraint(
        "execution_outcome IN ('pending', 'succeeded', 'failed')",
        name="ck_billing_usage_items_execution_outcome",
    ),
)

billing_reconciliation_audits = Table(
    "billing_reconciliation_audits",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "usage_item_id",
        String,
        ForeignKey("billing_usage_items.id"),
        nullable=False,
    ),
    Column(
        "usage_order_id",
        String,
        ForeignKey("billing_usage_orders.id"),
        nullable=False,
    ),
    Column("idempotency_key", String, nullable=False),
    Column("request_sha256", String, nullable=False),
    Column("actor_id", String, nullable=False),
    Column("reason", Text, nullable=False),
    Column("billability", String, nullable=False),
    Column(
        "actual_input_tokens",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column(
        "actual_output_tokens",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column("charged_credits", BigInteger, nullable=False, server_default="0"),
    Column("previous_status", String, nullable=False),
    Column("resolved_status", String, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "billability IN ('billable', 'not_billable')",
        name="ck_billing_reconciliation_audits_billability",
    ),
    CheckConstraint(
        "actual_input_tokens >= 0",
        name="ck_billing_reconciliation_audits_input_nonnegative",
    ),
    CheckConstraint(
        "actual_output_tokens >= 0",
        name="ck_billing_reconciliation_audits_output_nonnegative",
    ),
    CheckConstraint(
        "charged_credits >= 0",
        name="ck_billing_reconciliation_audits_charged_nonnegative",
    ),
)

billing_rollout_settings = Table(
    "billing_rollout_settings",
    metadata,
    Column("id", String, primary_key=True),
    Column("mode", String, nullable=False, server_default="shadow"),
    Column("billing_cutover_at", DateTime(timezone=True)),
    Column("cutover_actor_id", String),
    Column("updated_by", String, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "mode IN ('off', 'shadow', 'observe', 'enforced')",
        name="ck_billing_rollout_settings_mode",
    ),
)

billing_top_up_products = Table(
    "billing_top_up_products",
    metadata,
    Column("id", String, primary_key=True),
    Column("public_id", String, nullable=False, unique=True),
    Column("name", String, nullable=False),
    Column("description", Text),
    Column("payment_amount_fen", BigInteger, nullable=False),
    Column("purchased_credits", BigInteger, nullable=False),
    Column(
        "promotional_credits",
        BigInteger,
        nullable=False,
        server_default="0",
    ),
    Column("promotional_expiry_days", Integer),
    Column("status", String, nullable=False, server_default="active"),
    Column("display_order", Integer, nullable=False, server_default="0"),
    Column("created_by", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "payment_amount_fen > 0",
        name="ck_billing_top_up_products_amount_positive",
    ),
    CheckConstraint(
        "purchased_credits > 0",
        name="ck_billing_top_up_products_purchased_positive",
    ),
    CheckConstraint(
        "promotional_credits >= 0",
        name="ck_billing_top_up_products_promotional_nonnegative",
    ),
    CheckConstraint(
        "promotional_expiry_days IS NULL OR promotional_expiry_days > 0",
        name="ck_billing_top_up_products_expiry_positive",
    ),
    CheckConstraint(
        "status IN ('active', 'disabled')",
        name="ck_billing_top_up_products_status",
    ),
)

billing_top_up_claims = Table(
    "billing_top_up_claims",
    metadata,
    Column("id", String, primary_key=True),
    Column("public_id", String, nullable=False, unique=True),
    Column(
        "wallet_id",
        String,
        ForeignKey("billing_wallets.id"),
        nullable=False,
    ),
    Column(
        "product_id",
        String,
        ForeignKey("billing_top_up_products.id"),
        nullable=False,
    ),
    Column("owner_type", String, nullable=False),
    Column("owner_id", String, nullable=False),
    Column("product_snapshot_json", Text, nullable=False),
    Column(
        "payment_amount_fen", BigInteger, nullable=False, server_default="0"
    ),
    Column("payment_channel", String, nullable=False),
    Column("payer_reference", String, nullable=False),
    Column("customer_note", Text),
    Column("submission_idempotency_key", String, nullable=False, unique=True),
    Column("submission_request_sha256", String, nullable=False),
    Column("status", String, nullable=False, server_default="pending"),
    Column("reviewed_by", String),
    Column("review_reason", Text),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("ledger_business_key", String, unique=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "owner_type = 'user'",
        name="ck_billing_top_up_claims_owner_type",
    ),
    CheckConstraint(
        "payment_amount_fen >= 0",
        name="ck_billing_top_up_claims_amount_nonnegative",
    ),
    CheckConstraint(
        "payment_channel IN ('wechat', 'alipay', 'bank', 'other')",
        name="ck_billing_top_up_claims_channel",
    ),
    CheckConstraint(
        "status IN ('pending', 'approved', 'rejected')",
        name="ck_billing_top_up_claims_status",
    ),
    CheckConstraint(
        "status = 'pending' OR (reviewed_by IS NOT NULL AND "
        "review_reason IS NOT NULL AND reviewed_at IS NOT NULL)",
        name="ck_billing_top_up_claims_review_fields",
    ),
    CheckConstraint(
        "status != 'approved' OR ledger_business_key IS NOT NULL",
        name="ck_billing_top_up_claims_approved_ledger_key",
    ),
)

billing_top_up_audits = Table(
    "billing_top_up_audits",
    metadata,
    Column("id", String, primary_key=True),
    Column(
        "claim_id",
        String,
        ForeignKey("billing_top_up_claims.id"),
        nullable=False,
    ),
    Column("action", String, nullable=False),
    Column("actor_id", String, nullable=False),
    Column("reason", Text, nullable=False),
    Column("idempotency_key", String, nullable=False, unique=True),
    Column("request_sha256", String, nullable=False),
    Column("payment_amount_fen", BigInteger, nullable=False),
    Column("purchased_credits", BigInteger, nullable=False),
    Column(
        "promotional_credits", BigInteger, nullable=False, server_default="0"
    ),
    Column("claim_snapshot_json", Text, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint(
        "action IN ('submitted', 'approved', 'rejected')",
        name="ck_billing_top_up_audits_action",
    ),
    CheckConstraint(
        "payment_amount_fen >= 0 AND purchased_credits >= 0 "
        "AND promotional_credits >= 0",
        name="ck_billing_top_up_audits_amounts_nonnegative",
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
    "idx_open_api_invocations_billing_usage_order",
    open_api_invocations.c.billing_usage_order_id,
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
    "idx_billing_ledger_entries_usage_ranking",
    billing_ledger_entries.c.event_type,
    billing_ledger_entries.c.status,
    billing_ledger_entries.c.created_at.desc(),
    billing_ledger_entries.c.wallet_id,
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
    "uq_billing_usage_items_reconciliation_id",
    billing_usage_items.c.reconciliation_id,
    unique=True,
)
Index(
    "uq_billing_usage_items_order_item_key",
    billing_usage_items.c.usage_order_id,
    billing_usage_items.c.item_key,
    unique=True,
)
Index(
    "uq_billing_reconciliation_audits_idempotency",
    billing_reconciliation_audits.c.idempotency_key,
    unique=True,
)
Index(
    "idx_billing_reconciliation_audits_item_created",
    billing_reconciliation_audits.c.usage_item_id,
    billing_reconciliation_audits.c.created_at.desc(),
)
Index(
    "idx_billing_top_up_products_status_order",
    billing_top_up_products.c.status,
    billing_top_up_products.c.display_order,
)
Index(
    "idx_billing_top_up_claims_owner_created",
    billing_top_up_claims.c.owner_type,
    billing_top_up_claims.c.owner_id,
    billing_top_up_claims.c.created_at.desc(),
)
Index(
    "idx_billing_top_up_claims_status_created",
    billing_top_up_claims.c.status,
    billing_top_up_claims.c.created_at.asc(),
)
Index(
    "idx_billing_top_up_audits_claim_created",
    billing_top_up_audits.c.claim_id,
    billing_top_up_audits.c.created_at.asc(),
)
Index(
    "idx_billing_executions_payer_created",
    billing_executions.c.payer_user_id,
    billing_executions.c.created_at.desc(),
)
Index(
    "idx_billing_executions_source",
    billing_executions.c.source_type,
    billing_executions.c.source_id,
)
Index(
    "idx_billing_executions_state_lease",
    billing_executions.c.state,
    billing_executions.c.lease_expires_at,
)


def create_all(engine: Engine) -> None:
    """Create all known durable tables and indexes."""
    metadata.create_all(engine)
    _ensure_user_overdraft_columns(engine)
    _ensure_pricing_catalog_revision(engine)
    _ensure_pricing_audit_immutable(engine)
    _ensure_official_price_candidate_immutable(engine)
    _ensure_official_price_candidate_evidence_columns(engine)
    _ensure_pricing_collection_active_digest_index(engine)
    _ensure_pricing_model_mapping_columns(engine)
    _ensure_open_api_publication_binding_columns(engine)
    _ensure_knowledge_metadata_columns(engine)
    _ensure_billing_usage_order_columns(engine)
    _ensure_expert_team_billing_columns(engine)
    _ensure_open_api_billing_columns(engine)
    _ensure_billing_bigint_columns(engine)
    _ensure_billing_constraints(engine)
    _ensure_reconciliation_audit_immutable(engine)
    _ensure_top_up_audit_immutable(engine)
    _backfill_personal_wallets(engine)


def _ensure_user_overdraft_columns(engine: Engine) -> None:
    """Add private overdraft state to legacy databases exactly once."""
    inspector = inspect(engine)
    user_columns = {
        column["name"] for column in inspector.get_columns("users")
    }
    wallet_columns = {
        column["name"] for column in inspector.get_columns("billing_wallets")
    }
    created_capability = "billing_overdraft_enabled" not in user_columns
    boolean_type = (
        "BOOLEAN" if engine.dialect.name == "postgresql" else "INTEGER"
    )
    false_literal = "FALSE" if engine.dialect.name == "postgresql" else "0"
    with engine.begin() as conn:
        if created_capability:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN billing_overdraft_enabled "
                    f"{boolean_type} NOT NULL DEFAULT {false_literal}"
                )
            )
            conn.execute(
                text(
                    "UPDATE users SET billing_overdraft_enabled = "
                    f"{'TRUE' if engine.dialect.name == 'postgresql' else '1'} "
                    "WHERE username = 'szzz_admin' AND role = 'admin'"
                )
            )
        if "debt_credits" not in wallet_columns:
            conn.execute(
                text(
                    "ALTER TABLE billing_wallets ADD COLUMN debt_credits "
                    "BIGINT NOT NULL DEFAULT 0 CHECK (debt_credits >= 0)"
                )
            )
        if "held_overdraft_credits" not in wallet_columns:
            conn.execute(
                text(
                    "ALTER TABLE billing_wallets ADD COLUMN "
                    "held_overdraft_credits BIGINT NOT NULL DEFAULT 0 "
                    "CHECK (held_overdraft_credits >= 0)"
                )
            )


def _ensure_pricing_collection_active_digest_index(engine: Engine) -> None:
    """Deduplicate legacy active jobs before installing the partial index."""
    with engine.begin() as conn:
        rows = list(
            conn.execute(
                select(
                    billing_pricing_collection_jobs.c.id,
                    billing_pricing_collection_jobs.c.inventory_digest,
                )
                .where(
                    billing_pricing_collection_jobs.c.status.in_(
                        ("pending", "running")
                    )
                )
                .order_by(
                    billing_pricing_collection_jobs.c.created_at.desc()
                )
            ).mappings()
        )
        seen: set[str] = set()
        duplicates: list[str] = []
        for row in rows:
            digest = str(row["inventory_digest"])
            if digest in seen:
                duplicates.append(str(row["id"]))
            else:
                seen.add(digest)
        if duplicates:
            conn.execute(
                update(billing_pricing_collection_jobs)
                .where(billing_pricing_collection_jobs.c.id.in_(duplicates))
                .values(
                    status="failed",
                    error_summary="superseded during active-job migration",
                    finished_at=func.now(),
                )
            )
    billing_pricing_collection_active_digest_index.create(
        bind=engine, checkfirst=True
    )


def _ensure_official_price_candidate_evidence_columns(
    engine: Engine,
) -> None:
    """Upgrade price candidates created before evidence classification."""
    columns = {
        column["name"]
        for column in inspect(engine).get_columns(
            "billing_official_price_candidates"
        )
    }
    definitions = {
        "evidence_level": "VARCHAR NOT NULL DEFAULT 'official_verified'",
        "evidence_excerpt": "TEXT",
        "collector_version": "VARCHAR NOT NULL DEFAULT 'bundled'",
        "ai_model": "VARCHAR",
        "prompt_version": "VARCHAR",
        "confidence_decimal": "VARCHAR",
        "default_multiplier_decimal": "VARCHAR",
    }
    with engine.begin() as conn:
        for name, definition in definitions.items():
            if name not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE billing_official_price_candidates "
                        f"ADD COLUMN {name} {definition}"
                    )
                )


def _ensure_pricing_catalog_revision(engine: Engine) -> None:
    """Add optimistic catalog revision to databases created before pricing UI."""
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("billing_price_catalogs")
    }
    if "revision" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE billing_price_catalogs ADD COLUMN revision "
                "INTEGER NOT NULL DEFAULT 0"
            )
        )


def _ensure_pricing_audit_immutable(engine: Engine) -> None:
    """Reject changes to append-only pricing audit evidence."""
    if engine.dialect.name == "sqlite":
        statements = (
            "CREATE TRIGGER IF NOT EXISTS billing_pricing_audits_no_update "
            "BEFORE UPDATE ON billing_pricing_audits BEGIN SELECT RAISE(ABORT, "
            "'billing pricing audits are immutable'); END",
            "CREATE TRIGGER IF NOT EXISTS billing_pricing_audits_no_delete "
            "BEFORE DELETE ON billing_pricing_audits BEGIN SELECT RAISE(ABORT, "
            "'billing pricing audits are immutable'); END",
        )
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))
        return
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION billing_pricing_audits_immutable() "
                "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
                "'billing pricing audits are immutable'; END $$"
            )
        )
        for operation in ("UPDATE", "DELETE"):
            trigger = f"billing_pricing_audits_no_{operation.lower()}"
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger "
                    f"WHERE tgname = '{trigger}' AND tgrelid = "
                    "'billing_pricing_audits'::regclass) THEN "
                    f"CREATE TRIGGER {trigger} BEFORE {operation} ON "
                    "billing_pricing_audits FOR EACH ROW EXECUTE FUNCTION "
                    "billing_pricing_audits_immutable(); END IF; END $$"
                )
            )


def _ensure_official_price_candidate_immutable(engine: Engine) -> None:
    """Reject changes to append-only official price evidence."""
    table_name = "billing_official_price_candidates"
    message = "official price candidates are immutable"
    if engine.dialect.name == "sqlite":
        statements = (
            f"CREATE TRIGGER IF NOT EXISTS {table_name}_no_update "
            f"BEFORE UPDATE ON {table_name} BEGIN SELECT RAISE(ABORT, "
            f"'{message}'); END",
            f"CREATE TRIGGER IF NOT EXISTS {table_name}_no_delete "
            f"BEFORE DELETE ON {table_name} BEGIN SELECT RAISE(ABORT, "
            f"'{message}'); END",
        )
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))
        return
    if engine.dialect.name != "postgresql":
        return
    function_name = "billing_official_price_candidates_immutable"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE OR REPLACE FUNCTION {function_name}() RETURNS "
                "trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
                f"'{message}'; END $$"
            )
        )
        for operation in ("UPDATE", "DELETE"):
            trigger = f"{table_name}_no_{operation.lower()}"
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger "
                    f"WHERE tgname = '{trigger}' AND tgrelid = "
                    f"'{table_name}'::regclass) THEN CREATE TRIGGER "
                    f"{trigger} BEFORE {operation} ON {table_name} FOR EACH "
                    f"ROW EXECUTE FUNCTION {function_name}(); END IF; END $$"
                )
            )


def _ensure_pricing_model_mapping_columns(engine: Engine) -> None:
    """Add explicit official-provider identity to legacy mappings."""
    table_name = "billing_pricing_model_mappings"
    columns = {
        column["name"] for column in inspect(engine).get_columns(table_name)
    }
    if "official_provider_id" in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER TABLE {table_name} ADD COLUMN "
                "official_provider_id VARCHAR"
            )
        )
        conn.execute(
            text(
                f"UPDATE {table_name} SET official_provider_id = provider_id "
                "WHERE official_provider_id IS NULL"
            )
        )


def _ensure_reconciliation_audit_immutable(engine: Engine) -> None:
    """Reject updates and deletes against the append-only admin audit."""
    if engine.dialect.name == "sqlite":
        statements = (
            "CREATE TRIGGER IF NOT EXISTS "
            "billing_reconciliation_audits_no_update BEFORE UPDATE ON "
            "billing_reconciliation_audits BEGIN SELECT RAISE(ABORT, "
            "'billing reconciliation audits are immutable'); END",
            "CREATE TRIGGER IF NOT EXISTS "
            "billing_reconciliation_audits_no_delete BEFORE DELETE ON "
            "billing_reconciliation_audits BEGIN SELECT RAISE(ABORT, "
            "'billing reconciliation audits are immutable'); END",
        )
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))
        return
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION "
                "billing_reconciliation_audits_immutable() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
                "'billing reconciliation audits are immutable'; END $$",
            ),
        )
        for operation in ("UPDATE", "DELETE"):
            trigger = f"billing_reconciliation_audits_no_{operation.lower()}"
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger "
                    f"WHERE tgname = '{trigger}' AND tgrelid = "
                    "'billing_reconciliation_audits'::regclass) THEN "
                    f"CREATE TRIGGER {trigger} BEFORE {operation} ON "
                    "billing_reconciliation_audits FOR EACH ROW EXECUTE "
                    "FUNCTION billing_reconciliation_audits_immutable(); "
                    "END IF; END $$",
                ),
            )


def _ensure_top_up_audit_immutable(engine: Engine) -> None:
    """Reject updates and deletes against manual top-up audit rows."""
    if engine.dialect.name == "sqlite":
        statements = (
            "CREATE TRIGGER IF NOT EXISTS billing_top_up_audits_no_update "
            "BEFORE UPDATE ON billing_top_up_audits BEGIN SELECT RAISE(ABORT, "
            "'billing top-up audits are immutable'); END",
            "CREATE TRIGGER IF NOT EXISTS billing_top_up_audits_no_delete "
            "BEFORE DELETE ON billing_top_up_audits BEGIN SELECT RAISE(ABORT, "
            "'billing top-up audits are immutable'); END",
        )
        with engine.begin() as conn:
            for statement in statements:
                conn.execute(text(statement))
        return
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE OR REPLACE FUNCTION billing_top_up_audits_immutable() "
                "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
                "'billing top-up audits are immutable'; END $$",
            ),
        )
        for operation in ("UPDATE", "DELETE"):
            trigger = f"billing_top_up_audits_no_{operation.lower()}"
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger "
                    f"WHERE tgname = '{trigger}' AND tgrelid = "
                    "'billing_top_up_audits'::regclass) THEN "
                    f"CREATE TRIGGER {trigger} BEFORE {operation} ON "
                    "billing_top_up_audits FOR EACH ROW EXECUTE FUNCTION "
                    "billing_top_up_audits_immutable(); END IF; END $$",
                ),
            )


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
    inspector = inspect(engine)
    pending: list[tuple[str, str]] = []
    for table_name, column_names in columns.items():
        actual = {
            str(column["name"]): column["type"]
            for column in inspector.get_columns(table_name)
        }
        pending.extend(
            (table_name, column_name)
            for column_name in column_names
            if column_name in actual
            and not isinstance(actual[column_name], BigInteger)
        )
    if not pending:
        return
    with engine.begin() as conn:
        for table_name, column_name in pending:
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


def _ensure_expert_team_billing_columns(engine: Engine) -> None:
    """Add resumable billing state to existing expert-team runs."""
    inspector = inspect(engine)
    if "expert_team_runs" not in inspector.get_table_names():
        return
    existing = {
        column["name"] for column in inspector.get_columns("expert_team_runs")
    }
    additions = {
        "next_member_key": "VARCHAR",
        "required_credits": "BIGINT",
        "billing_usage_order_id": "VARCHAR",
    }
    with engine.begin() as conn:
        for column, column_type in additions.items():
            if column not in existing:
                conn.execute(
                    text(
                        f"ALTER TABLE expert_team_runs ADD COLUMN {column} "
                        f"{column_type}",
                    ),
                )


def _ensure_open_api_billing_columns(engine: Engine) -> None:
    """Upgrade OpenAPI billing data without changing ledger or token rows."""
    datetime_type = str(
        DateTime(timezone=True).compile(dialect=engine.dialect),
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
            "execution_owner_token": (
                "ALTER TABLE open_api_invocations ADD COLUMN "
                "execution_owner_token VARCHAR"
            ),
            "execution_fence_generation": (
                "ALTER TABLE open_api_invocations ADD COLUMN "
                "execution_fence_generation BIGINT NOT NULL DEFAULT 0"
            ),
            "execution_claimed_at": (
                "ALTER TABLE open_api_invocations ADD COLUMN "
                f"execution_claimed_at {datetime_type}"
            ),
            "execution_lease_expires_at": (
                "ALTER TABLE open_api_invocations ADD COLUMN "
                f"execution_lease_expires_at {datetime_type}"
            ),
            "expert_team_run_id": (
                "ALTER TABLE open_api_invocations ADD COLUMN "
                "expert_team_run_id VARCHAR"
            ),
            "terminal_event_json": (
                "ALTER TABLE open_api_invocations ADD COLUMN "
                "terminal_event_json TEXT"
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
            "reconciliation_id": (
                "ALTER TABLE billing_usage_items ADD COLUMN "
                "reconciliation_id VARCHAR"
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
            "execution_outcome": (
                "ALTER TABLE billing_usage_items ADD COLUMN "
                "execution_outcome VARCHAR NOT NULL DEFAULT 'pending'"
            ),
            "would_pass": (
                "ALTER TABLE billing_usage_items ADD COLUMN "
                "would_pass BOOLEAN"
            ),
            "would_block_reason": (
                "ALTER TABLE billing_usage_items ADD COLUMN "
                "would_block_reason VARCHAR"
            ),
        },
    }
    inspector = inspect(engine)
    existing_table_names = set(inspector.get_table_names())
    execution_outcome_added = False
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
                    if (
                        table_name == "billing_usage_items"
                        and column_name == "execution_outcome"
                    ):
                        execution_outcome_added = True

    if execution_outcome_added:
        _backfill_legacy_execution_outcomes(engine)

    _backfill_reconciliation_ids(engine)

    _validate_open_api_billing_history(engine)
    if (
        engine.dialect.name == "sqlite"
        and _sqlite_open_api_billing_rebuild_required(engine)
    ):
        _rebuild_sqlite_open_api_billing_tables(engine)
    elif engine.dialect.name == "postgresql":
        _ensure_postgresql_open_api_billing_constraints(engine)
    _ensure_open_api_billing_indexes(engine)


def _backfill_legacy_execution_outcomes(engine: Engine) -> None:
    """Derive outcome only for rows predating the outcome column."""
    compact_evidence = "REPLACE(supplier_evidence_json, ' ', '')"
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE billing_usage_items SET execution_outcome = CASE "
                "WHEN status = 'captured' THEN 'succeeded' "
                "WHEN status = 'released' THEN 'failed' "
                "WHEN status = 'reconciling' AND ("
                f"{compact_evidence} LIKE "
                '\'%"response_class":"success"%\' OR '
                f"{compact_evidence} LIKE "
                '\'%"response_class":"success_without_official_usage"%\''
                ") THEN 'succeeded' ELSE 'pending' END",
            ),
        )


def _backfill_reconciliation_ids(engine: Engine) -> None:
    """Give legacy unresolved items an opaque durable operator handle."""
    with engine.begin() as conn:
        item_ids = conn.execute(
            select(billing_usage_items.c.id).where(
                billing_usage_items.c.status == "reconciling",
                billing_usage_items.c.billability == "unknown",
                billing_usage_items.c.reconciliation_id.is_(None),
            ),
        ).scalars()
        for item_id in item_ids:
            conn.execute(
                update(billing_usage_items)
                .where(billing_usage_items.c.id == item_id)
                .values(reconciliation_id=str(uuid4())),
            )


def _validate_open_api_billing_history(engine: Engine) -> None:
    """Reject unsafe legacy values before adding financial constraints."""
    violations = {
        "open_api_invocations": (
            "quoted_credits IS NULL OR quoted_credits < 0 OR "
            "captured_credits IS NULL OR captured_credits < 0 OR "
            "released_credits IS NULL OR released_credits < 0 OR "
            "execution_fence_generation IS NULL OR "
            "execution_fence_generation < 0"
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
            "('unknown', 'billable', 'not_billable') OR "
            "execution_outcome IS NULL OR execution_outcome NOT IN "
            "('pending', 'succeeded', 'failed')"
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
            "ck_open_api_invocations_fence_generation_nonnegative",
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
            "ck_billing_usage_items_execution_outcome",
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
        "CREATE INDEX IF NOT EXISTS "
        "idx_open_api_invocations_billing_usage_order "
        "ON open_api_invocations (billing_usage_order_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_usage_orders_business "
        "ON billing_usage_orders (business_key)",
        "CREATE INDEX IF NOT EXISTS idx_billing_ledger_entries_usage_ranking "
        "ON billing_ledger_entries "
        "(event_type, status, created_at DESC, wallet_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_usage_orders_source "
        "ON billing_usage_orders (source_type, source_id)",
        "CREATE INDEX IF NOT EXISTS idx_billing_usage_orders_wallet_status "
        "ON billing_usage_orders (wallet_id, status, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_billing_usage_orders_supplier_reference "  # noqa: E501
        "ON billing_usage_orders (supplier_reference)",
        "CREATE INDEX IF NOT EXISTS idx_billing_usage_items_order "
        "ON billing_usage_items (usage_order_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_billing_usage_items_reconciliation_id "
        "ON billing_usage_items (reconciliation_id)",
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
            "billing_wallets",
            "ck_billing_wallets_debt_nonnegative",
            "c",
            "CHECK (debt_credits >= 0)",
        ),
        (
            "billing_wallets",
            "ck_billing_wallets_held_overdraft_nonnegative",
            "c",
            "CHECK (held_overdraft_credits >= 0)",
        ),
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
            "open_api_invocations",
            "ck_open_api_invocations_fence_generation_nonnegative",
            "c",
            "CHECK (execution_fence_generation >= 0)",
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
            "billing_usage_items",
            "ck_billing_usage_items_execution_outcome",
            "c",
            "CHECK (execution_outcome IN ('pending', 'succeeded', 'failed'))",
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
            validated = conn.scalar(
                text(
                    "SELECT pc.convalidated FROM pg_constraint AS pc "
                    "JOIN pg_class AS relation ON relation.oid = pc.conrelid "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = current_schema() AND "
                    "relation.relname = 'billing_credit_lots' AND "
                    "pc.conname = "
                    "'ck_billing_credit_lots_purchased_no_expiry' AND "
                    "pc.contype = 'c'",
                ),
            )
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
            if validated is not True:
                conn.execute(
                    text(
                        "ALTER TABLE billing_credit_lots "
                        "VALIDATE CONSTRAINT "
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
