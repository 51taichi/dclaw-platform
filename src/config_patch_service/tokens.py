"""Employee token issuance and verification."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from .audit import AuditService
from .db import ConfigPatchDatabase
from .models import AuthenticatedStaffToken, IssuedStaffToken, StaffTokenView


TOKEN_PREFIX = "dclaw_staff_"


class StaffTokenError(RuntimeError):
    pass


class InvalidStaffTokenError(StaffTokenError):
    pass


class ExpiredStaffTokenError(StaffTokenError):
    pass


class RevokedStaffTokenError(StaffTokenError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    return _as_utc(datetime.fromisoformat(value)) if value else None


class StaffTokenService:
    def __init__(
        self,
        database: ConfigPatchDatabase,
        *,
        pepper: str,
        audit: AuditService,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not pepper:
            raise ValueError("token pepper is required")
        self._database = database
        self._pepper = pepper.encode("utf-8")
        self._audit = audit
        self._clock = clock

    def _now(self) -> datetime:
        return _as_utc(self._clock())

    def _digest(self, raw_token: str) -> str:
        return hmac.new(self._pepper, raw_token.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _new_raw_token() -> str:
        return TOKEN_PREFIX + secrets.token_urlsafe(36)

    @staticmethod
    def _view(row: sqlite3.Row) -> StaffTokenView:
        return StaffTokenView(
            token_id=row["id"],
            employee_name=row["employee_name"],
            token_name=row["token_name"],
            token_prefix=row["token_prefix"],
            token_suffix=row["token_suffix"],
            expires_at=_parse_datetime(row["expires_at"]),
            revoked_at=_parse_datetime(row["revoked_at"]),
            last_used_at=_parse_datetime(row["last_used_at"]),
            created_at=_parse_datetime(row["created_at"]),
            updated_at=_parse_datetime(row["updated_at"]),
        )

    def create(
        self,
        *,
        employee_name: str,
        token_name: str,
        expires_at: datetime | None = None,
    ) -> IssuedStaffToken:
        employee_name = str(employee_name).strip()
        token_name = str(token_name).strip()
        if not employee_name or not token_name:
            raise ValueError("employee_name and token_name are required")
        raw_token = self._new_raw_token()
        token_id = uuid.uuid4().hex
        timestamp = self._now().isoformat()
        normalized_expiry = _as_utc(expires_at).isoformat() if expires_at else None
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO staff_tokens (
                    id, token_hmac, token_prefix, token_suffix, employee_name,
                    token_name, expires_at, revoked_at, last_used_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (
                    token_id,
                    self._digest(raw_token),
                    raw_token[:20],
                    raw_token[-4:],
                    employee_name,
                    token_name,
                    normalized_expiry,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM staff_tokens WHERE id = ?", (token_id,)
            ).fetchone()
        self._audit.record(
            "staff_token.create",
            token_id=token_id,
            employee_name=employee_name,
            result="success",
        )
        return IssuedStaffToken(**self._view(row).model_dump(), token=raw_token)

    def list(self) -> list[StaffTokenView]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM staff_tokens ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [self._view(row) for row in rows]

    def _get(self, token_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                "SELECT * FROM staff_tokens WHERE id = ?", (token_id,)
            ).fetchone()

    def revoke(self, token_id: str) -> StaffTokenView:
        existing = self._get(token_id)
        if existing is None:
            raise KeyError(token_id)
        timestamp = self._now().isoformat()
        with self._database.transaction() as connection:
            connection.execute(
                """
                UPDATE staff_tokens
                SET revoked_at = COALESCE(revoked_at, ?), updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, token_id),
            )
            row = connection.execute(
                "SELECT * FROM staff_tokens WHERE id = ?", (token_id,)
            ).fetchone()
        self._audit.record(
            "staff_token.revoke",
            token_id=token_id,
            employee_name=row["employee_name"],
            result="success",
        )
        return self._view(row)

    def rotate(self, token_id: str) -> IssuedStaffToken:
        existing = self._get(token_id)
        if existing is None:
            raise KeyError(token_id)
        raw_token = self._new_raw_token()
        timestamp = self._now().isoformat()
        with self._database.transaction() as connection:
            connection.execute(
                """
                UPDATE staff_tokens
                SET token_hmac = ?, token_prefix = ?, token_suffix = ?,
                    revoked_at = NULL, last_used_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    self._digest(raw_token),
                    raw_token[:20],
                    raw_token[-4:],
                    timestamp,
                    token_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM staff_tokens WHERE id = ?", (token_id,)
            ).fetchone()
        self._audit.record(
            "staff_token.rotate",
            token_id=token_id,
            employee_name=row["employee_name"],
            result="success",
        )
        return IssuedStaffToken(**self._view(row).model_dump(), token=raw_token)

    def authenticate(self, raw_token: str) -> AuthenticatedStaffToken:
        if not raw_token or not raw_token.startswith(TOKEN_PREFIX):
            self._audit.record("staff_token.authenticate", result="failure", metadata={"reason": "invalid"})
            raise InvalidStaffTokenError("invalid staff token")

        candidate = self._digest(raw_token)
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM staff_tokens ORDER BY id").fetchall()
        row = next(
            (stored for stored in rows if hmac.compare_digest(candidate, stored["token_hmac"])),
            None,
        )
        if row is None:
            self._audit.record("staff_token.authenticate", result="failure", metadata={"reason": "invalid"})
            raise InvalidStaffTokenError("invalid staff token")

        token_id = row["id"]
        employee_name = row["employee_name"]
        if row["revoked_at"]:
            self._audit.record(
                "staff_token.authenticate",
                token_id=token_id,
                employee_name=employee_name,
                result="failure",
                metadata={"reason": "revoked"},
            )
            raise RevokedStaffTokenError("staff token is revoked")

        now = self._now()
        expires_at = _parse_datetime(row["expires_at"])
        if expires_at is not None and now >= expires_at:
            self._audit.record(
                "staff_token.authenticate",
                token_id=token_id,
                employee_name=employee_name,
                result="failure",
                metadata={"reason": "expired"},
            )
            raise ExpiredStaffTokenError("staff token is expired")

        last_used_at = _parse_datetime(row["last_used_at"])
        if last_used_at is None or now - last_used_at >= timedelta(minutes=1):
            with self._database.transaction() as connection:
                connection.execute(
                    "UPDATE staff_tokens SET last_used_at = ?, updated_at = ? WHERE id = ?",
                    (now.isoformat(), now.isoformat(), token_id),
                )
        self._audit.record(
            "staff_token.authenticate",
            token_id=token_id,
            employee_name=employee_name,
            result="success",
        )
        return AuthenticatedStaffToken(
            token_id=token_id,
            employee_name=employee_name,
            token_name=row["token_name"],
        )
