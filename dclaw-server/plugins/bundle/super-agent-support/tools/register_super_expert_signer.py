#!/usr/bin/env python3
"""Atomically register one public signer for sealed Super Expert packages."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


REGISTRIES = ("trusted_signers.json", "official_super_expert_signers.json")


class SignerRegistrationError(RuntimeError):
    """Raised when a public signer cannot be safely registered."""


def _read_registry(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignerRegistrationError(f"invalid signer registry: {path}") from exc
    signers = payload.get("signers") if isinstance(payload, dict) else None
    if not isinstance(signers, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in signers.items()
    ):
        raise SignerRegistrationError(f"invalid signer registry: {path}")
    return dict(signers)


def _atomic_registry(path: Path, signers: dict[str, str]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {"signers": signers},
                stream,
                ensure_ascii=False,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o644)
    finally:
        if temporary.exists():
            temporary.unlink()


def _public_key(encoded: str) -> tuple[str, str]:
    try:
        raw = base64.b64decode(encoded.strip(), validate=True)
        Ed25519PublicKey.from_public_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise SignerRegistrationError(
            "public key must be one raw Ed25519 key encoded as Base64",
        ) from exc
    if len(raw) != 32:
        raise SignerRegistrationError("Ed25519 public key must be 32 bytes")
    canonical = base64.b64encode(raw).decode("ascii")
    return canonical, hashlib.sha256(raw).hexdigest()


def register_signer(
    *,
    sealed_root: Path,
    signer_id: str,
    public_key_base64: str,
    expected_fingerprint: str,
) -> dict[str, Any]:
    signer_id = signer_id.strip()
    if not signer_id or len(signer_id) > 128:
        raise SignerRegistrationError(
            "signer ID is required and limited to 128 characters",
        )
    public_key, fingerprint = _public_key(public_key_base64)
    if fingerprint != expected_fingerprint.lower():
        raise SignerRegistrationError("public key fingerprint does not match")
    sealed_root = sealed_root.resolve()
    sealed_root.mkdir(parents=True, exist_ok=True)
    lock_path = sealed_root / ".signer-registry.lock"
    changed: list[str] = []
    with lock_path.open("a+", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        registries = {
            name: _read_registry(sealed_root / name) for name in REGISTRIES
        }
        for name, signers in registries.items():
            existing = signers.get(signer_id)
            if existing is not None and existing != public_key:
                raise SignerRegistrationError(
                    f"signer ID conflicts with existing key in {name}",
                )
        for name, signers in registries.items():
            if signers.get(signer_id) == public_key:
                continue
            signers[signer_id] = public_key
            _atomic_registry(sealed_root / name, signers)
            changed.append(name)
    return {
        "status": "registered" if changed else "already-registered",
        "signer_id": signer_id,
        "public_key_sha256": fingerprint,
        "trusted": True,
        "official_for_super_expert": True,
        "changed_registries": changed,
        "activation": "reload dclaw.super-agent-support after registration",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sealed-root", required=True, type=Path)
    parser.add_argument("--signer-id", required=True)
    parser.add_argument("--public-key-file", required=True, type=Path)
    parser.add_argument("--expected-fingerprint", required=True)
    args = parser.parse_args()
    try:
        result = register_signer(
            sealed_root=args.sealed_root,
            signer_id=args.signer_id,
            public_key_base64=args.public_key_file.read_text(encoding="utf-8"),
            expected_fingerprint=args.expected_fingerprint,
        )
    except (OSError, SignerRegistrationError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
