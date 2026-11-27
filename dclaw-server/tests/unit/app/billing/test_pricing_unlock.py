from datetime import datetime, timedelta, timezone

import pytest

from qwenpaw.app.billing.pricing_unlock import (
    PersistentPricingUnlockLimiter,
    PricingUnlockDenied,
    PricingUnlockLimiter,
    PricingUnlockRateLimited,
    PricingUnlockService,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


class MemoryRepo:
    def __init__(self):
        self.rows = {}

    def create_unlock(
        self, actor_id, token_hash, fingerprint, expires_at, ip_address
    ):
        self.rows[token_hash] = (actor_id, fingerprint, expires_at)

    def validate_unlock(self, token_hash, actor_id, fingerprint, now):
        row = self.rows.get(token_hash)
        return bool(
            row
            and row[0] == actor_id
            and row[1] == fingerprint
            and row[2] > now
        )


def test_unlock_requires_current_admin_password_and_expires():
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    service = PricingUnlockService(
        MemoryRepo(),
        credential_loader=lambda actor_id: ("hash", "salt", "admin"),
        password_verifier=lambda password, stored_hash, salt: password
        == "correct",
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
        MemoryRepo(),
        credential_loader=lambda actor_id: ("h", "s", "user"),
        password_verifier=lambda *_: True,
    )
    with pytest.raises(PricingUnlockDenied):
        service.unlock("2", "correct", None)


def test_repeated_failures_are_rate_limited():
    service = PricingUnlockService(
        MemoryRepo(),
        credential_loader=lambda actor_id: ("h", "s", "admin"),
        password_verifier=lambda *_: False,
        limiter=PricingUnlockLimiter(limit=2),
    )
    for _ in range(2):
        with pytest.raises(PricingUnlockDenied):
            service.unlock("rate-test", "wrong", "127.0.0.1")
    with pytest.raises(PricingUnlockRateLimited):
        service.unlock("rate-test", "wrong", "127.0.0.1")


def test_unlock_failures_are_shared_and_security_audited(tmp_path):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    engine = create_engine_from_settings(
        get_storage_settings(
            {
                "QWENPAW_SQLITE_PATH": str(tmp_path / "unlock-rate.db"),
            }
        )
    )
    create_all(engine)
    repo = PricingAdminRepository(engine)

    def service():
        return PricingUnlockService(
            repo,
            credential_loader=lambda _actor: ("h", "s", "admin"),
            password_verifier=lambda *_: False,
            clock=lambda: now,
            limiter=PersistentPricingUnlockLimiter(repo, limit=1),
        )

    with pytest.raises(PricingUnlockDenied):
        service().unlock("1", "wrong", "10.0.0.1")
    with pytest.raises(PricingUnlockRateLimited):
        service().unlock("1", "wrong", "10.0.0.1")

    actions = {row["action"] for row in repo.list_audits()}
    assert actions == {"pricing.unlock_rate_limited", "pricing.unlock_failed"}
    engine.dispose()
