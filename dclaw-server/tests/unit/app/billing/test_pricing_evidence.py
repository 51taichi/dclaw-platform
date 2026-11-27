from decimal import Decimal

import pytest
from pydantic import ValidationError

from qwenpaw.app.billing.pricing_evidence import AiPriceExtraction


def _payload():
    return {
        "capability": "chat",
        "unit_key": "input_tokens",
        "unit_size": 1_000_000,
        "conditions": {"region": "cn-beijing"},
        "currency": "CNY",
        "price_decimal": "2.5",
        "fx_rate_decimal": "1",
        "source_urls": ["https://help.aliyun.com/zh/model-studio/model-pricing"],
        "confidence_decimal": "0.95",
        "evidence_excerpt": "输入价格为每百万 Token 2.5 元",
    }


def test_ai_price_extraction_accepts_strict_structured_evidence():
    result = AiPriceExtraction.model_validate(_payload())

    assert result.price_decimal == Decimal("2.5")
    assert result.rmb_cost == Decimal("2.5")


def test_ai_price_extraction_rejects_extra_fields_and_invalid_confidence():
    payload = _payload() | {
        "confidence_decimal": "1.1",
        "pretend_verified": True,
    }

    with pytest.raises(ValidationError):
        AiPriceExtraction.model_validate(payload)

