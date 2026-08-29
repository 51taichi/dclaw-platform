from datetime import datetime, timedelta, timezone
from decimal import Decimal

from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
    QuoteRequest,
)
from qwenpaw.app.billing.pricing_sync import ProtectionResult
from qwenpaw.app.billing.pricing_sync_runtime import AutoProtectionPublisher
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def test_auto_protection_publishes_bounded_clone_and_audit(tmp_path):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    engine = create_engine_from_settings(
        get_storage_settings(
            {
                "QWENPAW_SQLITE_PATH": str(tmp_path / "protection.db"),
            }
        )
    )
    create_all(engine)
    catalog_repo = PriceCatalogRepository(engine)
    pricing = PriceCatalogService(catalog_repo, clock=lambda: now)
    pricing.publish(
        PriceCatalogDraft(
            version="v1",
            effective_at=now,
            created_by="admin",
            rules=(
                PriceRule(
                    id="qwen",
                    provider_id="dashscope",
                    model_key="qwen-plus",
                    capability="chat",
                    unit_type="tokens",
                    input_credits_per_1k=10,
                    output_credits_per_1k=20,
                ),
            ),
        )
    )

    AutoProtectionPublisher(PricingAdminRepository(engine))(
        ProtectionResult(
            "dashscope/qwen-plus",
            Decimal("0.35"),
            Decimal("0.20"),
            Decimal("0.15"),
            "critical",
            False,
            now + timedelta(seconds=1),
        )
    )

    quote = pricing.quote(
        QuoteRequest(
            "dashscope",
            "qwen-plus",
            "chat",
            {},
            input_tokens=1000,
            output_tokens=1000,
        ),
        at=now + timedelta(seconds=1),
    )
    assert quote.credits == 36
    assert quote.catalog_version.startswith("protect-")
    assert PricingAdminRepository(engine).list_audits()[0]["action"] == (
        "catalog.auto_protected"
    )
    engine.dispose()


def test_auto_protection_composes_multiple_models_from_same_sync_batch(tmp_path):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "multi-protection.db")}
        )
    )
    create_all(engine)
    catalog_repo = PriceCatalogRepository(engine)
    pricing = PriceCatalogService(catalog_repo, clock=lambda: now)
    pricing.publish(
        PriceCatalogDraft(
            version="v1",
            effective_at=now,
            created_by="admin",
            rules=tuple(
                PriceRule(
                    id=model,
                    provider_id="dashscope",
                    model_key=model,
                    capability="chat",
                    unit_type="tokens",
                    input_credits_per_1k=10,
                    output_credits_per_1k=20,
                )
                for model in ("qwen-plus", "qwen-max")
            ),
        )
    )
    publisher = AutoProtectionPublisher(PricingAdminRepository(engine))
    created_at = now + timedelta(seconds=1)

    for model in ("qwen-plus", "qwen-max"):
        publisher(
            ProtectionResult(
                f"dashscope/{model}",
                Decimal("0.35"),
                Decimal("0.20"),
                Decimal("0.15"),
                "critical",
                False,
                created_at,
            )
        )

    for model in ("qwen-plus", "qwen-max"):
        quote = pricing.quote(
            QuoteRequest(
                "dashscope",
                model,
                "chat",
                {},
                input_tokens=1000,
                output_tokens=1000,
            ),
            at=created_at + timedelta(seconds=1),
        )
        assert quote.credits == 36
    engine.dispose()
