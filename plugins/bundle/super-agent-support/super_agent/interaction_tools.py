# -*- coding: utf-8 -*-
"""Request-local model tools for DClaw's basic interaction catalog.

The tools expose platform contracts and trusted card operations only. Business
meaning, wording, and the decision to ask a closed question stay with the Agent.
"""

# Keep concrete annotations: AgentScope resolves them directly when building
# tool schemas and cannot reliably resolve postponed Literal annotations.

from contextlib import contextmanager
from copy import copy
import hashlib
import json
from typing import Any, Callable, Literal

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from pydantic import ValidationError

from .interaction_cards import InteractionError
from .interaction_contract import (
    InteractionCreateRequest,
    InteractionValidationError,
)


CATALOG = "interaction.capabilities.list/1"
CREATE = "interaction.card.create/1"
CANCEL = "interaction.card.cancel/1"


def _response(value: Any) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(value, ensure_ascii=False, allow_nan=False),
            ),
        ],
    )


def _identity(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, sort_keys=True).encode("utf-8"),
    ).hexdigest()


def _validation_issues(error: ValidationError) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for item in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        path = ""
        for part in item["loc"]:
            if isinstance(part, int):
                path += f"[{part}]"
            else:
                path += ("." if path else "") + str(part)
        issue_type = str(item["type"])
        if issue_type == "missing":
            code = "FIELD_REQUIRED"
        elif issue_type == "extra_forbidden":
            code = "FIELD_NOT_ALLOWED"
        else:
            code = "INVALID_VALUE"
        issues.append({"field": path or "request", "code": code})
    return issues


def _domain_error(error: InteractionError) -> ToolResponse:
    payload: dict[str, Any] = {
        "error": error.code,
        "retryable": error.retryable,
    }
    if error.field:
        payload["field"] = error.field
    if error.guidance:
        payload["guidance"] = error.guidance
    return _response(payload)


def build_interaction_tools(
    *,
    grants: dict[str, str],
    installation_id: str,
    conversation_id: str,
    business_call: Callable,
    read_card: Callable[[str], dict[str, Any] | None] | None,
) -> dict[str, Callable]:
    """Build only tools authorized for this installation and request."""

    def authorized(capability: str) -> bool:
        return grants.get(capability) == "1"

    async def dispatch(
        capability: str,
        arguments: dict[str, Any],
    ) -> ToolResponse:
        if not authorized(capability):
            return _response(
                {"error": "CAPABILITY_UNAVAILABLE", "retryable": False},
            )
        try:
            return _response(await business_call(capability, arguments))
        except InteractionError as exc:
            return _domain_error(exc)
        except Exception:
            return _response(
                {
                    "error": "PLATFORM_OPERATION_UNCONFIRMED",
                    "retryable": True,
                    "guidance": (
                        "Read the current interaction status before retrying and retain "
                        "the same task_key, interaction_revision, and operation key. "
                        "Do not claim that a card exists."
                    ),
                },
            )

    async def interaction_component_catalog(
        component_types: list[str] = [],
    ) -> ToolResponse:
        """先读取基础交互能力目录，再创建任何客户交互卡片。

        不传类型时返回精简决策索引；确定类型后只请求该类型的详细
        Schema、默认值、限制、返回结构和正反例。完整闭集使用选择组件，
        答案无法预先列全的开放式事实问题使用 question_form；需要客户从已配对
        本地设备选择文件时使用 file_selector。

        Args:
            component_types: 精确类型列表：single_select、multi_select、question_form 或 file_selector。
        """
        if not isinstance(component_types, list) or any(
            not isinstance(item, str) or not item.strip()
            for item in component_types
        ):
            return _response(
                {
                    "error": "INVALID_CATALOG_REQUEST",
                    "issues": [
                        {"field": "component_types", "code": "INVALID_VALUE"},
                    ],
                    "retryable": True,
                },
            )
        return await dispatch(
            CATALOG,
            {"component_types": [item.strip() for item in component_types]},
        )

    async def interaction_card_create(
        task_key: Any = None,
        interaction_revision: Any = None,
        component_type: Literal[
            "single_select",
            "multi_select",
            "question_form",
            "file_selector",
        ]
        | None = None,
        card: Any = None,
        input_policy: Literal[
            "card_only",
            "card_or_text",
            "concurrent",
        ] = "card_only",
        replaces_interaction_id: str = "",
        expires_at: str = "",
        **unexpected: Any,
    ) -> ToolResponse:
        """创建真实的 DClaw 客户交互卡片；成功回执前不得声称卡片存在。

        创建前必须用 interaction_component_catalog 读取所选类型的详细契约。
        只能选一个时使用 single_select；允许多个同时成立时使用 multi_select。
        只有答案无法预先列全、必须由客户自由填写时才使用 question_form；
        其中每个开放问题对应一个 items 项，不能把可枚举问题降级为填空。
        需要客户选择本地文件时使用 file_selector；该类型还要求安装授权
        interaction.file.select/1，且 Agent 永远不会获得本地绝对路径或文件内容。
        option.id 可选但 text 必填；稳定业务候选同时传 ID 和文本，临时文本项
        可以只传文本。recommended 只显示“AI 推荐”，default_selected 才会预选，
        两者不得混用。补充信息默认关闭，开启后 required 默认 false。
        input_policy 默认 card_only，会在真实创建成功后禁用普通输入区。

        Args:
            task_key: 当前逻辑问题的稳定名称，重试时保持不变，最长 160 字符。
            interaction_revision: 正整数；问题或选项实质变化时递增。
            component_type: single_select、multi_select、question_form 或 file_selector，必须与 card Schema 一致。
            card: 完整类型化卡片对象，以实时目录的详细 Schema 为准。
            input_policy: card_only、card_or_text 或 concurrent；默认 card_only。
            replaces_interaction_id: 显式替换当前阻塞卡时传其真实 ID，否则留空。
            expires_at: 可选 RFC 3339 时区时间；留空表示不自动过期。
        """
        if unexpected:
            return _response(
                {
                    "error": "INVALID_INTERACTION_REQUEST",
                    "issues": [
                        {"field": field, "code": "FIELD_NOT_ALLOWED"}
                        for field in sorted(unexpected)
                    ],
                    "retryable": True,
                    "guidance": (
                        "Remove fields that are not declared by the selected catalog schema."
                    ),
                },
            )
        raw = {
            "task_key": task_key,
            "interaction_revision": interaction_revision,
            "component_type": component_type,
            "card": card,
            "input_policy": input_policy,
            "replaces_interaction_id": replaces_interaction_id or None,
            "expires_at": expires_at or None,
        }
        try:
            request = InteractionCreateRequest.model_validate(raw)
        except InteractionValidationError as exc:
            return _response(
                {
                    "error": exc.code,
                    "issues": exc.issues,
                    "retryable": exc.retryable,
                    "guidance": "Refresh the selected component contract and correct these fields.",
                },
            )
        except ValidationError as exc:
            return _response(
                {
                    "error": "INVALID_INTERACTION_REQUEST",
                    "issues": _validation_issues(exc),
                    "retryable": True,
                    "guidance": "Refresh the selected component contract and correct these fields.",
                },
            )
        operation = "interaction-create-" + _identity(
            installation_id,
            conversation_id,
            request.task_key,
            request.interaction_revision,
        )
        return await dispatch(
            CREATE,
            {
                "idempotency_key": operation,
                "request": request.model_dump(mode="json"),
            },
        )

    async def interaction_card_status(
        interaction_id: str = "",
    ) -> ToolResponse:
        """读取当前会话的一张交互卡；省略 ID 时读取当前活动阻塞卡。

        状态用于确认创建、提交、替换、取消或过期结果。不存在或不属于当前
        安装与会话的卡片统一返回 INTERACTION_NOT_FOUND。

        Args:
            interaction_id: 创建回执中的真实交互 ID；省略表示当前活动阻塞卡。
        """
        if read_card is None:
            return _response(
                {"error": "INTERACTION_NOT_FOUND", "retryable": False},
            )
        card_value = read_card(interaction_id.strip())
        if card_value is None:
            return _response(
                {"error": "INTERACTION_NOT_FOUND", "retryable": False},
            )
        return _response({"interaction": card_value})

    async def interaction_card_cancel(
        interaction_id: str,
        operation_key: str,
    ) -> ToolResponse:
        """显式取消当前会话中仍待提交的交互卡片。

        仅在问题失效且不立即用 replaces_interaction_id 替换时调用。重试同一取消
        动作必须保留 operation_key。

        Args:
            interaction_id: 创建回执中的真实交互 ID。
            operation_key: Agent 为本次逻辑取消动作生成并在重试时保留的稳定键。
        """
        if (
            not isinstance(interaction_id, str)
            or not interaction_id.strip()
            or not isinstance(operation_key, str)
            or not operation_key.strip()
            or len(operation_key) > 160
        ):
            return _response(
                {
                    "error": "INVALID_INTERACTION_REQUEST",
                    "retryable": True,
                    "guidance": "Pass a real interaction ID and a stable non-empty operation key.",
                },
            )
        operation = "interaction-cancel-" + _identity(
            installation_id,
            conversation_id,
            interaction_id.strip(),
            operation_key.strip(),
        )
        return await dispatch(
            CANCEL,
            {
                "idempotency_key": operation,
                "interaction_id": interaction_id.strip(),
            },
        )

    tools: dict[str, Callable] = {}
    if authorized(CATALOG):
        tools["interaction_component_catalog"] = interaction_component_catalog
    if authorized(CREATE) and authorized(CATALOG):
        tools["interaction_card_create"] = interaction_card_create
        if read_card is not None:
            tools["interaction_card_status"] = interaction_card_status
    if authorized(CANCEL) and authorized(CREATE) and authorized(CATALOG):
        tools["interaction_card_cancel"] = interaction_card_cancel
    return tools


@contextmanager
def bind_interaction_tools(agent: Any, tools: dict[str, Callable]):
    """Temporarily add interaction tools without mutating the base toolkit."""
    if not tools:
        yield
        return
    original = agent.toolkit
    scoped = copy(original)
    scoped.tools = dict(original.tools)
    for tool in tools.values():
        scoped.register_tool_function(tool, namesake_strategy="raise")
    agent.toolkit = scoped
    try:
        yield
    finally:
        agent.toolkit = original


__all__ = [
    "CATALOG",
    "CANCEL",
    "CREATE",
    "bind_interaction_tools",
    "build_interaction_tools",
]
