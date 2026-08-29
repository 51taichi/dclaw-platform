from datetime import datetime, timedelta, timezone

import pytest

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.pricing_admin_repo import (
    PricingAdminRepository,
    PricingRevisionConflict,
)
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def repo(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "db.sqlite")}),
    )
    create_all(engine)
    try:
        yield PricingAdminRepository(engine)
    finally:
        engine.dispose()


def _cost(amount: str, verified_at: datetime) -> dict:
    return {
        "provider_id": "dashscope",
        "model_key": "qwen-plus",
        "capability": "chat",
        "unit_key": "input_tokens",
        "source_type": "manual",
        "source_reference": "official-price-page",
        "original_currency": "CNY",
        "original_price_decimal": amount,
        "fx_rate_decimal": "1",
        "rmb_cost_decimal": amount,
        "conditions": {},
        "verification_status": "verified",
        "verified_at": verified_at,
    }


def test_latest_trusted_cost_preserves_history(repo):
    now = datetime.now(timezone.utc)
    first = repo.append_cost_snapshot(_cost("0.004", now))
    second = repo.append_cost_snapshot(_cost("0.006", now + timedelta(seconds=1)))
    assert first != second
    assert repo.latest_trusted_costs()[0]["rmb_cost_decimal"] == "0.006"
    assert len(repo.list_cost_snapshots()) == 2


def test_policy_rejects_stale_revision(repo):
    saved = repo.replace_policy(
        scope_type="global", scope_key="*", multiplier_decimal="1.5",
        settings={}, actor_id="1", expected_revision=0,
    )
    assert saved["revision"] == 1
    with pytest.raises(PricingRevisionConflict):
        repo.replace_policy(
            scope_type="global", scope_key="*", multiplier_decimal="1.6",
            settings={}, actor_id="1", expected_revision=0,
        )


def test_import_is_idempotent_and_unlock_expires(repo):
    first = repo.record_import("abc", "prices.xlsx", "1", {"rows": 1})
    second = repo.record_import("abc", "renamed.xlsx", "1", {"rows": 1})
    assert first["id"] == second["id"]

    now = datetime.now(timezone.utc)
    repo.create_unlock("1", "token-hash", now + timedelta(minutes=15), "127.0.0.1")
    assert repo.validate_unlock("token-hash", "1", now)
    assert not repo.validate_unlock("token-hash", "1", now + timedelta(minutes=16))
