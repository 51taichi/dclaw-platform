# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus
from qwenpaw.app.super_experts.interaction_cards import (
    InteractionCardRepository,
    InteractionError,
    InteractionService,
)
from qwenpaw.app.super_experts.interaction_contract import (
    InteractionCreateRequest,
)


def _request():
    return InteractionCreateRequest.model_validate(
        {
            "task_key": "pick-plan",
            "interaction_revision": 1,
            "component_type": "single_select",
            "card": {
                "title": "请选择方案",
                "options": [
                    {"id": "a", "text": "方案甲", "recommended": True},
                    {"text": "方案乙"},
                ],
                "supplement": {"enabled": True, "required": False},
            },
        },
    )


def _question_request(task_key: str = "business-context"):
    return InteractionCreateRequest.model_validate(
        {
            "task_key": task_key,
            "interaction_revision": 1,
            "component_type": "question_form",
            "card": {
                "title": "请补充以下信息",
                "items": [
                    {
                        "id": "scope",
                        "question": "服务范围？",
                        "required": True,
                        "max_length": 20,
                    },
                    {"question": "其他情况？", "required": False},
                ],
            },
        },
    )


def _file_request():
    return InteractionCreateRequest.model_validate(
        {
            "task_key": "source-file",
            "interaction_revision": 1,
            "component_type": "file_selector",
            "card": {
                "title": "请选择源视频",
                "accept_extensions": [".mp4"],
                "max_file_size_bytes": 100,
                "max_total_size_bytes": 100,
            },
        },
    )


class _GrantRepository:
    def __init__(self, *, file_select: bool = False):
        self.file_select = file_select
        self.grant = SimpleNamespace(
            installation_id="installation-1",
            tenant_id="local",
            agent_id="agent-1",
        )

    def get(self, installation_id):
        return self.grant if installation_id == "installation-1" else None

    def list_grants(self):
        return [self.grant]

    def authorize_capability(
        self,
        installation_id,
        capability,
        contract_version,
        *,
        tenant_id,
    ):
        return SimpleNamespace(
            allowed=(
                installation_id == "installation-1"
                and tenant_id == "local"
                and contract_version == "1"
                and capability
                in {
                    "interaction.card.create/1",
                    "interaction.card.cancel/1",
                }
                | (
                    {"interaction.file.select/1"}
                    if self.file_select
                    else set()
                )
            ),
        )


@pytest.mark.asyncio
async def test_platform_create_persists_card_and_publishes_separate_event(
    tmp_path,
):
    from qwenpaw.app.super_experts.service import SuperExpertPlatformService
    from qwenpaw.app.super_experts.events import SuperExpertEventRepository
    from qwenpaw.app.super_experts.aigc_tasks import AigcTaskRepository

    bus = MemoryRuntimeEventBus(max_events=20, max_age_seconds=60)
    interaction_service = InteractionService(
        InteractionCardRepository(tmp_path),
    )
    service = SuperExpertPlatformService(
        grant_repository=_GrantRepository(),
        task_repository=AigcTaskRepository(tmp_path / "aigc"),
        event_repository=SuperExpertEventRepository(tmp_path / "aigc"),
        event_bus=bus,
        interaction_service=interaction_service,
    )

    result = await service.execute_interaction(
        tenant_id="local",
        installation_id="installation-1",
        conversation_id="conversation-1",
        capability="interaction.card.create/1",
        contract_version="1",
        arguments={"request": _request().model_dump(mode="json")},
        idempotency_key="create-1",
    )

    assert result["interaction"]["status"] == "PENDING"
    events = await bus.replay(session_id="conversation-1", since_id=None)
    assert len(events) == 1
    assert events[0].type == "super_expert_interaction"
    envelope = events[0].payload["envelope"]
    assert envelope["event_type"] == "interaction.card.created"
    assert "material_task_id" not in envelope
    assert envelope["interaction"]["card"]["options"][0]["text"] == "方案甲"


def test_create_after_submission_replays_or_reports_semantic_conflict(tmp_path):
    interactions = InteractionService(InteractionCardRepository(tmp_path))
    request = _question_request()
    card = interactions.create(
        installation_id="installation-1",
        conversation_id="conversation-1",
        request=request,
        idempotency_key="create-original",
    )
    submitted = interactions.submit(
        interaction_id=card.interaction_id,
        installation_id="installation-1",
        conversation_id="conversation-1",
        version=card.version,
        answers=[{"id": "scope", "value": "空调维修"}],
        idempotency_key="submit-original",
    )

    replayed = interactions.create(
        installation_id="installation-1",
        conversation_id="conversation-1",
        request=request,
        idempotency_key="create-retry",
    )

    assert replayed == submitted

    changed = request.model_copy(
        update={
            "card": request.card.model_copy(
                update={"description": "请补充最新信息"},
            ),
        },
    )
    with pytest.raises(InteractionError) as caught:
        interactions.create(
            installation_id="installation-1",
            conversation_id="conversation-1",
            request=changed,
            idempotency_key="create-changed",
        )

    assert caught.value.code == "IDEMPOTENCY_CONFLICT"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_file_selector_requires_dedicated_installation_capability(
    tmp_path,
):
    from qwenpaw.app.super_experts.service import (
        SuperExpertPlatformError,
        SuperExpertPlatformService,
    )
    from qwenpaw.app.super_experts.events import SuperExpertEventRepository
    from qwenpaw.app.super_experts.aigc_tasks import AigcTaskRepository

    def build(grants):
        return SuperExpertPlatformService(
            grant_repository=grants,
            task_repository=AigcTaskRepository(tmp_path / "aigc"),
            event_repository=SuperExpertEventRepository(tmp_path / "aigc"),
            event_bus=MemoryRuntimeEventBus(max_events=20, max_age_seconds=60),
            interaction_service=InteractionService(
                InteractionCardRepository(
                    tmp_path / grants.__class__.__name__,
                ),
            ),
        )

    denied = build(_GrantRepository(file_select=False))
    with pytest.raises(SuperExpertPlatformError, match="not authorized"):
        await denied.execute_interaction(
            tenant_id="local",
            installation_id="installation-1",
            conversation_id="conversation-1",
            capability="interaction.card.create/1",
            contract_version="1",
            arguments={"request": _file_request().model_dump(mode="json")},
            idempotency_key="file-denied",
        )

    allowed = build(_GrantRepository(file_select=True))
    result = await allowed.execute_interaction(
        tenant_id="local",
        installation_id="installation-1",
        conversation_id="conversation-1",
        capability="interaction.card.create/1",
        contract_version="1",
        arguments={"request": _file_request().model_dump(mode="json")},
        idempotency_key="file-allowed",
    )
    assert result["interaction"]["component_type"] == "file_selector"


def test_question_form_submission_summary_shows_only_filled_values(tmp_path):
    from qwenpaw.app.routers import super_expert_platform as router_module

    interaction_service = InteractionService(
        InteractionCardRepository(tmp_path),
    )
    card = interaction_service.create(
        installation_id="installation-1",
        conversation_id="conversation-1",
        request=_question_request(),
        idempotency_key="create-question-summary",
    )
    card = interaction_service.submit(
        interaction_id=card.interaction_id,
        installation_id="installation-1",
        conversation_id="conversation-1",
        version=card.version,
        answers=[{"id": "scope", "value": "空调维修"}],
        idempotency_key="submit-question-summary",
    )

    assert router_module._interaction_submission_summary(card) == "空调维修"


def _platform_service(tmp_path):
    from qwenpaw.app.super_experts.service import SuperExpertPlatformService
    from qwenpaw.app.super_experts.events import SuperExpertEventRepository
    from qwenpaw.app.super_experts.aigc_tasks import AigcTaskRepository

    return SuperExpertPlatformService(
        grant_repository=_GrantRepository(),
        task_repository=AigcTaskRepository(tmp_path / "aigc"),
        event_repository=SuperExpertEventRepository(tmp_path / "aigc"),
        event_bus=MemoryRuntimeEventBus(max_events=20, max_age_seconds=60),
        interaction_service=InteractionService(
            InteractionCardRepository(tmp_path / "interactions"),
        ),
    )


@pytest.mark.asyncio
async def test_submit_returns_trusted_user_input_without_running_the_agent(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.routers import super_expert_platform as router_module

    service = _platform_service(tmp_path)
    card = service.interactions.create(
        installation_id="installation-1",
        conversation_id="conversation-1",
        request=_request(),
        idempotency_key="create-immediate-submit",
    )
    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: service,
    )
    monkeypatch.setattr(
        router_module,
        "ensure_chat_access",
        lambda *_args, **_kwargs: {
            "id": "chat-1",
            "session_id": "conversation-1",
        },
    )
    app = FastAPI()
    app.include_router(router_module.frontend_read_router)
    body = {
        "version": 1,
        "selected": [{"id": "a"}],
        "supplement": None,
        "idempotency_key": "submit-immediately",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        submitted = await client.post(
            f"/super-expert-platform/interactions/{card.interaction_id}/submit",
            json=body,
        )

    assert submitted.status_code == 200
    assert submitted.json() == {
        "interaction": submitted.json()["interaction"],
        "user_input": "方案甲",
    }
    events = await service.event_bus.replay(
        session_id="conversation-1",
        since_id=None,
    )
    interaction_events = [
        event for event in events if event.type == "super_expert_interaction"
    ]
    assert [
        event.payload["envelope"]["event_type"] for event in interaction_events
    ] == ["interaction.card.submitted"]


@pytest.mark.asyncio
async def test_restore_and_submit_routes_are_scoped_and_idempotent(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.routers import super_expert_platform as router_module

    service = _platform_service(tmp_path)
    card = service.interactions.create(
        installation_id="installation-1",
        conversation_id="conversation-1",
        request=_request(),
        idempotency_key="create-1",
    )
    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: service,
    )
    monkeypatch.setattr(
        router_module,
        "ensure_chat_access",
        lambda _request, conversation_id, **_kwargs: {
            "id": "chat-1",
            "session_id": conversation_id,
            "agent_id": "agent-1",
        },
    )
    app = FastAPI()
    app.include_router(router_module.frontend_read_router)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        restored = await client.get(
            "/super-expert-platform/interactions",
            params={"conversation_id": "conversation-1"},
        )
        submitted = await client.post(
            f"/super-expert-platform/interactions/{card.interaction_id}/submit",
            json={
                "version": 1,
                "selected": [{"id": "a"}],
                "supplement": "补充说明",
                "idempotency_key": "submit-1",
            },
        )
        replayed = await client.post(
            f"/super-expert-platform/interactions/{card.interaction_id}/submit",
            json={
                "version": 1,
                "selected": [{"id": "a"}],
                "supplement": "补充说明",
                "idempotency_key": "submit-1",
            },
        )
        conflicting_payload = await client.post(
            f"/super-expert-platform/interactions/{card.interaction_id}/submit",
            json={
                "version": 1,
                "selected": [{"text": "方案乙"}],
                "supplement": "补充说明",
                "idempotency_key": "submit-1",
            },
        )
        new_operation = await client.post(
            f"/super-expert-platform/interactions/{card.interaction_id}/submit",
            json={
                "version": 1,
                "selected": [{"id": "a"}],
                "supplement": "补充说明",
                "idempotency_key": "submit-2",
            },
        )

    assert restored.status_code == 200
    assert [
        item["interaction_id"] for item in restored.json()["interactions"]
    ] == [
        card.interaction_id,
    ]
    assert submitted.status_code == 200
    assert submitted.json()["interaction"]["answer"]["selected"] == [
        {"id": "a", "text": "方案甲"},
    ]
    assert submitted.json()["user_input"] == "方案甲\n补充说明"
    assert replayed.status_code == 200
    assert replayed.json()["user_input"] == "方案甲\n补充说明"
    assert conflicting_payload.status_code == 409
    assert (
        conflicting_payload.json()["detail"]["error"] == "IDEMPOTENCY_CONFLICT"
    )
    assert new_operation.status_code == 409
    assert new_operation.json()["detail"]["error"] == "INTERACTION_NOT_PENDING"


@pytest.mark.asyncio
async def test_question_form_route_persists_trusted_answers_and_rejects_missing_required(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app.routers import super_expert_platform as router_module

    service = _platform_service(tmp_path)
    first = service.interactions.create(
        installation_id="installation-1",
        conversation_id="conversation-1",
        request=_question_request(),
        idempotency_key="create-question-form",
    )
    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: service,
    )
    monkeypatch.setattr(
        router_module,
        "ensure_chat_access",
        lambda *_args, **_kwargs: {
            "id": "chat-1",
            "session_id": "conversation-1",
            "agent_id": "agent-1",
        },
    )
    app = FastAPI()
    app.include_router(router_module.frontend_read_router)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        submitted = await client.post(
            f"/super-expert-platform/interactions/{first.interaction_id}/submit",
            json={
                "version": 1,
                "answers": [{"id": "scope", "value": "  空调维修  "}],
                "idempotency_key": "submit-question-form",
            },
        )
        second = service.interactions.create(
            installation_id="installation-1",
            conversation_id="conversation-2",
            request=_question_request("second-context"),
            idempotency_key="create-second-question-form",
        )
        missing = await client.post(
            f"/super-expert-platform/interactions/{second.interaction_id}/submit",
            json={
                "version": 1,
                "answers": [],
                "idempotency_key": "submit-missing-required",
            },
        )

    assert submitted.status_code == 200
    assert submitted.json()["interaction"]["answer"]["answers"] == [
        {"id": "scope", "question": "服务范围？", "value": "空调维修"},
        {"id": None, "question": "其他情况？", "value": None},
    ]
    assert submitted.json()["user_input"] == "空调维修"
    assert missing.status_code == 422
    assert missing.json()["detail"]["error"] == "REQUIRED_ANSWER_MISSING"
