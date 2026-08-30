from datetime import datetime, timedelta, timezone

import pytest

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.pricing_admin_repo import (
    PricingAdminRepository,
    PricingRevisionConflict,
)
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def repo(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "db.sqlite")}
        ),
    )
    create_all(engine)
    try:
        yield PricingAdminRepository(engine)
    finally:
        engine.dispose()


def _cost(amount: str, verified_at: datetime) -> dict:
    return {
        "provider_id": "dashscope",
        "model_key": "qwen-plus",
        "capability": "chat",
        "unit_key": "input_tokens",
        "source_type": "manual",
        "source_reference": "official-price-page",
        "original_currency": "CNY",
        "original_price_decimal": amount,
        "fx_rate_decimal": "1",
        "rmb_cost_decimal": amount,
        "conditions": {},
        "verification_status": "verified",
        "verified_at": verified_at,
    }


def test_latest_trusted_cost_preserves_history(repo):
    now = datetime.now(timezone.utc)
    first = repo.append_cost_snapshot(_cost("0.004", now))
    second = repo.append_cost_snapshot(
        _cost("0.006", now + timedelta(seconds=1))
    )
    assert first != second
    assert repo.latest_trusted_costs()[0]["rmb_cost_decimal"] == "0.006"
    assert len(repo.list_cost_snapshots()) == 2


def test_policy_rejects_stale_revision(repo):
    saved = repo.replace_policy(
        scope_type="global",
        scope_key="*",
        multiplier_decimal="1.5",
        settings={},
        actor_id="1",
        expected_revision=0,
    )
    assert saved["revision"] == 1
    with pytest.raises(PricingRevisionConflict):
        repo.replace_policy(
            scope_type="global",
            scope_key="*",
            multiplier_decimal="1.6",
            settings={},
            actor_id="1",
            expected_revision=0,
        )


def test_import_is_idempotent_and_unlock_expires(repo):
    first = repo.record_import("abc", "prices.xlsx", "1", {"rows": 1})
    second = repo.record_import("abc", "renamed.xlsx", "1", {"rows": 1})
    assert first["id"] == second["id"]

    now = datetime.now(timezone.utc)
    repo.create_unlock(
        "1",
        "token-hash",
        "credentials-v1",
        now + timedelta(minutes=15),
        "127.0.0.1",
    )
    assert repo.validate_unlock("token-hash", "1", "credentials-v1", now)
    assert not repo.validate_unlock("token-hash", "1", "credentials-v2", now)
    assert not repo.validate_unlock(
        "token-hash", "1", "credentials-v1", now + timedelta(minutes=16)
    )


def test_official_candidate_is_append_only_and_digest_idempotent(repo):
    candidate = {
        "content_sha256": "official-digest",
        "provider_id": "dashscope",
        "official_model_id": "qwen-plus",
        "capability": "chat",
        "unit_key": "input_tokens",
        "conditions_digest": "conditions-digest",
        "conditions": {"unit_size": 1000},
        "source_url": "https://help.aliyun.com/pricing",
        "source_published_at": None,
        "original_currency": "CNY",
        "original_price_decimal": "0.004",
        "fx_rate_decimal": "1",
        "rmb_cost_decimal": "0.004",
        "verification_status": "verified",
        "registry_version": "2026-08-30",
    }

    first = repo.append_official_candidate(candidate)
    second = repo.append_official_candidate(candidate)

    assert first == second
    assert repo.latest_official_candidates()[0]["id"] == first


def test_exact_model_mapping_uses_optimistic_revision(repo):
    saved = repo.replace_model_mapping(
        "custom-provider", "qwen-alias", "dashscope", "qwen-plus", "1", 0
    )
    assert saved["revision"] == 1
    assert repo.list_model_mappings()[0]["official_model_id"] == "qwen-plus"

    with pytest.raises(PricingRevisionConflict):
        repo.replace_model_mapping(
            "custom-provider", "qwen-alias", "dashscope", "qwen-max", "1", 0
        )


def test_draft_exclusion_requires_reason_and_can_be_reversed(repo):
    with pytest.raises(ValueError, match="reason"):
        repo.replace_draft_exclusion(
            "draft-1", "custom-provider", "model-x", True, None, "1"
        )

    excluded = repo.replace_draft_exclusion(
        "draft-1",
        "custom-provider",
        "model-x",
        True,
        "No verified official price",
        "1",
    )
    assert excluded["excluded"] is True
    included = repo.replace_draft_exclusion(
        "draft-1", "custom-provider", "model-x", False, None, "1"
    )
    assert included["excluded"] is False


def test_collection_job_claim_has_one_winner(repo):
    now = datetime.now(timezone.utc)
    job = repo.create_collection_job("inventory-digest", "admin-1", now)

    winners = [
        repo.claim_collection_job(f"worker-{index}", now, 60)
        for index in range(2)
    ]

    assert sum(row is not None for row in winners) == 1
    assert repo.get_collection_job(job["id"])["status"] == "running"


def test_expired_collection_job_can_be_reclaimed(repo):
    now = datetime.now(timezone.utc)
    job = repo.create_collection_job("inventory-digest", "admin-1", now)
    first = repo.claim_collection_job("worker-1", now, 1)

    reclaimed = repo.claim_collection_job(
        "worker-2", now + timedelta(seconds=2), 60
    )

    assert first is not None
    assert reclaimed is not None
    assert reclaimed["id"] == job["id"]
    assert reclaimed["worker_id"] == "worker-2"


def test_collection_item_progress_is_idempotent(repo):
    now = datetime.now(timezone.utc)
    job = repo.create_collection_job("inventory-digest", "admin-1", now)
    repo.claim_collection_job("worker-1", now, 60)

    first = repo.update_collection_item(
        job["id"],
        "dashscope",
        "qwen3-max",
        "cn-beijing",
        status="official_succeeded",
        result={"candidate_count": 6},
        candidate_id="candidate-1",
        error_summary=None,
        now=now,
    )
    second = repo.update_collection_item(
        job["id"],
        "dashscope",
        "qwen3-max",
        "cn-beijing",
        status="official_succeeded",
        result={"candidate_count": 6},
        candidate_id="candidate-1",
        error_summary=None,
        now=now,
    )

    assert first["id"] == second["id"]
    assert repo.get_collection_job(job["id"])["progress"] == {
        "total": 1,
        "completed": 1,
        "official": 1,
        "ai": 0,
        "manual": 0,
        "failed": 0,
    }


def test_model_publication_decisions_are_model_scoped(repo):
    rows = repo.set_model_publication_decisions(
        "draft-1",
        [
            {
                "provider_id": "dashscope",
                "model_key": "qwen3-max",
                "include_in_publish": True,
                "reason": None,
            },
            {
                "provider_id": "dashscope",
                "model_key": "unknown",
                "include_in_publish": False,
                "reason": "价格待审核",
            },
        ],
        "admin-1",
    )

    assert {
        (row["model_key"], row["include_in_publish"]) for row in rows
    } == {("qwen3-max", True), ("unknown", False)}
