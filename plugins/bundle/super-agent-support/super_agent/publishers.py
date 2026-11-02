"""Durable signer and Agent ownership for plugin self-service publishing."""

from __future__ import annotations

import base64
import hashlib
import sqlite3
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class PublisherError(ValueError):
    pass


class PublisherRepository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS developer_signers (
                    signer_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(tenant_id, user_id, public_key)
                );
                CREATE TABLE IF NOT EXISTS developer_agents (
                    agent_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                """,
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def decode_public_key(encoded: str) -> tuple[str, Ed25519PublicKey]:
        try:
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) != 32:
                raise ValueError("wrong key length")
            key = Ed25519PublicKey.from_public_bytes(raw)
        except (TypeError, ValueError) as exc:
            raise PublisherError("invalid Ed25519 public key") from exc
        return base64.b64encode(raw).decode("ascii"), key

    def register_signer(
        self, tenant_id: str, user_id: str, public_key: str,
    ) -> tuple[str, Ed25519PublicKey]:
        encoded, key = self.decode_public_key(public_key)
        digest = hashlib.sha256(
            f"{tenant_id}\0{user_id}\0{encoded}".encode("utf-8"),
        ).hexdigest()
        signer_id = f"developer.{digest[:32]}"
        with self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO developer_signers
                   (signer_id, tenant_id, user_id, public_key, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (signer_id, tenant_id, user_id, encoded, int(time.time())),
            )
            row = db.execute(
                "SELECT tenant_id, user_id, public_key FROM developer_signers "
                "WHERE signer_id = ?",
                (signer_id,),
            ).fetchone()
        if row is None or (row["tenant_id"], row["user_id"], row["public_key"]) != (
            tenant_id, user_id, encoded,
        ):
            raise PublisherError("signer identity conflict")
        return signer_id, key

    def signer_owner(self, signer_id: str) -> tuple[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT tenant_id, user_id FROM developer_signers WHERE signer_id = ?",
                (signer_id,),
            ).fetchone()
        return (row["tenant_id"], row["user_id"]) if row else None

    def trusted_signers(self) -> dict[str, Ed25519PublicKey]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT signer_id, public_key FROM developer_signers",
            ).fetchall()
        return {
            row["signer_id"]: self.decode_public_key(row["public_key"])[1]
            for row in rows
        }

    def agent_owner(self, agent_id: str) -> tuple[str, str] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT tenant_id, user_id FROM developer_agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        return (row["tenant_id"], row["user_id"]) if row else None

    def claim_agent(self, agent_id: str, tenant_id: str, user_id: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                """INSERT OR IGNORE INTO developer_agents
                   (agent_id, tenant_id, user_id, created_at) VALUES (?, ?, ?, ?)""",
                (agent_id, tenant_id, user_id, int(time.time())),
            )
            row = db.execute(
                "SELECT tenant_id, user_id FROM developer_agents WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
        if row is None or (row["tenant_id"], row["user_id"]) != (
            tenant_id, user_id,
        ):
            raise PublisherError("agent_id is owned by another publisher")
        return cursor.rowcount == 1

    def release_new_claim(
        self, agent_id: str, tenant_id: str, user_id: str,
    ) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM developer_agents WHERE agent_id = ? "
                "AND tenant_id = ? AND user_id = ?",
                (agent_id, tenant_id, user_id),
            )
