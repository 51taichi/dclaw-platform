from decimal import Decimal

import pytest

from qwenpaw.app.billing.official_pricing import (
    OfficialPriceRegistry,
    OfficialPriceRegistryError,
)


def _row(**overrides):
    row = {
        "provider_id": "dashscope",
        "official_model_id": "qwen3-max",
        "capability": "chat",
        "unit_key": "input_tokens",
        "unit_size": 1_000_000,
        "conditions": {"input_tokens_max": 32_000},
        "original_currency": "CNY",
        "original_price_decimal": "2.5",
        "fx_rate_decimal": "1",
        "source_url": "https://help.aliyun.com/zh/model-studio/model-pricing",
        "source_published_at": None,
        "collected_at": "2026-08-30T00:00:00+08:00",
        "verification_status": "verified",
        "registry_version": "2026-08-30",
    }
    row.update(overrides)
    return row


def test_registry_rejects_duplicate_dimensions_and_float_prices():
    with pytest.raises(
        OfficialPriceRegistryError, match="duplicate dimension"
    ):
        OfficialPriceRegistry.from_records([_row(), _row()])

    with pytest.raises(OfficialPriceRegistryError, match="decimal string"):
        OfficialPriceRegistry.from_records([_row(original_price_decimal=2.5)])


def test_registry_requires_verifiable_evidence():
    with pytest.raises(OfficialPriceRegistryError, match="source_url"):
        OfficialPriceRegistry.from_records([_row(source_url="")])
    with pytest.raises(OfficialPriceRegistryError, match="currency"):
        OfficialPriceRegistry.from_records([_row(original_currency="DOGE")])
    with pytest.raises(OfficialPriceRegistryError, match="verified"):
        OfficialPriceRegistry.from_records(
            [_row(verification_status="unverified")]
        )
    with pytest.raises(OfficialPriceRegistryError, match="registry_version"):
        OfficialPriceRegistry.from_records([_row(registry_version="")])


def test_bundled_registry_contains_reviewed_multidimensional_prices():
    registry = OfficialPriceRegistry.load_bundled()
    dimensions = registry.dimensions("dashscope", "qwen3-max")

    assert {row.unit_key for row in dimensions} == {
        "input_tokens",
        "output_tokens",
    }
    assert len(dimensions) == 6
    assert dimensions[0].rmb_cost > Decimal("0")
    assert all(row.registry_version == "2026-08-30" for row in dimensions)
    assert registry.dimensions("volcengine-cn", "unverified-model") == ()
