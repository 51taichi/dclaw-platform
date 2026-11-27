from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from super_agent.interaction_cards import InteractionCardRepository, InteractionService
from super_agent.interaction_cards import InteractionError
from super_agent.interaction_contract import InteractionAnswer, InteractionCreateRequest
from super_agent.interaction_receipts import card_receipt
from super_agent.capabilities import PLATFORM_CAPABILITY_CATALOG_V1
from super_agent.service import SuperExpertPlatformService


SCHEMA = json.loads((
    Path(__file__).parents[1] / "devkit" / "schemas"
    / "interaction-card-receipt-v1" / "receipt.schema.json"
).read_text())


@pytest.mark.parametrize(
    "kind,selected,custom,valid",
    [
        ("single_select", [], "我有不同情况", True),
        ("single_select", [{"id": "a"}], None, True),
        ("single_select", [{"id": "a"}], "我有不同情况", False),
        ("single_select", [], None, False),
        ("multi_select", [{"id": "a"}, {"id": "b"}], "第三种情况", True),
        ("multi_select", [{"id": "a"}, {"id": "b"}], None, True),
        ("multi_select", [], "第三种情况", False),
    ],
)
def test_custom_choice_is_exclusive_for_single_and_counted_for_multi(
    tmp_path, kind, selected, custom, valid,
):
    request = InteractionCreateRequest.model_validate({
        "task_key": "choice",
        "interaction_revision": 1,
        "component_type": kind,
        "card": {
            "title": "Choice",
            "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            "supplement": {"enabled": True, "answer_mode": "choice"},
            **({"min_selections": 2, "max_selections": 3}
               if kind == "multi_select" else {}),
        },
        "input_policy": "card_or_text",
    })
    repo = InteractionCardRepository(tmp_path)
    created = repo.create(
        installation_id="install-a", conversation_id="task-a",
        request=request, idempotency_key="create-1",
        now=datetime(2026, 11, 27, tzinfo=timezone.utc),
    )
    kwargs = {
        "interaction_id": created.interaction_id,
        "installation_id": "install-a",
        "conversation_id": "task-a",
        "version": created.version,
        "selected": selected,
        "supplement": custom,
        "answers": None,
        "files": None,
        "idempotency_key": "submit-1",
        "now": datetime(2026, 11, 27, tzinfo=timezone.utc),
    }
    if valid:
        submitted = repo.submit(**kwargs)
        assert submitted.status.value == "SUBMITTED"
        assert submitted.answer.supplement == custom
        assert len(submitted.answer.selected) == len(selected)
    else:
        with pytest.raises(InteractionError, match="INVALID_SELECTION"):
            repo.submit(**kwargs)


def test_old_supplement_remains_a_note_and_does_not_replace_selection(tmp_path):
    request = InteractionCreateRequest.model_validate({
        "task_key": "old-choice",
        "interaction_revision": 1,
        "component_type": "single_select",
        "card": {
            "title": "Choice",
            "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
            "supplement": {"enabled": True},
        },
    })
    repo = InteractionCardRepository(tmp_path)
    created = repo.create(
        installation_id="install-a", conversation_id="task-a",
        request=request, idempotency_key="create-old",
        now=datetime(2026, 11, 27, tzinfo=timezone.utc),
    )
    with pytest.raises(InteractionError, match="INVALID_SELECTION"):
        repo.submit(
            interaction_id=created.interaction_id,
            installation_id="install-a", conversation_id="task-a",
            version=1, selected=[], supplement="只填文字",
            answers=None, files=None, idempotency_key="submit-old",
            now=datetime(2026, 11, 27, tzinfo=timezone.utc),
        )


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


def test_card_read_is_opt_in_scoped_and_schema_valid(tmp_path):
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    interactions = InteractionService(
        InteractionCardRepository(tmp_path), clock=lambda: now,
    )
    grants = SimpleNamespace(
        authorize_capability=lambda installation, capability, version, *, tenant_id: SimpleNamespace(
            allowed=(tenant_id == "tenant-a"
                     and capability == "interaction.card.read/1" and version == "1"),
        ),
    )
    service = SuperExpertPlatformService(
        grant_repository=grants, task_repository=SimpleNamespace(),
        event_repository=SimpleNamespace(), event_bus=SimpleNamespace(),
        interaction_service=interactions,
    )
    request = InteractionCreateRequest.model_validate({
        "task_key": "choice", "interaction_revision": 2,
        "component_type": "single_select",
        "card": {"title": "Choice", "options": [
            {"id": "a", "text": "A"}, {"id": "b", "text": "B"},
        ]},
    })
    card = interactions.create(
        installation_id="install-a", conversation_id="task-a",
        request=request, idempotency_key="create-2",
    )
    schema_root = Path(__file__).parents[1] / "devkit" / "schemas" / "interaction-card-read-v1"
    request_schema = json.loads((schema_root / "request.schema.json").read_text())
    response_schema = json.loads((schema_root / "response.schema.json").read_text())
    arguments = {"interaction_id": card.interaction_id}
    Draft202012Validator(request_schema).validate(arguments)

    def read(*, installation_id="install-a", conversation_id="task-a", tenant_id="tenant-a", args=None, compatible=None):
        return service.read_interaction(
            tenant_id=tenant_id, installation_id=installation_id,
            conversation_id=conversation_id, contract_version="1",
            arguments=arguments if args is None else args,
            compatible_installation_ids=compatible,
        )

    pending = read()
    Draft202012Validator(response_schema).validate(pending)
    assert pending["status"] == "PENDING"
    assert pending["input_policy"] == "card_only"
    assert pending["answer"] is None
    assert pending["submission_receipt"] is None
    for scope in ({"conversation_id": "task-b"}, {"installation_id": "install-b"}):
        missing = read(**scope)
        Draft202012Validator(response_schema).validate(missing)
        assert missing == {"contract": "interaction.card.read/1", "result": "not_found"}
    assert read(args={"interaction_id": "interaction-" + "0" * 32}) == missing

    submitted = interactions.submit(
        interaction_id=card.interaction_id, installation_id="install-a",
        conversation_id="task-a", version=card.version,
        selected=[{"id": "a"}], supplement=None, answers=None, files=None,
        idempotency_key="submit-2",
    )
    result = read()
    Draft202012Validator(response_schema).validate(result)
    assert result["answer"] == submitted.answer.model_dump(mode="json")
    assert result["submission_receipt"] == card_receipt(submitted, "submitted")
    encoded_answer = json.dumps(
        result["answer"], sort_keys=True, ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    assert result["submission_receipt"]["answer_sha256"] == hashlib.sha256(
        encoded_answer,
    ).hexdigest()
    assert read() == result
    assert read(installation_id="install-b") == missing
    compatible = frozenset({"install-a", "install-b"})
    assert read(installation_id="install-b", compatible=compatible) == result
    assert read(
        installation_id="install-b", conversation_id="task-b",
        compatible=compatible,
    ) == missing
    assert "interaction.card.read/1" in PLATFORM_CAPABILITY_CATALOG_V1

    from super_agent.interaction_cards import InteractionError
    from super_agent.service import SuperExpertPlatformError
    with pytest.raises(InteractionError, match="INVALID_INTERACTION_REQUEST"):
        read(args={"interaction_id": card.interaction_id, "idempotency_key": "forbidden"})
    with pytest.raises(SuperExpertPlatformError, match="not authorized"):
        read(tenant_id="tenant-b")
    with pytest.raises(SuperExpertPlatformError, match="current installation"):
        read(installation_id="install-b", compatible=frozenset({"install-a"}))


@pytest.mark.parametrize("component_type,fields", [
    ("multi_select", {"selected": [{"id": "a", "text": "A"}], "supplement": None}),
    ("question_form", {"answers": [{"id": "q", "question": "Question", "value": "Answer"}]}),
    ("file_selector", {"files": [{
        "local_file_ref": "lfr_" + "a" * 32,
        "display_name": "clip.mp4", "mime_type": "video/mp4",
        "size_bytes": 2, "device_id": "device-a", "last_modified_ms": 1,
    }]}),
])
def test_card_read_answer_schema_covers_all_component_shapes(component_type, fields):
    schema = json.loads((
        Path(__file__).parents[1] / "devkit" / "schemas"
        / "interaction-card-read-v1" / "response.schema.json"
    ).read_text())
    answer = InteractionAnswer.model_validate({
        "interaction_id": "interaction-" + "a" * 32,
        "component_type": component_type,
        "submitted_at": "2026-11-07T00:00:00Z",
        **fields,
    })
    Draft202012Validator({
        "$schema": schema["$schema"], "$defs": schema["$defs"],
        "$ref": "#/$defs/answer",
    }).validate(answer.model_dump(mode="json"))


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
