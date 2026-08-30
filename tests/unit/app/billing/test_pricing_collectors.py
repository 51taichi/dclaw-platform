from decimal import Decimal

import pytest

from qwenpaw.app.billing.pricing_collectors import (
    CollectedPriceCandidate,
    CollectionStage,
    OfficialPageAiCollector,
    OfficialRegistryCollector,
    PricingCollectionPipeline,
    StructuredAiCollector,
)
from qwenpaw.app.billing.official_pricing import OfficialPriceRegistry
from qwenpaw.app.billing.pricing_inventory import PriceableModel


def _model() -> PriceableModel:
    return PriceableModel(
        provider_id="dashscope",
        provider_name="百炼",
        model_key="qwen3-max",
        model_name="Qwen3 Max",
        category="text",
        official_model_id="qwen3-max",
        pricing_region="cn-beijing",
    )


def _candidate(level: str) -> CollectedPriceCandidate:
    return CollectedPriceCandidate(
        provider_id="dashscope",
        official_model_id="qwen3-max",
        pricing_region="cn-beijing",
        capability="chat",
        unit_key="input_tokens",
        unit_size=1_000_000,
        conditions={"region": "cn-beijing"},
        original_currency="CNY",
        original_price=Decimal("2.5"),
        rmb_cost=Decimal("2.5"),
        source_url="https://help.aliyun.com/pricing",
        evidence_level=level,
        evidence_excerpt="Qwen3 Max input price",
        collector_version="test-v1",
        ai_model=None,
        prompt_version=None,
        confidence=Decimal("1"),
    )


class _Stage:
    def __init__(self, result=()):
        self.result = result
        self.calls = 0

    def collect(self, _model):
        self.calls += 1
        return self.result


class _FailingStage:
    def collect(self, _model):
        raise RuntimeError("official endpoint unavailable")


@pytest.mark.parametrize(
    ("winner", "level", "multiplier", "included"),
    [
        (0, "official_verified", Decimal("1.5"), True),
        (1, "ai_official_extract", Decimal("1.6"), False),
        (2, "ai_multi_source", Decimal("1.8"), False),
        (3, "ai_no_evidence", Decimal("2.0"), False),
    ],
)
def test_pipeline_uses_ordered_evidence_chain(
    winner, level, multiplier, included
):
    stages = [
        _Stage((_candidate(level),)) if index == winner else _Stage()
        for index in range(4)
    ]
    pipeline = PricingCollectionPipeline(
        tuple(
            CollectionStage(name=f"stage-{index}", collector=stage)
            for index, stage in enumerate(stages)
        )
    )

    result = pipeline.collect(_model())

    assert result.evidence_level == level
    assert result.default_multiplier == multiplier
    assert result.default_include_in_publish is included
    assert [stage.calls for stage in stages] == [
        1 if index <= winner else 0 for index in range(4)
    ]


def test_pipeline_returns_failed_nonpublish_result_when_all_stages_fail():
    result = PricingCollectionPipeline(
        (CollectionStage("official", _Stage()),)
    ).collect(_model())

    assert result.evidence_level == "failed"
    assert result.default_multiplier is None
    assert result.default_include_in_publish is False
    assert result.candidates == ()


def test_pipeline_continues_to_ai_fallback_after_official_stage_error():
    result = PricingCollectionPipeline(
        (
            CollectionStage("official", _FailingStage()),
            CollectionStage(
                "ai-official",
                _Stage((_candidate("ai_official_extract"),)),
            ),
        )
    ).collect(_model())

    assert result.evidence_level == "ai_official_extract"
    assert result.attempt_errors == (
        "official: official endpoint unavailable",
    )


def test_candidate_rejects_non_https_or_unapproved_source():
    candidate = _candidate("official_verified")

    with pytest.raises(ValueError, match="untrusted pricing source"):
        candidate.validate(frozenset({"www.volcengine.com"}))


def test_official_registry_collector_keeps_exact_endpoint_region():
    collector = OfficialRegistryCollector(
        OfficialPriceRegistry.load_bundled(),
        {
            "dashscope": frozenset(
                {"help.aliyun.com", "dashscope.aliyun.com"}
            )
        },
    )

    rows = collector.collect(_model())

    assert len(rows) == 6
    assert {row.pricing_region for row in rows} == {"cn-beijing"}
    assert {row.evidence_level for row in rows} == {"official_verified"}
    assert {row.unit_size for row in rows} == {1_000_000}


def test_structured_ai_collector_marks_no_evidence_estimate_nonofficial():
    collector = StructuredAiCollector(
        extractor=lambda _model, _evidence: [
            {
                "capability": "chat",
                "unit_key": "input_tokens",
                "unit_size": 1_000_000,
                "conditions": {"region": "cn-beijing"},
                "currency": "CNY",
                "price_decimal": "3",
                "fx_rate_decimal": "1",
                "source_urls": [],
                "confidence_decimal": "0.4",
                "evidence_excerpt": "无官网证据的保守估算",
            }
        ],
        evidence_level="ai_no_evidence",
        ai_model="pricing-helper",
        prompt_version="v1",
        collector_version="ai-v1",
        official_hosts=frozenset({"help.aliyun.com"}),
        evidence_blocks=(),
    )

    rows = collector.collect(_model())

    assert rows[0].evidence_level == "ai_no_evidence"
    assert rows[0].source_url is None
    assert rows[0].ai_model == "pricing-helper"


def test_official_page_ai_collector_fetches_provider_official_page():
    seen = []

    def extract(_model, evidence):
        seen.extend(evidence)
        return [
            {
                "capability": "chat",
                "unit_key": "input_tokens",
                "unit_size": 1_000_000,
                "conditions": {"region": "cn-beijing"},
                "currency": "CNY",
                "price_decimal": "3",
                "fx_rate_decimal": "1",
                "source_urls": ["https://help.aliyun.com/pricing"],
                "confidence_decimal": "0.8",
                "evidence_excerpt": "每百万 Token 3 元",
            }
        ]

    collector = OfficialPageAiCollector(
        page_urls={"dashscope": "https://help.aliyun.com/pricing"},
        official_hosts={"dashscope": frozenset({"help.aliyun.com"})},
        fetcher=lambda url: f"source={url}; 每百万 Token 3 元",
        extractor=extract,
        ai_model="qwen",
    )

    rows = collector.collect(_model())

    assert rows[0].evidence_level == "ai_official_extract"
    assert "https://help.aliyun.com/pricing" in seen[0]
