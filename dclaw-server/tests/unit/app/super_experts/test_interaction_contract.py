# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError as PydanticValidationError

from qwenpaw.app.super_experts.interaction_contract import (
    InteractionAnswer,
    InteractionCreateRequest,
    InteractionValidationError,
    build_interaction_catalog,
    validate_card,
)


def _options() -> list[dict[str, object]]:
    return [
        {"id": "a", "text": "甲", "recommended": True},
        {"text": "乙", "default_selected": True},
    ]


def test_catalog_index_is_small_and_points_to_distinct_components():
    catalog = build_interaction_catalog([])

    assert catalog["catalog_version"] == "1"
    assert [item["component_type"] for item in catalog["components"]] == [
        "single_select",
        "multi_select",
        "question_form",
        "file_selector",
    ]
    assert all("schema" not in item for item in catalog["components"])


def test_file_selector_catalog_exposes_safe_local_reference_contract():
    catalog = build_interaction_catalog(["file_selector"])
    component = catalog["components"][0]

    assert component["required_capability"] == "interaction.file.select/1"
    assert component["schema"]["additionalProperties"] is False
    serialized = json.dumps(catalog["answer_schema"], ensure_ascii=False)
    assert "local_file_ref" in serialized
    assert "display_name" in serialized
    assert "absolute_path" not in serialized
    assert "canonical_path" not in serialized


def test_file_selector_rejects_unsafe_or_inconsistent_configuration():
    with pytest.raises(InteractionValidationError):
        validate_card(
            "file_selector",
            {"title": "选择文件", "multiple": False, "max_files": 2},
        )
    with pytest.raises(InteractionValidationError):
        validate_card(
            "file_selector",
            {"title": "选择文件", "accept_extensions": ["../secret"]},
        )
    with pytest.raises(InteractionValidationError):
        validate_card(
            "file_selector",
            {"title": "选择文件", "accept_extensions": [".mp4\n.exe"]},
        )


def test_filtered_catalog_exposes_only_requested_detailed_contract():
    catalog = build_interaction_catalog(["single_select"])

    assert [item["component_type"] for item in catalog["components"]] == [
        "single_select",
    ]
    component = catalog["components"][0]
    assert component["use_when"]
    assert component["do_not_use_when"]
    assert component["defaults"] == {
        "input_policy": "card_only",
        "layout": "auto",
        "supplement.enabled": False,
        "supplement.required": False,
    }
    assert component["schema"]["additionalProperties"] is False
    assert component["create_example"]["component_type"] == "single_select"
    assert catalog["answer_schema"]["additionalProperties"] is False


def test_catalog_rejects_unknown_component_type():
    with pytest.raises(InteractionValidationError) as error:
        build_interaction_catalog(["choice"])

    assert error.value.code == "INVALID_CATALOG_REQUEST"
    assert error.value.issues == [
        {"field": "component_types[0]", "code": "UNKNOWN_COMPONENT_TYPE"},
    ]


def test_card_string_fields_reject_non_strings_with_stable_validation_issue():
    with pytest.raises(InteractionValidationError) as error:
        validate_card(
            "single_select",
            {
                "title": 123,
                "options": [
                    {"text": "甲"},
                    {"text": "乙"},
                ],
            },
        )

    assert error.value.code == "INVALID_INTERACTION_REQUEST"
    assert error.value.issues == [
        {"field": "card.title", "code": "INVALID_VALUE"},
    ]


def test_card_creation_enforces_the_published_complete_schema():
    card = {
        "title": "请选择一项",
        "options": [{"text": "甲"}, {"text": "乙"}],
        "supplement": {"max_length": True},
    }
    schema = build_interaction_catalog(["single_select"])["components"][0]["schema"]
    assert not Draft202012Validator(schema).is_valid(card)

    with pytest.raises(InteractionValidationError) as error:
        validate_card("single_select", card)

    assert error.value.code == "INVALID_INTERACTION_REQUEST"
    assert error.value.issues == [
        {"field": "card.supplement.max_length", "code": "INVALID_VALUE"},
    ]
    with pytest.raises(PydanticValidationError):
        InteractionCreateRequest.model_validate(
            {
                "task_key": "customer-choice",
                "interaction_revision": 1,
                "component_type": "single_select",
                "card": card,
            },
        )


def test_question_form_catalog_exposes_strict_defaults_and_schema():
    catalog = build_interaction_catalog(["question_form"])

    component = catalog["components"][0]
    assert component["component_type"] == "question_form"
    assert component["defaults"] == {
        "input_policy": "card_only",
        "items[].placeholder": "请输入回答",
        "items[].required": True,
        "items[].max_length": 2000,
    }
    assert component["schema"]["additionalProperties"] is False
    assert component["create_example"]["component_type"] == "question_form"
    assert "answers" in catalog["answer_schema"]["properties"]


def test_question_form_applies_item_defaults_and_normalizes_optional_text():
    card = validate_card(
        "question_form",
        {
            "title": " 请补充以下信息 ",
            "description": "  ",
            "items": [
                {
                    "id": " scope ",
                    "question": " 服务范围？ ",
                    "description": " 例如空调维修 ",
                },
                {
                    "question": "其他情况？",
                    "required": False,
                    "placeholder": "选填",
                    "max_length": 5000,
                },
            ],
        },
    )

    assert card.title == "请补充以下信息"
    assert card.description is None
    assert card.items[0].id == "scope"
    assert card.items[0].question == "服务范围？"
    assert card.items[0].description == "例如空调维修"
    assert card.items[0].placeholder == "请输入回答"
    assert card.items[0].required is True
    assert card.items[0].max_length == 2000
    assert card.items[1].required is False
    assert card.items[1].max_length == 5000


@pytest.mark.parametrize(
    ("items", "issue"),
    [
        (
            [
                {"id": "same", "question": "问题一"},
                {"id": "same", "question": "问题二"},
            ],
            {"field": "card.items[1].id", "code": "DUPLICATE_QUESTION_ID"},
        ),
        (
            [{"question": "相同问题"}, {"question": "相同问题"}],
            {
                "field": "card.items[1].question",
                "code": "DUPLICATE_QUESTION_TEXT",
            },
        ),
    ],
)
def test_question_form_requires_unique_present_ids_and_questions(items, issue):
    with pytest.raises(InteractionValidationError) as error:
        validate_card("question_form", {"title": "请回答", "items": items})

    assert error.value.code == "INVALID_INTERACTION_REQUEST"
    assert error.value.issues == [issue]


def test_question_form_rejects_choice_fields_and_unknown_item_fields():
    with pytest.raises(InteractionValidationError) as error:
        validate_card(
            "question_form",
            {
                "title": "请回答",
                "items": [{"question": "问题", "recommended": True}],
                "layout": "list",
            },
        )

    assert {
        "card.items[0].recommended",
        "card.layout",
    }.issubset({item["field"] for item in error.value.issues})


def test_single_select_rejects_two_defaults():
    with pytest.raises(InteractionValidationError) as error:
        validate_card(
            "single_select",
            {
                "title": "选一个",
                "options": [
                    {"text": "甲", "default_selected": True},
                    {"text": "乙", "default_selected": True},
                ],
            },
        )

    assert error.value.code == "INVALID_INTERACTION_REQUEST"
    assert error.value.issues == [
        {"field": "card.options", "code": "TOO_MANY_DEFAULTS"},
    ]


def test_single_select_accepts_one_trusted_desktop_action():
    card = validate_card(
        "single_select",
        {
            "title": "正在启动本地助手",
            "options": [
                {
                    "id": "launch",
                    "text": "启动本地助手",
                    "default_selected": True,
                    "action_url": "https://relay.example.test/api/bootstrap/token/connect",
                    "auto_submit_on_desktop": True,
                },
                {"id": "later", "text": "稍后处理"},
            ],
        },
    )

    assert card.options[0].auto_submit_on_desktop is True
    assert card.options[0].action_url.endswith("/connect")


@pytest.mark.parametrize(
    "option",
    [
        {
            "text": "启动",
            "default_selected": True,
            "action_url": "dclaw-local-tool://connect?bootstrap=x",
            "auto_submit_on_desktop": True,
        },
        {"text": "启动", "auto_submit_on_desktop": True},
    ],
)
def test_desktop_action_rejects_untrusted_or_incomplete_options(option):
    with pytest.raises(InteractionValidationError):
        validate_card(
            "single_select",
            {"title": "启动", "options": [option, {"text": "稍后"}]},
        )


@pytest.mark.parametrize(
    ("options", "issue"),
    [
        (
            [{"id": "same", "text": "甲"}, {"id": "same", "text": "乙"}],
            {"field": "card.options[1].id", "code": "DUPLICATE_OPTION_ID"},
        ),
        (
            [{"text": "相同"}, {"text": "相同"}],
            {"field": "card.options[1].text", "code": "DUPLICATE_OPTION_TEXT"},
        ),
    ],
)
def test_options_require_unique_present_ids_and_text(options, issue):
    with pytest.raises(InteractionValidationError) as error:
        validate_card("single_select", {"title": "选一个", "options": options})

    assert issue in error.value.issues


def test_multi_select_enforces_bounds_and_optional_supplement():
    card = validate_card(
        "multi_select",
        {
            "title": "可多选",
            "options": _options(),
            "min_selections": 1,
            "max_selections": 2,
            "supplement": {"enabled": True, "required": False},
        },
    )

    assert card.min_selections == 1
    assert card.max_selections == 2
    assert card.supplement.enabled is True
    assert card.supplement.required is False
    assert card.options[0].recommended is True
    assert card.options[0].default_selected is False
    assert card.options[1].recommended is False
    assert card.options[1].default_selected is True


def test_multi_select_rejects_default_count_outside_bounds():
    with pytest.raises(InteractionValidationError) as error:
        validate_card(
            "multi_select",
            {
                "title": "至少选两个",
                "options": _options(),
                "min_selections": 2,
                "max_selections": 2,
            },
        )

    assert error.value.issues == [
        {
            "field": "card.options",
            "code": "DEFAULT_SELECTION_COUNT_OUT_OF_RANGE",
        },
    ]


def test_disabled_supplement_rejects_required_flag():
    with pytest.raises(InteractionValidationError) as error:
        validate_card(
            "single_select",
            {
                "title": "选一个",
                "options": _options(),
                "supplement": {"enabled": False, "required": True},
            },
        )

    assert error.value.issues == [
        {"field": "card.supplement.required", "code": "FIELD_NOT_ALLOWED"},
    ]


def test_create_request_defaults_to_card_only_and_parses_matching_card():
    request = InteractionCreateRequest.model_validate(
        {
            "task_key": "production-mode",
            "interaction_revision": 1,
            "component_type": "single_select",
            "card": {"title": "请选择", "options": _options()},
        },
    )

    assert request.input_policy.value == "card_only"
    assert request.card.title == "请选择"


def test_create_request_rejects_card_fields_from_another_component():
    with pytest.raises(ValueError):
        InteractionCreateRequest.model_validate(
            {
                "task_key": "wrong-shape",
                "interaction_revision": 1,
                "component_type": "single_select",
                "card": {
                    "title": "请选择",
                    "options": _options(),
                    "min_selections": 1,
                },
            },
        )


def test_answer_schema_supports_text_only_and_id_plus_text_options():
    answer = InteractionAnswer.model_validate(
        {
            "interaction_id": "interaction-1",
            "component_type": "multi_select",
            "selected": [
                {"id": "a", "text": "甲"},
                {"text": "乙"},
            ],
            "supplement": "补充",
            "submitted_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "schema_version": 1,
        },
    )

    assert answer.selected[0].id == "a"
    assert answer.selected[1].id is None
    assert answer.selected[1].text == "乙"
    assert "answers" not in answer.model_dump(mode="json")


def test_question_form_answer_serializes_only_the_question_branch():
    answer = InteractionAnswer.model_validate(
        {
            "interaction_id": "interaction-question-1",
            "component_type": "question_form",
            "answers": [
                {"id": "scope", "question": "服务范围？", "value": "空调维修"},
                {"question": "其他情况？", "value": None},
            ],
            "submitted_at": datetime(2026, 9, 17, tzinfo=timezone.utc),
            "schema_version": 1,
        },
    )

    payload = answer.model_dump(mode="json")
    assert "selected" not in payload
    assert "supplement" not in payload
    assert payload["answers"] == [
        {"id": "scope", "question": "服务范围？", "value": "空调维修"},
        {"id": None, "question": "其他情况？", "value": None},
    ]
