from datetime import datetime, timedelta, timezone

import pytest

from qwenpaw.app.billing.pricing_unlock import (
    PricingUnlockDenied,
    PricingUnlockLimiter,
    PricingUnlockRateLimited,
    PricingUnlockService,
)


class MemoryRepo:
    def __init__(self):
        self.rows = {}

    def create_unlock(self, actor_id, token_hash, fingerprint, expires_at, ip_address):
        self.rows[token_hash] = (actor_id, fingerprint, expires_at)

    def validate_unlock(self, token_hash, actor_id, fingerprint, now):
        row = self.rows.get(token_hash)
        return bool(row and row[0] == actor_id and row[1] == fingerprint
                    and row[2] > now)


def test_unlock_requires_current_admin_password_and_expires():
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    service = PricingUnlockService(
        MemoryRepo(),
        credential_loader=lambda actor_id: ("hash", "salt", "admin"),
        password_verifier=lambda password, stored_hash, salt: password == "correct",
        clock=lambda: now,
        token_factory=lambda: "opaque-token",
    )
    with pytest.raises(PricingUnlockDenied):
        service.unlock("1", "wrong", "127.0.0.1")
    unlock = service.unlock("1", "correct", "127.0.0.1")
    assert unlock.expires_at == now + timedelta(minutes=15)
    assert service.is_valid(unlock.token, "1")


def test_non_admin_cannot_unlock():
    service = PricingUnlockService(
        MemoryRepo(), credential_loader=lambda actor_id: ("h", "s", "user"),
        password_verifier=lambda *_: True,
    )
    with pytest.raises(PricingUnlockDenied):
        service.unlock("2", "correct", None)


def test_repeated_failures_are_rate_limited():
    service = PricingUnlockService(
        MemoryRepo(), credential_loader=lambda actor_id: ("h", "s", "admin"),
        password_verifier=lambda *_: False,
        limiter=PricingUnlockLimiter(limit=2),
    )
    for _ in range(2):
        with pytest.raises(PricingUnlockDenied):
            service.unlock("rate-test", "wrong", "127.0.0.1")
    with pytest.raises(PricingUnlockRateLimited):
        service.unlock("rate-test", "wrong", "127.0.0.1")
