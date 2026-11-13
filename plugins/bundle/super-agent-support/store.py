# -*- coding: utf-8 -*-
"""Plugin-owned durable SQLite state."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class StateStore:
    """Durable records for devices, packages, tasks, and credentials."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS pairings (
                    code_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    token_hash TEXT,
                    display_name TEXT NOT NULL,
                    runner_version TEXT NOT NULL,
                    protocol_version TEXT NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'windows-x64',
                    status TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL DEFAULT '[]',
                    last_seen INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
                CREATE TABLE IF NOT EXISTS packages (
                    package_id TEXT NOT NULL,
                    package_version TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    signer_id TEXT NOT NULL,
                    descriptor_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    status TEXT NOT NULL,
                    registered_at INTEGER NOT NULL,
                    PRIMARY KEY(package_id, package_version)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_packages_active_capability
                    ON packages(capability_id) WHERE status='active';
                CREATE TABLE IF NOT EXISTS public_components (
                    component_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS public_component_uploads (
                    upload_id TEXT PRIMARY KEY,
                    component_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    component_version TEXT NOT NULL,
                    object_key TEXT NOT NULL UNIQUE,
                    artifact_url TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    md5 TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    completed_at INTEGER,
                    registered_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS public_component_variants (
                    component_id TEXT NOT NULL REFERENCES public_components(component_id),
                    platform TEXT NOT NULL,
                    component_version TEXT NOT NULL,
                    availability TEXT NOT NULL,
                    provides_json TEXT NOT NULL,
                    descriptor_json TEXT NOT NULL DEFAULT '{}',
                    signer_id TEXT NOT NULL DEFAULT '',
                    signature TEXT NOT NULL DEFAULT '',
                    updated_by TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(component_id, platform)
                );
                CREATE TABLE IF NOT EXISTS component_registry_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    registry_version INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO component_registry_meta(
                    singleton,registry_version,updated_at
                ) VALUES(1,0,0);
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    invocation_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    checkpoint_json TEXT,
                    result_json TEXT,
                    error_json TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(user_id, agent_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, updated_at);
                CREATE TABLE IF NOT EXISTS task_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(task_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS credentials (
                    credential_ref TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    ciphertext BLOB NOT NULL,
                    scopes_json TEXT NOT NULL,
                    agent_ids_json TEXT NOT NULL,
                    installation_ids_json TEXT NOT NULL DEFAULT '[]',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS credential_slots (
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    installation_id TEXT NOT NULL,
                    credential_scope TEXT NOT NULL,
                    credential_slot TEXT NOT NULL,
                    credential_ref TEXT NOT NULL REFERENCES credentials(credential_ref)
                        ON DELETE CASCADE,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(
                        tenant_id,user_id,agent_id,release_id,installation_id,
                        credential_scope,credential_slot
                    )
                );
                CREATE INDEX IF NOT EXISTS idx_credential_slots_ref
                    ON credential_slots(credential_ref);
                CREATE TABLE IF NOT EXISTS temporary_resources (
                    resource_ref TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    installation_id TEXT NOT NULL,
                    invocation_id TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    max_size_bytes INTEGER NOT NULL,
                    size_bytes INTEGER,
                    sha256 TEXT,
                    status TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_temporary_resources_scope
                    ON temporary_resources(
                        tenant_id,user_id,agent_id,installation_id,expires_at
                    );
                CREATE TABLE IF NOT EXISTS local_file_refs (
                    local_file_ref TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'local',
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    installation_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    invocation_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    last_modified_ms INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_local_file_refs_scope
                    ON local_file_refs(user_id,agent_id,installation_id,device_id);
                CREATE TABLE IF NOT EXISTS managed_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'local',
                    user_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_managed_artifacts_user
                    ON managed_artifacts(tenant_id,user_id,created_at DESC);
                """,
            )
            columns = {
                row[1]
                for row in db.execute("PRAGMA table_info(devices)").fetchall()
            }
            if "token_hash" not in columns:
                db.execute("ALTER TABLE devices ADD COLUMN token_hash TEXT")
            if "platform" not in columns:
                db.execute(
                    "ALTER TABLE devices ADD COLUMN platform TEXT NOT NULL DEFAULT 'windows-x64'",
                )
            component_columns = {
                row[1]
                for row in db.execute(
                    "PRAGMA table_info(public_component_variants)",
                ).fetchall()
            }
            for name, definition in (
                ("descriptor_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("signer_id", "TEXT NOT NULL DEFAULT ''"),
                ("signature", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in component_columns:
                    db.execute(
                        f"ALTER TABLE public_component_variants ADD COLUMN {name} {definition}",
                    )
            disabled_legacy_components = db.execute(
                """
                UPDATE public_component_variants
                SET availability='disabled'
                WHERE availability='available' AND descriptor_json='{}'
                """,
            ).rowcount
            if disabled_legacy_components:
                db.execute(
                    """
                    UPDATE component_registry_meta
                    SET registry_version=registry_version+1,updated_at=?
                    WHERE singleton=1
                    """,
                    (int(time.time()),),
                )
            credential_columns = {
                row[1]
                for row in db.execute(
                    "PRAGMA table_info(credentials)",
                ).fetchall()
            }
            if "installation_ids_json" not in credential_columns:
                db.execute(
                    "ALTER TABLE credentials ADD COLUMN installation_ids_json TEXT NOT NULL DEFAULT '[]'",
                )
            task_columns = {
                row[1]
                for row in db.execute("PRAGMA table_info(tasks)").fetchall()
            }
            for name, definition in (
                ("tenant_id", "TEXT NOT NULL DEFAULT 'local'"),
                ("session_id", "TEXT NOT NULL DEFAULT ''"),
                ("installation_id", "TEXT NOT NULL DEFAULT ''"),
                ("release_id", "TEXT NOT NULL DEFAULT ''"),
                ("local_file_bindings_json", "TEXT NOT NULL DEFAULT '{}'"),
            ):
                if name not in task_columns:
                    db.execute(
                        f"ALTER TABLE tasks ADD COLUMN {name} {definition}",
                    )
            local_file_columns = {
                row[1]
                for row in db.execute(
                    "PRAGMA table_info(local_file_refs)",
                ).fetchall()
            }
            if "tenant_id" not in local_file_columns:
                db.execute(
                    "ALTER TABLE local_file_refs "
                    "ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'local'",
                )
            managed_artifact_columns = {
                row[1]
                for row in db.execute(
                    "PRAGMA table_info(managed_artifacts)",
                ).fetchall()
            }
            if "tenant_id" not in managed_artifact_columns:
                db.execute(
                    "ALTER TABLE managed_artifacts "
                    "ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'local'",
                )
            db.execute(
                "UPDATE tasks SET status='awaiting_input' WHERE status='waiting_for_input'",
            )

    def create_pairing(self, user_id: str, ttl_seconds: int = 300) -> str:
        code = "-".join(
            (secrets.token_hex(2).upper(), secrets.token_hex(2).upper()),
        )
        digest = hashlib.sha256(code.encode()).hexdigest()
        now = int(time.time())
        with self._lock, self._connect() as db:
            db.execute(
                "DELETE FROM pairings WHERE expires_at <= ? OR used_at IS NOT NULL",
                (now,),
            )
            db.execute(
                "INSERT INTO pairings(code_hash,user_id,expires_at) VALUES(?,?,?)",
                (digest, user_id, now + ttl_seconds),
            )
        return code

    def consume_pairing(self, code: str) -> str | None:
        digest = hashlib.sha256(code.encode()).hexdigest()
        now = int(time.time())
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT user_id,expires_at,used_at FROM pairings WHERE code_hash=?",
                (digest,),
            ).fetchone()
            if (
                row is None
                or row["used_at"] is not None
                or row["expires_at"] <= now
            ):
                return None
            changed = db.execute(
                "UPDATE pairings SET used_at=? WHERE code_hash=? AND used_at IS NULL",
                (now, digest),
            ).rowcount
            return str(row["user_id"]) if changed == 1 else None

    def upsert_device(
        self,
        *,
        device_id: str,
        user_id: str,
        display_name: str,
        runner_version: str,
        protocol_version: str,
        platform: str = "windows-x64",
        device_token: str | None = None,
        status: str = "online",
        capabilities: list[dict[str, Any]] | None = None,
    ) -> None:
        now = int(time.time())
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO devices(device_id,user_id,token_hash,display_name,runner_version,
                    protocol_version,platform,status,capabilities_json,last_seen)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET
                    user_id=excluded.user_id,
                    token_hash=COALESCE(excluded.token_hash,devices.token_hash),
                    display_name=excluded.display_name,
                    runner_version=excluded.runner_version,
                    protocol_version=excluded.protocol_version,
                    platform=excluded.platform,
                    status=excluded.status,
                    capabilities_json=CASE WHEN excluded.capabilities_json='[]'
                        THEN devices.capabilities_json ELSE excluded.capabilities_json END,
                    last_seen=excluded.last_seen
                """,
                (
                    device_id,
                    user_id,
                    hashlib.sha256(device_token.encode()).hexdigest()
                    if device_token
                    else None,
                    display_name,
                    runner_version,
                    protocol_version,
                    platform,
                    status,
                    _json(capabilities or []),
                    now,
                ),
            )

    def authenticate_device(
        self,
        device_id: str,
        device_token: str,
    ) -> dict[str, Any] | None:
        digest = hashlib.sha256(device_token.encode()).hexdigest()
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM devices WHERE device_id=? AND token_hash=?",
                (device_id, digest),
            ).fetchone()
        return self._device(row) if row is not None else None

    def update_device_capabilities(
        self,
        device_id: str,
        capabilities: list[dict[str, Any]],
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE devices SET capabilities_json=?,last_seen=?,status='online' WHERE device_id=?",
                (_json(capabilities), int(time.time()), device_id),
            )

    def set_device_status(self, device_id: str, status: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE devices SET status=?,last_seen=? WHERE device_id=?",
                (status, int(time.time()), device_id),
            )

    def list_devices(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM devices WHERE user_id=? ORDER BY last_seen DESC",
                (user_id,),
            ).fetchall()
        return [self._device(row) for row in rows]

    def get_device_for_user(
        self,
        device_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM devices WHERE device_id=? AND user_id=?",
                (device_id, user_id),
            ).fetchone()
        return self._device(row) if row is not None else None

    @staticmethod
    def _device(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result.pop("token_hash", None)
        result["capabilities"] = json.loads(result.pop("capabilities_json"))
        return result

    def register_package(
        self,
        descriptor: dict[str, Any],
        *,
        signer_id: str,
        signature: str,
    ) -> None:
        now = int(time.time())
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE packages SET status='superseded' WHERE capability_id=? AND status='active'",
                (descriptor["capability_id"],),
            )
            db.execute(
                """
                INSERT INTO packages(package_id,package_version,capability_id,signer_id,
                    descriptor_json,signature,status,registered_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(package_id,package_version) DO UPDATE SET
                    descriptor_json=excluded.descriptor_json,
                    signature=excluded.signature,
                    signer_id=excluded.signer_id,
                    status='active',
                    registered_at=excluded.registered_at
                """,
                (
                    descriptor["package_id"],
                    descriptor["package_version"],
                    descriptor["capability_id"],
                    signer_id,
                    _json(descriptor),
                    signature,
                    "active",
                    now,
                ),
            )

    def get_package_for_capability(
        self,
        capability_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT descriptor_json,signer_id,signature FROM packages WHERE capability_id=? AND status='active'",
                (capability_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "descriptor": json.loads(row["descriptor_json"]),
            "signer_id": row["signer_id"],
            "signature": row["signature"],
        }

    def list_packages(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT descriptor_json,signer_id,signature,status FROM packages ORDER BY registered_at DESC",
            ).fetchall()
        return [
            {
                "descriptor": json.loads(row["descriptor_json"]),
                "signer_id": row["signer_id"],
                "signature": row["signature"],
                "status": row["status"],
            }
            for row in rows
        ]

    def create_public_component_upload(self, record: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO public_component_uploads(
                    upload_id,component_id,platform,component_version,object_key,
                    artifact_url,size_bytes,sha256,md5,created_by,expires_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                tuple(record[key] for key in (
                    "upload_id", "component_id", "platform", "component_version",
                    "object_key", "artifact_url", "size_bytes", "sha256",
                    "md5", "created_by", "expires_at",
                )),
            )

    def get_public_component_upload(self, upload_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM public_component_uploads WHERE upload_id=?",
                (upload_id,),
            ).fetchone()
        return dict(row) if row else None

    def complete_public_component_upload(self, upload_id: str) -> bool:
        with self._lock, self._connect() as db:
            cursor = db.execute(
                """UPDATE public_component_uploads SET completed_at=?
                WHERE upload_id=? AND completed_at IS NULL AND expires_at>?""",
                (int(time.time()), upload_id, int(time.time())),
            )
            return cursor.rowcount == 1

    def get_public_component_upload_by_url(self, url: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM public_component_uploads WHERE artifact_url=?",
                (url,),
            ).fetchone()
        return dict(row) if row else None

    def mark_public_component_upload_registered(self, upload_id: str) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE public_component_uploads SET registered_at=? WHERE upload_id=?",
                (int(time.time()), upload_id),
            )

    def set_public_component_variant(
        self,
        *,
        descriptor: dict[str, Any],
        signer_id: str,
        signature: str,
        updated_by: str,
    ) -> dict[str, Any]:
        component_id = descriptor["component_id"]
        display_name = descriptor["display_name"]
        platform = descriptor["platform"]
        component_version = descriptor["component_version"]
        availability = descriptor["status"]
        provides = descriptor["provides"]
        notes = descriptor["notes"]
        now = int(time.time())
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO public_components(
                    component_id,display_name,notes,updated_by,updated_at
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(component_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    notes=excluded.notes,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
                """,
                (
                    component_id,
                    display_name,
                    notes,
                    updated_by,
                    now,
                ),
            )
            db.execute(
                """
                INSERT INTO public_component_variants(
                    component_id,platform,component_version,availability,
                    provides_json,descriptor_json,signer_id,signature,
                    updated_by,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(component_id,platform) DO UPDATE SET
                    component_version=excluded.component_version,
                    availability=excluded.availability,
                    provides_json=excluded.provides_json,
                    descriptor_json=excluded.descriptor_json,
                    signer_id=excluded.signer_id,
                    signature=excluded.signature,
                    updated_by=excluded.updated_by,
                    updated_at=excluded.updated_at
                """,
                (
                    component_id,
                    platform,
                    component_version,
                    availability,
                    _json(provides),
                    _json(descriptor),
                    signer_id,
                    signature,
                    updated_by,
                    now,
                ),
            )
            db.execute(
                """
                UPDATE component_registry_meta
                SET registry_version=registry_version+1,updated_at=?
                WHERE singleton=1
                """,
                (now,),
            )
        return self.get_public_component_registry()

    def get_public_component_registry(self) -> dict[str, Any]:
        with self._connect() as db:
            meta = db.execute(
                """
                SELECT registry_version,updated_at
                FROM component_registry_meta WHERE singleton=1
                """,
            ).fetchone()
            components = db.execute(
                """
                SELECT component_id,display_name,notes,updated_at
                FROM public_components ORDER BY component_id
                """,
            ).fetchall()
            variants = db.execute(
                """
                SELECT component_id,platform,component_version,availability,
                    provides_json,descriptor_json,signer_id,signature,updated_at
                FROM public_component_variants
                ORDER BY component_id,platform
                """,
            ).fetchall()
        variants_by_component: dict[str, list[dict[str, Any]]] = {}
        for row in variants:
            descriptor = json.loads(row["descriptor_json"])
            variant = (
                descriptor
                if descriptor
                else {
                    "platform": row["platform"],
                    "component_version": row["component_version"],
                    "status": row["availability"],
                    "provides": json.loads(row["provides_json"]),
                }
            )
            variants_by_component.setdefault(row["component_id"], []).append(
                {
                    **variant,
                    "version": row["component_version"],
                    "signer_id": row["signer_id"],
                    "signature": row["signature"],
                    "updated_at": int(row["updated_at"]),
                },
            )
        return {
            "registry_version": int(meta["registry_version"]),
            "updated_at": int(meta["updated_at"]),
            "components": [
                {
                    "component_id": row["component_id"],
                    "display_name": row["display_name"],
                    "notes": row["notes"],
                    "variants": variants_by_component.get(
                        row["component_id"],
                        [],
                    ),
                    "updated_at": int(row["updated_at"]),
                }
                for row in components
            ],
        }

    def get_public_component_variant(
        self,
        component_id: str,
        platform: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT descriptor_json,signer_id,signature
                FROM public_component_variants
                WHERE component_id=? AND platform=?
                """,
                (component_id, platform),
            ).fetchone()
        if row is None or not row["descriptor_json"]:
            return None
        descriptor = json.loads(row["descriptor_json"])
        if not descriptor:
            return None
        return {
            "descriptor": descriptor,
            "signer_id": row["signer_id"],
            "signature": row["signature"],
        }

    def create_task(
        self,
        *,
        user_id: str,
        agent_id: str,
        agent_name: str,
        invocation_id: str,
        capability_id: str,
        task_input: dict[str, Any],
        idempotency_key: str,
        device_id: str,
        max_concurrency: int,
        tenant_id: str = "local",
        session_id: str = "",
        installation_id: str = "",
        release_id: str = "",
        local_file_bindings: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        encoded_input = _json(task_input)
        encoded_bindings = _json(local_file_bindings or {})
        input_hash = hashlib.sha256(
            _json(
                {
                    "input": task_input,
                    "local_file_bindings": local_file_bindings or {},
                },
            ).encode(),
        ).hexdigest()
        now = int(time.time())
        task_id = uuid.uuid4().hex
        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT * FROM tasks WHERE user_id=? AND agent_id=? AND idempotency_key=?",
                (user_id, agent_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["input_hash"] != input_hash
                    or existing["capability_id"] != capability_id
                ):
                    raise ValueError("idempotency_conflict")
                return self._task(existing), False
            active = db.execute(
                """
                SELECT COUNT(*) AS count FROM tasks
                WHERE device_id=? AND capability_id=?
                    AND status IN ('queued','running','awaiting_input','cancelling')
                """,
                (device_id, capability_id),
            ).fetchone()["count"]
            if int(active) >= max_concurrency:
                raise ValueError("capacity")
            db.execute(
                """
                INSERT INTO tasks(task_id,user_id,agent_id,agent_name,invocation_id,
                    capability_id,idempotency_key,input_hash,input_json,device_id,status,
                    created_at,updated_at,tenant_id,session_id,installation_id,release_id,
                    local_file_bindings_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task_id,
                    user_id,
                    agent_id,
                    agent_name,
                    invocation_id,
                    capability_id,
                    idempotency_key,
                    input_hash,
                    encoded_input,
                    device_id,
                    "queued",
                    now,
                    now,
                    tenant_id,
                    session_id,
                    installation_id,
                    release_id,
                    encoded_bindings,
                ),
            )
            row = db.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return self._task(row), True

    def get_task(self, task_id: str, user_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM tasks WHERE task_id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
        return self._task(row) if row is not None else None

    def invocation_task_summaries(
        self, *, tenant_id: str, user_id: str, agent_id: str,
        session_id: str, installation_id: str, invocation_id: str,
    ) -> list[dict[str, Any]]:
        """Read task outcomes only inside the exact trusted invocation scope."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT task_id, capability_id, status, error_json, result_json "
                "FROM tasks WHERE tenant_id=? AND user_id=? AND agent_id=? "
                "AND session_id=? AND installation_id=? AND invocation_id=? "
                "ORDER BY created_at, task_id LIMIT 100",
                (tenant_id, user_id, agent_id, session_id, installation_id, invocation_id),
            ).fetchall()
        summaries = []
        for row in rows:
            error = json.loads(row["error_json"]) if row["error_json"] else None
            code = error.get("code") if isinstance(error, dict) else None
            summaries.append({
                "task_id_sha256": hashlib.sha256(row["task_id"].encode()).hexdigest(),
                "capability": row["capability_id"],
                "status": row["status"],
                "error_code": code,
                "result_sha256": (
                    hashlib.sha256(json.dumps(
                        json.loads(row["result_json"]), sort_keys=True,
                        separators=(",", ":"),
                    ).encode()).hexdigest() if row["result_json"] else None
                ),
            })
        return summaries

    def get_task_by_idempotency(
        self,
        user_id: str,
        agent_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM tasks "
                "WHERE user_id=? AND agent_id=? AND idempotency_key=?",
                (user_id, agent_id, idempotency_key),
            ).fetchone()
        return self._task(row) if row is not None else None

    def current_task(
        self,
        user_id: str,
        agent_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM tasks WHERE user_id=? AND agent_id=? ORDER BY updated_at DESC LIMIT 1",
                (user_id, agent_id),
            ).fetchone()
        return self._task(row) if row is not None else None

    def update_task(
        self,
        task_id: str,
        *,
        status: str,
        checkpoint: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE tasks SET status=?,checkpoint_json=?,result_json=?,error_json=?,updated_at=?
                WHERE task_id=?
                """,
                (
                    status,
                    _json(checkpoint) if checkpoint is not None else None,
                    _json(result) if result is not None else None,
                    _json(error) if error is not None else None,
                    int(time.time()),
                    task_id,
                ),
            )
            row = db.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        return self._task(row) if row is not None else None

    def append_event(
        self,
        task_id: str,
        sequence: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        with self._lock, self._connect() as db:
            latest = db.execute(
                "SELECT MAX(sequence) AS latest FROM task_events WHERE task_id=?",
                (task_id,),
            ).fetchone()["latest"]
            if latest is not None and sequence <= int(latest):
                return False
            try:
                db.execute(
                    "INSERT INTO task_events VALUES(?,?,?,?,?,?)",
                    (
                        uuid.uuid4().hex,
                        task_id,
                        sequence,
                        event_type,
                        _json(payload),
                        int(time.time()),
                    ),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    @staticmethod
    def _task(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        for source, target in (
            ("input_json", "input"),
            ("checkpoint_json", "checkpoint"),
            ("result_json", "result"),
            ("error_json", "error"),
            ("local_file_bindings_json", "local_file_bindings"),
        ):
            raw = result.pop(source)
            result[target] = json.loads(raw) if raw else None
        result.pop("input_hash", None)
        return result

    def save_local_file_ref(
        self,
        metadata: dict[str, Any],
        *,
        scope: dict[str, str],
        interaction_id: str,
        device_id: str,
        expires_at: int,
    ) -> bool:
        with self._lock, self._connect() as db:
            inserted = db.execute(
                """
                INSERT OR IGNORE INTO local_file_refs(
                    local_file_ref,tenant_id,user_id,session_id,agent_id,installation_id,
                    release_id,invocation_id,interaction_id,device_id,display_name,
                    mime_type,size_bytes,last_modified_ms,expires_at,revoked_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                """,
                (
                    metadata["local_file_ref"],
                    scope.get("tenant_id", "local"),
                    scope["user_id"],
                    scope["session_id"],
                    scope["agent_id"],
                    scope["installation_id"],
                    scope["release_id"],
                    scope["invocation_id"],
                    interaction_id,
                    device_id,
                    metadata["display_name"],
                    metadata["mime_type"],
                    metadata["size_bytes"],
                    metadata["last_modified_ms"],
                    expires_at,
                ),
            )
        return inserted.rowcount == 1

    def get_local_file_ref(self, local_file_ref: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM local_file_refs WHERE local_file_ref=?",
                (local_file_ref,),
            ).fetchone()
        return dict(row) if row is not None else None

    def revoke_local_file_ref(self, local_file_ref: str, user_id: str) -> bool:
        with self._lock, self._connect() as db:
            return (
                db.execute(
                    "UPDATE local_file_refs SET revoked_at=? WHERE local_file_ref=? AND user_id=?",
                    (int(time.time()), local_file_ref, user_id),
                ).rowcount
                == 1
            )

    def replace_managed_artifacts(
        self,
        tenant_id: str,
        user_id: str,
        device_id: str,
        artifacts: list[dict[str, Any]],
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "DELETE FROM managed_artifacts "
                "WHERE tenant_id=? AND user_id=? AND device_id=?",
                (tenant_id, user_id, device_id),
            )
            for item in artifacts:
                db.execute(
                    """
                    INSERT OR IGNORE INTO managed_artifacts(
                        artifact_id,tenant_id,user_id,device_id,task_id,display_name,
                        mime_type,size_bytes,created_at) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        item["artifact_id"],
                        tenant_id,
                        user_id,
                        device_id,
                        item["task_id"],
                        item["display_name"],
                        item["mime_type"],
                        item["size_bytes"],
                        item["created_at"],
                    ),
                )

    def list_managed_artifacts(
        self,
        tenant_id: str,
        user_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM managed_artifacts "
                "WHERE tenant_id=? AND user_id=? ORDER BY created_at DESC",
                (tenant_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_managed_artifact(
        self,
        artifact_id: str,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM managed_artifacts "
                "WHERE artifact_id=? AND tenant_id=? AND user_id=?",
                (artifact_id, tenant_id, user_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def delete_managed_artifact(
        self,
        artifact_id: str,
        tenant_id: str,
        user_id: str,
    ) -> bool:
        with self._lock, self._connect() as db:
            return (
                db.execute(
                    "DELETE FROM managed_artifacts "
                    "WHERE artifact_id=? AND tenant_id=? AND user_id=?",
                    (artifact_id, tenant_id, user_id),
                ).rowcount
                == 1
            )

    def put_credential(
        self,
        *,
        credential_ref: str,
        user_id: str,
        provider: str,
        ciphertext: bytes,
        scopes: list[str],
        agent_ids: list[str],
        installation_ids: list[str],
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO credentials(credential_ref,user_id,provider,ciphertext,
                    scopes_json,agent_ids_json,installation_ids_json,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(credential_ref) DO UPDATE SET
                    ciphertext=excluded.ciphertext,scopes_json=excluded.scopes_json,
                    agent_ids_json=excluded.agent_ids_json,
                    installation_ids_json=excluded.installation_ids_json,
                    updated_at=excluded.updated_at
                """,
                (
                    credential_ref,
                    user_id,
                    provider,
                    ciphertext,
                    _json(scopes),
                    _json(agent_ids),
                    _json(installation_ids),
                    int(time.time()),
                ),
            )

    def get_credential(self, credential_ref: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM credentials WHERE credential_ref=?",
                (credential_ref,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["scopes"] = json.loads(result.pop("scopes_json"))
        result["agent_ids"] = json.loads(result.pop("agent_ids_json"))
        result["installation_ids"] = json.loads(
            result.pop("installation_ids_json"),
        )
        return result

    def delete_credential(self, credential_ref: str, user_id: str) -> bool:
        with self._lock, self._connect() as db:
            db.execute(
                "DELETE FROM credential_slots WHERE credential_ref=? AND user_id=?",
                (credential_ref, user_id),
            )
            return (
                db.execute(
                    "DELETE FROM credentials WHERE credential_ref=? AND user_id=?",
                    (credential_ref, user_id),
                ).rowcount
                == 1
            )

    def put_credential_slot(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        release_id: str,
        installation_id: str,
        credential_scope: str,
        credential_slot: str,
        credential_ref: str,
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO credential_slots(
                    tenant_id,user_id,agent_id,release_id,installation_id,
                    credential_scope,credential_slot,credential_ref,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(
                    tenant_id,user_id,agent_id,release_id,installation_id,
                    credential_scope,credential_slot
                ) DO UPDATE SET
                    credential_ref=excluded.credential_ref,
                    updated_at=excluded.updated_at
                """,
                (
                    tenant_id,
                    user_id,
                    agent_id,
                    release_id,
                    installation_id,
                    credential_scope,
                    credential_slot,
                    credential_ref,
                    int(time.time()),
                ),
            )

    def get_credential_ref_for_slot(
        self,
        *,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        release_id: str,
        installation_id: str,
        credential_scope: str,
        credential_slot: str,
    ) -> str | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT credential_ref FROM credential_slots
                WHERE tenant_id=? AND user_id=? AND agent_id=? AND release_id=?
                    AND installation_id=? AND credential_scope=?
                    AND credential_slot=?
                """,
                (
                    tenant_id,
                    user_id,
                    agent_id,
                    release_id,
                    installation_id,
                    credential_scope,
                    credential_slot,
                ),
            ).fetchone()
        return str(row["credential_ref"]) if row is not None else None

    def put_temporary_resource(self, value: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                INSERT INTO temporary_resources(
                    resource_ref,tenant_id,user_id,session_id,agent_id,release_id,
                    installation_id,invocation_id,object_key,mime_type,purpose,
                    max_size_bytes,size_bytes,sha256,status,expires_at,revoked_at,
                    created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,'pending',?,NULL,?)
                """,
                (
                    value["resource_ref"],
                    value["tenant_id"],
                    value["user_id"],
                    value["session_id"],
                    value["agent_id"],
                    value["release_id"],
                    value["installation_id"],
                    value["invocation_id"],
                    value["object_key"],
                    value["mime_type"],
                    value["purpose"],
                    value["max_size_bytes"],
                    value["expires_at"],
                    value["created_at"],
                ),
            )

    def get_temporary_resource(self, resource_ref: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM temporary_resources WHERE resource_ref=?",
                (resource_ref,),
            ).fetchone()
        return dict(row) if row is not None else None

    def complete_temporary_resource(
        self,
        resource_ref: str,
        *,
        size_bytes: int,
        sha256: str,
    ) -> bool:
        with self._lock, self._connect() as db:
            return (
                db.execute(
                    """
                    UPDATE temporary_resources
                    SET size_bytes=?,sha256=?,status='ready'
                    WHERE resource_ref=? AND status='pending' AND revoked_at IS NULL
                    """,
                    (size_bytes, sha256, resource_ref),
                ).rowcount
                == 1
            )

    def revoke_temporary_resource(self, resource_ref: str) -> bool:
        with self._lock, self._connect() as db:
            return (
                db.execute(
                    """
                    UPDATE temporary_resources
                    SET status='revoked',revoked_at=?
                    WHERE resource_ref=? AND revoked_at IS NULL
                    """,
                    (int(time.time()), resource_ref),
                ).rowcount
                == 1
            )
