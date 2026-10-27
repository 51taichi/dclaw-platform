# -*- coding: utf-8 -*-
"""Installation-bound business service identity and controlled transport."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import re
import socket
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .session import SessionError, SessionSigner
from .store import StateStore

CAPABILITY_ID = "business.service.installation-identity/1"
DEFAULT_TTL_SECONDS = 120
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 300
MAX_RESPONSE_BYTES = 1_048_576
MAX_REQUEST_BYTES = 1_048_576
RATE_LIMIT_PER_MINUTE = 30
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SAFE_HEADERS = {
    "accept",
    "content-type",
    "idempotency-key",
    "user-agent",
    "x-request-id",
}


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _public_hostname(hostname: str | None) -> bool:
    if not hostname:
        return False
    lowered = hostname.rstrip(".").lower()
    reserved_suffixes = (".local", ".localhost", ".test", ".example", ".invalid")
    if (
        lowered in {"localhost", "localhost.localdomain"}
        or lowered.endswith(reserved_suffixes)
    ):
        return False
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        if "." not in lowered:
            return False
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(
                    lowered,
                    443,
                    type=socket.SOCK_STREAM,
                )
            }
        except (OSError, socket.gaierror):
            return False
        return bool(addresses) and all(
            ipaddress.ip_address(address).is_global for address in addresses
        )
    return address.is_global


def _validated_https_url(
    value: str,
    *,
    allow_query: bool = True,
) -> tuple[str, str]:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise BusinessIdentityError("AUDIENCE_NOT_ALLOWED") from exc
    if (
        parsed.scheme != "https"
        or not _public_hostname(parsed.hostname)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (parsed.query and not allow_query)
    ):
        raise BusinessIdentityError("AUDIENCE_NOT_ALLOWED")
    hostname = parsed.hostname.lower()
    host_literal = f"[{hostname}]" if ":" in hostname else hostname
    origin = f"https://{host_literal}"
    if port and port != 443:
        origin += f":{port}"
    return hostname, origin


def _validated_path(value: str) -> str:
    path = urlsplit(value).path or "/"
    if (
        "%" in path
        or "\\" in path
        or "//" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        raise BusinessIdentityError("AUDIENCE_NOT_ALLOWED")
    return path


@dataclass(frozen=True)
class BusinessIdentityError(ValueError):
    reason: str

    @property
    def code(self) -> str:
        return f"BUSINESS_IDENTITY.{self.reason}"

    def __str__(self) -> str:
        return self.code


class BusinessIdentityManager:
    """Own service grants, one-time bindings, signing, and outbound injection."""

    def __init__(
        self,
        store: StateStore,
        master_key: bytes,
        signer: SessionSigner,
        *,
        issuer: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if len(master_key) < 32:
            raise ValueError("business identity master key must be at least 32 bytes")
        _validated_https_url(issuer, allow_query=False)
        _validated_path(issuer)
        self._path = store.path
        self._master_key = bytes(master_key)
        self._session_signer = signer
        self._issuer = issuer.rstrip("/")
        self._transport = transport
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS business_identity_services (
                    service_id TEXT PRIMARY KEY,
                    developer_id TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    allowed_domains_json TEXT NOT NULL,
                    allowed_scopes_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    revoked_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS business_identity_grants (
                    grant_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    installation_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    revoked_at INTEGER,
                    UNIQUE(tenant_id,user_id,agent_id,release_id,installation_id,service_id)
                );
                CREATE INDEX IF NOT EXISTS idx_business_identity_grants_scope
                    ON business_identity_grants(
                        tenant_id,user_id,agent_id,release_id,installation_id,service_id
                    );
                CREATE TABLE IF NOT EXISTS business_identity_keys (
                    key_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    retired_at INTEGER,
                    revoked_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS business_identity_bindings (
                    binding_ref TEXT PRIMARY KEY,
                    grant_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    release_id TEXT NOT NULL,
                    installation_id TEXT NOT NULL,
                    invocation_id TEXT NOT NULL,
                    service_id TEXT NOT NULL,
                    audience TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    jti TEXT NOT NULL UNIQUE,
                    key_id TEXT NOT NULL,
                    issued_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    audit_id TEXT NOT NULL,
                    used_at INTEGER,
                    verified_at INTEGER,
                    revoked_at INTEGER,
                    UNIQUE(tenant_id,installation_id,service_id,idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS business_identity_revocations (
                    revocation_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE(kind,tenant_id,subject_id)
                );
                CREATE TABLE IF NOT EXISTS business_identity_audit (
                    audit_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT,
                    agent_id TEXT,
                    release_id TEXT,
                    installation_id TEXT,
                    service_id TEXT,
                    scopes_json TEXT NOT NULL,
                    audience TEXT,
                    result TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    key_id TEXT,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_business_identity_audit_time
                    ON business_identity_audit(created_at DESC);
                """,
            )
            if db.execute(
                "SELECT 1 FROM business_identity_keys WHERE status='active'",
            ).fetchone() is None:
                db.execute(
                    "INSERT INTO business_identity_keys(key_id,status,created_at) VALUES(?,?,?)",
                    (f"bik_{uuid.uuid4().hex}", "active", int(time.time())),
                )
            binding_columns = {
                row[1]
                for row in db.execute(
                    "PRAGMA table_info(business_identity_bindings)",
                ).fetchall()
            }
            if "verified_at" not in binding_columns:
                db.execute(
                    "ALTER TABLE business_identity_bindings ADD COLUMN verified_at INTEGER",
                )

    @staticmethod
    def _validate_id(value: str) -> str:
        if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
            raise BusinessIdentityError("INVALID_REQUEST")
        return value

    @staticmethod
    def _validate_scopes(scopes: list[str]) -> list[str]:
        if (
            not isinstance(scopes, list)
            or not scopes
            or len(scopes) > 64
            or len(set(scopes)) != len(scopes)
            or not all(isinstance(item, str) and _SCOPE_PATTERN.fullmatch(item) for item in scopes)
        ):
            raise BusinessIdentityError("INVALID_REQUEST")
        return sorted(scopes)

    def _private_key(self, key_id: str) -> Ed25519PrivateKey:
        seed = hmac.new(
            self._master_key,
            b"dclaw:business-identity:ed25519:v1:" + key_id.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return Ed25519PrivateKey.from_private_bytes(seed)

    def _public_jwk(self, row: sqlite3.Row) -> dict[str, Any]:
        raw = self._private_key(str(row["key_id"])).public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return {
            "kty": "OKP",
            "crv": "Ed25519",
            "use": "sig",
            "alg": "EdDSA",
            "kid": str(row["key_id"]),
            "x": _encode(raw),
            "status": str(row["status"]),
        }

    def verification_keys(self) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM business_identity_keys ORDER BY created_at DESC",
            ).fetchall()
        return {"issuer": self._issuer, "keys": [self._public_jwk(row) for row in rows]}

    def register_service(
        self,
        *,
        actor_id: str,
        developer_id: str,
        service_id: str,
        audience: str,
        allowed_domains: list[str],
        allowed_scopes: list[str],
    ) -> dict[str, Any]:
        developer_id = self._validate_id(developer_id)
        service_id = self._validate_id(service_id)
        audience_host, _ = _validated_https_url(
            audience,
            allow_query=False,
        )
        _validated_path(audience)
        if (
            not isinstance(allowed_domains, list)
            or not allowed_domains
            or len(set(allowed_domains)) != len(allowed_domains)
        ):
            raise BusinessIdentityError("INVALID_REQUEST")
        domains = sorted(domain.rstrip(".").lower() for domain in allowed_domains)
        if audience_host not in domains or not all(_public_hostname(domain) for domain in domains):
            raise BusinessIdentityError("AUDIENCE_NOT_ALLOWED")
        scopes = self._validate_scopes(allowed_scopes)
        now = int(time.time())
        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT * FROM business_identity_services WHERE service_id=?",
                (service_id,),
            ).fetchone()
            if existing is not None:
                if existing["revoked_at"] is not None:
                    raise BusinessIdentityError("SERVICE_REVOKED")
                unchanged = (
                    existing["developer_id"] == developer_id
                    and existing["audience"] == audience
                    and json.loads(existing["allowed_domains_json"]) == domains
                    and json.loads(existing["allowed_scopes_json"]) == scopes
                )
                if not unchanged:
                    raise BusinessIdentityError("SERVICE_UPDATE_REQUIRES_NEW_ID")
                return {
                    "service_id": service_id,
                    "developer_id": developer_id,
                    "audience": audience,
                    "allowed_domains": domains,
                    "allowed_scopes": scopes,
                    "issuer": self._issuer,
                }
            db.execute(
                """
                INSERT INTO business_identity_services(
                    service_id,developer_id,audience,allowed_domains_json,
                    allowed_scopes_json,created_at,updated_at,revoked_at
                ) VALUES(?,?,?,?,?,?,?,NULL)
                """,
                (service_id, developer_id, audience, _json(domains), _json(scopes), now, now),
            )
        return {
            "service_id": service_id,
            "developer_id": developer_id,
            "audience": audience,
            "allowed_domains": domains,
            "allowed_scopes": scopes,
            "issuer": self._issuer,
        }

    def grant_installation(
        self,
        *,
        actor_id: str,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        release_id: str,
        installation_id: str,
        service_id: str,
        audience: str,
        scopes: list[str],
    ) -> dict[str, Any]:
        values = [tenant_id, user_id, agent_id, release_id, installation_id, service_id]
        if not all(isinstance(value, str) and value for value in values):
            raise BusinessIdentityError("INVALID_REQUEST")
        scopes = self._validate_scopes(scopes)
        with self._lock, self._connect() as db:
            service = db.execute(
                "SELECT * FROM business_identity_services WHERE service_id=? AND revoked_at IS NULL",
                (service_id,),
            ).fetchone()
            if service is None:
                raise BusinessIdentityError("SERVICE_UNKNOWN")
            if audience != service["audience"]:
                raise BusinessIdentityError("AUDIENCE_NOT_ALLOWED")
            if not set(scopes).issubset(json.loads(service["allowed_scopes_json"])):
                raise BusinessIdentityError("SCOPE_NOT_ALLOWED")
            grant_id = f"big_{uuid.uuid4().hex}"
            now = int(time.time())
            db.execute(
                """
                INSERT INTO business_identity_grants(
                    grant_id,tenant_id,user_id,agent_id,release_id,installation_id,
                    service_id,audience,scopes_json,created_at,revoked_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(tenant_id,user_id,agent_id,release_id,installation_id,service_id)
                DO UPDATE SET grant_id=excluded.grant_id,audience=excluded.audience,
                    scopes_json=excluded.scopes_json,created_at=excluded.created_at,revoked_at=NULL
                """,
                (
                    grant_id, tenant_id, user_id, agent_id, release_id, installation_id,
                    service_id, audience, _json(scopes), now,
                ),
            )
        return {
            "grant_id": grant_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "release_id": release_id,
            "installation_id": installation_id,
            "service_id": service_id,
            "audience": audience,
            "scopes": scopes,
        }

    def _audit(
        self,
        db: sqlite3.Connection,
        *,
        action: str,
        actor_id: str,
        trace_id: str,
        result: str,
        reason_code: str,
        identity: dict[str, Any] | None = None,
        service_id: str | None = None,
        audience: str | None = None,
        scopes: list[str] | None = None,
        key_id: str | None = None,
        audit_id: str | None = None,
    ) -> str:
        identity = identity or {}
        audit_id = audit_id or f"bia_{uuid.uuid4().hex}"
        db.execute(
            """
            INSERT INTO business_identity_audit(
                audit_id,trace_id,action,actor_id,tenant_id,user_id,agent_id,
                release_id,installation_id,service_id,scopes_json,audience,
                result,reason_code,key_id,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                audit_id, trace_id, action, actor_id, str(identity.get("t") or "local"),
                identity.get("u"), identity.get("a"), identity.get("r"), identity.get("g"),
                service_id, _json(scopes or []), audience, result, reason_code, key_id,
                int(time.time()),
            ),
        )
        return audit_id

    def _identity(self, token: str) -> dict[str, Any]:
        try:
            identity = self._session_signer.verify(token)
        except SessionError as exc:
            raise BusinessIdentityError("AUTHENTICATION_FAILED") from exc
        capabilities = set(identity.get("c") or [])
        if CAPABILITY_ID not in capabilities:
            raise BusinessIdentityError("NOT_GRANTED")
        return identity

    def _audit_denial(
        self,
        *,
        action: str,
        error: BusinessIdentityError,
        trace_id: str,
        identity: dict[str, Any] | None,
        service_id: str | None,
        audience: str | None,
        scopes: list[str] | None,
    ) -> None:
        with self._lock, self._connect() as db:
            self._audit(
                db,
                action=action,
                actor_id=str((identity or {}).get("u") or "anonymous"),
                trace_id=trace_id,
                result="denied",
                reason_code=error.code,
                identity=identity,
                service_id=service_id if isinstance(service_id, str) else None,
                audience=audience if isinstance(audience, str) else None,
                scopes=scopes if isinstance(scopes, list) else None,
            )

    @staticmethod
    def _revoked(db: sqlite3.Connection, kind: str, tenant_id: str, subject_id: str) -> bool:
        return db.execute(
            "SELECT 1 FROM business_identity_revocations WHERE kind=? AND tenant_id=? AND subject_id=?",
            (kind, tenant_id, subject_id),
        ).fetchone() is not None

    def issue(
        self,
        *,
        dclaw_session_token: str,
        service_id: str,
        audience: str,
        scopes: list[str],
        idempotency_key: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: int | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        current_trace = trace_id or uuid.uuid4().hex
        identity: dict[str, Any] | None = None
        try:
            identity = self._identity(dclaw_session_token)
            return self._issue(
                identity=identity,
                service_id=service_id,
                audience=audience,
                scopes=scopes,
                idempotency_key=idempotency_key,
                ttl_seconds=ttl_seconds,
                now=now,
                trace_id=current_trace,
            )
        except BusinessIdentityError as exc:
            self._audit_denial(
                action="issue",
                error=exc,
                trace_id=current_trace,
                identity=identity,
                service_id=service_id,
                audience=audience,
                scopes=scopes,
            )
            raise

    def _issue(
        self,
        *,
        identity: dict[str, Any],
        service_id: str,
        audience: str,
        scopes: list[str],
        idempotency_key: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        now: int | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        service_id = self._validate_id(service_id)
        scopes = self._validate_scopes(scopes)
        if (
            not isinstance(idempotency_key, str)
            or not 16 <= len(idempotency_key) <= 128
            or not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS
        ):
            raise BusinessIdentityError("INVALID_REQUEST")
        current = int(time.time()) if now is None else int(now)
        with self._lock, self._connect() as db:
            existing = db.execute(
                """
                SELECT * FROM business_identity_bindings
                WHERE tenant_id=? AND installation_id=? AND service_id=? AND idempotency_key=?
                """,
                (identity["t"], identity["g"], service_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if (
                    existing["audience"] != audience
                    or json.loads(existing["scopes_json"]) != scopes
                    or existing["release_id"] != identity["r"]
                    or existing["agent_id"] != identity["a"]
                ):
                    raise BusinessIdentityError("IDEMPOTENCY_CONFLICT")
                if existing["used_at"] is not None:
                    raise BusinessIdentityError("BINDING_REPLAYED")
                if existing["revoked_at"] is not None:
                    raise BusinessIdentityError("BINDING_REVOKED")
                if existing["expires_at"] <= current:
                    raise BusinessIdentityError("BINDING_EXPIRED")
                return self._binding_response(existing)
            service = db.execute(
                "SELECT * FROM business_identity_services WHERE service_id=? AND revoked_at IS NULL",
                (service_id,),
            ).fetchone()
            if service is None:
                raise BusinessIdentityError("SERVICE_UNKNOWN")
            if audience != service["audience"]:
                raise BusinessIdentityError("AUDIENCE_NOT_ALLOWED")
            if not set(scopes).issubset(json.loads(service["allowed_scopes_json"])):
                raise BusinessIdentityError("SCOPE_NOT_ALLOWED")
            if self._revoked(db, "installation", identity["t"], identity["g"]):
                raise BusinessIdentityError("INSTALLATION_REVOKED")
            release_subject = f'{identity["a"]}:{identity["r"]}'
            if self._revoked(db, "release", identity["t"], release_subject):
                raise BusinessIdentityError("RELEASE_MISMATCH")
            grant = db.execute(
                """
                SELECT * FROM business_identity_grants
                WHERE tenant_id=? AND user_id=? AND agent_id=? AND release_id=?
                    AND installation_id=? AND service_id=? AND revoked_at IS NULL
                """,
                (identity["t"], identity["u"], identity["a"], identity["r"], identity["g"], service_id),
            ).fetchone()
            if grant is None:
                release_exists = db.execute(
                    """
                    SELECT 1 FROM business_identity_grants
                    WHERE tenant_id=? AND user_id=? AND agent_id=? AND installation_id=?
                        AND service_id=? AND revoked_at IS NULL
                    """,
                    (identity["t"], identity["u"], identity["a"], identity["g"], service_id),
                ).fetchone()
                raise BusinessIdentityError("RELEASE_MISMATCH" if release_exists else "NOT_GRANTED")
            if audience != grant["audience"]:
                raise BusinessIdentityError("AUDIENCE_NOT_ALLOWED")
            if not set(scopes).issubset(json.loads(grant["scopes_json"])):
                raise BusinessIdentityError("SCOPE_NOT_ALLOWED")
            recent = db.execute(
                """
                SELECT COUNT(*) FROM business_identity_audit
                WHERE action='issue' AND tenant_id=? AND installation_id=? AND created_at>?
                """,
                (identity["t"], identity["g"], current - 60),
            ).fetchone()[0]
            if recent >= RATE_LIMIT_PER_MINUTE:
                raise BusinessIdentityError("RATE_LIMITED")
            key = db.execute(
                "SELECT * FROM business_identity_keys WHERE status='active' AND revoked_at IS NULL",
            ).fetchone()
            if key is None:
                raise BusinessIdentityError("SIGNER_UNAVAILABLE")
            binding_ref = f"bir_{uuid.uuid4().hex}"
            jti = f"bij_{uuid.uuid4().hex}"
            audit_id = f"bia_{uuid.uuid4().hex}"
            expires_at = current + ttl_seconds
            db.execute(
                """
                INSERT INTO business_identity_bindings(
                    binding_ref,grant_id,tenant_id,user_id,session_id,agent_id,release_id,
                    installation_id,invocation_id,service_id,audience,scopes_json,idempotency_key,
                    jti,key_id,issued_at,expires_at,audit_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    binding_ref, grant["grant_id"], identity["t"], identity["u"], identity["s"],
                    identity["a"], identity["r"], identity["g"], identity["i"], service_id,
                    audience, _json(scopes), idempotency_key, jti, key["key_id"], current,
                    expires_at, audit_id,
                ),
            )
            self._audit(
                db, action="issue", actor_id=identity["u"], trace_id=trace_id,
                result="allowed", reason_code="BUSINESS_IDENTITY.ISSUED", identity=identity,
                service_id=service_id, audience=audience, scopes=scopes, key_id=key["key_id"],
                audit_id=audit_id,
            )
            row = db.execute(
                "SELECT * FROM business_identity_bindings WHERE binding_ref=?",
                (binding_ref,),
            ).fetchone()
        return self._binding_response(row)

    def _binding_response(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "binding_ref": str(row["binding_ref"]),
            "service_id": str(row["service_id"]),
            "audience": str(row["audience"]),
            "scopes": json.loads(row["scopes_json"]),
            "issued_at": int(row["issued_at"]),
            "expires_at": int(row["expires_at"]),
            "issuer": self._issuer,
            "key_id": str(row["key_id"]),
            "audit_id": str(row["audit_id"]),
        }

    def _sign_assertion(self, row: sqlite3.Row) -> str:
        subject = hashlib.sha256(
            f'{row["tenant_id"]}\0{row["installation_id"]}'.encode("utf-8"),
        ).hexdigest()
        header = {"alg": "EdDSA", "kid": row["key_id"], "typ": "JWT"}
        payload = {
            "iss": self._issuer,
            "aud": row["audience"],
            "sub": f"urn:dclaw:installation:{subject}",
            "jti": row["jti"],
            "iat": row["issued_at"],
            "nbf": row["issued_at"],
            "exp": row["expires_at"],
            "tenant_id": row["tenant_id"],
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "agent_id": row["agent_id"],
            "release_id": row["release_id"],
            "installation_id": row["installation_id"],
            "invocation_id": row["invocation_id"],
            "service_id": row["service_id"],
            "scopes": json.loads(row["scopes_json"]),
        }
        signing_input = f"{_encode(_json(header).encode())}.{_encode(_json(payload).encode())}"
        signature = self._private_key(str(row["key_id"])).sign(signing_input.encode("ascii"))
        return f"{signing_input}.{_encode(signature)}"

    def verify_assertion(
        self,
        assertion: str,
        *,
        audience: str,
        installation_id: str,
        release_id: str,
        agent_id: str,
        service_id: str,
        required_scopes: list[str],
        now: int | None = None,
    ) -> dict[str, Any]:
        required_scopes = self._validate_scopes(required_scopes)
        try:
            encoded_header, encoded_payload, encoded_signature = assertion.split(".")
            header = json.loads(base64.urlsafe_b64decode(encoded_header + "=" * (-len(encoded_header) % 4)))
            payload = json.loads(base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4)))
            with self._connect() as db:
                key = db.execute(
                    "SELECT * FROM business_identity_keys WHERE key_id=?",
                    (header.get("kid"),),
                ).fetchone()
            if key is None or key["revoked_at"] is not None or header.get("alg") != "EdDSA":
                raise ValueError
            self._private_key(str(key["key_id"])).public_key().verify(
                base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4)),
                f"{encoded_header}.{encoded_payload}".encode("ascii"),
            )
            current = int(time.time()) if now is None else int(now)
            if (
                payload.get("iss") != self._issuer
                or not isinstance(payload.get("iat"), int)
                or not isinstance(payload.get("nbf"), int)
                or not isinstance(payload.get("exp"), int)
                or payload["nbf"] > current + 30
                or payload["exp"] <= current - 30
                or payload["exp"] - payload["iat"] > MAX_TTL_SECONDS
            ):
                raise ValueError
            if (
                payload.get("aud") != audience
                or payload.get("installation_id") != installation_id
                or payload.get("release_id") != release_id
                or payload.get("agent_id") != agent_id
                or payload.get("service_id") != service_id
                or not set(required_scopes).issubset(payload.get("scopes") or [])
            ):
                raise BusinessIdentityError("ASSERTION_SCOPE_MISMATCH")
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                binding = db.execute(
                    "SELECT * FROM business_identity_bindings WHERE jti=?",
                    (payload.get("jti"),),
                ).fetchone()
                if binding is not None and binding["verified_at"] is not None:
                    raise BusinessIdentityError("ASSERTION_REPLAYED")
                if (
                    binding is None
                    or binding["used_at"] is None
                    or binding["revoked_at"] is not None
                    or any(
                        payload.get(claim) != binding[column]
                        for claim, column in (
                            ("tenant_id", "tenant_id"),
                            ("user_id", "user_id"),
                            ("session_id", "session_id"),
                            ("agent_id", "agent_id"),
                            ("release_id", "release_id"),
                            ("installation_id", "installation_id"),
                            ("invocation_id", "invocation_id"),
                            ("service_id", "service_id"),
                            ("aud", "audience"),
                            ("jti", "jti"),
                            ("iat", "issued_at"),
                            ("exp", "expires_at"),
                        )
                    )
                    or payload.get("scopes") != json.loads(binding["scopes_json"])
                ):
                    raise BusinessIdentityError("ASSERTION_REVOKED")
                service = db.execute(
                    "SELECT 1 FROM business_identity_services WHERE service_id=? AND revoked_at IS NULL",
                    (binding["service_id"],),
                ).fetchone()
                grant = db.execute(
                    "SELECT 1 FROM business_identity_grants WHERE grant_id=? AND revoked_at IS NULL",
                    (binding["grant_id"],),
                ).fetchone()
                if service is None or grant is None:
                    raise BusinessIdentityError("ASSERTION_REVOKED")
                if self._revoked(
                    db,
                    "installation",
                    str(binding["tenant_id"]),
                    str(binding["installation_id"]),
                ) or self._revoked(
                    db,
                    "release",
                    str(binding["tenant_id"]),
                    f'{binding["agent_id"]}:{binding["release_id"]}',
                ):
                    raise BusinessIdentityError("ASSERTION_REVOKED")
                changed = db.execute(
                    """
                    UPDATE business_identity_bindings SET verified_at=?
                    WHERE jti=? AND verified_at IS NULL
                    """,
                    (current, payload["jti"]),
                ).rowcount
                if changed != 1:
                    raise BusinessIdentityError("ASSERTION_REPLAYED")
            return payload
        except BusinessIdentityError:
            raise
        except Exception as exc:
            raise BusinessIdentityError("ASSERTION_INVALID") from exc

    def _consume_binding(self, binding_ref: str, identity: dict[str, Any], now: int) -> tuple[sqlite3.Row, dict[str, Any]]:
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM business_identity_bindings WHERE binding_ref=?",
                (binding_ref,),
            ).fetchone()
            if row is None or any(
                row[column] != identity[claim]
                for column, claim in (
                    ("tenant_id", "t"), ("user_id", "u"), ("session_id", "s"),
                    ("agent_id", "a"), ("release_id", "r"), ("installation_id", "g"),
                    ("invocation_id", "i"),
                )
            ):
                raise BusinessIdentityError("BINDING_UNKNOWN")
            if row["used_at"] is not None:
                raise BusinessIdentityError("BINDING_REPLAYED")
            if row["revoked_at"] is not None:
                raise BusinessIdentityError("BINDING_REVOKED")
            if row["expires_at"] <= now:
                raise BusinessIdentityError("BINDING_EXPIRED")
            service = db.execute(
                "SELECT * FROM business_identity_services WHERE service_id=? AND revoked_at IS NULL",
                (row["service_id"],),
            ).fetchone()
            grant = db.execute(
                "SELECT * FROM business_identity_grants WHERE grant_id=? AND revoked_at IS NULL",
                (row["grant_id"],),
            ).fetchone()
            key = db.execute(
                "SELECT * FROM business_identity_keys WHERE key_id=? AND revoked_at IS NULL",
                (row["key_id"],),
            ).fetchone()
            if service is None or grant is None:
                raise BusinessIdentityError("NOT_GRANTED")
            if key is None:
                raise BusinessIdentityError("SIGNER_UNAVAILABLE")
            if self._revoked(db, "installation", identity["t"], identity["g"]):
                raise BusinessIdentityError("INSTALLATION_REVOKED")
            if self._revoked(db, "release", identity["t"], f'{identity["a"]}:{identity["r"]}'):
                raise BusinessIdentityError("RELEASE_MISMATCH")
            changed = db.execute(
                "UPDATE business_identity_bindings SET used_at=? WHERE binding_ref=? AND used_at IS NULL",
                (now, binding_ref),
            ).rowcount
            if changed != 1:
                raise BusinessIdentityError("BINDING_REPLAYED")
            return row, dict(service)

    async def outbound_request(
        self,
        *,
        dclaw_session_token: str,
        binding_ref: str,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        text_body: str | None = None,
        timeout_seconds: int = 30,
        now: int | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        current_trace = trace_id or uuid.uuid4().hex
        identity: dict[str, Any] | None = None
        try:
            identity = self._identity(dclaw_session_token)
            return await self._outbound_request(
                identity=identity,
                binding_ref=binding_ref,
                method=method,
                url=url,
                headers=headers,
                json_body=json_body,
                text_body=text_body,
                timeout_seconds=timeout_seconds,
                now=now,
                trace_id=current_trace,
            )
        except BusinessIdentityError as exc:
            self._audit_denial(
                action="inject",
                error=exc,
                trace_id=current_trace,
                identity=identity,
                service_id=None,
                audience=None,
                scopes=None,
            )
            raise

    async def _outbound_request(
        self,
        *,
        identity: dict[str, Any],
        binding_ref: str,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        text_body: str | None = None,
        timeout_seconds: int = 30,
        now: int | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(binding_ref, str) or not re.fullmatch(r"bir_[0-9a-f]{32}", binding_ref):
            raise BusinessIdentityError("INVALID_REQUEST")
        method = str(method).upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise BusinessIdentityError("INVALID_REQUEST")
        if json_body is not None and text_body is not None:
            raise BusinessIdentityError("INVALID_REQUEST")
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 60:
            raise BusinessIdentityError("INVALID_REQUEST")
        host, origin = _validated_https_url(url)
        raw_body = _json(json_body).encode() if json_body is not None else (text_body or "").encode()
        if len(raw_body) > MAX_REQUEST_BYTES:
            raise BusinessIdentityError("INVALID_REQUEST")
        request_headers: dict[str, str] = {}
        for name, value in (headers or {}).items():
            lowered = str(name).lower()
            if lowered not in _SAFE_HEADERS or not isinstance(value, str) or len(value) > 2048:
                raise BusinessIdentityError("INVALID_REQUEST")
            request_headers[name] = value
        current = int(time.time()) if now is None else int(now)
        row, service = self._consume_binding(binding_ref, identity, current)
        allowed_domains = json.loads(service["allowed_domains_json"])
        _, audience_origin = _validated_https_url(
            str(row["audience"]),
            allow_query=False,
        )
        target_path = _validated_path(url)
        audience_path = _validated_path(str(row["audience"]))
        path_allowed = (
            audience_path == "/"
            or target_path == audience_path
            or target_path.startswith(audience_path.rstrip("/") + "/")
        )
        if host not in allowed_domains or origin != audience_origin or not path_allowed:
            raise BusinessIdentityError("AUDIENCE_NOT_ALLOWED")
        assertion = self._sign_assertion(row)
        request_headers["Authorization"] = f"Bearer {assertion}"
        if json_body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                follow_redirects=False,
                timeout=float(timeout_seconds),
            ) as client:
                async with client.stream(
                    method,
                    url,
                    headers=request_headers,
                    content=raw_body or None,
                ) as response:
                    if 300 <= response.status_code < 400:
                        raise BusinessIdentityError("REDIRECT_REJECTED")
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_size = int(content_length)
                        except ValueError as exc:
                            raise BusinessIdentityError("UPSTREAM_FAILED") from exc
                        if declared_size > MAX_RESPONSE_BYTES:
                            raise BusinessIdentityError("RESPONSE_TOO_LARGE")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise BusinessIdentityError("RESPONSE_TOO_LARGE")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    status_code = response.status_code
                    content_type = response.headers.get(
                        "content-type",
                        "application/octet-stream",
                    ).split(";", 1)[0]
            with self._lock, self._connect() as db:
                self._audit(
                    db, action="inject", actor_id=identity["u"], trace_id=trace_id,
                    result="allowed", reason_code="BUSINESS_IDENTITY.INJECTED", identity=identity,
                    service_id=row["service_id"], audience=row["audience"],
                    scopes=json.loads(row["scopes_json"]), key_id=row["key_id"],
                )
            result: dict[str, Any] = {
                "status_code": status_code,
                "content_type": content_type,
                "body_text": content.decode("utf-8", errors="replace"),
            }
            return result
        except BusinessIdentityError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            with self._lock, self._connect() as db:
                self._audit(
                    db, action="inject", actor_id=identity["u"], trace_id=trace_id,
                    result="denied", reason_code="BUSINESS_IDENTITY.UPSTREAM_FAILED",
                    identity=identity, service_id=row["service_id"], audience=row["audience"],
                    scopes=json.loads(row["scopes_json"]), key_id=row["key_id"],
                )
            raise BusinessIdentityError("UPSTREAM_FAILED") from exc

    def rotate_key(self, *, actor_id: str, emergency: bool = False) -> dict[str, Any]:
        now = int(time.time())
        new_key_id = f"bik_{uuid.uuid4().hex}"
        with self._lock, self._connect() as db:
            old = db.execute(
                "SELECT * FROM business_identity_keys WHERE status='active'",
            ).fetchone()
            db.execute(
                "INSERT INTO business_identity_keys(key_id,status,created_at) VALUES(?,?,?)",
                (new_key_id, "active", now),
            )
            if old is not None:
                status = "revoked" if emergency else "retired"
                db.execute(
                    "UPDATE business_identity_keys SET status=?,retired_at=?,revoked_at=? WHERE key_id=?",
                    (status, now, now if emergency else None, old["key_id"]),
                )
                if emergency:
                    db.execute(
                        "UPDATE business_identity_bindings SET revoked_at=? WHERE key_id=? AND used_at IS NULL",
                        (now, old["key_id"]),
                    )
            self._audit(
                db, action="rotate", actor_id=actor_id, trace_id=uuid.uuid4().hex,
                result="allowed", reason_code="BUSINESS_IDENTITY.KEY_ROTATED", key_id=new_key_id,
            )
        return {"key_id": new_key_id, "previous_key_id": old["key_id"] if old else None, "emergency": emergency}

    def revoke(
        self,
        *,
        actor_id: str,
        kind: str,
        tenant_id: str,
        subject_id: str,
        reason: str,
    ) -> dict[str, Any]:
        if kind not in {"service", "grant", "installation", "release", "key", "binding"}:
            raise BusinessIdentityError("INVALID_REQUEST")
        if not all(isinstance(value, str) and value for value in (tenant_id, subject_id, reason)):
            raise BusinessIdentityError("INVALID_REQUEST")
        now = int(time.time())
        with self._lock, self._connect() as db:
            if kind == "service":
                changed = db.execute(
                    "UPDATE business_identity_services SET revoked_at=? WHERE service_id=? AND revoked_at IS NULL",
                    (now, subject_id),
                ).rowcount
            elif kind == "grant":
                changed = db.execute(
                    "UPDATE business_identity_grants SET revoked_at=? WHERE grant_id=? AND revoked_at IS NULL",
                    (now, subject_id),
                ).rowcount
            elif kind == "key":
                changed = db.execute(
                    "UPDATE business_identity_keys SET status='revoked',revoked_at=? WHERE key_id=? AND revoked_at IS NULL",
                    (now, subject_id),
                ).rowcount
            elif kind == "binding":
                changed = db.execute(
                    "UPDATE business_identity_bindings SET revoked_at=? WHERE binding_ref=? AND revoked_at IS NULL",
                    (now, subject_id),
                ).rowcount
            else:
                db.execute(
                    """
                    INSERT INTO business_identity_revocations(
                        revocation_id,kind,tenant_id,subject_id,reason,created_at
                    ) VALUES(?,?,?,?,?,?)
                    ON CONFLICT(kind,tenant_id,subject_id) DO UPDATE SET
                        reason=excluded.reason,created_at=excluded.created_at
                    """,
                    (f"birv_{uuid.uuid4().hex}", kind, tenant_id, subject_id, reason, now),
                )
                changed = 1
            if not changed:
                raise BusinessIdentityError("REVOCATION_TARGET_UNKNOWN")
            self._audit(
                db, action="revoke", actor_id=actor_id, trace_id=uuid.uuid4().hex,
                result="allowed", reason_code=f"BUSINESS_IDENTITY.{kind.upper()}_REVOKED",
                identity={"t": tenant_id},
            )
        return {"revoked": True, "kind": kind, "tenant_id": tenant_id, "subject_id": subject_id}

    def audit_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
            raise BusinessIdentityError("INVALID_REQUEST")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM business_identity_audit ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["scopes"] = json.loads(item.pop("scopes_json"))
            result.append(item)
        return result
