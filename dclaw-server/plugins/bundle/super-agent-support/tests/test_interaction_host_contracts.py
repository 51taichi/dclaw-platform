from __future__ import annotations

import copy
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from pydantic import ValidationError as PydanticValidationError

from developer_pack.archive import build_archive
from super_agent.interaction_cards import InteractionCardRepository
from super_agent.interaction_contract import (
    InteractionCreateRequest,
    build_interaction_catalog,
)
from super_agent.interaction_receipts import card_receipt
from devkit.validate_live_card import validate_live_card
from devkit.interaction_card_api_demo import (
    CardContractError,
    component_for_answer,
    create_card,
    create_question_card,
    create_single_select,
    verify_created,
)


PLUGIN_ROOT = Path(__file__).parents[1]
SCHEMAS = PLUGIN_ROOT / "devkit" / "schemas"
EXAMPLE = PLUGIN_ROOT / "devkit" / "examples" / "interaction-host-v1" / "single-select-success.json"
LIVE_CATALOG = PLUGIN_ROOT / "devkit" / "fixtures" / "interaction-host-v1" / "single-select-live-catalog.json"
CARD_TYPE_EXAMPLES = PLUGIN_ROOT / "devkit" / "examples" / "interaction-host-v1" / "card-type-examples.json"


def _schema(relative: str) -> dict:
    result = json.loads((SCHEMAS / relative).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(result)
    return result


def _validate(relative: str, value: object) -> None:
    Draft202012Validator(
        _schema(relative), format_checker=FormatChecker(),
    ).validate(value)


def test_direct_host_catalog_and_single_select_example_match_runtime(tmp_path):
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    catalog_arguments = example["catalog_call"]["arguments"]
    _validate("interaction-capabilities-list-v1/request.schema.json", catalog_arguments)

    index = build_interaction_catalog([])
    detailed = build_interaction_catalog(catalog_arguments["component_types"])
    for response in (index, detailed):
        _validate("interaction-capabilities-list-v1/response.schema.json", response)
    assert "schema" not in index["components"][0]
    for kind in ("single_select", "multi_select", "question_form", "file_selector"):
        live = build_interaction_catalog([kind])
        _validate("interaction-capabilities-list-v1/response.schema.json", live)
        Draft202012Validator.check_schema(live["components"][0]["schema"])
    component = detailed["components"][0]
    assert component["component_type"] == "single_select"
    assert example["catalog_call"]["live_card_schema_location"] == "components[0].schema"
    Draft202012Validator.check_schema(component["schema"])

    create_arguments = example["create_call"]["arguments"]
    _validate("interaction-card-create-v1/request.schema.json", create_arguments)
    Draft202012Validator(component["schema"]).validate(
        create_arguments["request"]["card"],
    )
    request = InteractionCreateRequest.model_validate(create_arguments["request"])
    now = datetime(2026, 11, 9, tzinfo=timezone.utc)
    repo = InteractionCardRepository(tmp_path)
    card = repo.create(
        installation_id=example["trusted_scope_example"]["installation_id"],
        conversation_id=example["trusted_scope_example"]["conversation_id"],
        request=request,
        idempotency_key=create_arguments["idempotency_key"],
        now=now,
    )
    actual = {
        "interaction": card.model_dump(mode="json"),
        "receipt": card_receipt(card, "created"),
    }
    assert actual == example["create_result"]
    _validate("interaction-card-create-v1/response.schema.json", actual)
    _validate("interaction-card-receipt-v1/receipt.schema.json", actual["receipt"])
    receipt = actual["receipt"]
    assert receipt["event_id"] == actual["interaction"]["transitions"][0]["event_id"]
    assert receipt["interaction_id"] == actual["interaction"]["interaction_id"]
    assert receipt["version"] == actual["interaction"]["version"]

    submitted = repo.submit(
        interaction_id=card.interaction_id,
        installation_id=example["trusted_scope_example"]["installation_id"],
        conversation_id=example["trusted_scope_example"]["conversation_id"],
        version=1,
        selected=[{"id": "short-video"}],
        supplement=None,
        answers=None,
        files=None,
        idempotency_key="submit-primary-channel-rev-1",
        now=now,
    )
    replay = repo.create(
        installation_id=example["trusted_scope_example"]["installation_id"],
        conversation_id=example["trusted_scope_example"]["conversation_id"],
        request=request,
        idempotency_key=create_arguments["idempotency_key"],
        now=now,
    )
    assert replay == submitted
    replay_result = {
        "interaction": replay.model_dump(mode="json"),
        "receipt": card_receipt(replay, "created"),
    }
    _validate("interaction-card-create-v1/response.schema.json", replay_result)
    assert replay_result["interaction"]["status"] == "SUBMITTED"
    assert replay_result["receipt"] == receipt


def test_live_catalog_fixture_exercises_complete_schema():
    catalog = json.loads(LIVE_CATALOG.read_text(encoding="utf-8"))
    assert catalog == build_interaction_catalog(["single_select"])
    component = catalog["components"][0]
    assert "$defs" in component["schema"]
    assert component["schema"]["properties"]["supplement"]["$ref"].startswith("#/$defs/")
    example = component["create_example"]["card"]
    validate_live_card(catalog, "single_select", example)
    with pytest.raises(ValidationError) as missing_title:
        validate_live_card(catalog, "single_select", {"options": example["options"]})
    assert missing_title.value.validator == "required"
    with pytest.raises(ValidationError) as extra_field:
        validate_live_card(catalog, "single_select", {**example, "unknown": True})
    assert extra_field.value.validator == "additionalProperties"


def test_every_card_type_example_matches_public_host_and_live_component_schemas():
    examples = json.loads(CARD_TYPE_EXAMPLES.read_text(encoding="utf-8"))["examples"]
    assert len(examples) == 4
    for example in examples:
        kind = component_for_answer(example["answer_kind"])
        proposal = example["proposal"]
        assert proposal["component_type"] == kind
        assert proposal["task_key"] == example["task_key"]
        catalog = build_interaction_catalog([kind])
        validate_live_card(catalog, kind, proposal["card"])
        if kind == "question_form":
            assert len(proposal["card"]["items"]) == 1
        arguments = {
            "idempotency_key": example["idempotency_key"],
            "request": {
                "task_key": example["task_key"],
                "interaction_revision": example["interaction_revision"],
                "component_type": kind,
                "input_policy": example["input_policy"],
                "card": proposal["card"],
            },
        }
        _validate("interaction-card-create-v1/request.schema.json", arguments)
        InteractionCreateRequest.model_validate(arguments["request"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [
    "single_select", "multi_select", "question_form", "file_selector",
])
async def test_api_demo_uses_same_host_boundary_for_each_component(kind):
    catalog = build_interaction_catalog([kind])
    example = catalog["components"][0]["create_example"]
    checked = []

    class Host:
        calls = []

        async def call(self, capability, arguments):
            self.calls.append((capability, arguments))
            if capability == "interaction.capabilities.list/1":
                assert arguments == {"component_types": [kind]}
                return catalog
            assert capability == "interaction.card.create/1"
            request = arguments["request"]
            InteractionCreateRequest.model_validate(request)
            return {
                "interaction": {
                    "interaction_id": "interaction-demo",
                    "status": "PENDING",
                    "version": 1,
                    "task_key": request["task_key"],
                    "interaction_revision": request["interaction_revision"],
                    "component_type": kind,
                    "input_policy": request["input_policy"],
                    "binding": {
                        "installation_id": "install-demo",
                        "conversation_id": "task-demo",
                    },
                    "transitions": [{"action": "create", "event_id": "created-demo"}],
                },
                "receipt": {
                    "contract": "interaction.card.receipt/1",
                    "action": "created",
                    "status": "PENDING",
                    "interaction_id": "interaction-demo",
                    "event_id": "created-demo",
                    "version": 1,
                    "task_key": request["task_key"],
                    "interaction_revision": request["interaction_revision"],
                    "installation_id": "install-demo",
                    "conversation_id": "task-demo",
                },
            }

    host = Host()
    interaction_id = await create_card(
        host,
        component_type=kind,
        task_key=example["task_key"],
        interaction_revision=example["interaction_revision"],
        card=example["card"],
        check_business=lambda candidate: checked.append(candidate),
        idempotency_key=f"{kind}-rev-1",
    )
    assert interaction_id == "interaction-demo"
    assert checked == [example["card"]]
    assert [name for name, _ in host.calls] == [
        "interaction.capabilities.list/1", "interaction.card.create/1",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("answer_kind", "kind"), [
    ("one_choice", "single_select"),
    ("many_choices", "multi_select"),
    ("open_text", "question_form"),
    ("local_file", "file_selector"),
])
async def test_answer_kind_drives_model_proposal_and_host_request(answer_kind, kind):
    catalog = build_interaction_catalog([kind])
    example = catalog["components"][0]["create_example"]
    assert component_for_answer(answer_kind) == kind

    class Host:
        calls = []

        async def call(self, capability, arguments):
            self.calls.append((capability, arguments))
            if capability == "interaction.capabilities.list/1":
                assert arguments == {"component_types": [kind]}
                return catalog
            assert capability == "interaction.card.create/1"
            _validate("interaction-card-create-v1/request.schema.json", arguments)
            request = InteractionCreateRequest.model_validate(arguments["request"])
            assert request.component_type == kind
            assert arguments["request"]["input_policy"] == "card_or_text"
            return {
                "interaction": {
                    "interaction_id": "interaction-demo", "status": "PENDING",
                    "version": 1, "task_key": request.task_key,
                    "interaction_revision": request.interaction_revision,
                    "component_type": kind, "input_policy": "card_or_text",
                    "binding": {"installation_id": "install-demo", "conversation_id": "task-demo"},
                    "transitions": [{"action": "create", "event_id": "created-demo"}],
                },
                "receipt": {
                    "contract": "interaction.card.receipt/1", "action": "created",
                    "status": "PENDING", "interaction_id": "interaction-demo",
                    "event_id": "created-demo", "version": 1,
                    "task_key": request.task_key,
                    "interaction_revision": request.interaction_revision,
                    "installation_id": "install-demo", "conversation_id": "task-demo",
                },
            }

    host = Host()
    proposal = {
        "task_key": "customer-question", "component_type": kind,
        "card": example["card"],
    }
    interaction_id = await create_question_card(
        host, answer_kind=answer_kind, proposal=proposal,
        task_key="customer-question", interaction_revision=1,
        check_business=lambda card: None,
        idempotency_key="customer-question-rev-1",
    )
    assert interaction_id == "interaction-demo"
    assert [name for name, _ in host.calls] == [
        "interaction.capabilities.list/1", "interaction.card.create/1",
    ]


@pytest.mark.asyncio
async def test_proposal_rejects_internal_union_type_and_multi_item_form_before_host():
    class Host:
        calls = []

        async def call(self, capability, arguments):
            self.calls.append((capability, arguments))
            raise AssertionError("invalid proposal must not cross Host boundary")

    host = Host()
    common = {
        "host": host, "task_key": "customer-question",
        "interaction_revision": 1, "check_business": lambda card: None,
        "idempotency_key": "customer-question-rev-1",
    }
    with pytest.raises(CardContractError, match="component does not match"):
        await create_question_card(
            **common, answer_kind="one_choice",
            proposal={"task_key": "customer-question",
                      "component_type": "single_select_or_multi_select", "card": {}},
        )
    with pytest.raises(CardContractError, match="one question_form item"):
        await create_question_card(
            **common, answer_kind="open_text",
            proposal={"task_key": "customer-question", "component_type": "question_form",
                      "card": {"title": "两个问题", "items": [
                          {"question": "第一个？"}, {"question": "第二个？"},
                      ]}},
        )
    assert host.calls == []


@pytest.mark.asyncio
async def test_api_demo_rejects_wrong_catalog_version_before_create():
    class Host:
        calls = []
        catalog = None

        async def call(self, capability, arguments):
            self.calls.append((capability, arguments))
            assert capability == "interaction.capabilities.list/1"
            return self.catalog

    host = Host()
    for catalog in (None, {**build_interaction_catalog(["single_select"]),
                            "catalog_version": "unknown"}):
        host.catalog = catalog
        host.calls.clear()
        with pytest.raises(CardContractError, match="missing detailed component"):
            await create_card(
                host, component_type="single_select", task_key="primary-channel",
                interaction_revision=1, card={"title": "渠道", "options": []},
                check_business=lambda card: None, idempotency_key="primary-channel-1",
            )
        assert [name for name, _ in host.calls] == ["interaction.capabilities.list/1"]


def test_api_demo_rejects_missing_created_event_id():
    request = {
        "task_key": "task-demo", "interaction_revision": 1,
        "component_type": "single_select", "input_policy": "card_only",
    }
    result = {
        "interaction": {
            "interaction_id": "interaction-demo", "status": "PENDING",
            "version": 1, **request,
            "binding": {"installation_id": "install-demo", "conversation_id": "task-demo"},
            "transitions": [{"action": "create"}],
        },
        "receipt": {
            "contract": "interaction.card.receipt/1", "action": "created",
            "status": "PENDING", "interaction_id": "interaction-demo",
            "version": 1, "task_key": "task-demo", "interaction_revision": 1,
            "installation_id": "install-demo", "conversation_id": "task-demo",
        },
    }
    with pytest.raises(CardContractError, match="created receipt"):
        verify_created(result, request)


def test_failed_invocation_rolls_back_only_its_pending_card(tmp_path):
    repo = InteractionCardRepository(tmp_path)
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    request = InteractionCreateRequest.model_validate(
        build_interaction_catalog(["single_select"])["components"][0][
            "create_example"
        ],
    )
    card = repo.create(
        installation_id="install", conversation_id="session",
        request=request, idempotency_key="create-1",
        invocation_id="invocation-1", now=now,
    )
    cancelled, restored, replayed = repo.rollback_create(
        interaction_id=card.interaction_id,
        installation_id="install", conversation_id="session",
        invocation_id="invocation-1", operation_key="rollback-1", now=now,
    )
    assert cancelled.status.value == "CANCELLED"
    assert restored is None
    assert replayed is False
    replay, _, replayed = repo.rollback_create(
        interaction_id=card.interaction_id,
        installation_id="install", conversation_id="session",
        invocation_id="invocation-1", operation_key="rollback-1", now=now,
    )
    assert replay.status.value == "CANCELLED"
    assert replayed is True


def test_rollback_rejects_replay_owned_by_another_invocation(tmp_path):
    repo = InteractionCardRepository(tmp_path)
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    request = InteractionCreateRequest.model_validate(
        build_interaction_catalog(["single_select"])["components"][0][
            "create_example"
        ],
    )
    card = repo.create(
        installation_id="install", conversation_id="session", request=request,
        idempotency_key="create-owner", invocation_id="owner", now=now,
    )
    replay = repo.create(
        installation_id="install", conversation_id="session", request=request,
        idempotency_key="create-replay", invocation_id="replayer", now=now,
    )
    assert replay.interaction_id == card.interaction_id
    with pytest.raises(Exception, match="INTERACTION_ROLLBACK_NOT_OWNED"):
        repo.rollback_create(
            interaction_id=card.interaction_id,
            installation_id="install", conversation_id="session",
            invocation_id="replayer", operation_key="rollback-replayer", now=now,
        )
    assert repo.get_owned(
        card.interaction_id,
        installation_id="install", conversation_id="session",
        now=now,
    ).status.value == "PENDING"


@pytest.mark.asyncio
async def test_api_demo_uses_live_catalog_and_verifies_created_receipt(tmp_path):
    catalog = build_interaction_catalog(["single_select"])
    example = catalog["components"][0]["create_example"]
    repo = InteractionCardRepository(tmp_path)

    class Host:
        calls = []
        corrupt_receipt = False
        catalog_override = None

        async def call(self, capability, arguments):
            self.calls.append((capability, arguments))
            if capability == "interaction.capabilities.list/1":
                return self.catalog_override or catalog
            assert capability == "interaction.card.create/1"
            try:
                request = InteractionCreateRequest.model_validate(arguments["request"])
            except PydanticValidationError:
                return {"error": "INVALID_INTERACTION_REQUEST"}
            card = repo.create(
                installation_id="install-demo",
                conversation_id="task-demo",
                request=request,
                idempotency_key=arguments["idempotency_key"],
                now=datetime(2026, 11, 10, tzinfo=timezone.utc),
            )
            receipt = card_receipt(card, "created")
            if self.corrupt_receipt:
                receipt["interaction_id"] = "wrong-interaction"
            return {"interaction": card.model_dump(mode="json"), "receipt": receipt}

    host = Host()
    arguments = {
        "task_key": example["task_key"],
        "interaction_revision": example["interaction_revision"],
        "card": example["card"],
        "expected_title": example["card"]["title"],
        "expected_option_ids": [item.get("id") for item in example["card"]["options"]],
        "idempotency_key": "customer-choice-rev-1",
    }
    interaction_id = await create_single_select(host, **arguments)
    assert interaction_id.startswith("interaction-")
    assert [name for name, _ in host.calls] == [
        "interaction.capabilities.list/1", "interaction.card.create/1",
    ]
    assert host.calls[1][1]["request"]["card"] == example["card"]

    host.calls.clear()
    with pytest.raises(CardContractError, match="missing persisted interaction"):
        await create_single_select(host, **{**arguments, "card": {
            **example["card"], "unknown": True,
        }})
    assert [name for name, _ in host.calls] == [
        "interaction.capabilities.list/1", "interaction.card.create/1",
    ]

    host.calls.clear()
    with pytest.raises(CardContractError, match="option IDs or order"):
        await create_single_select(host, **{
            **arguments, "expected_option_ids": ["other"],
        })
    assert [name for name, _ in host.calls] == ["interaction.capabilities.list/1"]

    host.corrupt_receipt = True
    with pytest.raises(CardContractError, match="created receipt"):
        await create_single_select(host, **arguments)

    host.calls.clear()
    host.catalog_override = copy.deepcopy(catalog)
    host.catalog_override["components"][0]["schema"] = None
    with pytest.raises(CardContractError, match="missing detailed component"):
        await create_single_select(host, **arguments)
    assert [name for name, _ in host.calls] == ["interaction.capabilities.list/1"]


def test_direct_host_schemas_reject_extra_fields_and_bad_created_receipt():
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    create_request = example["create_call"]["arguments"]
    with pytest.raises(ValidationError):
        _validate(
            "interaction-card-create-v1/request.schema.json",
            {**create_request, "installation_id": "untrusted"},
        )
    with pytest.raises(ValidationError):
        _validate(
            "interaction-card-create-v1/response.schema.json",
            {**example["create_result"], "receipt": {
                **example["create_result"]["receipt"], "action": "submitted",
            }},
        )


def test_public_archives_include_direct_host_contracts_and_example():
    payload, metadata = build_archive(PLUGIN_ROOT)
    prefix = f"dclaw-super-agent-developer-pack-{metadata['version']}/"
    files = [
        "devkit/schemas/interaction-capabilities-list-v1/request.schema.json",
        "devkit/schemas/interaction-capabilities-list-v1/response.schema.json",
        "devkit/schemas/interaction-card-create-v1/request.schema.json",
        "devkit/schemas/interaction-card-create-v1/response.schema.json",
        "devkit/examples/interaction-host-v1/single-select-success.json",
        "devkit/examples/interaction-host-v1/card-type-examples.json",
        "devkit/examples/interaction-host-v1/README.md",
        "devkit/fixtures/interaction-host-v1/single-select-live-catalog.json",
        "devkit/validate_live_card.py",
        "devkit/interaction_card_api_demo.py",
        "devkit/operation-catalog.json",
    ]
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert all(prefix + path in names for path in files)
        catalog = json.loads(archive.read(prefix + "devkit/operation-catalog.json"))
        assert catalog["interaction_host"]["catalog"]["live_card_schema_location"] == "components[].schema"
        assert catalog["interaction_host"]["card_create"]["success_example"] == (
            "examples/interaction-host-v1/single-select-success.json"
        )
        assert catalog["interaction_host"]["catalog"]["api_demo"] == (
            "interaction_card_api_demo.py"
        )
