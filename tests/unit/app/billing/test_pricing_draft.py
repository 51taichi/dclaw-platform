import json
from decimal import Decimal

from qwenpaw.app.billing.official_pricing import OfficialPriceRegistry
from qwenpaw.app.billing.pricing_draft import PricingDraftBuilder
from qwenpaw.app.billing.pricing_inventory import PriceableModel


def test_builder_expands_verified_dimensions_with_default_multiplier():
    model = PriceableModel(
        "dashscope",
        "百炼",
        "qwen3-max",
        "Qwen3 Max",
        "text",
        official_model_id="qwen3-max",
        pricing_region="cn-beijing",
    )
    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], costs=[], mappings=[], exclusions=[]
    )

    assert len(draft.rows) == 6
    assert {row.unit_key for row in draft.rows} == {
        "input_tokens",
        "output_tokens",
    }
    assert all(row.multiplier == Decimal("1.5") for row in draft.rows)
    first = draft.rows[0]
    assert first.rmb_sale_price == first.rmb_cost * Decimal("1.5")
    assert first.credits > 0
    assert draft.coverage.matched_models == 1
    assert draft.coverage.missing_models == 0


def test_builder_expands_unpriced_text_model_into_fillable_token_dimensions():
    model = PriceableModel(
        "custom-provider", "Custom", "alias", "Alias", "text"
    )
    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], costs=[], mappings=[], exclusions=[]
    )

    assert len(draft.rows) == 2
    assert {row.unit_key for row in draft.rows} == {
        "input_tokens",
        "output_tokens",
    }
    assert all(row.capability == "chat" for row in draft.rows)
    assert all(row.unit_size == 1_000_000 for row in draft.rows)
    assert all(row.conditions == {} for row in draft.rows)
    assert all(row.rmb_cost is None for row in draft.rows)
    assert all(row.source_type == "manual" for row in draft.rows)
    assert all(
        row.verification_status == "manual_pending" for row in draft.rows
    )
    assert all(row.include_in_publish is True for row in draft.rows)
    assert all(row.approval_reason == "管理员人工定价" for row in draft.rows)
    assert draft.risks[0].code == "official_model_unmatched"


def test_explicit_mapping_and_verified_cost_override_are_used():
    model = PriceableModel(
        "custom-provider", "Custom", "alias", "Alias", "text"
    )
    costs = [
        {
            "provider_id": "custom-provider",
            "model_key": "alias",
            "capability": "chat",
            "unit_key": "input_tokens",
            "rmb_cost_decimal": "3",
            "verification_status": "verified",
            "conditions_json": "{}",
        }
    ]
    mappings = [
        {
            "provider_id": "custom-provider",
            "model_key": "alias",
            "official_provider_id": "dashscope",
            "official_model_id": "qwen3-max",
        }
    ]
    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], costs, mappings, exclusions=[]
    )

    override = next(
        row for row in draft.rows if row.unit_key == "input_tokens"
    )
    assert override.rmb_cost == Decimal("3")
    assert override.source_type == "trusted_cost"


def test_exclusion_resolves_missing_model_only_with_reason():
    model = PriceableModel(
        "volcengine-cn",
        "火山方舟",
        "unknown",
        "Unknown",
        "text",
        official_model_id="unknown",
    )
    exclusions = [
        {
            "provider_id": "volcengine-cn",
            "model_key": "unknown",
            "excluded": True,
            "reason": "Official price is not published",
        }
    ]
    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], [], [], exclusions
    )

    assert draft.coverage.excluded_models == 1
    assert draft.coverage.blocking_models == 0


def test_verified_tier_cost_overrides_only_the_same_conditions():
    model = PriceableModel(
        "dashscope",
        "百炼",
        "qwen3-max",
        "Qwen3 Max",
        "text",
        official_model_id="qwen3-max",
        pricing_region="cn-beijing",
    )
    conditions = {
        "input_tokens_min_exclusive": 0,
        "input_tokens_max": 32000,
        "region": "cn-beijing",
    }
    costs = [
        {
            "provider_id": "dashscope",
            "model_key": "qwen3-max",
            "capability": "chat",
            "unit_key": "input_tokens",
            "rmb_cost_decimal": "9.99",
            "verification_status": "verified",
            "conditions_json": (
                '{"input_tokens_max":32000,'
                '"input_tokens_min_exclusive":0,"region":"cn-beijing"}'
            ),
        }
    ]

    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], costs, [], []
    )

    inputs = [row for row in draft.rows if row.unit_key == "input_tokens"]
    assert len(inputs) == 3
    assert sum(row.conditions == conditions for row in inputs) == 1
    matching = next(row for row in inputs if row.conditions == conditions)
    others = [row for row in inputs if row.conditions != conditions]
    assert matching.rmb_cost == Decimal("9.99")
    assert all(row.rmb_cost != Decimal("9.99") for row in others)


def test_verified_manual_costs_cover_model_without_bundled_registry():
    model = PriceableModel(
        "custom-provider", "Custom", "private-model", "Private", "text"
    )
    costs = [
        {
            "provider_id": "custom-provider",
            "model_key": "private-model",
            "capability": "chat",
            "unit_key": unit,
            "rmb_cost_decimal": amount,
            "verification_status": "verified",
            "conditions_json": '{"unit_size":1000}',
        }
        for unit, amount in (
            ("input_tokens", "0.01"),
            ("output_tokens", "0.02"),
        )
    ]

    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], costs, [], []
    )

    assert draft.coverage.matched_models == 1
    assert draft.coverage.missing_models == 0
    assert {row.unit_key for row in draft.rows} == {
        "input_tokens",
        "output_tokens",
    }
    assert all(row.source_type == "trusted_cost" for row in draft.rows)


def test_legacy_token_cost_without_unit_size_keeps_per_million_semantics():
    model = PriceableModel(
        "custom-provider", "Custom", "private-model", "Private", "text"
    )
    costs = [
        {
            "provider_id": "custom-provider",
            "model_key": "private-model",
            "capability": "chat",
            "unit_key": unit,
            "rmb_cost_decimal": amount,
            "verification_status": "verified",
            "conditions_json": "{}",
        }
        for unit, amount in (
            ("input_tokens", "76"),
            ("output_tokens", "341"),
        )
    ]

    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], costs, [], []
    )

    assert {row.unit_size for row in draft.rows} == {1_000_000}


def test_region_specific_registry_price_never_crosses_provider_endpoint():
    singapore = PriceableModel(
        "dashscope",
        "DashScope",
        "qwen3-max",
        "Qwen3 Max",
        "text",
        official_model_id="qwen3-max",
        pricing_region="ap-southeast-1",
    )

    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [singapore],
        [
            {
                "provider_id": "dashscope",
                "model_key": "qwen3-max",
                "capability": "chat",
                "unit_key": "input_tokens",
                "rmb_cost_decimal": "2.5",
                "verification_status": "verified",
                "conditions_json": '{"region":"cn-beijing"}',
            }
        ],
        [],
        [],
    )

    assert {row.source_type for row in draft.rows} == {"manual"}
    assert {row.unit_key for row in draft.rows} == {
        "input_tokens",
        "output_tokens",
    }
    assert draft.coverage.blocking_models == 1


def test_ai_estimate_candidate_appears_with_safe_multiplier_and_nonpublish():
    builder = PricingDraftBuilder(OfficialPriceRegistry.from_records(()))
    model = PriceableModel(
        "dashscope",
        "百炼",
        "future-model",
        "Future Model",
        "text",
        official_model_id="future-model",
        pricing_region="cn-beijing",
    )
    candidate = {
        "provider_id": "dashscope",
        "official_model_id": "future-model",
        "capability": "chat",
        "unit_key": "input_tokens",
        "conditions_json": ('{"region":"cn-beijing","unit_size":1000000}'),
        "source_url": "",
        "rmb_cost_decimal": "3",
        "evidence_level": "ai_no_evidence",
        "verification_status": "candidate",
        "registry_version": "ai-v1",
        "default_multiplier_decimal": "2.0",
    }

    result = builder.build((model,), (), (), (), (candidate,), ())

    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.evidence_level == "ai_no_evidence"
    assert row.multiplier == Decimal("2.0")
    assert row.include_in_publish is False
    assert row.rmb_sale_price == Decimal("6.0")


def test_latest_collected_candidate_overrides_bundled_registry_price():
    builder = PricingDraftBuilder(OfficialPriceRegistry.load_bundled())
    model = PriceableModel(
        "dashscope",
        "百炼",
        "qwen3-max",
        "Qwen3 Max",
        "text",
        official_model_id="qwen3-max",
        pricing_region="cn-beijing",
    )
    candidate = {
        "provider_id": "dashscope",
        "official_model_id": "qwen3-max",
        "capability": "chat",
        "unit_key": "input_tokens",
        "conditions_json": json.dumps(
            {"region": "cn-beijing", "unit_size": 1_000_000}
        ),
        "source_url": "https://help.aliyun.com/new-pricing",
        "rmb_cost_decimal": "4.0",
        "evidence_level": "official_verified",
        "verification_status": "verified",
        "registry_version": "new",
        "default_multiplier_decimal": "1.5",
    }

    result = builder.build((model,), (), (), (), (candidate,), ())

    assert len(result.rows) == 1
    assert result.rows[0].rmb_cost == Decimal("4.0")
    assert result.rows[0].registry_version == "new"
