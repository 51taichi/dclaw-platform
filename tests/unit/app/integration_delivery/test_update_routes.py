from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.integration_delivery import auth, router as router_module
from qwenpaw.app.integration_delivery.models import (
    DeliveryOperationView,
    DeliveryValidation,
)
from qwenpaw.app.integration_delivery.update import (
    DeliveryBundleError,
    DeliveryIdempotencyKeyReused,
    DeliverySourceChanged,
)


AUTH = {
    auth.CLIENT_HEADER: "worktool",
    auth.SECRET_HEADER: "secret-value",
}
BASELINE = {
    "X-DClaw-Expected-Agent-Digest": "sha256:" + "1" * 64,
    "X-DClaw-Expected-Knowledge-Digest": "sha256:" + "2" * 64,
}


class _Updater:
    def __init__(self) -> None:
        self.body = None
        self.error = None
        self.calls = 0

    def validate(self, agent_id, archive, **kwargs):
        self.body = archive
        if self.error:
            raise self.error
        return DeliveryValidation(
            agent_id=agent_id,
            agent_profile_id="standard-2026.09",
            source_version="workspace",
            agent_digest="sha256:" + "3" * 64,
            knowledge_digest="sha256:" + "4" * 64,
        )

    def apply(self, agent_id, archive, operation_id, **kwargs):
        self.calls += 1
        self.body = archive
        if self.error:
            raise self.error
        return DeliveryOperationView(
            operation_id=operation_id,
            agent_id=agent_id,
            status="applied",
            previous_agent_digest=BASELINE["X-DClaw-Expected-Agent-Digest"],
            previous_knowledge_digest=BASELINE[
                "X-DClaw-Expected-Knowledge-Digest"
            ],
            agent_digest="sha256:" + "3" * 64,
            knowledge_digest="sha256:" + "4" * 64,
        )

    def get_operation(self, agent_id, operation_id):
        return self.apply(agent_id, b"", operation_id)

    def restore(self, agent_id, operation_id):
        result = self.apply(agent_id, b"", operation_id)
        return result.model_copy(update={"status": "restored"})


def _client(monkeypatch, updater: _Updater) -> TestClient:
    monkeypatch.setenv(
        auth.CLIENT_SECRETS_ENV,
        '{"worktool":"secret-value"}',
    )
    app = FastAPI()
    app.include_router(router_module.router)
    app.dependency_overrides[router_module.get_integration_delivery_updater] = (
        lambda: updater
    )
    return TestClient(app)


def test_write_routes_require_integration_authentication(monkeypatch) -> None:
    client = _client(monkeypatch, _Updater())

    response = client.post(
        "/internal/integrations/v1/agents/a_service/delivery-bundle/validate",
        content=b"zip-content",
        headers=BASELINE,
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "INVALID_INTEGRATION_CREDENTIAL"


def test_validate_receives_raw_zip_and_returns_stable_contract(monkeypatch) -> None:
    updater = _Updater()
    client = _client(monkeypatch, updater)

    response = client.post(
        "/internal/integrations/v1/agents/a_service/delivery-bundle/validate",
        content=b"zip-content",
        headers={**AUTH, **BASELINE, "Content-Type": "application/zip"},
    )

    assert response.status_code == 200
    assert updater.body == b"zip-content"
    assert response.json()["valid"] is True
    assert response.json()["agentId"] == "a_service"


def test_apply_requires_idempotency_and_baseline_headers(monkeypatch) -> None:
    client = _client(monkeypatch, _Updater())

    response = client.put(
        "/internal/integrations/v1/agents/a_service/delivery-bundle",
        content=b"zip-content",
        headers=AUTH,
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "DCLAW_REQUEST_INVALID"


def test_apply_returns_operation_and_same_key_is_stable(monkeypatch) -> None:
    updater = _Updater()
    client = _client(monkeypatch, updater)
    headers = {**AUTH, **BASELINE, "Idempotency-Key": "release-r6"}

    first = client.put(
        "/internal/integrations/v1/agents/a_service/delivery-bundle",
        content=b"zip-content",
        headers=headers,
    )
    second = client.put(
        "/internal/integrations/v1/agents/a_service/delivery-bundle",
        content=b"zip-content",
        headers=headers,
    )

    assert first.status_code == 200
    assert second.json()["operationId"] == first.json()["operationId"]
    assert len(first.json()["operationId"]) == 64


def test_write_errors_have_stable_codes(monkeypatch) -> None:
    updater = _Updater()
    client = _client(monkeypatch, updater)
    headers = {**AUTH, **BASELINE, "Idempotency-Key": "release-r6"}
    cases = [
        (DeliverySourceChanged("changed"), 409, "DCLAW_SOURCE_CHANGED"),
        (
            DeliveryIdempotencyKeyReused("reused"),
            409,
            "IDEMPOTENCY_KEY_REUSED",
        ),
        (
            DeliveryBundleError("invalid"),
            400,
            "DCLAW_DELIVERY_BUNDLE_INVALID",
        ),
    ]
    for error, status, code in cases:
        updater.error = error
        response = client.put(
            "/internal/integrations/v1/agents/a_service/delivery-bundle",
            content=b"private-zip-content",
            headers=headers,
        )
        assert response.status_code == status
        assert response.json()["detail"] == {"code": code}


def test_query_and_restore_operation(monkeypatch) -> None:
    client = _client(monkeypatch, _Updater())
    operation_id = "a" * 64

    queried = client.get(
        f"/internal/integrations/v1/agents/a_service/delivery-operations/{operation_id}",
        headers=AUTH,
    )
    restored = client.post(
        f"/internal/integrations/v1/agents/a_service/delivery-operations/{operation_id}/restore",
        headers={**AUTH, "Idempotency-Key": "restore-r6"},
    )

    assert queried.status_code == 200
    assert restored.status_code == 200
    assert restored.json()["status"] == "restored"
