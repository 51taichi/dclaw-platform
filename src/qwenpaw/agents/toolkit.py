"""DClaw tool registration facade over AgentScope 2's Toolkit."""

from __future__ import annotations

import inspect
import json
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from agentscope.message import ToolCallBlock
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.skill import LocalSkillLoader
from agentscope.state import AgentState
from agentscope.tool import (
    FunctionTool,
    ToolChunk,
    ToolGroup,
    Toolkit,
    ToolResponse,
)


class DClawToolkit(Toolkit):
    """Keep synchronous DClaw assembly while executing with Toolkit 2.0."""

    def __init__(self) -> None:
        super().__init__()
        self._skill_paths: dict[str, str] = {}
        self._active_groups: set[str] = set()

    @classmethod
    def from_toolkit(
        cls,
        source: Toolkit,
        *,
        tool_names: set[str] | None = None,
    ) -> "DClawToolkit":
        """Clone a toolkit without sharing mutable tool-group containers."""
        cloned = cls()
        cloned.tool_groups = [
            ToolGroup(
                name=group.name,
                description=group.description,
                instructions=group.instructions,
                tools=[
                    tool
                    for tool in group.tools
                    if tool_names is None or tool.name in tool_names
                ],
                skills_or_loaders=list(group.skills_or_loaders),
                mcps=list(group.mcps),
            )
            for group in source.tool_groups
        ]
        if isinstance(source, cls):
            cloned._skill_paths = dict(source._skill_paths)
            cloned._active_groups = set(source._active_groups)
        return cloned

    @property
    def tools(self) -> dict[str, Any]:
        return {
            tool.name: tool
            for group in self.tool_groups
            for tool in group.tools
        }

    @property
    def skills(self) -> dict[str, str]:
        return dict(self._skill_paths)

    @property
    def groups(self) -> dict[str, ToolGroup]:
        return {group.name: group for group in self.tool_groups}

    def register_tool_function(
        self,
        tool_func: Callable[..., Any],
        *,
        namesake_strategy: str = "skip",
        async_execution: bool = False,
        **kwargs: Any,
    ) -> None:
        del async_execution
        json_schema = kwargs.get("json_schema")
        input_schema = (
            json_schema.get("function", {}).get("parameters")
            if isinstance(json_schema, dict)
            else None
        )

        @wraps(tool_func)
        async def invoke(*args: Any, **call_kwargs: Any) -> Any:
            result = tool_func(*args, **call_kwargs)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ToolResponse):
                return ToolChunk(
                    content=result.content,
                    state=result.state,
                    metadata=result.metadata,
                )
            return result

        tool = FunctionTool(
            invoke,
            input_schema=input_schema,
            permission=kwargs.get("permission")
            or PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                message="DClaw applies its own tool policy before execution.",
                decision_reason="dclaw_tool_policy",
            ),
        )
        tool.original_func = tool_func
        existing = self.tools.get(tool.name)
        if existing is not None:
            if namesake_strategy == "skip":
                return
            if namesake_strategy == "raise":
                raise ValueError(f"Tool '{tool.name}' is already registered")
            if namesake_strategy == "rename":
                suffix = 2
                base_name = tool.name
                while f"{base_name}_{suffix}" in self.tools:
                    suffix += 1
                tool.name = f"{base_name}_{suffix}"
        basic = self.groups["basic"]
        basic.tools = [item for item in basic.tools if item.name != tool.name]
        basic.tools.append(tool)

    def get_json_schemas(self) -> list[dict[str, Any]]:
        """Return schemas synchronously for legacy DClaw assembly code."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self.tools.values()
        ]

    async def call_tool_function(
        self,
        tool_call: dict[str, Any] | ToolCallBlock,
    ) -> Any:
        """Adapt the AgentScope 1 tool-call entrypoint to 2.0 streaming."""
        if isinstance(tool_call, dict):
            raw_input = tool_call.get("input", {})
            tool_call = ToolCallBlock(
                id=str(tool_call.get("id") or ""),
                name=str(tool_call.get("name") or ""),
                input=(
                    raw_input
                    if isinstance(raw_input, str)
                    else json.dumps(raw_input, ensure_ascii=False)
                ),
            )
        return self.call_tool(tool_call, AgentState())

    def register_agent_skill(self, skill_dir: str) -> None:
        path = str(Path(skill_dir).resolve())
        name = Path(path).name
        if name in self._skill_paths:
            return
        self.groups["basic"].skills_or_loaders.append(
            LocalSkillLoader(directory=path),
        )
        self._skill_paths[name] = path

    async def register_mcp_client(
        self,
        client: Any,
        *,
        namesake_strategy: str = "skip",
        execution_timeout: float | None = None,
    ) -> None:
        del namesake_strategy
        if execution_timeout is not None:
            client.execution_timeout = execution_timeout
        group = self.groups["basic"]
        group.mcps = [item for item in group.mcps if item.name != client.name]
        group.mcps.append(client)

    def create_tool_group(
        self,
        name: str,
        description: str,
        **kwargs: Any,
    ) -> None:
        if name in self.groups:
            return
        self.tool_groups.append(
            ToolGroup(name=name, description=description, **kwargs),
        )

    def update_tool_groups(
        self,
        groups: list[str],
        *,
        active: bool,
    ) -> None:
        if active:
            self._active_groups.update(groups)
        else:
            self._active_groups.difference_update(groups)
