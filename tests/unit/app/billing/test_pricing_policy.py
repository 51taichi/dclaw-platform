from decimal import Decimal

from qwenpaw.app.billing.pricing_models import (
    ModelIdentity,
    PricingDefaults,
    PricingPolicy,
    TrustedCost,
)
from qwenpaw.app.billing.pricing_policy import (
    build_catalog_rules,
    price_cost,
    resolve_multiplier,
)

DEFAULTS = PricingDefaults()


def test_price_cost_applies_buffer_floor_and_ceiling_rounding():
    result = price_cost(
        TrustedCost(rmb_cost=Decimal("0.0100"), unit_key="input_tokens"),
        Decimal("1.1"),
        DEFAULTS,
    )
    assert result.applied_multiplier == Decimal("1.3")
    assert result.rmb_sale_price == Decimal("0.0136500")
    assert result.credits == 2


def test_resolve_multiplier_uses_most_specific_policy():
    policies = (
        PricingPolicy("global", "*", Decimal("1.4")),
        PricingPolicy("provider", "dashscope", Decimal("1.5")),
        PricingPolicy("category", "text", Decimal("1.6")),
        PricingPolicy("model", "dashscope/qwen-plus", Decimal("1.8")),
    )
    result = resolve_multiplier(
        policies,
        ModelIdentity("dashscope", "qwen-plus", "text"),
    )
    assert result.value == Decimal("1.8")
    assert result.scope_type == "model"


def test_build_token_rule_contains_server_calculation_snapshot():
    identity = ModelIdentity("dashscope", "qwen-plus", "text")
    rules = build_catalog_rules(
        (identity,),
        {
            ("dashscope", "qwen-plus", "input_tokens"):
                TrustedCost(Decimal("0.004"), "input_tokens"),
            ("dashscope", "qwen-plus", "output_tokens"):
                TrustedCost(Decimal("0.012"), "output_tokens"),
        },
        (PricingPolicy("global", "*", Decimal("1.5")),),
        DEFAULTS,
    )
    assert len(rules) == 1
    assert rules[0].input_credits_per_1k == 1
    assert rules[0].output_credits_per_1k == 2
    assert rules[0].metadata["currency"] == "CNY"
    assert rules[0].metadata["risk_buffer"] == "0.05"
    assert rules[0].metadata["multiplier_scope"] == "global"
