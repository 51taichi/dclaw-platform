"""Signed public Component registry owned by the support plugin."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA, SECP256R1
from jsonschema import Draft202012Validator

from .store import StateStore


class PublicComponentError(ValueError):
    """A public Component descriptor or signature is invalid."""


class PublicComponentRegistry:
    def __init__(
        self,
        store: StateStore,
        schema_path: Path,
        trusted_signers: dict[str, str],
    ) -> None:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self._validator = Draft202012Validator(schema)
        self._trusted_signers = {}
        for signer_id, encoded_key in trusted_signers.items():
            try:
                public_key = serialization.load_der_public_key(
                    base64.b64decode(encoded_key, validate=True),
                )
                if not isinstance(public_key.curve, SECP256R1):
                    raise ValueError("unsupported public key curve")
            except (AttributeError, TypeError, ValueError) as exc:
                raise PublicComponentError(
                    f"trusted public Component signer is invalid: {signer_id}",
                ) from exc
            self._trusted_signers[signer_id] = encoded_key
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
        updated_by: str,
    ) -> dict[str, Any]:
        errors = sorted(
            self._validator.iter_errors(descriptor),
            key=lambda item: list(item.path),
        )
        if errors:
            raise PublicComponentError(
                f"invalid public Component descriptor: {errors[0].message}",
            )
        encoded_key = self._trusted_signers.get(signer_id)
        if not encoded_key:
            raise PublicComponentError("public Component signer is not trusted")
        try:
            public_key = serialization.load_der_public_key(
                base64.b64decode(encoded_key),
            )
            if not isinstance(public_key.curve, SECP256R1):
                raise ValueError("unsupported public key curve")
            public_key.verify(
                base64.b64decode(signature),
                self.canonical_payload(descriptor),
                ECDSA(hashes.SHA256()),
            )
        except (AttributeError, TypeError, ValueError, InvalidSignature) as exc:
            raise PublicComponentError(
                "public Component signature is invalid",
            ) from exc
        return self._store.set_public_component_variant(
            descriptor=descriptor,
            signer_id=signer_id,
            signature=signature,
            updated_by=updated_by,
        )

    def resolve(
        self,
        requirements: list[dict[str, str]],
        *,
        platform: str,
    ) -> list[dict[str, Any]]:
        resolved: dict[str, dict[str, Any]] = {}
        visiting: set[str] = set()

        def visit(component_id: str, version: str) -> None:
            existing = resolved.get(component_id)
            if existing is not None:
                if existing["descriptor"]["component_version"] != version:
                    raise PublicComponentError(
                        f"conflicting public Component versions: {component_id}",
                    )
                return
            if component_id in visiting:
                raise PublicComponentError(
                    f"public Component dependency cycle: {component_id}",
                )
            envelope = self._store.get_public_component_variant(
                component_id,
                platform,
            )
            if envelope is None:
                raise PublicComponentError(
                    f"public Component is not registered: {component_id}@{platform}",
                )
            descriptor = envelope["descriptor"]
            if (
                descriptor["status"] != "available"
                or descriptor["component_version"] != version
            ):
                raise PublicComponentError(
                    f"public Component is unavailable: {component_id}@{version}",
                )
            visiting.add(component_id)
            for dependency in descriptor.get("dependencies", []):
                visit(dependency["component_id"], dependency["version"])
            visiting.remove(component_id)
            encoded_key = self._trusted_signers.get(envelope["signer_id"])
            if not encoded_key:
                raise PublicComponentError(
                    f"public Component signer is no longer trusted: {component_id}",
                )
            resolved[component_id] = {
                **envelope,
                "signer_public_key": encoded_key,
                "canonical_payload": base64.b64encode(
                    self.canonical_payload(descriptor),
                ).decode("ascii"),
            }

        for requirement in requirements:
            visit(requirement["component_id"], requirement["version"])
        return list(resolved.values())
