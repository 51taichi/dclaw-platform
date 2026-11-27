from __future__ import annotations

import json
import logging

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.integration_delivery.auth import (
    AuthenticatedIntegrationClient,
    require_integration_client,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()

    @app.get("/api/internal/integrations/v1/probe")
    def probe(
        identity: AuthenticatedIntegrationClient = Depends(
            require_integration_client
        ),
    ) -> dict[str, str]:
        return {"clientId": identity.client_id}

    return TestClient(app)


def _configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DCLAW_INTEGRATION_CLIENT_SECRETS_JSON",
        json.dumps(
            {
                "ai-customer-service-test": "test-secret",
                "ai-customer-service-prod": "prod-secret",
            }
        ),
    )


def _headers(client_id: str, secret: str) -> dict[str, str]:
    return {
        "X-DClaw-Integration-Client": client_id,
        "X-DClaw-Integration-Secret": secret,
    }


@pytest.mark.parametrize("configured", [None, "", "{}", "[]", "not-json"])
def test_integration_api_is_unavailable_for_missing_or_invalid_configuration(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    configured: str | None,
) -> None:
    if configured is None:
        monkeypatch.delenv(
            "DCLAW_INTEGRATION_CLIENT_SECRETS_JSON", raising=False
        )
    else:
        monkeypatch.setenv(
            "DCLAW_INTEGRATION_CLIENT_SECRETS_JSON", configured
        )

    response = client.get(
        "/api/internal/integrations/v1/probe",
        headers=_headers("ai-customer-service-test", "test-secret"),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == (
        "INTEGRATION_API_NOT_CONFIGURED"
    )


def test_integration_api_rejects_duplicate_or_empty_clients(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    for configured in (
        '{"duplicate":"one","duplicate":"two"}',
        '{"":"secret"}',
        '{"client":""}',
        '{"client":1}',
    ):
        monkeypatch.setenv(
            "DCLAW_INTEGRATION_CLIENT_SECRETS_JSON", configured
        )
        response = client.get(
            "/api/internal/integrations/v1/probe",
            headers=_headers("client", "secret"),
        )
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == (
            "INTEGRATION_API_NOT_CONFIGURED"
        )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-DClaw-Integration-Client": "ai-customer-service-test"},
        {"X-DClaw-Integration-Secret": "test-secret"},
        _headers("unknown", "test-secret"),
        _headers("ai-customer-service-test", "wrong"),
        _headers("ai-customer-service-test", "prod-secret"),
        _headers("ai-customer-service-prod", "test-secret"),
        {"Authorization": "Bearer ordinary-user-token"},
    ],
)
def test_integration_api_rejects_missing_unknown_or_mismatched_identity(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    headers: dict[str, str],
) -> None:
    _configured(monkeypatch)

    response = client.get(
        "/api/internal/integrations/v1/probe", headers=headers
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == (
        "INVALID_INTEGRATION_CREDENTIAL"
    )


@pytest.mark.parametrize(
    ("client_id", "secret"),
    [
        ("ai-customer-service-test", "test-secret"),
        ("ai-customer-service-prod", "prod-secret"),
    ],
)
def test_integration_api_accepts_each_configured_service_identity(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    client_id: str,
    secret: str,
) -> None:
    _configured(monkeypatch)

    response = client.get(
        "/api/internal/integrations/v1/probe",
        headers=_headers(client_id, secret),
    )

    assert response.status_code == 200
    assert response.json() == {"clientId": client_id}


def test_integration_authentication_never_logs_credentials(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configured = "configured-secret-must-not-leak"
    supplied = "supplied-secret-must-not-leak"
    monkeypatch.setenv(
        "DCLAW_INTEGRATION_CLIENT_SECRETS_JSON",
        json.dumps({"customer-service": configured}),
    )

    with caplog.at_level(logging.DEBUG):
        response = client.get(
            "/api/internal/integrations/v1/probe",
            headers=_headers("customer-service", supplied),
        )

    assert response.status_code == 401
    assert configured not in caplog.text
    assert supplied not in caplog.text


def test_global_auth_delegates_the_integration_prefix_to_its_own_guard() -> None:
    from qwenpaw.app.auth import _PUBLIC_PREFIXES

    assert "/api/internal/integrations/" in _PUBLIC_PREFIXES
