import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
    QuoteRequest,
)
from qwenpaw.app.billing.pricing_sync import ProtectionResult
from qwenpaw.app.billing.pricing_collectors import (
    CollectedPriceCandidate,
    ModelCollectionResult,
)
from qwenpaw.app.billing.pricing_inventory import PriceableModel
from qwenpaw.app.billing.pricing_sync_runtime import (
    AutoProtectionPublisher,
    PricingCollectionRuntime,
    pricing_collection_loop,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.repos.pricing_admin_repo import PricingAdminRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


def test_auto_protection_records_candidate_without_publishing_catalog(
    tmp_path,
):
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
    assert quote.credits == 30
    assert quote.catalog_version == "v1"
    assert PricingAdminRepository(engine).list_audits()[0]["action"] == (
        "pricing.protection_candidate"
    )
    engine.dispose()


def test_auto_protection_never_changes_any_model_in_same_sync_batch(tmp_path):
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
        assert quote.credits == 30
        assert quote.catalog_version == "v1"
    engine.dispose()


def test_durable_collection_job_records_partial_progress(tmp_path):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "collection.db")}
        )
    )
    create_all(engine)
    repository = PricingAdminRepository(engine)
    models = (
        PriceableModel(
            "dashscope",
            "百炼",
            "official",
            "Official",
            "text",
            official_model_id="official",
            pricing_region="cn-beijing",
        ),
        PriceableModel(
            "dashscope",
            "百炼",
            "missing",
            "Missing",
            "text",
            official_model_id="missing",
            pricing_region="cn-beijing",
        ),
    )

    class Inventory:
        def list_enabled(self):
            return models

    class Pipeline:
        def collect(self, model):
            level = (
                "official_verified"
                if model.model_key == "official"
                else "failed"
            )
            candidates = (
                (
                    CollectedPriceCandidate(
                        provider_id="dashscope",
                        official_model_id="official",
                        pricing_region="cn-beijing",
                        capability="chat",
                        unit_key="input_tokens",
                        unit_size=1_000_000,
                        conditions={"region": "cn-beijing"},
                        original_currency="CNY",
                        original_price=Decimal("2.5"),
                        rmb_cost=Decimal("2.5"),
                        source_url="https://help.aliyun.com/pricing",
                        evidence_level="official_verified",
                        evidence_excerpt="每百万 Token 2.5 元",
                        collector_version="registry-v1",
                        ai_model=None,
                        prompt_version=None,
                        confidence=Decimal("1"),
                    ),
                )
                if level == "official_verified"
                else ()
            )
            return ModelCollectionResult(
                model.provider_id,
                model.model_key,
                model.pricing_region,
                level,
                Decimal("1.5") if level == "official_verified" else None,
                level == "official_verified",
                candidates,
            )

    runtime = PricingCollectionRuntime(
        repository,
        Inventory(),
        Pipeline(),
        clock=lambda: now,
    )

    queued = runtime.enqueue("admin-1")
    assert queued["status"] == "pending"

    status = asyncio.run(runtime.run_pending_once("worker-1"))
    completed = repository.get_collection_job(queued["id"])

    assert status == "partially_succeeded"
    assert completed["status"] == "partially_succeeded"
    assert completed["progress"] == {
        "total": 2,
        "completed": 2,
        "official": 1,
        "ai": 0,
        "manual": 0,
        "failed": 1,
    }
    persisted = repository.latest_official_candidates()
    assert len(persisted) == 1
    assert persisted[0]["evidence_level"] == "official_verified"
    engine.dispose()


def test_collection_loop_processes_pending_job_before_sleep(
    tmp_path, monkeypatch
):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "loop.db")}
        )
    )
    create_all(engine)
    repository = PricingAdminRepository(engine)
    model = PriceableModel("p", "P", "m", "M", "text")

    class Inventory:
        def list_enabled(self):
            return (model,)

    class Pipeline:
        def collect(self, selected):
            return ModelCollectionResult(
                selected.provider_id,
                selected.model_key,
                None,
                "failed",
                None,
                False,
                (),
            )

    runtime = PricingCollectionRuntime(
        repository, Inventory(), Pipeline(), clock=lambda: now
    )
    job = runtime.enqueue("admin")

    async def stop_after_first_cycle(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_first_cycle)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pricing_collection_loop(runtime, "worker"))

    assert repository.get_collection_job(job["id"])["status"] == "failed"
    engine.dispose()


def test_durable_collection_job_isolates_one_model_pipeline_failure(tmp_path):
    now = datetime(2026, 8, 30, tzinfo=timezone.utc)
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "isolated-failure.db")}
        )
    )
    create_all(engine)
    repository = PricingAdminRepository(engine)
    models = tuple(
        PriceableModel(
            "dashscope",
            "百炼",
            key,
            key,
            "text",
            official_model_id=key,
            pricing_region="cn-beijing",
        )
        for key in ("broken", "healthy")
    )

    class Inventory:
        def list_enabled(self):
            return models

    class Pipeline:
        def collect(self, model):
            if model.model_key == "broken":
                raise RuntimeError("collector crashed")
            return ModelCollectionResult(
                model.provider_id,
                model.model_key,
                model.pricing_region,
                "failed",
                None,
                False,
                (),
            )

    runtime = PricingCollectionRuntime(
        repository, Inventory(), Pipeline(), clock=lambda: now
    )
    queued = runtime.enqueue("admin-1")

    assert asyncio.run(runtime.run_pending_once("worker-1")) == "failed"
    detail = repository.get_collection_job(queued["id"])
    assert detail is not None
    assert {item["model_key"] for item in detail["items"]} == {
        "broken",
        "healthy",
    }
    assert next(
        item for item in detail["items"] if item["model_key"] == "broken"
    )["status"] == "failed"
    engine.dispose()
