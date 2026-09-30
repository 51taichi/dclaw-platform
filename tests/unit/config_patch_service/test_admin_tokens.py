from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from config_patch_service.app import create_app


ADMIN_HEADER = {"X-Config-Patch-Admin-Secret": "test-admin-secret-never-log"}


def test_admin_token_lifecycle_returns_plaintext_only_on_create_and_rotate(client: TestClient):
    created_response = client.post(
        "/internal/admin/v1/staff-tokens",
        headers=ADMIN_HEADER,
        json={"employeeName": "张三", "tokenName": "Codex"},
    )
    assert created_response.status_code == 201
    created = created_response.json()
    raw_token = created.pop("token")
    assert raw_token.startswith("dclaw_staff_")
    assert created["employeeName"] == "张三"

    listed_response = client.get(
        "/internal/admin/v1/staff-tokens",
        headers=ADMIN_HEADER,
    )
    assert listed_response.status_code == 200
    listed = listed_response.json()["tokens"]
    assert len(listed) == 1
    assert "token" not in listed[0]

    rotated_response = client.post(
        f"/internal/admin/v1/staff-tokens/{created['tokenId']}/rotate",
        headers=ADMIN_HEADER,
    )
    assert rotated_response.status_code == 200
    rotated = rotated_response.json()
    assert rotated["tokenId"] == created["tokenId"]
    assert rotated["token"] != raw_token

    revoked_response = client.post(
        f"/internal/admin/v1/staff-tokens/{created['tokenId']}/revoke",
        headers=ADMIN_HEADER,
    )
    assert revoked_response.status_code == 200
    assert revoked_response.json()["revokedAt"] is not None
    assert "token" not in revoked_response.json()


def test_admin_authentication_has_stable_fail_closed_codes(client: TestClient, settings, clock):
    missing = client.get("/internal/admin/v1/staff-tokens")
    wrong = client.get(
        "/internal/admin/v1/staff-tokens",
        headers={"X-Config-Patch-Admin-Secret": "wrong"},
    )
    unconfigured = TestClient(
        create_app(settings=replace(settings, admin_secret=""), clock=clock)
    ).get(
        "/internal/admin/v1/staff-tokens",
        headers={"X-Config-Patch-Admin-Secret": "anything"},
    )

    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "INVALID_ADMIN_CREDENTIAL"
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "INVALID_ADMIN_CREDENTIAL"
    assert unconfigured.status_code == 503
    assert unconfigured.json()["detail"]["code"] == "ADMIN_AUTH_NOT_CONFIGURED"


def test_admin_routes_return_not_found_for_unknown_token(client: TestClient):
    for operation in ("revoke", "rotate"):
        response = client.post(
            f"/internal/admin/v1/staff-tokens/missing/{operation}",
            headers=ADMIN_HEADER,
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "STAFF_TOKEN_NOT_FOUND"


def test_health_is_public_and_does_not_disclose_configuration(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "dclaw-config-patch",
        "version": "phase1",
    }
    serialized = response.text
    for forbidden in ("secret", "pepper", "dataDir", "upstream"):
        assert forbidden not in serialized
