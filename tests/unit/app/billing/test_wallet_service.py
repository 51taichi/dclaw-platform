# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import select

from qwenpaw.app.billing.models import WalletBalance
from qwenpaw.app.billing.service import WalletService
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.schema import billing_credit_lots, create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "wallet-service.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def service(engine):
    return WalletService(BillingRepository(engine))


def test_get_or_create_personal_wallet_gives_existing_user_one_wallet(
    service,
):
    first = service.get_or_create_personal_wallet(18)
    second = service.get_or_create_personal_wallet(18)

    assert first == WalletBalance(0, 0, 0, 0, 0)
    assert second == first


def test_signup_trial_is_granted_once_for_a_risk_identity(service, engine):
    first = service.grant_signup_trial(
        user_id=18,
        verified_mobile="+8613800138000",
        risk_key="device:abc",
    )
    repeated = service.grant_signup_trial(
        user_id=18,
        verified_mobile="+8613800138000",
        risk_key="device:abc",
    )

    assert first.granted is True
    assert first.balance == WalletBalance(100, 0, 0, 100, 0)
    assert repeated.granted is False
    assert repeated.balance == first.balance

    with engine.connect() as conn:
        lot = conn.execute(select(billing_credit_lots)).mappings().one()
    expiry = lot["expires_at"].replace(tzinfo=timezone.utc)
    assert expiry > datetime.now(timezone.utc) + timedelta(days=6)
    assert expiry <= datetime.now(timezone.utc) + timedelta(days=8)


def test_unverified_mobile_does_not_grant_signup_trial(service):
    result = service.grant_signup_trial(
        user_id=18,
        verified_mobile="",
        risk_key="device:abc",
    )

    assert result.granted is False
    assert result.balance == WalletBalance(0, 0, 0, 0, 0)


def test_signup_trial_lot_limits_capabilities_to_standard_text_and_image(
    service,
    engine,
):
    service.grant_signup_trial(
        user_id=18,
        verified_mobile="+8613800138000",
        risk_key="device:abc",
    )

    with engine.connect() as conn:
        lot = conn.execute(select(billing_credit_lots)).mappings().one()
    metadata = json.loads(lot["metadata_json"])

    assert metadata["allowed_capabilities"] == ["text", "image"]
    assert metadata["denied_capabilities"] == [
        "video",
        "high_cost",
        "fixed_workflow",
    ]
    assert metadata["allowed_tiers"] == ["standard"]


def test_concurrent_signup_trial_requests_grant_once_per_risk_identity(
    service,
):
    start = Barrier(2)

    def grant_for(user_id: int):
        start.wait()
        return service.grant_signup_trial(
            user_id=user_id,
            verified_mobile="+8613800138000",
            risk_key="device:shared",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(grant_for, (18, 19)))

    assert sum(result.granted for result in results) == 1
    assert sorted(result.balance.promotional for result in results) == [0, 100]
