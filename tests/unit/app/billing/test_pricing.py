# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from qwenpaw.app.billing.pricing import (
    AmbiguousPriceRuleError,
    CatalogImmutableError,
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
    QuoteRequest,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock():
    return MutableClock(datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "pricing.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def repo(engine):
    return PriceCatalogRepository(engine)


@pytest.fixture
def service(repo, clock):
    return PriceCatalogService(repo, clock=clock)


def _rule(
    rule_id: str,
    unit_type: str,
    *,
    provider_id: str = "aliyun",
    model_key: str = "model-1",
    capability: str = "generate",
    priority: int = 0,
    unit_size: int = 1,
    credits_per_unit: int = 0,
    input_credits_per_1k: int = 0,
    output_credits_per_1k: int = 0,
    parameter_match: dict | None = None,
) -> PriceRule:
    return PriceRule(
        id=rule_id,
        provider_id=provider_id,
        model_key=model_key,
        capability=capability,
        unit_type=unit_type,
        priority=priority,
        unit_size=unit_size,
        credits_per_unit=credits_per_unit,
        input_credits_per_1k=input_credits_per_1k,
        output_credits_per_1k=output_credits_per_1k,
        parameter_match=parameter_match or {},
    )


def _catalog(
    version: str,
    clock: MutableClock,
    *rules: PriceRule,
) -> PriceCatalogDraft:
    return PriceCatalogDraft(
        version=version,
        effective_at=clock.now,
        rules=rules,
        created_by="admin:pricing-test",
    )


def test_token_rates_round_each_input_and_output_component_up(service, clock):
    service.publish(
        _catalog(
            "2026-08-token",
            clock,
            _rule(
                "text-standard",
                "tokens",
                capability="chat",
                input_credits_per_1k=2,
                output_credits_per_1k=5,
            ),
        ),
    )

    quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "chat",
            {},
            input_tokens=1_001,
            output_tokens=1,
        ),
    )

    assert quote.credits == 4
    assert quote.unit_breakdown == {"input_tokens": 3, "output_tokens": 1}
    assert quote.snapshot["usage"] == {
        "input_tokens": 1_001,
        "output_tokens": 1,
    }
    assert quote.snapshot["request"]["input_tokens"] == 1_001
    assert quote.snapshot["request"]["output_tokens"] == 1


def test_image_count_multiplies_the_published_retail_rate(service, clock):
    service.publish(
        _catalog(
            "2026-08-image",
            clock,
            _rule(
                "image-standard",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
            ),
        ),
    )

    quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {"count": 3},
        ),
    )

    assert quote.credits == 150
    assert quote.unit_breakdown == {"image_count": 150}


def test_video_duration_uses_integer_ceiling_for_the_published_unit(
    service,
    clock,
):
    service.publish(
        _catalog(
            "2026-08-video",
            clock,
            _rule(
                "video-standard",
                "video_duration",
                capability="text_to_video",
                unit_size=3,
                credits_per_unit=10,
            ),
        ),
    )

    quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_video",
            {"duration_seconds": 7},
        ),
    )

    assert quote.credits == 24
    assert quote.unit_breakdown == {"video_duration_seconds": 24}


def test_fixed_workflow_price_is_one_published_invocation_price(
    service,
    clock,
):
    service.publish(
        _catalog(
            "2026-08-workflow",
            clock,
            _rule(
                "research-workflow",
                "fixed_workflow",
                model_key="deep-research-v1",
                capability="workflow",
                credits_per_unit=900,
                parameter_match={"workflow_key": "research"},
            ),
        ),
    )

    quote = service.quote(
        QuoteRequest(
            "aliyun",
            "deep-research-v1",
            "workflow",
            {"workflow_key": "research", "component_estimate": 1_500},
        ),
    )

    assert quote.credits == 900
    assert quote.unit_breakdown == {"workflow_invocation": 900}


def test_more_specific_parameter_rule_wins_before_priority(service, clock):
    service.publish(
        _catalog(
            "2026-08-specificity",
            clock,
            _rule(
                "generic",
                "image_count",
                capability="text_to_image",
                priority=100,
                credits_per_unit=50,
            ),
            _rule(
                "hd",
                "image_count",
                capability="text_to_image",
                credits_per_unit=80,
                parameter_match={"resolution": "1024x1024"},
            ),
        ),
    )

    quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {"count": 1, "resolution": "1024x1024"},
        ),
    )

    assert quote.rule_id == "hd"
    assert quote.credits == 80


def test_priority_breaks_ties_between_equally_specific_rules(service, clock):
    low = _rule(
        "hd-low-priority",
        "image_count",
        capability="text_to_image",
        priority=1,
        credits_per_unit=75,
        parameter_match={"resolution": "1024x1024"},
    )
    high = replace(low, id="hd-high-priority", priority=2, credits_per_unit=80)
    service.publish(_catalog("2026-08-priority", clock, low, high))

    quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {"count": 1, "resolution": "1024x1024"},
        ),
    )

    assert quote.rule_id == "hd-high-priority"
    assert quote.credits == 80


def test_publication_rejects_overlapping_rules_with_the_same_precedence(
    service,
    clock,
):
    resolution = _rule(
        "by-resolution",
        "image_count",
        capability="text_to_image",
        credits_per_unit=80,
        parameter_match={"resolution": "1024x1024"},
    )
    quality = replace(
        resolution,
        id="by-quality",
        credits_per_unit=90,
        parameter_match={"quality": "hd"},
    )

    with pytest.raises(
        AmbiguousPriceRuleError,
        match="by-quality.*by-resolution",
    ):
        service.publish(
            _catalog("2026-08-ambiguous", clock, resolution, quality),
        )


def test_existing_quote_keeps_its_snapshot_after_a_later_publication(
    service,
    clock,
):
    first_rule = _rule(
        "image-v1",
        "image_count",
        capability="text_to_image",
        credits_per_unit=50,
    )
    service.publish(_catalog("v1", clock, first_rule))
    first = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {"count": 1},
        ),
    )
    first_snapshot = dict(first.snapshot)

    clock.now += timedelta(seconds=1)
    service.publish(
        _catalog(
            "v2",
            clock,
            replace(first_rule, id="image-v2", credits_per_unit=80),
        ),
    )

    assert first.credits == 50
    assert first.catalog_version == "v1"
    assert first.snapshot == first_snapshot
    assert service.quote(first.request).credits == 80


def test_effective_time_is_normalized_to_utc_before_persistence(
    service,
    clock,
):
    same_instant_in_china = clock.now.astimezone(
        timezone(timedelta(hours=8)),
    )
    service.publish(
        PriceCatalogDraft(
            version="timezone-normalized",
            effective_at=same_instant_in_china,
            rules=(
                _rule(
                    "timezone-image",
                    "image_count",
                    capability="text_to_image",
                    credits_per_unit=50,
                ),
            ),
            created_by="admin:pricing-test",
        ),
    )

    quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {"count": 1},
        ),
    )

    assert quote.catalog_version == "timezone-normalized"


def test_historical_lookup_does_not_apply_a_later_backdated_publication(
    service,
    clock,
):
    original_time = clock.now
    first_rule = _rule(
        "historical-v1",
        "image_count",
        capability="text_to_image",
        credits_per_unit=50,
    )
    service.publish(_catalog("historical-v1", clock, first_rule))

    clock.now += timedelta(hours=1)
    service.publish(
        PriceCatalogDraft(
            version="historical-v2",
            effective_at=original_time,
            rules=(
                replace(
                    first_rule,
                    id="historical-v2",
                    credits_per_unit=80,
                ),
            ),
        ),
    )

    historical = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {"count": 1},
        ),
        at=original_time,
    )

    assert historical.catalog_version == "historical-v1"
    assert historical.credits == 50


def test_published_catalog_cannot_have_its_rules_replaced(
    service,
    repo,
    clock,
):
    catalog_id = service.publish(
        _catalog(
            "immutable",
            clock,
            _rule(
                "immutable-image",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
            ),
        ),
    )

    with pytest.raises(CatalogImmutableError):
        repo.replace_draft_rules(catalog_id, [])


def test_supplier_cost_and_discount_data_never_changes_a_retail_quote(
    service,
    clock,
):
    service.publish(
        _catalog(
            "retail-authority",
            clock,
            _rule(
                "retail-image",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
            ),
        ),
    )
    cheap_supplier = QuoteRequest(
        "aliyun",
        "model-1",
        "text_to_image",
        {"count": 2, "supplier_cost_fen": 0, "supplier_discount": 100},
    )
    expensive_supplier = QuoteRequest(
        "aliyun",
        "model-1",
        "text_to_image",
        {"count": 2, "supplier_cost_fen": 10_000, "supplier_discount": 0},
    )

    assert service.quote(cheap_supplier).credits == 100
    assert service.quote(expensive_supplier).credits == 100


def test_publication_rejects_supplier_commercial_data_as_a_rule_selector(
    service,
    clock,
):
    supplier_discount_rule = _rule(
        "supplier-discount",
        "image_count",
        capability="text_to_image",
        credits_per_unit=10,
        parameter_match={"supplier_discount": 50},
    )

    with pytest.raises(ValueError, match="supplier commercial data"):
        service.publish(
            _catalog(
                "supplier-dependent",
                clock,
                supplier_discount_rule,
            ),
        )
