# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.integration_delivery import router as router_module


def test_platform_capability_catalog_is_generic_and_versioned() -> None:
    app = FastAPI()
    app.dependency_overrides[
        router_module.require_integration_client
    ] = lambda: None
    app.include_router(router_module.router, prefix="/api")

    response = TestClient(app).get(
        "/api/internal/integrations/v1/capabilities",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == "dclaw-integration-capabilities.v1"
    assert body["version"] == "2026.10.02"
    assert set(body["profiles"]) == {
        "standard-2026.09",
        "super-expert-2026.09",
    }
    assert body["profiles"]["standard-2026.09"] == {
        "profileId": "standard-2026.09",
        "name": "普通专家",
        "capabilities": [
            "文件化Agent源码",
            "DClaw平台工具",
            "经验库检索",
        ],
    }
    assert body["profiles"]["super-expert-2026.09"] == {
        "profileId": "super-expert-2026.09",
        "name": "超级专家",
        "capabilities": [
            "超级专家源码快照",
            "超级专家运行能力",
            "DClaw平台工具",
            "经验库检索",
        ],
    }
    assert body["platformCapabilities"] == [
        "agent-delivery-context",
        "agent-source-bundle",
        "knowledge-source-bundle",
        "agent-delivery-validate",
        "agent-delivery-update",
        "knowledge-delivery-update",
        "delivery-restore",
    ]
    assert "AI客服" not in response.text
    assert "状态机" not in response.text
    assert "标签" not in response.text
    assert "Bot" not in response.text


def test_router_exposes_only_generic_platform_paths() -> None:
    paths = {route.path for route in router_module.router.routes}

    assert paths == {
        "/internal/integrations/v1/capabilities",
        "/internal/integrations/v1/agents/{agent_id}/delivery-context",
        "/internal/integrations/v1/agents/{agent_id}/source-bundle",
        "/internal/integrations/v1/agents/{agent_id}/delivery-bundle/validate",
        "/internal/integrations/v1/agents/{agent_id}/delivery-bundle",
        "/internal/integrations/v1/agents/{agent_id}/"
        "delivery-operations/{operation_id}",
        "/internal/integrations/v1/agents/{agent_id}/"
        "delivery-operations/{operation_id}/restore",
    }
