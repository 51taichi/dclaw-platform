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
        recent = [value for value in self.failures.get(key, []) if value > cutoff]
        self.failures[key] = recent
        if len(recent) >= self.limit:
            raise PricingUnlockRateLimited("pricing unlock rate limited")

    def failure(self, key: tuple[str, str | None], now: datetime) -> None:
        self.failures.setdefault(key, []).append(now)

    def success(self, key: tuple[str, str | None]) -> None:
        self.failures.pop(key, None)


_UNLOCK_LIMITER = PricingUnlockLimiter()


class UnlockRepository(Protocol):
    def create_unlock(self, actor_id: str, token_hash: str,
                      credential_fingerprint: str,
                      expires_at: datetime, ip_address: str | None) -> str | None: ...
    def validate_unlock(self, token_hash: str, actor_id: str,
                        credential_fingerprint: str,
                        now: datetime) -> bool: ...


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
        limiter: PricingUnlockLimiter | None = None,
    ) -> None:
        self.repository = repository
        self.credential_loader = credential_loader
        self.password_verifier = password_verifier
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self.limiter = limiter or _UNLOCK_LIMITER

    def unlock(self, actor_id: str, password: str,
               ip_address: str | None) -> PricingUnlock:
        credentials = self.credential_loader(actor_id)
        now = self.clock()
        limit_key = (actor_id, ip_address)
        self.limiter.check(limit_key, now)
        if credentials is None:
            self.limiter.failure(limit_key, now)
            raise PricingUnlockDenied("pricing unlock denied")
        stored_hash, salt, role = credentials
        if role != "admin" or not self.password_verifier(
            password, stored_hash, salt,
        ):
            self.limiter.failure(limit_key, now)
            raise PricingUnlockDenied("pricing unlock denied")
        self.limiter.success(limit_key)
        expires_at = now + timedelta(minutes=15)
        token = self.token_factory()
        self.repository.create_unlock(
            actor_id, self._hash(token), self._fingerprint(credentials),
            expires_at, ip_address,
        )
        return PricingUnlock(token, expires_at)

    def is_valid(self, token: str, actor_id: str) -> bool:
        credentials = self.credential_loader(actor_id)
        if credentials is None or credentials[2] != "admin":
            return False
        return self.repository.validate_unlock(
            self._hash(token), actor_id, self._fingerprint(credentials),
            self.clock(),
        )

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint(credentials: tuple[str, str, str]) -> str:
        return hashlib.sha256("\0".join(credentials).encode("utf-8")).hexdigest()
