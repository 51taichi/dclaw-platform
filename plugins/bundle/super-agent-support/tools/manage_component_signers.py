#!/usr/bin/env python3
"""Manage the plugin-owned public Component signer trust store."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePublicKey,
    SECP256R1,
)


TRUST_FILENAME = "trusted_component_signers.json"


class SignerTrustError(RuntimeError):
    """The signer trust operation is invalid."""


def _path(state_dir: Path) -> Path:
    return state_dir / TRUST_FILENAME


def _load(state_dir: Path) -> dict[str, str]:
    path = _path(state_dir)
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignerTrustError("Component signer trust store is invalid") from exc
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not key
        or not isinstance(item, str)
        or not item
        for key, item in value.items()
    ):
        raise SignerTrustError("Component signer trust store is invalid")
    return value


def _write(state_dir: Path, value: dict[str, str]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _path(state_dir)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def _encoded_public_key(path: Path) -> tuple[str, str]:
    try:
        public_key = serialization.load_pem_public_key(path.read_bytes())
        if not isinstance(public_key, EllipticCurvePublicKey) or not isinstance(
            public_key.curve,
            SECP256R1,
        ):
            raise ValueError("public key must use P-256")
        der = public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise SignerTrustError("P-256 public key is invalid") from exc
    return base64.b64encode(der).decode("ascii"), hashlib.sha256(der).hexdigest()


def set_signer(state_dir: Path, signer_id: str, public_key: Path) -> dict:
    encoded, fingerprint = _encoded_public_key(public_key)
    trust = _load(state_dir)
    status = "unchanged" if trust.get(signer_id) == encoded else "updated"
    trust[signer_id] = encoded
    _write(state_dir, trust)
    return {
        "status": status,
        "signer_id": signer_id,
        "fingerprint_sha256": fingerprint,
        "trusted_signer_ids": sorted(trust),
    }


def remove_signer(state_dir: Path, signer_id: str) -> dict:
    trust = _load(state_dir)
    existed = signer_id in trust
    trust.pop(signer_id, None)
    _write(state_dir, trust)
    return {
        "status": "removed" if existed else "absent",
        "signer_id": signer_id,
        "trusted_signer_ids": sorted(trust),
    }


def list_signers(state_dir: Path) -> dict:
    trust = _load(state_dir)
    return {
        "trusted_signer_ids": sorted(trust),
        "count": len(trust),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=os.environ.get("DCLAW_SUPER_AGENT_SUPPORT_STATE_DIR"),
        required=not bool(os.environ.get("DCLAW_SUPER_AGENT_SUPPORT_STATE_DIR")),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    set_command = commands.add_parser("set")
    set_command.add_argument("--signer-id", required=True)
    set_command.add_argument("--public-key", type=Path, required=True)
    remove = commands.add_parser("remove")
    remove.add_argument("--signer-id", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "set":
            result = set_signer(args.state_dir, args.signer_id, args.public_key)
        elif args.command == "remove":
            result = remove_signer(args.state_dir, args.signer_id)
        else:
            result = list_signers(args.state_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except SignerTrustError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
