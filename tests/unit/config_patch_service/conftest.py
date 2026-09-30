from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from config_patch_service.app import create_app
from config_patch_service.audit import AuditService
from config_patch_service.db import ConfigPatchDatabase
from config_patch_service.settings import ConfigPatchSettings
from config_patch_service.tokens import StaffTokenService


@dataclass
class MutableClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc))


@pytest.fixture
def settings(tmp_path) -> ConfigPatchSettings:
    return ConfigPatchSettings(
        data_dir=tmp_path / "config-patch-data",
        token_pepper="test-token-pepper-never-log",
        admin_secret="test-admin-secret-never-log",
        dclaw_service_secret="test-dclaw-service-secret",
        omnichannel_service_secret="test-omnichannel-service-secret",
    )


@pytest.fixture
def database(settings: ConfigPatchSettings) -> ConfigPatchDatabase:
    database = ConfigPatchDatabase(settings.database_path)
    database.initialize()
    return database


@pytest.fixture
def token_service(
    database: ConfigPatchDatabase,
    settings: ConfigPatchSettings,
    clock: MutableClock,
) -> StaffTokenService:
    audit = AuditService(database, clock=clock)
    return StaffTokenService(
        database,
        pepper=settings.token_pepper,
        audit=audit,
        clock=clock,
    )


@pytest.fixture
def client(
    settings: ConfigPatchSettings,
    clock: MutableClock,
) -> TestClient:
    return TestClient(create_app(settings=settings, clock=clock))
