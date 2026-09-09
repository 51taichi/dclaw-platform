from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from qwenpaw.app.aigc.billing import (
    find_aigc_job_reservation,
    reserve_aigc_job,
    settle_cancelled_aigc_job,
)
from qwenpaw.app.aigc.models import AigcJob
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.usage import InsufficientUsageCreditsError
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_usage_items,
    billing_usage_orders,
    create_all,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    result = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "aigc-billing.db")},
        ),
    )
    create_all(result)
    pricing = PriceCatalogService(PriceCatalogRepository(result))
    pricing.publish(
        PriceCatalogDraft(
            version="aigc-unit-prices",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="mxapi-image",
                    provider_id="mxapi",
                    model_key="gpt-image-2",
                    capability="text_to_image",
                    unit_type="image_count",
                    credits_per_unit=300,
                    metadata={"economic_tier": "standard"},
                ),
                PriceRule(
                    id="mxapi-video",
                    provider_id="mxapi",
                    model_key="grok-imagine-video-1.5",
                    capability="text_to_video",
                    unit_type="video_duration",
                    credits_per_unit=120,
                    metadata={"economic_tier": "standard"},
                ),
            ),
        ),
    )
    try:
        yield result
    finally:
        result.dispose()


def _job(
    job_id: str,
    *,
    capability: str,
    model_id: str,
    parameters: dict,
) -> AigcJob:
    timestamp = datetime.now(timezone.utc).isoformat()
    return AigcJob(
        id=job_id,
        canvas_id="canvas-1",
        node_id="node-1",
        capability=capability,
        provider_id="mxapi",
        model_id=model_id,
        inputs={"prompt": "not persisted in billing"},
        parameters=parameters,
        status="running",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _fund(engine, owner: str, credits: int = 2_000):
    repository = BillingRepository(engine)
    wallet = repository.ensure_wallet("user", owner)
    repository.grant(
        str(wallet["id"]),
        credits=credits,
        credit_type="purchased",
        expires_at=None,
        idempotency_key=f"fund:{owner}",
    )
    return repository, wallet


def test_aigc_image_admits_without_hold_and_captures_published_price(engine):
    repository, wallet = _fund(engine, "user-1")
    job = _job(
        "image-job-1",
        capability="text_to_image",
        model_id="gpt-image-2",
        parameters={"imageCount": 2, "prompt": "must not enter billing"},
    )

    reservation = reserve_aigc_job(job, "user-1", engine=engine)

    assert reservation is not None
    assert reservation.quoted_credits == 600
    balance = repository.balance(str(wallet["id"]))
    assert balance.held == 0
    assert balance.available == 2_000

    reservation.settle_success(
        outputs=[object(), object()], supplier_reference="task-1"
    )

    balance = repository.balance(str(wallet["id"]))
    assert balance.held == 0
    assert balance.available == 1_400
    with engine.connect() as connection:
        order = connection.execute(select(billing_usage_orders)).mappings().one()
        item = connection.execute(select(billing_usage_items)).mappings().one()
    assert order["source_type"] == "aigc"
    assert order["source_id"] == "image-job-1"
    assert order["captured_credits"] == 600
    assert item["provider_id"] == "mxapi"
    assert item["model_key"] == "gpt-image-2"
    assert item["charged_credits"] == 600
    assert "not persisted" not in str(item["usage_snapshot_json"])


def test_aigc_image_to_video_uses_published_text_to_video_price(engine):
    repository, wallet = _fund(engine, "user-video")
    job = _job(
        "video-job-1",
        capability="image_to_video",
        model_id="grok-imagine-video-1.5",
        parameters={"duration": 5},
    )

    reservation = reserve_aigc_job(job, "user-video", engine=engine)

    assert reservation is not None
    assert reservation.pricing_capability == "text_to_video"
    assert reservation.quoted_credits == 600
    reservation.settle_success(outputs=[object()], supplier_reference="video-task-1")
    assert repository.balance(str(wallet["id"])).available == 1_400


def test_aigc_admission_is_idempotent_and_blocks_zero_balance(engine):
    repository, wallet = _fund(engine, "replay-user", credits=300)
    job = _job(
        "replay-image-job",
        capability="text_to_image",
        model_id="gpt-image-2",
        parameters={"imageCount": 1},
    )

    first = reserve_aigc_job(job, "replay-user", engine=engine)
    replay = reserve_aigc_job(job, "replay-user", engine=engine)

    assert first is not None and replay is not None
    assert replay.usage_order_id == first.usage_order_id
    balance = repository.balance(str(wallet["id"]))
    assert balance.held == 0
    assert balance.available == 300

    insufficient = _job(
        "unfunded-image-job",
        capability="text_to_image",
        model_id="gpt-image-2",
        parameters={"imageCount": 1},
    )
    with pytest.raises(InsufficientUsageCreditsError):
        reserve_aigc_job(insufficient, "unfunded-user", engine=engine)


def test_cancelled_unsubmitted_aigc_job_records_release_without_hold(
    engine,
    monkeypatch,
):
    repository, wallet = _fund(engine, "cancel-user", credits=300)
    job = _job(
        "cancel-image-job",
        capability="text_to_image",
        model_id="gpt-image-2",
        parameters={"imageCount": 1},
    )
    reservation = reserve_aigc_job(job, "cancel-user", engine=engine)
    assert reservation is not None
    balance = repository.balance(str(wallet["id"]))
    assert balance.held == 0
    assert balance.available == 300

    # Cleanup must honor the enforced order even if an operator changes the
    # process-wide default after the reservation was created.
    monkeypatch.setenv("DCLAW_BILLING_MODE", "off")
    settle_cancelled_aigc_job(job, "cancel-user", engine=engine)

    recovered = find_aigc_job_reservation(job, "cancel-user", engine=engine)
    assert recovered is not None
    assert recovered.item_status == "released"
    balance = repository.balance(str(wallet["id"]))
    assert balance.held == 0
    assert balance.available == 300


def test_cancelled_accepted_aigc_job_reconciles_without_hold(engine):
    repository, wallet = _fund(engine, "accepted-user", credits=600)
    job = _job(
        "accepted-video-job",
        capability="text_to_video",
        model_id="grok-imagine-video-1.5",
        parameters={"duration": 5},
    )
    reservation = reserve_aigc_job(job, "accepted-user", engine=engine)
    assert reservation is not None

    settle_cancelled_aigc_job(
        job,
        "accepted-user",
        supplier_references=["remote-video-task"],
        engine=engine,
    )

    recovered = find_aigc_job_reservation(job, "accepted-user", engine=engine)
    assert recovered is not None
    assert recovered.item_status == "reconciling"
    balance = repository.balance(str(wallet["id"]))
    assert balance.held == 0
    assert balance.available == 600
