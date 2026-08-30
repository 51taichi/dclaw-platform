from datetime import datetime, timezone
from io import BytesIO

from openpyxl import load_workbook

from qwenpaw.app.billing.pricing import PriceCatalogService, QuoteRequest
from qwenpaw.app.billing.pricing_admin import PricingAdminService
from qwenpaw.app.billing.pricing_inventory import PriceableModel
from qwenpaw.app.billing.pricing_excel import PricingExcelService
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


def test_first_catalog_workbook_lists_enabled_models_and_publishes_subset(
    tmp_path,
):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "first-catalog.db")}
        )
    )
    create_all(engine)
    admin_repo = PricingAdminRepository(engine)
    catalog_repo = PriceCatalogRepository(engine)
    pricing = PriceCatalogService(catalog_repo, clock=lambda: now)
    inventory = type(
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
    admin = PricingAdminService(
        admin_repo,
        pricing,
        catalog_repo,
        inventory,
        clock=lambda: now,
    )
    excel = PricingExcelService(
        admin_repo,
        preview_builder=lambda actor, rows, import_id: (
            admin.preview_initial_catalog(
                actor, rows, import_id, persist=False
            )
        ),
        confirmation_builder=lambda actor, rows, import_id: (
            admin.preview_initial_catalog(
                actor, rows, import_id, persist=False
            )
        ),
        draft_builder=admin.preview_initial_catalog,
    )
    generated = admin.generate_draft("1")
    assert generated["coverage"]["blocking_models"] == 1
    workbook = load_workbook(BytesIO(excel.export_draft(generated["result"])))
    sheet = workbook["价格草案"]
    headers = {cell.value: cell.column for cell in sheet[1]}
    for row_number in range(2, sheet.max_row + 1):
        if sheet.cell(row_number, headers["模型ID"]).value == "unpriced-model":
            sheet.cell(row_number, headers["是否纳入本次发布"], "否")
            sheet.cell(row_number, headers["排除原因"], "暂无可信官方价格")
    content = BytesIO()
    workbook.save(content)

    imported = excel.preview_import(content.getvalue(), "prices.xlsx", "1")
    assert imported["status"] == "ready"
    confirmed = excel.confirm_import(imported["id"], "1")
    published = admin.publish_preview(
        confirmed["pricing_preview"]["catalog_id"], "1"
    )

    quote = pricing.quote(
        QuoteRequest(
            "dashscope",
            "qwen3-max",
            "chat",
            {"pricing_region": "cn-beijing"},
            input_tokens=30_000,
        )
    )
    assert published["status"] == "published"
    assert quote.credits == 12
    assert {
        rule["model_key"]
        for rule in catalog_repo.get_catalog(published["id"])["rules"]
    } == {"qwen3-max"}
    engine.dispose()
