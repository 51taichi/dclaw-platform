"""DClaw-owned plan models and notebook for AgentScope 2."""

from __future__ import annotations

import inspect
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from pydantic import BaseModel, Field

from ..agents.message_compat import Msg


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class SubTask(BaseModel):
    name: str
    description: str
    expected_outcome: str
    outcome: str | None = None
    state: Literal["todo", "in_progress", "done", "abandoned"] = "todo"
    created_at: str = Field(default_factory=_timestamp)
    finished_at: str | None = None

    def finish(self, outcome: str) -> None:
        self.state = "done"
        self.outcome = outcome
        self.finished_at = _timestamp()

    def to_markdown(self, detailed: bool = False) -> str:
        marker = {
            "todo": "[ ]",
            "in_progress": "[ ] [WIP]",
            "done": "[x]",
            "abandoned": "[ ] [Abandoned]",
        }[self.state]
        if not detailed:
            return f"- {marker} {self.name}"
        values = [
            f"- {marker} {self.name}",
            f"  - Description: {self.description}",
            f"  - Expected Outcome: {self.expected_outcome}",
            f"  - State: {self.state}",
        ]
        if self.outcome:
            values.append(f"  - Actual Outcome: {self.outcome}")
        return "\n".join(values)


class Plan(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    description: str
    expected_outcome: str
    subtasks: list[SubTask]
    created_at: str = Field(default_factory=_timestamp)
    state: Literal["todo", "in_progress", "done", "abandoned"] = "todo"
    finished_at: str | None = None
    outcome: str | None = None

    def refresh_plan_state(self) -> str:
        if self.state in {"done", "abandoned"}:
            return ""
        active = any(item.state == "in_progress" for item in self.subtasks)
        target = "in_progress" if active else "todo"
        if self.state == target:
            return ""
        self.state = target
        return f"The plan state has been updated to '{target}'."

    def finish(self, state: Literal["done", "abandoned"], outcome: str) -> None:
        self.state = state
        self.outcome = outcome
        self.finished_at = _timestamp()

    def to_markdown(self, detailed: bool = False) -> str:
        tasks = "\n".join(
            item.to_markdown(detailed=detailed) for item in self.subtasks
        )
        return "\n".join(
            [
                f"# {self.name}",
                f"**Description**: {self.description}",
                f"**Expected Outcome**: {self.expected_outcome}",
                f"**State**: {self.state}",
                "## Subtasks",
                tasks,
            ],
        )


class InMemoryPlanStorage:
    def __init__(self) -> None:
        self.plans: OrderedDict[str, Plan] = OrderedDict()

    async def add_plan(self, plan: Plan, override: bool = True) -> None:
        if plan.id in self.plans and not override:
            raise ValueError(f"Plan with id {plan.id} already exists.")
        self.plans[plan.id] = plan

    async def get_plans(self) -> list[Plan]:
        return list(self.plans.values())

    async def get_plan(self, plan_id: str) -> Plan | None:
        return self.plans.get(plan_id)

    def state_dict(self) -> dict[str, Any]:
        return {
            "plans": {
                key: value.model_dump(mode="json")
                for key, value in self.plans.items()
            },
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.plans = OrderedDict(
            (key, Plan.model_validate(value))
            for key, value in (state.get("plans") or {}).items()
        )


class DefaultPlanToHint:
    hint_prefix = "<system-hint>"
    hint_suffix = "</system-hint>"

    def __call__(self, plan: Plan | None) -> str | None:
        if plan is None:
            return None
        return f"{self.hint_prefix}{plan.to_markdown()}{self.hint_suffix}"


class PlanNotebook:
    description = "Create, revise, execute, and persist a structured plan."

    def __init__(
        self,
        max_subtasks: int | None = None,
        plan_to_hint: Callable[[Plan | None], str | None] | None = None,
        storage: InMemoryPlanStorage | None = None,
    ) -> None:
        self.max_tasks = max_subtasks
        self.plan_to_hint = plan_to_hint or DefaultPlanToHint()
        self.storage = storage or InMemoryPlanStorage()
        self.current_plan: Plan | None = None
        self._plan_change_hooks: OrderedDict[
            str,
            Callable[["PlanNotebook", Plan | None], None | Awaitable[None]],
        ] = OrderedDict()

    def _response(self, text: str) -> ToolResponse:
        return ToolResponse(content=[TextBlock(text=text)])

    def _require_plan(self) -> Plan:
        if self.current_plan is None:
            raise ValueError("Create a plan before using this tool.")
        return self.current_plan

    async def _trigger_plan_change_hooks(self) -> None:
        for hook in self._plan_change_hooks.values():
            result = hook(self, self.current_plan)
            if inspect.isawaitable(result):
                await result

    async def create_plan(
        self,
        name: str,
        description: str,
        expected_outcome: str,
        subtasks: list[SubTask],
    ) -> ToolResponse:
        if self.max_tasks is not None and len(subtasks) > self.max_tasks:
            return self._response(
                f"A plan can contain at most {self.max_tasks} subtasks.",
            )
        replaced = self.current_plan is not None
        self.current_plan = Plan(
            name=name,
            description=description,
            expected_outcome=expected_outcome,
            subtasks=[SubTask.model_validate(item) for item in subtasks],
        )
        await self._trigger_plan_change_hooks()
        verb = "replaced" if replaced else "created"
        return self._response(f"Plan '{name}' {verb} successfully.")

    async def revise_current_plan(
        self,
        subtask_idx: int,
        action: Literal["add", "revise", "delete"],
        subtask: SubTask | None = None,
    ) -> ToolResponse:
        plan = self._require_plan()
        subtask_idx = int(subtask_idx)
        if action == "add":
            if subtask is None or not 0 <= subtask_idx <= len(plan.subtasks):
                return self._response("Invalid add operation.")
            plan.subtasks.insert(subtask_idx, SubTask.model_validate(subtask))
        elif action == "revise":
            if subtask is None or not 0 <= subtask_idx < len(plan.subtasks):
                return self._response("Invalid revise operation.")
            plan.subtasks[subtask_idx] = SubTask.model_validate(subtask)
        elif action == "delete" and 0 <= subtask_idx < len(plan.subtasks):
            plan.subtasks.pop(subtask_idx)
        else:
            return self._response("Invalid plan revision operation.")
        await self._trigger_plan_change_hooks()
        return self._response("Plan revised successfully.")

    async def update_subtask_state(
        self,
        subtask_idx: int,
        state: Literal["todo", "in_progress", "abandoned"],
    ) -> ToolResponse:
        plan = self._require_plan()
        subtask_idx = int(subtask_idx)
        if not 0 <= subtask_idx < len(plan.subtasks):
            return self._response("Invalid subtask index.")
        if state == "in_progress":
            unfinished = [
                item
                for item in plan.subtasks[:subtask_idx]
                if item.state not in {"done", "abandoned"}
            ]
            active = [item for item in plan.subtasks if item.state == "in_progress"]
            if unfinished or active:
                return self._response("Finish the earlier active subtask first.")
        plan.subtasks[subtask_idx].state = state
        suffix = plan.refresh_plan_state()
        await self._trigger_plan_change_hooks()
        return self._response(f"Subtask state updated successfully. {suffix}")

    async def finish_subtask(
        self,
        subtask_idx: int,
        subtask_outcome: str,
    ) -> ToolResponse:
        plan = self._require_plan()
        subtask_idx = int(subtask_idx)
        if not 0 <= subtask_idx < len(plan.subtasks):
            return self._response("Invalid subtask index.")
        plan.subtasks[subtask_idx].finish(subtask_outcome)
        if subtask_idx + 1 < len(plan.subtasks):
            plan.subtasks[subtask_idx + 1].state = "in_progress"
        plan.refresh_plan_state()
        await self._trigger_plan_change_hooks()
        return self._response("Subtask finished successfully.")

    async def view_subtasks(self, subtask_idx: list[int]) -> ToolResponse:
        plan = self._require_plan()
        values = [
            plan.subtasks[index].to_markdown(detailed=True)
            for index in subtask_idx
            if 0 <= index < len(plan.subtasks)
        ]
        return self._response("\n\n".join(values) or "No valid subtasks.")

    async def finish_plan(
        self,
        state: Literal["done", "abandoned"],
        outcome: str,
    ) -> ToolResponse:
        if self.current_plan is None:
            return self._response("There is no plan to finish.")
        self.current_plan.finish(state, outcome)
        await self.storage.add_plan(self.current_plan)
        self.current_plan = None
        await self._trigger_plan_change_hooks()
        return self._response(f"The plan finished as '{state}'.")

    async def view_historical_plans(self) -> ToolResponse:
        plans = await self.storage.get_plans()
        return self._response(
            "\n".join(f"{item.id}: {item.name} ({item.state})" for item in plans)
            or "No historical plans.",
        )

    async def recover_historical_plan(self, plan_id: str) -> ToolResponse:
        plan = await self.storage.get_plan(plan_id)
        if plan is None:
            return self._response(f"Cannot find plan '{plan_id}'.")
        self.current_plan = plan.model_copy(deep=True)
        await self._trigger_plan_change_hooks()
        return self._response(f"Plan '{plan.name}' recovered successfully.")

    def list_tools(self) -> list[Callable[..., Awaitable[ToolResponse]]]:
        return [
            self.view_subtasks,
            self.update_subtask_state,
            self.finish_subtask,
            self.create_plan,
            self.revise_current_plan,
            self.finish_plan,
            self.view_historical_plans,
            self.recover_historical_plan,
        ]

    async def get_current_hint(self) -> Msg | None:
        hint = self.plan_to_hint(self.current_plan)
        if not hint:
            return None
        return Msg(name="plan", role="user", content=hint)

    def register_plan_change_hook(
        self,
        hook_name: str,
        hook: Callable[["PlanNotebook", Plan | None], None | Awaitable[None]],
    ) -> None:
        self._plan_change_hooks[hook_name] = hook

    def state_dict(self) -> dict[str, Any]:
        return {
            "current_plan": (
                self.current_plan.model_dump(mode="json")
                if self.current_plan is not None
                else None
            ),
            "storage": self.storage.state_dict(),
        }

    def load_state_dict(self, state: dict[str, Any], strict: bool = False) -> None:
        del strict
        current = state.get("current_plan")
        self.current_plan = Plan.model_validate(current) if current else None
        self.storage.load_state_dict(state.get("storage") or state)

