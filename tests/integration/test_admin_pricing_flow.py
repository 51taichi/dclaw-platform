from datetime import datetime, timezone

from qwenpaw.app.billing.pricing import PriceCatalogService, QuoteRequest
from qwenpaw.app.billing.pricing_admin import PricingAdminService
from qwenpaw.app.billing.pricing_inventory import PriceableModel
from qwenpaw.app.billing.pricing_unlock import PricingUnlockService
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def test_admin_can_unlock_publish_verified_rmb_prices_and_quote_open_api(
    tmp_path,
):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    engine = create_engine_from_settings(
        get_storage_settings(
            {
                "QWENPAW_SQLITE_PATH": str(tmp_path / "pricing-flow.db"),
            }
        )
    )
    create_all(engine)
    admin_repo = PricingAdminRepository(engine)
    catalog_repo = PriceCatalogRepository(engine)
    catalogs = PriceCatalogService(catalog_repo, clock=lambda: now)
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
    admin = PricingAdminService(
        admin_repo,
        catalogs,
        catalog_repo,
        inventory,
        clock=lambda: now,
    )
    unlocks = PricingUnlockService(
        admin_repo,
        credential_loader=lambda _actor: ("hash", "salt", "admin"),
        password_verifier=lambda password, *_: password == "admin-password",
        clock=lambda: now,
        token_factory=lambda: "one-time-pricing-token",
    )

    unlock = unlocks.unlock("1", "admin-password", "127.0.0.1")
    assert unlocks.is_valid(unlock.token, "1") is True
    admin.save_policy("global", "*", "1.5", {}, "1", 0)
    for unit, amount in (
        ("input_tokens", "0.004"),
        ("output_tokens", "0.012"),
    ):
        admin_repo.append_cost_snapshot(
            {
                "provider_id": "dashscope",
                "model_key": "qwen-plus",
                "capability": "chat",
                "unit_key": unit,
                "source_type": "official_api",
                "source_reference": "provider-price-id",
                "original_currency": "CNY",
                "original_price_decimal": amount,
                "fx_rate_decimal": "1",
                "rmb_cost_decimal": amount,
                "conditions": {},
                "verification_status": "verified",
                "verified_at": now,
            }
        )

    preview = admin.preview_initial_catalog("1")
    assert preview["publishable"] is True
    published = admin.publish_preview(preview["catalog_id"], "1")
    assert published["status"] == "published"

    quote = catalogs.quote(
        QuoteRequest(
            provider_id="dashscope",
            model_key="qwen-plus",
            capability="chat",
            parameters={},
            input_tokens=1000,
            output_tokens=1000,
        )
    )
    assert quote.catalog_version == published["version"]
    assert quote.credits > 0
    assert quote.snapshot["rule"]["metadata"]["currency"] == "CNY"
    engine.dispose()
