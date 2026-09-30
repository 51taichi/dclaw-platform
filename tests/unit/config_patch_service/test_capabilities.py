from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from config_patch_service.app import create_app
from config_patch_service.capabilities import CapabilityCatalogError, CapabilityCatalogService


def test_catalog_declares_responsibility_profiles_semantics_and_request_contract():
    catalog = CapabilityCatalogService().load()

    assert catalog.schema_version == "capability-catalog.v1"
    assert catalog.version
    assert {module.module_id for module in catalog.modules} == {
        "agent",
        "state-machine-and-tags",
        "knowledge",
    }
    assert set(catalog.profiles) == {"standard-2026.09", "super-expert-2026.09"}
    assert set(catalog.semantics) == {"stateMachine", "tags", "knowledge"}
    assert catalog.capability_request.required_fields == [
        "botId",
        "requirement",
        "missingCapability",
        "suggestedPlatformChange",
    ]
    assert "demo" not in json.dumps(catalog.model_dump(), ensure_ascii=False).lower()


def test_unknown_profile_and_corrupt_catalog_fail_closed(tmp_path):
    service = CapabilityCatalogService()
    service.load()
    with pytest.raises(CapabilityCatalogError, match="unknown capability profile"):
        service.get_profile("invented-profile")

    corrupt = tmp_path / "catalog.json"
    corrupt.write_text('{"schemaVersion":"wrong","profiles":{}}', encoding="utf-8")
    with pytest.raises(CapabilityCatalogError):
        CapabilityCatalogService(path=corrupt).load()


def test_capability_route_requires_staff_token_and_returns_validated_catalog(
    settings,
    clock,
):
    client = TestClient(create_app(settings=settings, clock=clock))
    denied = client.get("/staff/v1/capabilities")
    assert denied.status_code == 401

    issued = client.post(
        "/internal/admin/v1/staff-tokens",
        headers={"X-Config-Patch-Admin-Secret": settings.admin_secret},
        json={"employeeName": "员工甲", "tokenName": "Codex"},
    ).json()
    response = client.get(
        "/staff/v1/capabilities",
        headers={"Authorization": f"Bearer {issued['token']}"},
    )

    assert response.status_code == 200
    assert response.json()["schemaVersion"] == "capability-catalog.v1"
    assert "standard-2026.09" in response.json()["profiles"]
