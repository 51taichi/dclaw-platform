"""Encrypted credential references scoped to users, agents, and operations."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .store import StateStore


class CredentialError(ValueError):
    """Credential registration or resolution was rejected."""


class CredentialBroker:
    """Store secrets encrypted and return only opaque references to callers."""

    def __init__(self, store: StateStore, master_key: bytes) -> None:
        derived = hashlib.sha256(
            master_key + b":credential-broker:v1"
        ).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))
        self._store = store

    def bind(
        self,
        *,
        user_id: str,
        provider: str,
        secret: dict[str, Any],
        scopes: list[str],
        agent_ids: list[str],
        installation_ids: list[str],
    ) -> str:
        if (
            not user_id
            or not provider
            or not isinstance(secret, dict)
            or not secret
        ):
            raise CredentialError("invalid credential binding")
        if not scopes or not all(
            isinstance(item, str) and item for item in scopes
        ):
            raise CredentialError("credential scopes are required")
        if not installation_ids:
            raise CredentialError(
                "credential installation binding is required"
            )
        reference = f"cred_{uuid.uuid4().hex}"
        ciphertext = self._fernet.encrypt(
            json.dumps(secret, separators=(",", ":"), sort_keys=True).encode(),
        )
        self._store.put_credential(
            credential_ref=reference,
            user_id=user_id,
            provider=provider,
            ciphertext=ciphertext,
            scopes=scopes,
            agent_ids=agent_ids,
            installation_ids=installation_ids,
        )
        return reference

    def resolve(
        self,
        reference: str,
        *,
        user_id: str,
        agent_id: str,
        installation_id: str,
        required_scope: str,
    ) -> dict[str, Any]:
        row = self._store.get_credential(reference)
        if (
            row is None
            or row["user_id"] != user_id
            or required_scope not in row["scopes"]
            or (row["agent_ids"] and agent_id not in row["agent_ids"])
            or installation_id not in row["installation_ids"]
        ):
            raise CredentialError("credential access denied")
        try:
            value = json.loads(self._fernet.decrypt(row["ciphertext"]))
        except (InvalidToken, ValueError, TypeError) as exc:
            raise CredentialError("credential cannot be decrypted") from exc
        if not isinstance(value, dict):
            raise CredentialError("credential payload is invalid")
        return value

    def revoke(self, reference: str, *, user_id: str) -> bool:
        return self._store.delete_credential(reference, user_id)
