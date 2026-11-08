"""Signed capability package descriptor verification."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator

from .store import StateStore


class PackageError(ValueError):
    """Capability package metadata or signature is invalid."""


class CapabilityPackageRegistry:
    def __init__(
        self,
        store: StateStore,
        schema_path: Path,
        trusted_signers: dict[str, str],
        trust_path: Path | None = None,
    ) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)
        self._trusted_signers = dict(trusted_signers)
        self._trust_path = Path(trust_path) if trust_path is not None else None
        self._trust_lock = threading.RLock()
        self._store = store

    def trust_signer(self, signer_id: str, public_key: str) -> dict[str, str]:
        if (
            not isinstance(signer_id, str)
            or not 1 <= len(signer_id) <= 128
            or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in signer_id)
            or not isinstance(public_key, str)
        ):
            raise PackageError("invalid capability package signer")
        try:
            key_bytes = base64.b64decode(public_key, validate=True)
            Ed25519PublicKey.from_public_bytes(key_bytes)
        except (ValueError, TypeError) as exc:
            raise PackageError("invalid capability package public key") from exc
        if self._trust_path is None:
            raise PackageError("capability package signer registration unavailable")
        canonical = base64.b64encode(key_bytes).decode("ascii")
        with self._trust_lock:
            old = self._trusted_signers.get(signer_id)
            if old is not None and old != canonical:
                raise PackageError("capability package signer id is already trusted")
            if old is None:
                saved = dict(self._trusted_signers)
                saved[signer_id] = canonical
                path = self._trust_path
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_name(path.name + ".tmp")
                temporary.write_text(json.dumps(saved, sort_keys=True), encoding="utf-8")
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
                self._trusted_signers = saved
        return {
            "signer_id": signer_id,
            "public_key_sha256": hashlib.sha256(key_bytes).hexdigest(),
            "status": "registered" if old is None else "already_registered",
        }

    @staticmethod
    def canonical_payload(descriptor: dict[str, Any]) -> bytes:
        return json.dumps(
            descriptor,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def register(
        self,
        descriptor: dict[str, Any],
        *,
        signer_id: str,
        signature: str,
    ) -> None:
        errors = sorted(
            self._validator.iter_errors(descriptor),
            key=lambda item: list(item.path),
        )
        if errors:
            raise PackageError(
                f"invalid capability descriptor: {errors[0].message}"
            )
        for schema_name, declaration in descriptor["schemas"].items():
            try:
                Draft202012Validator.check_schema(declaration["document"])
            except Exception as exc:
                raise PackageError(
                    f"invalid {schema_name} JSON Schema"
                ) from exc
        encoded_key = self._trusted_signers.get(signer_id)
        if not encoded_key:
            raise PackageError("capability package signer is not trusted")
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(encoded_key)
            )
            public_key.verify(
                base64.b64decode(signature),
                self.canonical_payload(descriptor),
            )
        except (ValueError, InvalidSignature) as exc:
            raise PackageError(
                "capability package signature is invalid"
            ) from exc
        self._store.register_package(
            descriptor,
            signer_id=signer_id,
            signature=signature,
        )
