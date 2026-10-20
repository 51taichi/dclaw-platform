"""Signed capability package descriptor verification."""

from __future__ import annotations

import base64
import json
from pathlib import Path
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
    ) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)
        self._trusted_signers = dict(trusted_signers)
        self._store = store

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
