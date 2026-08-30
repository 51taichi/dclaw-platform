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


def test_builder_keeps_unmapped_custom_model_as_blocking_row():
    model = PriceableModel(
        "custom-provider", "Custom", "alias", "Alias", "text"
    )
    draft = PricingDraftBuilder(OfficialPriceRegistry.load_bundled()).build(
        [model], costs=[], mappings=[], exclusions=[]
    )

    assert len(draft.rows) == 1
    assert draft.rows[0].verification_status == "unmatched"
    assert draft.rows[0].include_in_publish is False
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
