from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from qwenpaw.app.billing.pricing_sync import (
    PricingSource,
    PricingSyncService,
    ProtectionRateLimited,
    refresh_official_candidates,
)
from qwenpaw.app.billing.official_pricing import OfficialPriceRegistry
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


class Adapter:
    def __init__(self):
        self.calls = 0

    def fetch(self):
        self.calls += 1
        return ()


def test_daily_check_respects_each_source_interval():
    daily, weekly = Adapter(), Adapter()
    service = PricingSyncService(
        (
            PricingSource("official", "official_api", daily),
            PricingSource("aggregator", "aggregator", weekly),
        )
    )
    assert service.check_due_sources(NOW) == ("official", "aggregator")
    assert service.check_due_sources(NOW + timedelta(days=1)) == ("official",)
    assert daily.calls == 2
    assert weekly.calls == 1


def test_protection_caps_raise_and_rate_limits_model():
    published = []
    service = PricingSyncService((), protection_publisher=published.append)
    result = service.apply_protection(
        "dashscope/qwen-plus",
        Decimal("0.35"),
        NOW,
    )
    assert result.applied_raise == Decimal("0.20")
    assert result.remaining_risk == Decimal("0.15")
    assert result.alert_level == "critical"
    assert published == [result]
    with pytest.raises(ProtectionRateLimited):
        service.apply_protection(
            "dashscope/qwen-plus",
            Decimal("0.10"),
            NOW + timedelta(hours=1),
        )


def test_supplier_decrease_never_auto_publishes():
    published = []
    service = PricingSyncService((), protection_publisher=published.append)
    result = service.apply_protection(
        "dashscope/qwen-plus",
        Decimal("-0.10"),
        NOW,
    )
    assert result.requires_review is True
    assert result.applied_raise == Decimal(0)
    assert published == []


def test_protection_rate_limit_survives_service_restart(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {
                "QWENPAW_SQLITE_PATH": str(tmp_path / "sync-state.db"),
            }
        )
    )
    create_all(engine)
    state = PricingAdminRepository(engine)
    PricingSyncService((), state_store=state).apply_protection(
        "dashscope/qwen-plus",
        Decimal("0.10"),
        NOW,
    )

    restarted = PricingSyncService((), state_store=state)
    with pytest.raises(ProtectionRateLimited):
        restarted.apply_protection(
            "dashscope/qwen-plus",
            Decimal("0.10"),
            NOW + timedelta(hours=1),
        )
    engine.dispose()


def test_official_refresh_appends_candidates_without_trusting_or_publishing(
    tmp_path,
):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "candidates.db")}
        )
    )
    create_all(engine)
    repo = PricingAdminRepository(engine)

    first = refresh_official_candidates(
        OfficialPriceRegistry.load_bundled(), repo
    )
    second = refresh_official_candidates(
        OfficialPriceRegistry.load_bundled(), repo
    )

    assert first["candidate_count"] == 6
    assert second == first
    candidates = repo.latest_official_candidates()
    assert len(candidates) == 6
    assert {row["evidence_level"] for row in candidates} == {
        "official_verified"
    }
    assert {row["default_multiplier_decimal"] for row in candidates} == {
        "1.5"
    }
    assert all(row["collector_version"] for row in candidates)
    assert repo.latest_trusted_costs() == []
    engine.dispose()
