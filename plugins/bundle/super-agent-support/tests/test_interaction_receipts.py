from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from super_agent.interaction_cards import InteractionCardRepository, InteractionService
from super_agent.interaction_contract import InteractionCreateRequest
from super_agent.interaction_receipts import card_receipt
from super_agent.service import SuperExpertPlatformService


SCHEMA = json.loads((
    Path(__file__).parents[1] / "devkit" / "schemas"
    / "interaction-card-receipt-v1" / "receipt.schema.json"
).read_text())


def test_create_submit_and_replay_have_stable_scoped_receipts(tmp_path):
    repo = InteractionCardRepository(tmp_path)
    request = InteractionCreateRequest.model_validate({
        "task_key": "choice",
        "interaction_revision": 1,
        "component_type": "single_select",
        "card": {"title": "Choice", "options": [
            {"id": "a", "text": "A"}, {"id": "b", "text": "B"},
        ]},
    })
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    created = repo.create(
        installation_id="install-a", conversation_id="task-a",
        request=request, idempotency_key="create-1", now=now,
    )
    created_receipt = card_receipt(created, "created")
    Draft202012Validator(SCHEMA).validate(created_receipt)
    assert created_receipt["answer_sha256"] is None
    submitted = repo.submit(
        interaction_id=created.interaction_id,
        installation_id="install-a", conversation_id="task-a",
        version=created.version, selected=[{"id": "a"}],
        supplement=None, answers=None, files=None,
        idempotency_key="submit-1", now=now,
    )
    submitted_receipt = card_receipt(submitted, "submitted")
    Draft202012Validator(SCHEMA).validate(submitted_receipt)
    assert submitted_receipt["status"] == "SUBMITTED"
    assert submitted_receipt["version"] == 2
    assert len(submitted_receipt["answer_sha256"]) == 64
    assert card_receipt(submitted, "created") == created_receipt
    assert card_receipt(repo.create(
        installation_id="install-a", conversation_id="task-a",
        request=request, idempotency_key="create-1", now=now,
    ), "created") == created_receipt
    assert card_receipt(repo.submit(
        interaction_id=created.interaction_id,
        installation_id="install-a", conversation_id="task-a",
        version=created.version, selected=[{"id": "a"}],
        supplement=None, answers=None, files=None,
        idempotency_key="submit-1", now=now,
    ), "submitted") == submitted_receipt


@pytest.mark.asyncio
async def test_create_replay_after_submit_does_not_publish_a_new_card(tmp_path):
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    interactions = InteractionService(
        InteractionCardRepository(tmp_path), clock=lambda: now,
    )
    events = []

    class EventBus:
        async def publish(self, event):
            events.append(event)

    service = SuperExpertPlatformService(
        grant_repository=SimpleNamespace(authorize_capability=lambda *_, **__: SimpleNamespace(allowed=True)),
        task_repository=SimpleNamespace(), event_repository=SimpleNamespace(),
        event_bus=EventBus(), interaction_service=interactions,
    )
    request = {
        "task_key": "choice", "interaction_revision": 1,
        "component_type": "single_select",
        "card": {"title": "Choice", "options": [
            {"id": "a", "text": "A"}, {"id": "b", "text": "B"},
        ]},
    }
    arguments = {
        "tenant_id": "local", "installation_id": "install-a",
        "conversation_id": "task-a", "capability": "interaction.card.create/1",
        "contract_version": "1", "arguments": {"request": request},
        "idempotency_key": "create-1",
    }
    created = await service.execute_interaction(**arguments)
    card = interactions.submit(
        interaction_id=created["interaction"]["interaction_id"],
        installation_id="install-a", conversation_id="task-a",
        version=1, selected=[{"id": "a"}], supplement=None,
        answers=None, files=None, idempotency_key="submit-1",
    )
    replay = await service.execute_interaction(**arguments)

    assert replay["receipt"] == created["receipt"]
    assert replay["interaction"]["status"] == "SUBMITTED"
    assert card.status.value == "SUBMITTED"
    assert [event.payload["envelope"]["event_type"] for event in events] == [
        "interaction.card.created",
    ]
