from __future__ import annotations

import json
import logging
from datetime import timedelta

from fastapi.testclient import TestClient


ADMIN_HEADER = {"X-Config-Patch-Admin-Secret": "test-admin-secret-never-log"}


def issue(client: TestClient, *, employee: str = "员工甲", expires_at: str | None = None):
    body = {"employeeName": employee, "tokenName": "Codex"}
    if expires_at is not None:
        body["expiresAt"] = expires_at
    response = client.post(
        "/internal/admin/v1/staff-tokens",
        headers=ADMIN_HEADER,
        json=body,
    )
    assert response.status_code == 201
    return response.json()


def test_whoami_requires_a_valid_nonexpired_nonrevoked_staff_bearer(client: TestClient, clock):
    active = issue(client)

    missing = client.get("/staff/v1/whoami")
    invalid = client.get(
        "/staff/v1/whoami",
        headers={"Authorization": "Bearer dclaw_staff_invalid"},
    )
    valid = client.get(
        "/staff/v1/whoami",
        headers={"Authorization": f"Bearer {active['token']}"},
    )

    expired = issue(
        client,
        employee="过期员工",
        expires_at=(clock.value - timedelta(seconds=1)).isoformat(),
    )
    expired_response = client.get(
        "/staff/v1/whoami",
        headers={"Authorization": f"Bearer {expired['token']}"},
    )

    revoked = issue(client, employee="撤销员工")
    client.post(
        f"/internal/admin/v1/staff-tokens/{revoked['tokenId']}/revoke",
        headers=ADMIN_HEADER,
    )
    revoked_response = client.get(
        "/staff/v1/whoami",
        headers={"Authorization": f"Bearer {revoked['token']}"},
    )

    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "STAFF_TOKEN_REQUIRED"
    assert invalid.status_code == 401
    assert invalid.json()["detail"]["code"] == "INVALID_STAFF_TOKEN"
    assert valid.status_code == 200
    assert valid.json()["employeeName"] == "员工甲"
    assert "token" not in valid.json()
    assert expired_response.status_code == 401
    assert expired_response.json()["detail"]["code"] == "STAFF_TOKEN_EXPIRED"
    assert revoked_response.status_code == 401
    assert revoked_response.json()["detail"]["code"] == "STAFF_TOKEN_REVOKED"


def test_admin_and_staff_credentials_cannot_substitute_for_each_other(client: TestClient):
    issued = issue(client)

    staff_on_admin = client.get(
        "/internal/admin/v1/staff-tokens",
        headers={"Authorization": f"Bearer {issued['token']}"},
    )
    admin_on_staff = client.get(
        "/staff/v1/whoami",
        headers=ADMIN_HEADER,
    )

    assert staff_on_admin.status_code == 401
    assert staff_on_admin.json()["detail"]["code"] == "INVALID_ADMIN_CREDENTIAL"
    assert admin_on_staff.status_code == 401
    assert admin_on_staff.json()["detail"]["code"] == "STAFF_TOKEN_REQUIRED"


def test_token_audit_and_logs_never_contain_credentials(
    client: TestClient,
    settings,
    caplog,
):
    caplog.set_level(logging.INFO, logger="config_patch_service.audit")
    issued = issue(client, employee="审计员工")
    raw_token = issued["token"]

    client.get(
        "/staff/v1/whoami",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    client.get(
        "/staff/v1/whoami",
        headers={"Authorization": "Bearer dclaw_staff_bad-secret-value"},
    )
    client.post(
        f"/internal/admin/v1/staff-tokens/{issued['tokenId']}/rotate",
        headers=ADMIN_HEADER,
    )
    client.post(
        f"/internal/admin/v1/staff-tokens/{issued['tokenId']}/revoke",
        headers=ADMIN_HEADER,
    )

    database = client.app.state.config_patch_database
    with database.connect() as connection:
        events = [dict(row) for row in connection.execute(
            "SELECT action, token_id, employee_name, result, metadata_json FROM audit_events ORDER BY id"
        )]

    assert {event["action"] for event in events}.issuperset(
        {"staff_token.create", "staff_token.authenticate", "staff_token.rotate", "staff_token.revoke"}
    )
    assert any(event["result"] == "failure" for event in events)
    assert all(set(json.loads(event["metadata_json"])).isdisjoint(
        {"token", "authorization", "pepper", "secret"}) for event in events)

    rendered = caplog.text + json.dumps(events, ensure_ascii=False)
    for forbidden in (
        raw_token,
        "dclaw_staff_bad-secret-value",
        settings.token_pepper,
        settings.admin_secret,
        f"Bearer {raw_token}",
    ):
        assert forbidden not in rendered
