# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.dialects import postgresql

from qwenpaw.app.billing.pricing import (
    AmbiguousPriceRuleError,
    CatalogImmutableError,
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
    PriceRuleNotFoundError,
    QuoteRequest,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_price_catalogs,
    billing_price_rules,
    create_all,
)
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

    with pytest.raises(
        ValueError,
        match="unsupported price selector key: supplier_discount",
    ):
        service.publish(
            _catalog(
                "supplier-dependent",
                clock,
                supplier_discount_rule,
            ),
        )


def test_json_roundtrip_canonicalizes_tuple_and_list_selectors(service, clock):
    service.publish(
        _catalog(
            "json-canonical",
            clock,
            _rule(
                "tuple-size",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
                parameter_match={"size": (1024, 1024)},
            ),
        ),
    )
    request = QuoteRequest(
        "aliyun",
        "model-1",
        "text_to_image",
        {"count": 1, "size": (1024, 1024)},
    )

    quote = service.quote(request)

    assert quote.rule_id == "tuple-size"
    assert not isinstance(request.parameters["size"], list)
    assert json.loads(
        json.dumps(request.to_jsonable()["parameters"]),
    ) == {
        "count": 1,
        "size": [1024, 1024],
    }


def test_json_type_identity_distinguishes_boolean_and_integer_selectors(
    service,
    clock,
):
    service.publish(
        _catalog(
            "json-type-identity",
            clock,
            _rule(
                "audio-boolean",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
                parameter_match={"audio": True},
            ),
            _rule(
                "audio-integer",
                "image_count",
                capability="text_to_image",
                credits_per_unit=80,
                parameter_match={"audio": 1},
            ),
        ),
    )

    boolean_quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {"count": 1, "audio": True},
        ),
    )
    integer_quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {"count": 1, "audio": 1},
        ),
    )

    assert boolean_quote.rule_id == "audio-boolean"
    assert integer_quote.rule_id == "audio-integer"


@pytest.mark.parametrize(
    "parameters",
    [
        {"client_context": {1, 2}},
        {"client_context": float("nan")},
        {"client_context": float("inf")},
        {1: "non-string JSON object key"},
    ],
)
def test_quote_request_rejects_non_json_or_non_finite_parameters(parameters):
    with pytest.raises(ValueError, match="parameters must be strict JSON"):
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            parameters,
        )


@pytest.mark.parametrize(
    "rule_field",
    [
        {"parameter_match": {"quality": float("nan")}},
        {"metadata": {"admin_note": {"not", "json"}}},
    ],
)
def test_price_rule_rejects_non_json_or_non_finite_fields(rule_field):
    with pytest.raises(ValueError, match="must be strict JSON"):
        PriceRule(
            id="invalid-json",
            provider_id="aliyun",
            model_key="model-1",
            capability="text_to_image",
            unit_type="image_count",
            credits_per_unit=50,
            **rule_field,
        )


def test_quote_snapshot_and_nested_values_are_deeply_immutable(
    service,
    clock,
):
    service.publish(
        _catalog(
            "immutable-quote",
            clock,
            _rule(
                "immutable-quote-rule",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
            ),
        ),
    )
    source_parameters = {
        "count": 1,
        "client_context": {"steps": ["draft", "submit"]},
    }
    request = QuoteRequest(
        "aliyun",
        "model-1",
        "text_to_image",
        source_parameters,
    )
    quote = service.quote(request)
    original_json = json.dumps(
        quote.to_jsonable()["snapshot"],
        sort_keys=True,
    )

    source_parameters["count"] = 99
    source_parameters["client_context"]["steps"].append("mutated")
    with pytest.raises(TypeError):
        request.parameters["count"] = 99
    with pytest.raises(TypeError):
        quote.unit_breakdown["image_count"] = 0
    with pytest.raises(TypeError):
        quote.snapshot["credits"] = 0
    with pytest.raises(TypeError):
        quote.snapshot["request"]["parameters"]["client_context"][
            "steps"
        ].append("mutated")

    assert json.dumps(request.to_jsonable()["parameters"], sort_keys=True)
    assert json.dumps(quote.to_jsonable()["unit_breakdown"], sort_keys=True)
    assert (
        json.dumps(quote.to_jsonable()["snapshot"], sort_keys=True)
        == original_json
    )
    assert quote.credits == 50
    assert quote.request.parameters["count"] == 1


def test_mutable_builtin_descriptors_cannot_bypass_quote_immutability(
    service,
    clock,
):
    service.publish(
        _catalog(
            "descriptor-bypass",
            clock,
            _rule(
                "descriptor-bypass-rule",
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
            {"count": 1, "client_context": {"steps": ["submit"]}},
        ),
    )

    with pytest.raises(TypeError):
        dict.__setitem__(quote.snapshot, "credits", 0)
    with pytest.raises(TypeError):
        list.append(
            quote.snapshot["request"]["parameters"]["client_context"]["steps"],
            "mutated",
        )

    assert quote.credits == 50
    assert quote.snapshot["credits"] == 50
    assert quote.snapshot["request"]["parameters"]["client_context"] == {
        "steps": ["submit"],
    }


def test_quote_has_an_explicit_detached_json_serialization_contract(
    service,
    clock,
):
    service.publish(
        _catalog(
            "explicit-json",
            clock,
            _rule(
                "explicit-json-rule",
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
            {"count": 1, "client_context": {"steps": ["submit"]}},
        ),
    )

    payload = quote.to_jsonable()
    encoded = json.dumps(payload, allow_nan=False, sort_keys=True)
    payload["snapshot"]["credits"] = 0
    payload["request"]["parameters"]["client_context"]["steps"].append(
        "mutated",
    )

    assert json.loads(encoded)["credits"] == 50
    assert quote.snapshot["credits"] == 50
    assert quote.request.to_jsonable()["parameters"]["client_context"] == {
        "steps": ["submit"],
    }


def test_controller_selector_allowlist_is_accepted(service, clock):
    allowed_selectors = {
        "count": 1,
        "duration_seconds": 5,
        "resolution": "1024x1024",
        "quality": "hd",
        "generation_mode": "text",
        "audio": False,
        "aspect_ratio": "1:1",
        "tier": "standard",
        "workflow_key": "research",
        "operation": "generate",
        "size": [1024, 1024],
    }
    service.publish(
        _catalog(
            "selector-allowlist",
            clock,
            _rule(
                "all-allowed-selectors",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
                parameter_match=allowed_selectors,
            ),
        ),
    )

    quote = service.quote(
        QuoteRequest(
            "aliyun",
            "model-1",
            "text_to_image",
            {**allowed_selectors, "supplier_cost_fen": 1_000},
        ),
    )

    assert quote.rule_id == "all-allowed-selectors"
    assert quote.credits == 50


@pytest.mark.parametrize(
    "unknown_key",
    ["supplier_cost_fen", "customer_discount", "component_estimate"],
)
def test_publication_rejects_every_non_allowlisted_selector(
    service,
    clock,
    unknown_key,
):
    rule = _rule(
        f"unknown-{unknown_key}",
        "image_count",
        capability="text_to_image",
        credits_per_unit=50,
        parameter_match={unknown_key: 1},
    )

    with pytest.raises(
        ValueError,
        match=f"unsupported price selector key: {unknown_key}",
    ):
        service.publish(_catalog(f"unknown-{unknown_key}", clock, rule))


def test_no_matching_rule_raises_a_specific_error(service, clock):
    service.publish(
        _catalog(
            "no-match",
            clock,
            _rule(
                "image-only",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
            ),
        ),
    )

    with pytest.raises(PriceRuleNotFoundError, match="text_to_video"):
        service.quote(
            QuoteRequest(
                "aliyun",
                "model-1",
                "text_to_video",
                {"duration_seconds": 5},
            ),
        )


def test_empty_catalog_is_rejected_before_persistence(service, clock, engine):
    with pytest.raises(ValueError, match="at least one price rule"):
        service.publish(_catalog("empty", clock))

    with engine.connect() as conn:
        assert (
            conn.scalar(
                select(func.count()).select_from(billing_price_catalogs),
            )
            == 0
        )


@pytest.mark.parametrize(
    ("unit_type", "parameters"),
    [
        ("image_count", {"count": 0}),
        ("image_count", {"count": -1}),
        ("video_duration", {"duration_seconds": 0}),
        ("video_duration", {"duration_seconds": -1}),
    ],
)
def test_non_positive_quote_quantities_are_rejected(
    service,
    clock,
    unit_type,
    parameters,
):
    capability = (
        "text_to_image" if unit_type == "image_count" else "text_to_video"
    )
    service.publish(
        _catalog(
            f"quantity-{unit_type}",
            clock,
            _rule(
                f"quantity-{unit_type}",
                unit_type,
                capability=capability,
                credits_per_unit=50,
            ),
        ),
    )

    with pytest.raises(ValueError, match="must be a positive integer"):
        service.quote(
            QuoteRequest(
                "aliyun",
                "model-1",
                capability,
                parameters,
            ),
        )


@pytest.mark.parametrize(
    "rule",
    [
        _rule("zero-image", "image_count", credits_per_unit=0),
        _rule("negative-image", "image_count", credits_per_unit=-1),
        _rule("zero-token", "tokens"),
        _rule("negative-token", "tokens", input_credits_per_1k=-1),
    ],
)
def test_zero_or_negative_retail_rates_are_rejected(service, clock, rule):
    with pytest.raises(
        ValueError,
        match="rate|credits_per_unit|credits_per_1k",
    ):
        service.publish(_catalog(f"invalid-rate-{rule.id}", clock, rule))


def test_atomic_publication_rolls_back_and_same_version_can_retry(
    repo,
    engine,
    clock,
):
    draft = _catalog(
        "atomic-retry",
        clock,
        _rule(
            "atomic-retry-rule",
            "image_count",
            capability="text_to_image",
            credits_per_unit=50,
        ),
    )

    def fail_rule_insert(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith("INSERT INTO billing_price_rules"):
            raise RuntimeError("injected rule insert failure")

    event.listen(engine, "before_cursor_execute", fail_rule_insert)
    try:
        with pytest.raises(RuntimeError, match="injected rule insert failure"):
            repo.publish_catalog(draft, published_at=clock.now)
    finally:
        event.remove(engine, "before_cursor_execute", fail_rule_insert)

    with engine.connect() as conn:
        assert (
            conn.scalar(
                select(func.count()).select_from(billing_price_catalogs),
            )
            == 0
        )
        assert (
            conn.scalar(select(func.count()).select_from(billing_price_rules))
            == 0
        )

    catalog_id = repo.publish_catalog(draft, published_at=clock.now)
    assert catalog_id


def test_draft_mutation_statements_lock_and_guard_catalog_status(repo):
    lock_sql = str(
        repo._draft_for_update_statement("catalog-id").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ),
    )
    delete_sql = str(
        repo._guarded_delete_rules_statement("catalog-id").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ),
    )

    assert lock_sql.rstrip().endswith("FOR UPDATE")
    assert "billing_price_catalogs.status = 'draft'" in delete_sql
    assert "EXISTS" in delete_sql


def test_locked_draft_publish_validates_current_rules_before_status_update(
    service,
    repo,
    clock,
):
    catalog_id = service.create_draft(
        _catalog(
            "locked-publish",
            clock,
            _rule(
                "locked-image",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
            ),
        ),
    )
    observed_rule_ids = []

    def reject_current_catalog(catalog):
        observed_rule_ids.extend(rule["id"] for rule in catalog["rules"])
        raise ValueError("current draft rules are invalid")

    with pytest.raises(ValueError, match="current draft rules are invalid"):
        repo.publish_draft_validated(
            catalog_id,
            published_at=clock.now,
            validate=reject_current_catalog,
        )

    assert observed_rule_ids == ["locked-image"]
    assert repo.get_catalog(catalog_id)["status"] == "draft"


def test_service_rejects_ambiguous_rules_replaced_before_locked_publish(
    service,
    repo,
    clock,
):
    catalog_id = service.create_draft(
        _catalog(
            "replaced-before-publish",
            clock,
            _rule(
                "original-image",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
            ),
        ),
    )
    repo.replace_draft_rules(
        catalog_id,
        (
            _rule(
                "ambiguous-a",
                "image_count",
                capability="text_to_image",
                credits_per_unit=50,
            ),
            _rule(
                "ambiguous-b",
                "image_count",
                capability="text_to_image",
                credits_per_unit=80,
            ),
        ),
    )

    with pytest.raises(AmbiguousPriceRuleError):
        service.publish_draft(catalog_id)

    assert repo.get_catalog(catalog_id)["status"] == "draft"
