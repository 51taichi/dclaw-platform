"""Trusted Ed25519 signer configuration."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = logging.getLogger(__name__)


def load_trusted_signers(path: Path) -> dict[str, Ed25519PublicKey]:
    """Load raw base64 Ed25519 public keys; invalid entries are isolated."""
    if not Path(path).exists():
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Ignoring invalid sealed signer registry: %s", exc)
        return {}
    signers: dict[str, Ed25519PublicKey] = {}
    for signer_id, encoded in (payload.get("signers", {}) or {}).items():
        try:
            raw = base64.b64decode(encoded, validate=True)
            signers[str(signer_id)] = Ed25519PublicKey.from_public_bytes(raw)
        except (TypeError, ValueError) as exc:
            logger.error("Ignoring invalid sealed signer %s: %s", signer_id, exc)
    return signers
