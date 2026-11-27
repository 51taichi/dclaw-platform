from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.integration_delivery import router as router_module
from qwenpaw.app.integration_delivery.service import (
    DclawConfigurationContextService,
)
from qwenpaw.app.sealed_agents.models import (
    RuntimeValidationRecord,
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.config.config import AgentProfileConfig, AgentProfileRef, Config


class _PublicationRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_publications(self, enabled_only: bool = False):
        assert enabled_only is False
        return list(self.rows)


class _WalletRepository:
    def __init__(self, existing_owner_ids=()):
        self.existing_owner_ids = set(existing_owner_ids)

    def get_wallet(self, owner_type: str, owner_id: str):
        assert owner_type == "user"
        if owner_id not in self.existing_owner_ids:
            return None
        return {"id": f"wallet-{owner_id}", "owner_id": owner_id}


class _SealedRegistry:
    def __init__(self, records=()):
        self.records = {record.agent_id: record for record in records}

    def get_agent(self, agent_id: str):
        return self.records.get(agent_id)


def _standard_config(*, enabled: bool = True) -> Config:
    config = Config()
    config.agents.profiles = {
        "a_service": AgentProfileRef(
            id="a_service",
            workspace_dir="/srv/workspaces/a_service",
            enabled=enabled,
        ),
    }
    return config


def _standard_profile() -> AgentProfileConfig:
    return AgentProfileConfig(
        id="a_service",
        name="售后客服",
        workspace_dir="/srv/workspaces/a_service",
    )


def _publication(**overrides):
    row = {
        "id": "publication-1",
        "public_id": "pub-a-service",
        "target_type": "agent",
        "target_id": "a_service",
        "status": "enabled",
        "bound_user_id": "42",
        "knowledge_base_id": "kb-a-service",
    }
    row.update(overrides)
    return row


def _sealed_record(*, active: bool = True, enabled: bool = True):
    release = SealedReleaseRecord(
        release_id="rel-1",
        version="2.3.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="official",
        package_type="super_expert",
        runtime_adapter="standard",
        runtime_contract_version="1",
        runtime_validation=RuntimeValidationRecord(
            status="valid",
            adapter="standard",
            contract_version="1",
        ),
        state="active" if active else "ready",
    )
    return SealedAgentRecord(
        agent_id="a_service",
        name="超级售后客服",
        enabled=enabled,
        active_release_id=release.release_id if active else None,
        releases=[release],
    )


def _service(
    *,
    config=None,
    sealed_records=(),
    publications=None,
    wallet_owner_ids=("42",),
):
    return DclawConfigurationContextService(
        config_loader=lambda: config if config is not None else Config(),
        agent_loader=lambda _agent_id: _standard_profile(),
        sealed_registry=_SealedRegistry(sealed_records),
        publication_repository=_PublicationRepository(
            [_publication()] if publications is None else publications,
        ),
        wallet_repository=_WalletRepository(wallet_owner_ids),
    )


def test_ready_standard_agent_context_resolves_publication_and_wallet():
    context = _service(config=_standard_config()).describe("a_service")

    assert context.model_dump(by_alias=True) == {
        "agentId": "a_service",
        "agentType": "standard",
        "agentProfileId": "standard-2026.09",
        "enabled": True,
        "sourceVersion": "workspace",
        "publicationId": "publication-1",
        "openapiPublicId": "pub-a-service",
        "knowledgeBaseId": "kb-a-service",
        "billingAccountConfigured": True,
        "readiness": {"ready": True, "missingItems": []},
    }


def test_ready_super_expert_uses_active_source_release():
    context = _service(
        config=Config(),
        sealed_records=[_sealed_record()],
    ).describe("a_service")

    assert context.agent_type == "sealed"
    assert context.agent_profile_id == "super-expert-2026.09"
    assert context.source_version == "2.3.0"
    assert context.readiness.ready is True


def test_delivery_context_route_returns_platform_agent_identity():
    service = _service(config=_standard_config())
    app = FastAPI()
    app.dependency_overrides[router_module.require_integration_client] = (
        lambda: None
    )
    app.dependency_overrides[
        router_module.get_dclaw_configuration_context_service
    ] = lambda: service
    app.include_router(router_module.router, prefix="/api")

    response = TestClient(app).get(
        "/api/internal/integrations/v1/agents/a_service/delivery-context"
    )

    assert response.status_code == 200
    assert response.json()["agentId"] == "a_service"
    assert response.json()["agentProfileId"] == "standard-2026.09"
    assert response.json()["readiness"]["ready"] is True


@pytest.mark.parametrize(
    ("service", "expected_missing"),
    [
        (_service(config=Config(), publications=[]), ["agent"]),
        (
            _service(config=_standard_config(enabled=False)),
            ["agent_enabled"],
        ),
        (
            _service(
                config=Config(),
                sealed_records=[_sealed_record(active=False)],
            ),
            ["agent_active_release"],
        ),
        (
            _service(config=_standard_config(), publications=[]),
            ["openapi_publication"],
        ),
        (
            _service(
                config=_standard_config(),
                publications=[_publication(status="disabled")],
            ),
            ["openapi_publication_enabled"],
        ),
        (
            _service(
                config=_standard_config(),
                publications=[_publication(target_id="different_agent")],
            ),
            ["openapi_publication"],
        ),
        (
            _service(config=_standard_config(), wallet_owner_ids=()),
            ["billing_account"],
        ),
    ],
)
def test_context_reports_each_bootstrap_failure(service, expected_missing):
    context = service.describe("a_service")

    assert context.readiness.ready is False
    for item in expected_missing:
        assert item in context.readiness.missing_items


def test_context_accumulates_all_missing_items_instead_of_stopping_early():
    context = _service(
        config=_standard_config(enabled=False),
        publications=[
            _publication(
                status="disabled",
                bound_user_id="",
                knowledge_base_id="",
            ),
        ],
        wallet_owner_ids=(),
    ).describe("a_service")

    assert context.readiness.missing_items == [
        "agent_enabled",
        "openapi_publication_enabled",
        "knowledge_base",
        "billing_account",
    ]
