"""Immutable v1 contract for DClaw's basic interaction capabilities."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_serializer,
    model_validator,
)


class InteractionValidationError(ValueError):
    """Public-safe validation failure with stable field-level issues."""

    def __init__(
        self,
        code: str,
        issues: list[dict[str, str]],
        *,
        retryable: bool = True,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.issues = issues
        self.retryable = retryable


class InteractionComponentType(str, Enum):
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    QUESTION_FORM = "question_form"


class InteractionInputPolicy(str, Enum):
    CARD_ONLY = "card_only"
    CARD_OR_TEXT = "card_or_text"
    CONCURRENT = "concurrent"


class InteractionStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"


class InteractionLayout(str, Enum):
    AUTO = "auto"
    LIST = "list"
    GRID = "grid"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _strip_required(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def _strip_optional(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("must be a string")
    stripped = value.strip()
    return stripped or None


class InteractionOption(_StrictFrozenModel):
    id: str | None = Field(default=None, min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=1000)
    recommended: bool = False
    default_selected: bool = False
    action_url: str | None = Field(default=None, max_length=2048)
    auto_submit_on_desktop: bool = False

    _clean_id = field_validator("id", mode="before")(_strip_optional)
    _clean_text = field_validator("text", mode="before")(_strip_required)
    _clean_description = field_validator("description", mode="before")(
        _strip_optional
    )

    @field_validator("action_url", mode="before")
    @classmethod
    def validate_action_url(cls, value: Any) -> str | None:
        value = _strip_optional(value)
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("action URL must be a credential-free HTTPS URL")
        return value

    @model_validator(mode="after")
    def validate_desktop_action(self) -> "InteractionOption":
        if self.auto_submit_on_desktop and (
            self.action_url is None or not self.default_selected
        ):
            raise ValueError(
                "desktop auto-submit requires a default-selected action URL"
            )
        return self

    @model_serializer(mode="wrap")
    def serialize_optional_action(self, handler: Any) -> dict[str, Any]:
        payload = handler(self)
        if self.action_url is None:
            payload.pop("action_url", None)
        if not self.auto_submit_on_desktop:
            payload.pop("auto_submit_on_desktop", None)
        return payload


class InteractionSupplement(_StrictFrozenModel):
    enabled: bool = False
    label: str = Field(default="补充信息", min_length=1, max_length=80)
    placeholder: str = Field(
        default="如有其他情况可以补充",
        min_length=1,
        max_length=200,
    )
    required: bool = False
    max_length: int = Field(default=2000, ge=1, le=5000)

    _clean_label = field_validator("label", mode="before")(_strip_required)
    _clean_placeholder = field_validator("placeholder", mode="before")(
        _strip_required
    )


class _ChoiceCard(_StrictFrozenModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    options: tuple[InteractionOption, ...] = Field(min_length=2, max_length=20)
    supplement: InteractionSupplement = Field(
        default_factory=InteractionSupplement,
    )
    layout: InteractionLayout = InteractionLayout.AUTO

    _clean_title = field_validator("title", mode="before")(_strip_required)
    _clean_description = field_validator("description", mode="before")(
        _strip_optional
    )

    @model_validator(mode="after")
    def validate_desktop_auto_submit(self) -> "_ChoiceCard":
        if sum(option.auto_submit_on_desktop for option in self.options) > 1:
            raise ValueError("only one desktop auto-submit option is allowed")
        return self


class SingleSelectCard(_ChoiceCard):
    pass


class MultiSelectCard(_ChoiceCard):
    min_selections: int = Field(default=1, ge=0, le=20)
    max_selections: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def resolve_and_validate_bounds(self) -> "MultiSelectCard":
        maximum = self.max_selections
        if maximum is None:
            maximum = len(self.options)
            object.__setattr__(self, "max_selections", maximum)
        if maximum > len(self.options) or self.min_selections > maximum:
            raise ValueError("selection bounds are invalid")
        return self


class InteractionQuestionItem(_StrictFrozenModel):
    id: str | None = Field(default=None, min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=1000)
    placeholder: str = Field(
        default="请输入回答",
        min_length=1,
        max_length=200,
    )
    required: bool = True
    max_length: int = Field(default=2000, ge=1, le=5000)

    _clean_id = field_validator("id", mode="before")(_strip_optional)
    _clean_question = field_validator("question", mode="before")(_strip_required)
    _clean_description = field_validator("description", mode="before")(
        _strip_optional
    )
    _clean_placeholder = field_validator("placeholder", mode="before")(
        _strip_required
    )


class QuestionFormCard(_StrictFrozenModel):
    title: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    items: tuple[InteractionQuestionItem, ...] = Field(min_length=1, max_length=20)

    _clean_title = field_validator("title", mode="before")(_strip_required)
    _clean_description = field_validator("description", mode="before")(
        _strip_optional
    )


InteractionCard = SingleSelectCard | MultiSelectCard | QuestionFormCard


def _preflight_card(component_type: str, card: Any) -> None:
    if not isinstance(card, dict):
        raise InteractionValidationError(
            "INVALID_INTERACTION_REQUEST",
            [{"field": "card", "code": "OBJECT_REQUIRED"}],
        )
    options = card.get("options")
    if isinstance(options, (list, tuple)):
        ids: set[str] = set()
        texts: set[str] = set()
        defaults = 0
        for index, option in enumerate(options):
            if not isinstance(option, dict):
                continue
            option_id = option.get("id")
            if isinstance(option_id, str) and option_id.strip():
                normalized = option_id.strip()
                if normalized in ids:
                    raise InteractionValidationError(
                        "INVALID_INTERACTION_REQUEST",
                        [{
                            "field": f"card.options[{index}].id",
                            "code": "DUPLICATE_OPTION_ID",
                        }],
                    )
                ids.add(normalized)
            option_text = option.get("text")
            if isinstance(option_text, str) and option_text.strip():
                normalized = option_text.strip()
                if normalized in texts:
                    raise InteractionValidationError(
                        "INVALID_INTERACTION_REQUEST",
                        [{
                            "field": f"card.options[{index}].text",
                            "code": "DUPLICATE_OPTION_TEXT",
                        }],
                    )
                texts.add(normalized)
            defaults += option.get("default_selected") is True
        if component_type == InteractionComponentType.SINGLE_SELECT.value and defaults > 1:
            raise InteractionValidationError(
                "INVALID_INTERACTION_REQUEST",
                [{"field": "card.options", "code": "TOO_MANY_DEFAULTS"}],
            )
        if component_type == InteractionComponentType.MULTI_SELECT.value and defaults:
            minimum = card.get("min_selections", 1)
            maximum = card.get("max_selections", len(options))
            if (
                type(minimum) is int
                and type(maximum) is int
                and not minimum <= defaults <= maximum
            ):
                raise InteractionValidationError(
                    "INVALID_INTERACTION_REQUEST",
                    [{
                        "field": "card.options",
                        "code": "DEFAULT_SELECTION_COUNT_OUT_OF_RANGE",
                    }],
                )
    supplement = card.get("supplement")
    if (
        isinstance(supplement, dict)
        and supplement.get("enabled") is False
        and supplement.get("required") is True
    ):
        raise InteractionValidationError(
            "INVALID_INTERACTION_REQUEST",
            [{
                "field": "card.supplement.required",
                "code": "FIELD_NOT_ALLOWED",
            }],
        )
    if component_type == InteractionComponentType.QUESTION_FORM.value:
        items = card.get("items")
        if isinstance(items, (list, tuple)):
            ids: set[str] = set()
            questions: set[str] = set()
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                if isinstance(item_id, str) and item_id.strip():
                    normalized_id = item_id.strip()
                    if normalized_id in ids:
                        raise InteractionValidationError(
                            "INVALID_INTERACTION_REQUEST",
                            [{
                                "field": f"card.items[{index}].id",
                                "code": "DUPLICATE_QUESTION_ID",
                            }],
                        )
                    ids.add(normalized_id)
                question = item.get("question")
                if isinstance(question, str) and question.strip():
                    normalized_question = question.strip()
                    if normalized_question in questions:
                        raise InteractionValidationError(
                            "INVALID_INTERACTION_REQUEST",
                            [{
                                "field": f"card.items[{index}].question",
                                "code": "DUPLICATE_QUESTION_TEXT",
                            }],
                        )
                    questions.add(normalized_question)


def _validation_issues(error: ValidationError) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        path = "card"
        for part in item["loc"]:
            path += f"[{part}]" if isinstance(part, int) else f".{part}"
        issue_type = str(item["type"])
        if issue_type == "missing":
            code = "FIELD_REQUIRED"
        elif issue_type == "extra_forbidden":
            code = "FIELD_NOT_ALLOWED"
        else:
            code = "INVALID_VALUE"
        issues.append({"field": path, "code": code})
    return issues


def validate_card(component_type: str, card: Any) -> InteractionCard:
    """Validate a card against the exact selected component contract."""
    try:
        kind = InteractionComponentType(component_type)
    except (TypeError, ValueError) as exc:
        raise InteractionValidationError(
            "INVALID_INTERACTION_REQUEST",
            [{"field": "component_type", "code": "UNKNOWN_COMPONENT_TYPE"}],
        ) from exc
    _preflight_card(kind.value, card)
    model = {
        InteractionComponentType.SINGLE_SELECT: SingleSelectCard,
        InteractionComponentType.MULTI_SELECT: MultiSelectCard,
        InteractionComponentType.QUESTION_FORM: QuestionFormCard,
    }[kind]
    try:
        return model.model_validate(card)
    except ValidationError as exc:
        raise InteractionValidationError(
            "INVALID_INTERACTION_REQUEST",
            _validation_issues(exc),
        ) from exc


class InteractionCreateRequest(_StrictFrozenModel):
    task_key: str = Field(min_length=1, max_length=160)
    interaction_revision: int = Field(ge=1)
    component_type: InteractionComponentType
    card: InteractionCard
    input_policy: InteractionInputPolicy = InteractionInputPolicy.CARD_ONLY
    replaces_interaction_id: str | None = Field(default=None, min_length=1)
    expires_at: datetime | None = None

    _clean_task_key = field_validator("task_key", mode="before")(_strip_required)
    _clean_replacement = field_validator(
        "replaces_interaction_id",
        mode="before",
    )(_strip_optional)

    @model_validator(mode="before")
    @classmethod
    def parse_exact_card(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        component_type = value.get("component_type")
        if isinstance(component_type, InteractionComponentType):
            component_type = component_type.value
        parsed = validate_card(str(component_type or ""), value.get("card"))
        return {**value, "card": parsed}


class InteractionResolvedOption(_StrictFrozenModel):
    id: str | None = Field(default=None, min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=500)


class InteractionResolvedAnswer(_StrictFrozenModel):
    id: str | None = Field(default=None, min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=500)
    value: str | None = Field(default=None, max_length=5000)


class InteractionAnswer(_StrictFrozenModel):
    interaction_id: str = Field(min_length=1)
    component_type: InteractionComponentType
    selected: tuple[InteractionResolvedOption, ...] = ()
    supplement: str | None = Field(default=None, max_length=5000)
    answers: tuple[InteractionResolvedAnswer, ...] = ()
    submitted_at: datetime
    schema_version: Literal[1] = 1

    @model_validator(mode="after")
    def validate_component_answer(self) -> "InteractionAnswer":
        if self.component_type is InteractionComponentType.QUESTION_FORM:
            if self.selected or self.supplement is not None or not self.answers:
                raise ValueError("question form answer shape is invalid")
        elif self.answers:
            raise ValueError("choice answer shape is invalid")
        return self

    @model_serializer(mode="wrap")
    def serialize_component_answer(self, handler: Any) -> dict[str, Any]:
        payload = handler(self)
        if self.component_type is InteractionComponentType.QUESTION_FORM:
            payload.pop("selected", None)
            payload.pop("supplement", None)
        else:
            payload.pop("answers", None)
        return payload


_COMPONENT_COPY = {
    InteractionComponentType.SINGLE_SELECT: {
        "summary": "客户必须且只能从预设选项中选择一项。",
        "use_when": [
            "当前问题具有两个及以上完整预设选项",
            "客户只需要选择一个最贴近项",
        ],
        "do_not_use_when": [
            "需要客户自由描述事实",
            "允许同时选择多个选项",
        ],
    },
    InteractionComponentType.MULTI_SELECT: {
        "summary": "客户可以从预设选项中选择多项，并受数量上下限约束。",
        "use_when": [
            "多个选项可以同时成立",
            "需要明确最少或最多选择数量",
        ],
        "do_not_use_when": [
            "只能选择一个答案",
            "需要客户自由描述事实",
        ],
    },
    InteractionComponentType.QUESTION_FORM: {
        "summary": "客户逐项填写一个或多个无法可靠枚举答案的开放式问题。",
        "use_when": [
            "答案无法预先列全且必须由客户自由填写",
            "需要在一张卡片中收集一个或多个开放式事实",
        ],
        "do_not_use_when": [
            "可以提供两个及以上完整预设选项",
            "需要客户上传素材而不是填写文本",
        ],
    },
}


def _component_entry(kind: InteractionComponentType, *, detailed: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "component_type": kind.value,
        "contract_version": "1",
        **_COMPONENT_COPY[kind],
    }
    if not detailed:
        return entry
    model = {
        InteractionComponentType.SINGLE_SELECT: SingleSelectCard,
        InteractionComponentType.MULTI_SELECT: MultiSelectCard,
        InteractionComponentType.QUESTION_FORM: QuestionFormCard,
    }[kind]
    if kind is InteractionComponentType.QUESTION_FORM:
        entry.update({
            "defaults": {
                "input_policy": "card_only",
                "items[].placeholder": "请输入回答",
                "items[].required": True,
                "items[].max_length": 2000,
            },
            "schema": model.model_json_schema(),
            "create_example": {
                "task_key": "customer-open-questions",
                "interaction_revision": 1,
                "component_type": kind.value,
                "input_policy": "card_only",
                "card": {
                    "title": "请补充以下信息",
                    "items": [
                        {
                            "id": "business-context",
                            "question": "请介绍目前的具体业务情况。",
                            "required": True,
                        },
                    ],
                },
            },
            "error_examples": [
                {
                    "error": "INVALID_INTERACTION_REQUEST",
                    "issues": [{"field": "card.items", "code": "INVALID_VALUE"}],
                    "retryable": True,
                },
            ],
        })
        return entry
    example: dict[str, Any] = {
        "task_key": "customer-choice",
        "interaction_revision": 1,
        "component_type": kind.value,
        "input_policy": "card_only",
        "card": {
            "title": "请选择最贴近的一项" if kind is InteractionComponentType.SINGLE_SELECT else "请选择所有符合项",
            "options": [
                {"id": "option-a", "text": "选项甲", "recommended": True},
                {"text": "选项乙"},
            ],
            "supplement": {"enabled": True, "required": False},
            "layout": "auto",
        },
    }
    if kind is InteractionComponentType.MULTI_SELECT:
        example["card"].update({"min_selections": 1, "max_selections": 2})
    entry.update({
        "defaults": {
            "input_policy": "card_only",
            "layout": "auto",
            "supplement.enabled": False,
            "supplement.required": False,
        },
        "schema": model.model_json_schema(),
        "create_example": example,
        "error_examples": [
            {
                "error": "INVALID_INTERACTION_REQUEST",
                "issues": [{"field": "card.options", "code": "INVALID_VALUE"}],
                "retryable": True,
            },
        ],
    })
    return entry


def build_interaction_catalog(component_types: list[str]) -> dict[str, Any]:
    """Return a concise index or exact detailed component contracts."""
    if not isinstance(component_types, list):
        raise InteractionValidationError(
            "INVALID_CATALOG_REQUEST",
            [{"field": "component_types", "code": "ARRAY_REQUIRED"}],
        )
    if component_types:
        kinds: list[InteractionComponentType] = []
        for index, value in enumerate(component_types):
            try:
                kind = InteractionComponentType(value)
            except (TypeError, ValueError) as exc:
                raise InteractionValidationError(
                    "INVALID_CATALOG_REQUEST",
                    [{
                        "field": f"component_types[{index}]",
                        "code": "UNKNOWN_COMPONENT_TYPE",
                    }],
                ) from exc
            if kind not in kinds:
                kinds.append(kind)
    else:
        kinds = list(InteractionComponentType)
    detailed = bool(component_types)
    result = {
        "catalog_version": "1",
        "components": [
            _component_entry(kind, detailed=detailed)
            for kind in kinds
        ],
    }
    if detailed:
        result["answer_schema"] = InteractionAnswer.model_json_schema()
    return result


__all__ = [
    "InteractionAnswer",
    "InteractionCard",
    "InteractionComponentType",
    "InteractionCreateRequest",
    "InteractionInputPolicy",
    "InteractionLayout",
    "InteractionOption",
    "InteractionQuestionItem",
    "InteractionResolvedAnswer",
    "InteractionResolvedOption",
    "InteractionStatus",
    "InteractionSupplement",
    "InteractionValidationError",
    "MultiSelectCard",
    "QuestionFormCard",
    "SingleSelectCard",
    "build_interaction_catalog",
    "validate_card",
]
