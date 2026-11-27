"""Local cross-boundary interaction flow without external services."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus
from qwenpaw.app.super_experts.aigc_tasks import AigcTaskRepository
from qwenpaw.app.super_experts.events import SuperExpertEventRepository
from qwenpaw.app.super_experts.grants import AuthorizationDecision
from qwenpaw.app.super_experts.interaction_cards import (
    InteractionCardRepository,
    InteractionService,
)
from qwenpaw.app.super_experts.interaction_contract import build_interaction_catalog
from qwenpaw.app.super_experts.service import SuperExpertPlatformService


class GrantedInstallation:
    grant = SimpleNamespace(
        installation_id="installation-1",
        tenant_id="local",
        agent_id="luyu",
    )

    def get(self, installation_id):
        return self.grant if installation_id == self.grant.installation_id else None

    def list_grants(self):
        return [self.grant]

    def authorize_capability(
        self, installation_id, capability, contract_version, *, tenant_id,
    ):
        allowed = (
            installation_id == self.grant.installation_id
            and tenant_id == self.grant.tenant_id
            and contract_version == "1"
            and capability in {
                "interaction.card.create/1",
                "interaction.card.cancel/1",
            }
        )
        return AuthorizationDecision(
            allowed=allowed,
            installation_id=installation_id,
            capability_id=capability,
            contract_version=contract_version,
            reason="granted" if allowed else "not_granted",
        )


@pytest.mark.asyncio
async def test_catalog_create_restore_submit_as_user_input_and_restore(
    monkeypatch, tmp_path,
):
    from qwenpaw.app.routers import super_expert_platform as routes

    catalog = build_interaction_catalog(["single_select"])
    assert catalog["components"][0]["component_type"] == "single_select"
    question_catalog = build_interaction_catalog(["question_form"])
    assert question_catalog["components"][0]["component_type"] == "question_form"
    bus = MemoryRuntimeEventBus(max_events=20, max_age_seconds=60)
    interactions = InteractionService(
        InteractionCardRepository(tmp_path / "interactions"),
    )
    platform = SuperExpertPlatformService(
        grant_repository=GrantedInstallation(),
        task_repository=AigcTaskRepository(tmp_path / "aigc"),
        event_repository=SuperExpertEventRepository(tmp_path / "aigc"),
        event_bus=bus,
        interaction_service=interactions,
    )
    created = await platform.execute_interaction(
        tenant_id="local",
        installation_id="installation-1",
        conversation_id="conversation-1",
        capability="interaction.card.create/1",
        contract_version="1",
        arguments={
            "request": {
                "task_key": "direction",
                "interaction_revision": 1,
                "component_type": "single_select",
                "input_policy": "card_only",
                "card": {
                    "title": "请选择方向",
                    "options": [
                        {"id": "a", "text": "方向甲", "recommended": True},
                        {"text": "方向乙"},
                    ],
                    "supplement": {"enabled": True, "required": False},
                },
            },
        },
        idempotency_key="create-direction-1",
    )
    interaction_id = created["interaction"]["interaction_id"]

    monkeypatch.setattr(routes, "get_super_expert_platform_service", lambda: platform)
    monkeypatch.setattr(
        routes,
        "ensure_chat_access",
        lambda *_args, **_kwargs: {
            "id": "chat-1",
            "session_id": "conversation-1",
            "agent_id": "luyu",
        },
    )
    app = FastAPI()
    app.include_router(routes.frontend_read_router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test",
    ) as client:
        before = await client.get(
            "/super-expert-platform/interactions",
            params={"conversation_id": "conversation-1"},
        )
        submitted = await client.post(
            f"/super-expert-platform/interactions/{interaction_id}/submit",
            json={
                "version": 1,
                "selected": [{"id": "a", "text": "篡改文本"}],
                "supplement": "补充",
                "idempotency_key": "submit-direction-1",
            },
        )
        question_created = await platform.execute_interaction(
            tenant_id="local",
            installation_id="installation-1",
            conversation_id="conversation-1",
            capability="interaction.card.create/1",
            contract_version="1",
            arguments={
                "request": {
                    "task_key": "business-context",
                    "interaction_revision": 1,
                    "component_type": "question_form",
                    "input_policy": "card_only",
                    "card": {
                        "title": "请补充以下信息",
                        "items": [
                            {
                                "id": "scope",
                                "question": "服务范围？",
                                "required": True,
                            },
                            {"question": "其他情况？", "required": False},
                        ],
                    },
                },
            },
            idempotency_key="create-business-context-1",
        )
        question_submitted = await client.post(
            "/super-expert-platform/interactions/"
            f"{question_created['interaction']['interaction_id']}/submit",
            json={
                "version": 1,
                "answers": [{"id": "scope", "value": "  空调维修  "}],
                "idempotency_key": "submit-business-context-1",
            },
        )
        after = await client.get(
            "/super-expert-platform/interactions",
            params={"conversation_id": "conversation-1"},
        )

    assert before.json()["interactions"][0]["status"] == "PENDING"
    assert before.json()["interactions"][0]["input_policy"] == "card_only"
    assert submitted.status_code == 200
    assert submitted.json()["user_input"] == "方向甲\n补充"
    assert question_submitted.status_code == 200
    assert question_submitted.json()["user_input"] == "空调维修"
    restored = after.json()["interactions"][0]
    assert restored["status"] == "SUBMITTED"
    events = await bus.replay(session_id="conversation-1", since_id=None)
    event_types_by_interaction = {}
    for event in events:
        envelope = event.payload["envelope"]
        event_types_by_interaction.setdefault(
            envelope["interaction_id"],
            [],
        ).append(envelope["event_type"])
    assert set(event_types_by_interaction) == {
        interaction_id,
        question_created["interaction"]["interaction_id"],
    }
    assert all(
        event_types == [
            "interaction.card.created",
            "interaction.card.submitted",
        ]
        for event_types in event_types_by_interaction.values()
    )
