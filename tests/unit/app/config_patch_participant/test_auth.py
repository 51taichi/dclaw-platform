from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.config_patch_participant import router as router_module


class _ReadyService:
    def describe(self, agent_id: str):
        from qwenpaw.app.config_patch_participant.models import (
            DclawConfigurationContext,
            Readiness,
        )

        return DclawConfigurationContext(
            agent_id=agent_id,
            agent_type="standard",
            agent_profile_id="standard-2026.09",
            enabled=True,
            source_version="workspace",
            readiness=Readiness(ready=True),
        )


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[
        router_module.get_dclaw_configuration_context_service
    ] = lambda: _ReadyService()
    app.include_router(router_module.router, prefix="/api")
    return TestClient(app)


def test_internal_route_is_unavailable_without_configured_service_secret(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
):
    monkeypatch.delenv("DCLAW_CONFIG_PATCH_INTERNAL_SECRET", raising=False)

    response = client.get(
        "/api/internal/config-patch/v1/agents/a_service/context",
        headers={"X-DClaw-Config-Patch-Secret": "caller-secret"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CONFIG_PATCH_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-DClaw-Config-Patch-Secret": "wrong"},
        {"Authorization": "Bearer ordinary-user-token"},
        {"Authorization": "Bearer admin-token"},
        {"Authorization": "Bearer dclaw_staff_employee-token"},
    ],
)
def test_internal_route_rejects_every_identity_except_service_secret(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    headers: dict[str, str],
):
    monkeypatch.setenv("DCLAW_CONFIG_PATCH_INTERNAL_SECRET", "internal-only")

    response = client.get(
        "/api/internal/config-patch/v1/agents/a_service/context",
        headers=headers,
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_SERVICE_CREDENTIAL"


def test_internal_route_accepts_exact_service_secret(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
):
    monkeypatch.setenv("DCLAW_CONFIG_PATCH_INTERNAL_SECRET", "internal-only")

    response = client.get(
        "/api/internal/config-patch/v1/agents/a_service/context",
        headers={"X-DClaw-Config-Patch-Secret": "internal-only"},
    )

    assert response.status_code == 200
    assert response.json()["agentId"] == "a_service"
    assert response.json()["readiness"] == {"ready": True, "missingItems": []}


def test_auth_failures_do_not_log_credentials(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
):
    configured = "configured-secret-must-not-leak"
    supplied = "supplied-secret-must-not-leak"
    monkeypatch.setenv("DCLAW_CONFIG_PATCH_INTERNAL_SECRET", configured)

    with caplog.at_level(logging.DEBUG):
        response = client.get(
            "/api/internal/config-patch/v1/agents/a_service/context",
            headers={"X-DClaw-Config-Patch-Secret": supplied},
        )

    assert response.status_code == 401
    rendered = caplog.text
    assert configured not in rendered
    assert supplied not in rendered
