from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from developer_pack.archive import build_archive
from super_agent.interaction_cards import InteractionCardRepository
from super_agent.interaction_contract import (
    InteractionCreateRequest,
    build_interaction_catalog,
)
from super_agent.interaction_receipts import card_receipt


PLUGIN_ROOT = Path(__file__).parents[1]
SCHEMAS = PLUGIN_ROOT / "devkit" / "schemas"
EXAMPLE = PLUGIN_ROOT / "devkit" / "examples" / "interaction-host-v1" / "single-select-success.json"


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
        "devkit/examples/interaction-host-v1/README.md",
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
