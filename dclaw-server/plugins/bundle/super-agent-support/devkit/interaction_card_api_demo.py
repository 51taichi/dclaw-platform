"""Reference direct Host card flow for a signed Super Agent runtime.

The business runtime supplies the approved question, option IDs and revision.
This reference covers the shared platform boundary only; it never asks a model
to call a card tool or treats a model candidate as a persisted card.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

class CardContractError(ValueError):
    """A catalog, candidate or Host receipt failed the public card contract."""


ANSWER_COMPONENTS = {
    "one_choice": "single_select",
    "many_choices": "multi_select",
    "open_text": "question_form",
    "local_file": "file_selector",
}


def component_for_answer(answer_kind: str) -> str:
    """Map the Agent's business answer shape to a real Host component type."""
    try:
        return ANSWER_COMPONENTS[answer_kind]
    except (KeyError, TypeError) as exc:
        raise CardContractError("unsupported answer kind") from exc


async def create_question_card(
    host: Any,
    *,
    answer_kind: str,
    proposal: dict[str, Any],
    task_key: str,
    interaction_revision: int,
    check_business: Callable[[dict[str, Any]], None],
    idempotency_key: str,
    input_policy: str = "card_or_text",
) -> str:
    """Validate one model proposal before crossing the direct Host boundary."""
    component_type = component_for_answer(answer_kind)
    if not isinstance(proposal, dict) or set(proposal) != {
        "task_key", "component_type", "card",
    }:
        raise CardContractError("invalid card proposal shape")
    if proposal["task_key"] != task_key:
        raise CardContractError("candidate changed the approved task key")
    if proposal["component_type"] != component_type:
        raise CardContractError("candidate component does not match answer kind")
    card = proposal["card"]
    if not isinstance(card, dict):
        raise CardContractError("invalid card body")
    if component_type == "question_form" and (
        not isinstance(card.get("items"), list) or len(card["items"]) != 1
    ):
        raise CardContractError("one question_form item is required")
    return await create_card(
        host,
        component_type=component_type,
        task_key=task_key,
        interaction_revision=interaction_revision,
        card=card,
        check_business=check_business,
        idempotency_key=idempotency_key,
        input_policy=input_policy,
    )


def verify_created(result: dict[str, Any], request: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        raise CardContractError("invalid Host create result")
    interaction = result.get("interaction")
    receipt = result.get("receipt")
    if not isinstance(interaction, dict) or not isinstance(receipt, dict):
        raise CardContractError("missing persisted interaction or receipt")
    binding = interaction.get("binding")
    transitions = interaction.get("transitions")
    if not isinstance(binding, dict) or not isinstance(transitions, list):
        raise CardContractError("missing trusted binding or transition")
    created = [
        item for item in transitions
        if isinstance(item, dict) and item.get("action") == "create"
    ]
    interaction_id = interaction.get("interaction_id")
    if (
        not isinstance(interaction_id, str) or not interaction_id
        or interaction.get("status") != "PENDING"
        or not isinstance(interaction.get("version"), int)
        or interaction["version"] < 1
        or len(created) != 1
        or not isinstance(created[0].get("event_id"), str)
        or not created[0]["event_id"]
        or receipt.get("contract") != "interaction.card.receipt/1"
        or receipt.get("action") != "created"
        or receipt.get("status") != "PENDING"
        or receipt.get("interaction_id") != interaction_id
        or receipt.get("event_id") != created[0].get("event_id")
        or receipt.get("version") != interaction["version"]
        or receipt.get("task_key") != request["task_key"]
        or receipt.get("interaction_revision") != request["interaction_revision"]
        or interaction.get("task_key") != request["task_key"]
        or interaction.get("interaction_revision") != request["interaction_revision"]
        or interaction.get("component_type") != request["component_type"]
        or interaction.get("input_policy") != request["input_policy"]
    ):
        raise CardContractError("created receipt does not match persisted card")
    for key in ("installation_id", "conversation_id"):
        if not isinstance(binding.get(key), str) or not binding[key]:
            raise CardContractError("missing trusted scope")
        if receipt.get(key) != binding[key]:
            raise CardContractError("created receipt scope mismatch")
    return interaction_id


async def create_card(
    host: Any,
    *,
    component_type: str,
    task_key: str,
    interaction_revision: int,
    card: dict[str, Any],
    check_business: Callable[[dict[str, Any]], None],
    idempotency_key: str,
    input_policy: str = "card_only",
    replaces_interaction_id: str | None = None,
) -> str:
    """Use the same Host boundary for every published card component."""
    if component_type not in (
        "single_select", "multi_select", "question_form", "file_selector",
    ):
        raise CardContractError("unsupported component type")
    if (
        not isinstance(task_key, str) or not 1 <= len(task_key) <= 160
        or type(interaction_revision) is not int or interaction_revision < 1
        or not isinstance(idempotency_key, str) or not idempotency_key
    ):
        raise CardContractError("invalid stable card identity")
    if input_policy not in ("card_only", "card_or_text", "concurrent"):
        raise CardContractError("invalid input policy")
    catalog = await host.call(
        "interaction.capabilities.list/1", {"component_types": [component_type]},
    )
    components = [
        item for item in catalog.get("components", [])
        if isinstance(item, dict) and item.get("component_type") == component_type
    ] if isinstance(catalog, dict) else []
    if (
        not isinstance(catalog, dict)
        or catalog.get("catalog_version") != "1"
        or len(components) != 1
        or components[0].get("contract_version") != "1"
        or not isinstance(components[0].get("schema"), dict)
    ):
        raise CardContractError("missing detailed component")
    create_example = components[0].get("create_example")
    if not isinstance(create_example, dict) or not isinstance(
        create_example.get("card"), dict,
    ):
        raise CardContractError("missing Host create example")
    check_business(card)

    request = {
        "task_key": task_key,
        "interaction_revision": interaction_revision,
        "component_type": component_type,
        "input_policy": input_policy,
        "card": card,
    }
    if replaces_interaction_id is not None:
        request["replaces_interaction_id"] = replaces_interaction_id
    result = await host.call(
        "interaction.card.create/1",
        {"idempotency_key": idempotency_key, "request": request},
    )
    return verify_created(result, request)


async def create_single_select(
    host: Any,
    *,
    task_key: str,
    interaction_revision: int,
    card: dict[str, Any],
    expected_title: str,
    expected_option_ids: list[str],
    idempotency_key: str,
    input_policy: str = "card_only",
) -> str:
    """Single-select example: keep the approved question and option order."""
    def check_business(candidate: dict[str, Any]) -> None:
        if candidate.get("title") != expected_title:
            raise CardContractError("candidate changed the approved question")
        actual_ids = [item.get("id") for item in candidate.get("options", [])]
        if actual_ids != expected_option_ids:
            raise CardContractError("candidate changed option IDs or order")

    return await create_card(
        host,
        component_type="single_select",
        task_key=task_key,
        interaction_revision=interaction_revision,
        card=card,
        check_business=check_business,
        idempotency_key=idempotency_key,
        input_policy=input_policy,
    )
