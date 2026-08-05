# -*- coding: utf-8 -*-
"""SQLite Database layer for Multi-User architecture."""
import sqlite3
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any

from ..constant import SECRET_DIR

DB_PATH = SECRET_DIR / "qwenpaw.db"

# Thread-local storage for sqlite connections
_local = threading.local()


def _configure_connection(conn: sqlite3.Connection) -> None:
    """Apply connection-local SQLite settings used by the web app."""
    conn.row_factory = sqlite3.Row
    # WAL allows readers during writes, which is important for chat polling.
    conn.execute("PRAGMA journal_mode=WAL")
    # Keep transient write contention from becoming immediate 500s.
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")

def get_db() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn"):
        # We use check_same_thread=False because FastAPI might use thread pools
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _configure_connection(_local.conn)
    return _local.conn

def init_db():
    """Initialize the SQLite schema."""
    # Ensure directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. User Connections table (for MCP Connectors)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_connections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            connector_key TEXT NOT NULL,
            oauth_tokens TEXT,
            custom_envs TEXT,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE(user_id, connector_key)
        )
    ''')
    # 3. Capability Registry (Global Market for MCP, Skills, Tools)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS capability_registry (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            manifest TEXT NOT NULL,
            is_public BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 4. User Capabilities (User Subscriptions)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_capabilities (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            capability_id TEXT NOT NULL,
            enabled BOOLEAN DEFAULT 1,
            credentials TEXT,
            preferences TEXT,
            subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (capability_id) REFERENCES capability_registry (id),
            UNIQUE(user_id, capability_id)
        )
    ''')
    
    # 5. Chats table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # 6. Messages table (used by AgentScope Session)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT,
            meta TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats (id)
        )
    ''')
    
    # 7. Token Usage Logs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS token_usage_logs (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            model_name TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')

    # 8. Expert team templates
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expert_team_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT 'all',
            tags TEXT NOT NULL DEFAULT '[]',
            icon TEXT DEFAULT '',
            enabled BOOLEAN DEFAULT 1,
            leader_agent_id TEXT NOT NULL DEFAULT 'default',
            members TEXT NOT NULL DEFAULT '[]',
            workflow TEXT NOT NULL DEFAULT '[]',
            usage_count INTEGER DEFAULT 0,
            source TEXT DEFAULT 'custom',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 9. Expert team root runs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expert_team_runs (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            root_chat_id TEXT NOT NULL,
            root_session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            state TEXT DEFAULT 'pending',
            input_text TEXT DEFAULT '',
            final_summary TEXT,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES expert_team_templates (id)
        )
    ''')

    # 10. Expert team member runs
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expert_team_member_runs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            member_key TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            state TEXT DEFAULT 'pending',
            stage_index INTEGER DEFAULT 0,
            task_id TEXT,
            child_session_id TEXT,
            input_text TEXT DEFAULT '',
            output_text TEXT,
            error TEXT,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (run_id) REFERENCES expert_team_runs (id)
        )
    ''')

    # 11. Open API publications
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS open_api_publications (
            id TEXT PRIMARY KEY,
            public_id TEXT UNIQUE NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            bound_user_id TEXT NOT NULL,
            knowledge_base_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'enabled',
            allowed_scopes TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    publication_columns = {
        str(row[1])
        for row in cursor.execute("PRAGMA table_info(open_api_publications)").fetchall()
    }
    if "bound_user_id" not in publication_columns:
        cursor.execute(
            "ALTER TABLE open_api_publications ADD COLUMN bound_user_id TEXT",
        )
    if "knowledge_base_id" not in publication_columns:
        cursor.execute(
            "ALTER TABLE open_api_publications ADD COLUMN knowledge_base_id TEXT",
        )
    cursor.execute(
        """
        UPDATE open_api_publications
        SET bound_user_id = owner_user_id
        WHERE bound_user_id IS NULL OR bound_user_id = ''
        """,
    )
    cursor.execute(
        """
        UPDATE open_api_publications
        SET knowledge_base_id = 'openapi-' || id
        WHERE knowledge_base_id IS NULL OR knowledge_base_id = ''
        """,
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_open_api_publications_knowledge_base
        ON open_api_publications (knowledge_base_id)
        """,
    )

    # 12. Open API external apps
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS open_api_external_apps (
            id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'enabled',
            ip_allowlist TEXT NOT NULL DEFAULT '[]',
            quota_policy TEXT NOT NULL DEFAULT '{}',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 13. Open API keys
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS open_api_keys (
            id TEXT PRIMARY KEY,
            app_id TEXT NOT NULL,
            publication_id TEXT NOT NULL,
            key_hash TEXT UNIQUE NOT NULL,
            key_prefix TEXT NOT NULL,
            key_suffix TEXT NOT NULL,
            scopes TEXT NOT NULL DEFAULT '[]',
            status TEXT DEFAULT 'active',
            expires_at TEXT,
            last_used_at TEXT,
            last_used_ip TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (app_id) REFERENCES open_api_external_apps (id),
            FOREIGN KEY (publication_id) REFERENCES open_api_publications (id)
        )
    ''')

    # 14. Open API invocations
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS open_api_invocations (
            id TEXT PRIMARY KEY,
            app_id TEXT NOT NULL,
            publication_id TEXT NOT NULL,
            api_key_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            chat_id TEXT,
            external_session_id TEXT,
            external_user_id TEXT,
            status TEXT NOT NULL,
            status_code INTEGER,
            latency_ms INTEGER DEFAULT 0,
            token_summary TEXT NOT NULL DEFAULT '{}',
            error_summary TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (app_id) REFERENCES open_api_external_apps (id),
            FOREIGN KEY (publication_id) REFERENCES open_api_publications (id),
            FOREIGN KEY (api_key_id) REFERENCES open_api_keys (id)
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chats_user_agent_updated
        ON chats (user_id, agent_id, updated_at DESC)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chats_session_user_channel_agent
        ON chats (session_id, user_id, channel, agent_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_messages_chat_timestamp
        ON messages (chat_id, timestamp ASC)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_expert_team_runs_user_state_updated
        ON expert_team_runs (user_id, state, updated_at DESC)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_expert_team_member_runs_run_state
        ON expert_team_member_runs (run_id, state)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_open_api_publications_target
        ON open_api_publications (target_type, target_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_open_api_external_apps_owner_status
        ON open_api_external_apps (owner_user_id, status)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_open_api_keys_app_publication
        ON open_api_keys (app_id, publication_id)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_open_api_invocations_publication_created
        ON open_api_invocations (publication_id, created_at DESC)
    ''')
    
    conn.commit()

# Automatically initialize tables
init_db()
