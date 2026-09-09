from datetime import datetime, timezone

import pytest

from qwenpaw.app.billing.official_pricing import OfficialPriceRegistry
from qwenpaw.app.billing.pricing import PriceCatalogService, QuoteRequest
from qwenpaw.app.billing.pricing_admin import PricingAdminService
from qwenpaw.app.billing.pricing_inventory import PriceableModel
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


def _import_rows(pricing):
    return [
        {
            **row,
            "rmb_cost_decimal": row.pop("rmb_cost"),
            "multiplier_decimal": row.pop("multiplier"),
            "excluded": not row.pop("include_in_publish"),
        }
        for row in map(dict, pricing.generate_draft("1")["rows"])
    ]


@pytest.fixture
def service(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {
                "QWENPAW_SQLITE_PATH": str(tmp_path / "pricing.db"),
            }
        )
    )
    create_all(engine)
    admin_repo = PricingAdminRepository(engine)
    catalog_repo = PriceCatalogRepository(engine)
    inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel("dashscope", "百炼", "qwen-plus", "Qwen Plus", "text"),
            )
        },
    )()
    value = PricingAdminService(
        admin_repo,
        PriceCatalogService(catalog_repo, clock=lambda: NOW),
        catalog_repo,
        inventory,
        clock=lambda: NOW,
    )
    try:
        yield value, admin_repo
    finally:
        engine.dispose()


def test_initial_preview_blocks_model_without_trusted_cost(service):
    pricing, _repo = service
    preview = pricing.preview_initial_catalog("1")
    assert preview["publishable"] is False
    assert {item["unit_key"] for item in preview["blockers"]} == {
        "input_tokens",
        "output_tokens",
    }


def test_generate_draft_reads_persisted_ai_candidate(service):
    pricing, repo = service
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel(
                    "dashscope",
                    "百炼",
                    "future-model",
                    "Future",
                    "text",
                    official_model_id="future-model",
                    pricing_region="cn-beijing",
                ),
            )
        },
    )()
    repo.append_official_candidate(
        {
            "content_sha256": "candidate-digest",
            "provider_id": "dashscope",
            "official_model_id": "future-model",
            "capability": "chat",
            "unit_key": "input_tokens",
            "conditions_digest": "conditions-digest",
            "conditions": {
                "region": "cn-beijing",
                "unit_size": 1_000_000,
            },
            "source_url": "",
            "source_published_at": None,
            "original_currency": "CNY",
            "original_price_decimal": "3",
            "fx_rate_decimal": "1",
            "rmb_cost_decimal": "3",
            "verification_status": "candidate",
            "registry_version": "ai-v1",
            "evidence_level": "ai_no_evidence",
            "collector_version": "ai-v1",
            "default_multiplier_decimal": "2.0",
        }
    )

    generated = pricing.generate_draft("1")

    assert generated["rows"][0]["evidence_level"] == "ai_no_evidence"
    assert generated["rows"][0]["include_in_publish"] is False

    draft_key = generated["draft_key"]
    with pytest.raises(ValueError, match="approval reason"):
        pricing.set_model_decisions(
            draft_key,
            [
                {
                    "provider_id": "dashscope",
                    "model_key": "future-model",
                    "include_in_publish": True,
                    "reason": None,
                }
            ],
            "admin-1",
        )

    saved = pricing.set_model_decisions(
        draft_key,
        [
            {
                "provider_id": "dashscope",
                "model_key": "future-model",
                "include_in_publish": True,
                "reason": "已人工核对并接受估算风险",
            }
        ],
        "admin-1",
    )

    assert saved[0]["include_in_publish"] is True
    assert pricing.generate_draft("1")["rows"][0]["include_in_publish"] is True
    assert repo.list_audits()[0]["action"] == "draft.model_decisions.updated"

    batch = pricing.batch_set_model_decision(
        draft_key,
        include_in_publish=False,
        provider_ids=["dashscope"],
        evidence_levels=["ai_no_evidence"],
        model_keys=[],
        reason="下一版再审核",
        actor_id="admin-1",
    )
    assert batch["updated_models"] == 1
    assert pricing.generate_draft("1")["rows"][0]["include_in_publish"] is False


def test_initial_preview_blocks_non_text_model_without_any_trusted_cost(
    service,
):
    pricing, repo = service
    repo.replace_policy(
        scope_type="global",
        scope_key="*",
        multiplier_decimal="1.5",
        settings={},
        actor_id="1",
        expected_revision=0,
    )
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel("volcengine", "火山引擎", "seedream", "Seedream", "image"),
            )
        },
    )()

    preview = pricing.preview_initial_catalog("1")

    assert preview["publishable"] is False
    assert preview["blockers"] == [
        {
            "code": "trusted_cost_missing",
            "provider_id": "volcengine",
            "model_key": "seedream",
            "unit_key": "any",
        }
    ]


def test_policy_cost_preview_publish_and_rollback(service):
    pricing, repo = service
    pricing.save_policy("global", "*", "1.5", {}, "1", 0)
    for unit, amount in (
        ("input_tokens", "0.004"),
        ("output_tokens", "0.012"),
    ):
        repo.append_cost_snapshot(
            {
                "provider_id": "dashscope",
                "model_key": "qwen-plus",
                "capability": "chat",
                "unit_key": unit,
                "source_type": "manual",
                "source_reference": "official",
                "original_currency": "CNY",
                "original_price_decimal": amount,
                "fx_rate_decimal": "1",
                "rmb_cost_decimal": amount,
                "conditions": {},
                "verification_status": "verified",
                "verified_at": NOW,
            }
        )
    preview = pricing.preview_initial_catalog("1")
    assert preview["publishable"] is True
    published = pricing.publish_preview(preview["catalog_id"], "1")
    assert published["status"] == "published"
    rolled_back = pricing.rollback(published["id"], "1")
    assert rolled_back["status"] == "published"
    assert rolled_back["version"] != published["version"]
    assert {row["action"] for row in repo.list_audits()} >= {
        "policy.updated",
        "catalog.published",
        "catalog.rolled_back",
    }


def test_import_draft_cannot_publish_until_import_is_confirmed(service):
    pricing, repo = service
    rows = []
    for unit, amount in (
        ("input_tokens", "0.004"),
        ("output_tokens", "0.012"),
    ):
        rows.append(
            {
                "provider_id": "dashscope",
                "model_key": "qwen-plus",
                "category": "text",
                "unit_key": unit,
                "rmb_cost_decimal": amount,
                "multiplier_decimal": "1.5",
                "verification_status": "verified",
                "verified_at": NOW.isoformat(),
            }
        )
    imported = repo.record_import(
        "digest", "prices.xlsx", "1", {"status": "ready", "valid_rows": rows}
    )
    preview = pricing.preview_initial_catalog("1", rows, import_id=imported["id"])

    with pytest.raises(ValueError, match="import is not confirmed"):
        pricing.publish_preview(preview["catalog_id"], "1")
    with pytest.raises(ValueError, match="published catalog"):
        pricing.rollback(preview["catalog_id"], "1")

    repo.apply_import_rows(
        imported["id"],
        rows,
        "prices.xlsx",
        "1",
        preview,
    )
    assert pricing.publish_preview(preview["catalog_id"], "1")["status"] == (
        "published"
    )


def test_confirmed_verified_import_persists_unit_size_for_round_trip(service):
    _pricing, repo = service
    rows = [
        {
            "provider_id": "dashscope",
            "model_key": "qwen-plus",
            "category": "text",
            "capability": "chat",
            "unit_key": "input_tokens",
            "unit_size": 1_000_000,
            "conditions": {},
            "rmb_cost_decimal": "76",
            "multiplier_decimal": "1.5",
            "source_type": "trusted_cost",
            "source_url": "https://example.com/pricing",
            "verification_status": "verified",
            "excluded": False,
        }
    ]
    imported = repo.record_import(
        "unit-size-digest",
        "prices.xlsx",
        "1",
        {"status": "ready", "valid_rows": rows},
    )

    repo.apply_import_rows(imported["id"], rows, "prices.xlsx", "1", {})

    stored = repo.latest_trusted_costs()[0]
    assert stored["conditions_json"] == '{"unit_size":1000000}'


def test_generated_draft_lists_enabled_models_and_allows_reasoned_subset(
    service,
):
    pricing, repo = service
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel(
                    "dashscope",
                    "百炼",
                    "qwen3-max",
                    "Qwen3 Max",
                    "text",
                    official_model_id="qwen3-max",
                    pricing_region="cn-beijing",
                ),
                PriceableModel(
                    "volcengine-cn",
                    "火山方舟",
                    "unpriced-model",
                    "Unpriced",
                    "text",
                    official_model_id="unpriced-model",
                ),
            )
        },
    )()

    generated = pricing.generate_draft("1")

    assert generated["coverage"] == {
        "enabled_models": 2,
        "matched_models": 1,
        "missing_models": 1,
        "excluded_models": 0,
        "blocking_models": 1,
    }
    assert {row["model_key"] for row in generated["rows"]} == {
        "qwen3-max",
        "unpriced-model",
    }

    pricing.set_exclusion(
        generated["draft_key"],
        "volcengine-cn",
        "unpriced-model",
        True,
        "暂未获得可核验的官方价格",
        "1",
    )
    regenerated = pricing.generate_draft("1")

    assert regenerated["coverage"]["blocking_models"] == 0
    assert regenerated["coverage"]["excluded_models"] == 1
    exclusions = repo.list_draft_exclusions(generated["draft_key"])
    assert exclusions[0]["reason"] == "暂未获得可核验的官方价格"


def test_admin_can_save_exact_mapping_and_regenerate_verified_rows(service):
    pricing, repo = service
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel(
                    "custom-qwen",
                    "Custom",
                    "alias",
                    "Alias",
                    "text",
                    pricing_region="cn-beijing",
                ),
            )
        },
    )()

    saved = pricing.save_model_mapping(
        "custom-qwen", "alias", "dashscope", "qwen3-max", 0, "1"
    )
    regenerated = pricing.generate_draft("1")

    assert saved["revision"] == 1
    assert regenerated["coverage"]["matched_models"] == 1
    assert len(regenerated["rows"]) == 6
    assert repo.list_audits()[-1]["action"] == "model.mapping.updated"


def test_imported_exclusion_publishes_only_eligible_models(service):
    pricing, _repo = service
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel(
                    "dashscope",
                    "百炼",
                    "qwen3-max",
                    "Qwen3 Max",
                    "text",
                    official_model_id="qwen3-max",
                    pricing_region="cn-beijing",
                ),
                PriceableModel(
                    "volcengine-cn",
                    "火山方舟",
                    "unpriced-model",
                    "Unpriced",
                    "text",
                    official_model_id="unpriced-model",
                ),
            )
        },
    )()
    rows = _import_rows(pricing)
    for row in rows:
        if row["model_key"] == "unpriced-model":
            row["excluded"] = True
            row["exclusion_reason"] = "暂不纳入"

    preview = pricing.preview_initial_catalog("1", rows)

    assert preview["publishable"] is True
    catalog = pricing.catalogs.get_catalog(preview["catalog_id"])
    assert {rule["model_key"] for rule in catalog["rules"]} == {"qwen3-max"}


def test_imported_multidimensional_token_prices_keep_official_tiers(service):
    pricing, _repo = service
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel(
                    "dashscope",
                    "百炼",
                    "qwen3-max",
                    "Qwen3 Max",
                    "text",
                    official_model_id="qwen3-max",
                    pricing_region="cn-beijing",
                ),
            )
        },
    )()
    rows = _import_rows(pricing)

    preview = pricing.preview_initial_catalog("1", rows)
    pricing.publish_preview(preview["catalog_id"], "1")
    low = pricing.pricing.quote(
        QuoteRequest(
            "dashscope",
            "qwen3-max",
            "chat",
            {"pricing_region": "cn-beijing"},
            input_tokens=30_000,
        )
    )
    medium = pricing.pricing.quote(
        QuoteRequest(
            "dashscope",
            "qwen3-max",
            "chat",
            {"pricing_region": "cn-beijing"},
            input_tokens=40_000,
        )
    )

    assert low.credits == 12
    assert medium.credits == 24
    assert {
        item["unit_size"] for item in low.snapshot["rule"]["metadata"]["dimensions"]
    } == {1_000_000}


def test_imported_draft_rejects_missing_dimension_and_read_only_tampering(
    service,
):
    pricing, _repo = service
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel(
                    "dashscope",
                    "百炼",
                    "qwen3-max",
                    "Qwen3 Max",
                    "text",
                    official_model_id="qwen3-max",
                    pricing_region="cn-beijing",
                ),
            )
        },
    )()
    rows = _import_rows(pricing)

    with pytest.raises(ValueError, match="dimensions are incomplete"):
        pricing.preview_initial_catalog("1", rows[:-1])

    rows[0]["unit_size"] = 1_000_000_000_000
    with pytest.raises(ValueError, match="read-only field changed: unit_size"):
        pricing.preview_initial_catalog("1", rows)

    rows = _import_rows(pricing)
    rows[0]["rmb_cost_decimal"] = "0.000001"
    preview = pricing.preview_initial_catalog("1", rows, persist=False)
    assert preview["publishable"] is True
    assert preview["review"]["manual_dimensions"] == 1
    assert rows[0]["source_type"] == "manual"
    assert rows[0]["verification_status"] == "manual_pending"

    rows[0].update(
        source_type="manual",
        verification_status="manual_pending",
        source_url="https://example.com/reviewed-price",
    )
    assert pricing.preview_initial_catalog("1", rows)["publishable"] is True

    rows = _import_rows(pricing)
    rows[0].update(excluded=True, exclusion_reason="only one dimension")
    with pytest.raises(ValueError, match="included together"):
        pricing.preview_initial_catalog("1", rows)


def test_missing_text_model_accepts_exported_input_and_output_completion(
    service,
):
    pricing, _repo = service
    rows = _import_rows(pricing)
    assert {row["unit_key"] for row in rows} == {
        "input_tokens",
        "output_tokens",
    }
    for row in rows:
        row.update(
            rmb_cost_decimal=("10" if row["unit_key"] == "input_tokens" else "45"),
            source_url="https://example.com/vendor-price",
        )

    preview = pricing.preview_initial_catalog("1", rows)

    assert preview["publishable"] is True
    catalog = pricing.catalogs.get_catalog(preview["catalog_id"])
    dimensions = catalog["rules"][0]["metadata"]["dimensions"]
    assert {item["unit_key"] for item in dimensions} == {
        "input_tokens",
        "output_tokens",
    }


def test_publish_rejects_when_enabled_model_endpoint_region_changed(service):
    pricing, repo = service
    pricing.save_policy("global", "*", "1.5", {}, "1", 0)
    for unit, amount in (
        ("input_tokens", "0.004"),
        ("output_tokens", "0.012"),
    ):
        repo.append_cost_snapshot(
            {
                "provider_id": "dashscope",
                "model_key": "qwen-plus",
                "capability": "chat",
                "unit_key": unit,
                "source_type": "manual",
                "source_reference": "https://example.com/prices",
                "original_currency": "CNY",
                "original_price_decimal": amount,
                "fx_rate_decimal": "1",
                "rmb_cost_decimal": amount,
                "conditions": {},
                "verification_status": "verified",
                "verified_at": NOW,
            }
        )
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel(
                    "dashscope",
                    "百炼",
                    "qwen-plus",
                    "Qwen Plus",
                    "text",
                    pricing_region="cn-beijing",
                ),
            )
        },
    )()
    preview = pricing.preview_initial_catalog("1")
    pricing.inventory = type(
        "Inventory",
        (),
        {
            "list_enabled": lambda self: (
                PriceableModel(
                    "dashscope",
                    "百炼",
                    "qwen-plus",
                    "Qwen Plus",
                    "text",
                    pricing_region="ap-southeast-1",
                ),
            )
        },
    )()

    with pytest.raises(ValueError, match="inventory changed"):
        pricing.publish_preview(preview["catalog_id"], "1")


def test_excel_cost_and_per_dimension_multiplier_survive_full_roundtrip(service):
    from io import BytesIO
    from decimal import Decimal
    from openpyxl import load_workbook
    from qwenpaw.app.billing.pricing_excel import PricingExcelService

    pricing, repo = service
    excel = PricingExcelService(
        repo,
        preview_builder=lambda actor, rows, iid: pricing.preview_initial_catalog(
            actor, rows, iid, persist=False
        ),
        draft_builder=pricing.preview_initial_catalog,
    )
    book = load_workbook(
        BytesIO(excel.export_draft(pricing.generate_draft("1")["result"]))
    )
    sheet = book.active
    headers = {cell.value: cell.column for cell in sheet[1]}
    for index, multiplier in ((2, "2"), (3, "3")):
        sheet.cell(index, headers["人民币成本"], "4")
        sheet.cell(index, headers["默认倍率"], multiplier)
        sheet.cell(index, headers["人民币销售价"], "123")
        sheet.cell(index, headers["积分价格"], 12300)
    data = BytesIO()
    book.save(data)
    preview = excel.preview_import(data.getvalue(), "edited.xlsx", "1")
    assert preview["status"] == "ready", preview
    assert preview["pricing_preview"]["review"]["manual_dimensions"] == 2
    confirmed = excel.confirm_import(preview["id"], "1")
    published = pricing.publish_preview(confirmed["pricing_preview"]["catalog_id"], "1")
    dimensions = published["rules"][0]["metadata"]["dimensions"]
    assert [d["unit_size"] for d in dimensions] == [1_000_000, 1_000_000]
    assert [d["credits_per_unit"] for d in dimensions] == [800, 1200]
    exported = pricing.generate_draft("1")["result"]
    assert [row.multiplier for row in exported.rows] == [Decimal("2"), Decimal("3")]
    assert [row.credits for row in exported.rows] == [800, 1200]
    again = excel.preview_import(excel.export_draft(exported), "again.xlsx", "1")
    assert again["status"] == "ready", again
    assert len(again["valid_rows"]) == 2
