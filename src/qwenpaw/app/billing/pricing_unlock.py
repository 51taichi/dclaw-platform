"""Short-lived password re-verification for sensitive pricing commands."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol


class PricingUnlockDenied(PermissionError):
    """The actor is not an admin or the supplied password is invalid."""


class PricingUnlockRateLimited(PricingUnlockDenied):
    """Too many failed billing unlock attempts."""


class PricingUnlockLimiter:
    def __init__(self, limit: int = 5) -> None:
        self.limit = limit
        self.failures: dict[tuple[str, str | None], list[datetime]] = {}

    def check(self, key: tuple[str, str | None], now: datetime) -> None:
        cutoff = now - timedelta(minutes=15)
        recent = [
            value for value in self.failures.get(key, []) if value > cutoff
        ]
        self.failures[key] = recent
        if len(recent) >= self.limit:
            raise PricingUnlockRateLimited("pricing unlock rate limited")

    def failure(self, key: tuple[str, str | None], now: datetime) -> None:
        self.failures.setdefault(key, []).append(now)

    def success(self, key: tuple[str, str | None]) -> None:
        self.failures.pop(key, None)


class PersistentPricingUnlockLimiter:
    """Shared database limiter that survives workers and container restarts."""

    def __init__(self, repository: UnlockRepository, limit: int = 5) -> None:
        self.repository = repository
        self.limit = limit

    def check(self, key: tuple[str, str | None], now: datetime) -> None:
        failures = self.repository.recent_unlock_failures(
            key[0],
            key[1],
            now - timedelta(minutes=15),
        )
        if failures >= self.limit:
            raise PricingUnlockRateLimited("pricing unlock rate limited")

    def failure(self, key: tuple[str, str | None], now: datetime) -> None:
        self.repository.record_unlock_attempt(key[0], key[1], False, now)

    def success(
        self, key: tuple[str, str | None], now: datetime | None = None
    ) -> None:
        self.repository.record_unlock_attempt(
            key[0],
            key[1],
            True,
            now or datetime.now(timezone.utc),
        )


_UNLOCK_LIMITER = PricingUnlockLimiter()


class UnlockRepository(Protocol):
    def create_unlock(  # noqa: E704
        self,
        actor_id: str,
        token_hash: str,
        credential_fingerprint: str,
        expires_at: datetime,
        ip_address: str | None,
    ) -> str | None: ...

    def validate_unlock(  # noqa: E704
        self,
        token_hash: str,
        actor_id: str,
        credential_fingerprint: str,
        now: datetime,
    ) -> bool: ...

    def recent_unlock_failures(  # noqa: E704
        self, actor_id: str, ip_address: str | None, since: datetime
    ) -> int: ...

    def record_unlock_attempt(  # noqa: E704
        self,
        actor_id: str,
        ip_address: str | None,
        succeeded: bool,
        occurred_at: datetime,
    ) -> None: ...

    def append_audit(  # noqa: E704
        self,
        action: str,
        actor_id: str,
        before: dict,
        after: dict,
        metadata: dict | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class PricingUnlock:
    token: str
    expires_at: datetime


class PricingUnlockService:
    def __init__(
        self,
        repository: UnlockRepository,
        *,
        credential_loader: Callable[[str], tuple[str, str, str] | None],
        password_verifier: Callable[[str, str, str], bool],
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
        limiter: (
            PricingUnlockLimiter | PersistentPricingUnlockLimiter | None
        ) = None,
    ) -> None:
        self.repository = repository
        self.credential_loader = credential_loader
        self.password_verifier = password_verifier
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.token_factory = token_factory or (
            lambda: secrets.token_urlsafe(32)
        )
        self.limiter = limiter or _UNLOCK_LIMITER

    def unlock(
        self, actor_id: str, password: str, ip_address: str | None
    ) -> PricingUnlock:
        credentials = self.credential_loader(actor_id)
        now = self.clock()
        limit_key = (actor_id, ip_address)
        try:
            self.limiter.check(limit_key, now)
        except PricingUnlockRateLimited:
            self._audit("pricing.unlock_rate_limited", actor_id, ip_address)
            raise
        if credentials is None:
            self.limiter.failure(limit_key, now)
            self._audit("pricing.unlock_failed", actor_id, ip_address)
            raise PricingUnlockDenied("pricing unlock denied")
        stored_hash, salt, role = credentials
        if role != "admin" or not self.password_verifier(
            password,
            stored_hash,
            salt,
        ):
            self.limiter.failure(limit_key, now)
            self._audit("pricing.unlock_failed", actor_id, ip_address)
            raise PricingUnlockDenied("pricing unlock denied")
        if isinstance(self.limiter, PersistentPricingUnlockLimiter):
            self.limiter.success(limit_key, now)
        else:
            self.limiter.success(limit_key)
        expires_at = now + timedelta(minutes=15)
        token = self.token_factory()
        self.repository.create_unlock(
            actor_id,
            self._hash(token),
            self._fingerprint(credentials),
            expires_at,
            ip_address,
        )
        self._audit("pricing.unlock_succeeded", actor_id, ip_address)
        return PricingUnlock(token, expires_at)

    def _audit(
        self, action: str, actor_id: str, ip_address: str | None
    ) -> None:
        append = getattr(self.repository, "append_audit", None)
        if append is not None:
            append(action, actor_id, {}, {}, {"ip_address": ip_address})

    def is_valid(self, token: str, actor_id: str) -> bool:
        credentials = self.credential_loader(actor_id)
        if credentials is None or credentials[2] != "admin":
            return False
        return self.repository.validate_unlock(
            self._hash(token),
            actor_id,
            self._fingerprint(credentials),
            self.clock(),
        )

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint(credentials: tuple[str, str, str]) -> str:
        return hashlib.sha256(
            "\0".join(credentials).encode("utf-8")
        ).hexdigest()
