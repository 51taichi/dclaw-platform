from datetime import datetime, timezone

import pytest

from qwenpaw.app.billing.pricing import PriceCatalogService
from qwenpaw.app.billing.pricing_admin import PricingAdminService
from qwenpaw.app.billing.pricing_inventory import PriceableModel
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings

NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


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
                PriceableModel(
                    "dashscope", "百炼", "qwen-plus", "Qwen Plus", "text"
                ),
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
                PriceableModel(
                    "volcengine", "火山引擎", "seedream", "Seedream", "image"
                ),
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
    preview = pricing.preview_initial_catalog(
        "1", rows, import_id=imported["id"]
    )

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
