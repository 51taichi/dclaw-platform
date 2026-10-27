#!/usr/bin/env python3
"""Offline verifier with a mandatory durable replay cache for DClaw identity."""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_ASSERTION_LIFETIME_SECONDS = 300
DEFAULT_CLOCK_SKEW_SECONDS = 30


class BusinessIdentityVerificationError(ValueError):
    """A stable verification or replay failure."""


def _decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise BusinessIdentityVerificationError(
            "BUSINESS_IDENTITY.ASSERTION_INVALID",
        ) from exc


class SQLiteJtiReplayCache:
    """Persist consumed JWT IDs until their expiry plus clock skew."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS business_identity_consumed_jti (
                    issuer TEXT NOT NULL,
                    jti TEXT NOT NULL,
                    retain_until INTEGER NOT NULL,
                    consumed_at INTEGER NOT NULL,
                    PRIMARY KEY(issuer,jti)
                )
                """,
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def consume(
        self,
        *,
        issuer: str,
        jti: str,
        expires_at: int,
        now: int,
        clock_skew_seconds: int,
    ) -> None:
        retain_until = expires_at + clock_skew_seconds
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM business_identity_consumed_jti WHERE retain_until<=?",
                (now,),
            )
            try:
                db.execute(
                    """
                    INSERT INTO business_identity_consumed_jti(
                        issuer,jti,retain_until,consumed_at
                    ) VALUES(?,?,?,?)
                    """,
                    (issuer, jti, retain_until, now),
                )
            except sqlite3.IntegrityError as exc:
                raise BusinessIdentityVerificationError(
                    "BUSINESS_IDENTITY.ASSERTION_REPLAYED",
                ) from exc


def verify_business_identity_assertion(
    assertion: str,
    *,
    jwks: dict[str, Any],
    expected_issuer: str,
    expected_audience: str,
    expected_installation_id: str,
    expected_release_id: str,
    expected_agent_id: str,
    expected_service_id: str,
    required_scopes: list[str],
    replay_cache: SQLiteJtiReplayCache,
    now: int | None = None,
    clock_skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
) -> dict[str, Any]:
    """Verify an EdDSA assertion and atomically consume its ``jti`` once."""
    if replay_cache is None:
        raise BusinessIdentityVerificationError(
            "BUSINESS_IDENTITY.REPLAY_CACHE_REQUIRED",
        )
    if (
        not isinstance(required_scopes, list)
        or not required_scopes
        or len(set(required_scopes)) != len(required_scopes)
        or not all(isinstance(scope, str) and scope for scope in required_scopes)
    ):
        raise BusinessIdentityVerificationError(
            "BUSINESS_IDENTITY.INVALID_REQUEST",
        )
    if not 0 <= clock_skew_seconds <= 120:
        raise BusinessIdentityVerificationError(
            "BUSINESS_IDENTITY.INVALID_REQUEST",
        )
    try:
        encoded_header, encoded_payload, encoded_signature = assertion.split(".")
        header = json.loads(_decode(encoded_header))
        payload = json.loads(_decode(encoded_payload))
        if jwks.get("issuer") != expected_issuer:
            raise ValueError
        keys = jwks["keys"]
        key = next(item for item in keys if item.get("kid") == header.get("kid"))
        if (
            header.get("alg") != "EdDSA"
            or header.get("typ") != "JWT"
            or key.get("kty") != "OKP"
            or key.get("crv") != "Ed25519"
            or key.get("alg") != "EdDSA"
            or key.get("use") != "sig"
            or key.get("status") == "revoked"
        ):
            raise ValueError
        Ed25519PublicKey.from_public_bytes(_decode(key["x"])).verify(
            _decode(encoded_signature),
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
        )
        current = int(time.time()) if now is None else int(now)
        required_strings = (
            "iss",
            "aud",
            "sub",
            "jti",
            "tenant_id",
            "user_id",
            "session_id",
            "agent_id",
            "release_id",
            "installation_id",
            "invocation_id",
            "service_id",
        )
        if (
            not isinstance(payload, dict)
            or not all(
                isinstance(payload.get(name), str) and payload[name]
                for name in required_strings
            )
            or not all(isinstance(payload.get(name), int) for name in ("iat", "nbf", "exp"))
            or not isinstance(payload.get("scopes"), list)
            or not payload["scopes"]
            or not all(isinstance(scope, str) and scope for scope in payload["scopes"])
            or payload["iss"] != expected_issuer
            or payload["aud"] != expected_audience
            or payload["installation_id"] != expected_installation_id
            or payload["release_id"] != expected_release_id
            or payload["agent_id"] != expected_agent_id
            or payload["service_id"] != expected_service_id
            or not set(required_scopes).issubset(payload["scopes"])
            or payload["nbf"] > current + clock_skew_seconds
            or payload["exp"] <= current - clock_skew_seconds
            or payload["exp"] - payload["iat"] > MAX_ASSERTION_LIFETIME_SECONDS
        ):
            raise ValueError
    except BusinessIdentityVerificationError:
        raise
    except Exception as exc:
        raise BusinessIdentityVerificationError(
            "BUSINESS_IDENTITY.ASSERTION_INVALID",
        ) from exc
    replay_cache.consume(
        issuer=payload["iss"],
        jti=payload["jti"],
        expires_at=payload["exp"],
        now=current,
        clock_skew_seconds=clock_skew_seconds,
    )
    return payload
