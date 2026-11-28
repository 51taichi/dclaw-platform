"""Opt-in, invocation-local capability guide and action gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STAGE_CAPABILITIES = {
    "interaction": "interaction.capabilities.list/1",
    "aigc": "aigc.workflow.capabilities.list/1",
    "local": "local.task.start/1",
}

ANSWER_KIND_MAP = {
    "one_choice": ("single_select",),
    "many_choices": ("multi_select",),
    "one_or_many_choices": ("single_select", "multi_select"),
    "open_text": ("question_form",),
    "local_file": ("file_selector",),
}

_ACTION_PREFIXES = {
    "card.create": "aigc",
    "card.update": "aigc",
    "interaction.card.create/1": "interaction",
    "interaction.card.cancel/1": "interaction",
    "interaction.file.select/1": "interaction",
    "aigc.workflow.create/1": "aigc",
    "aigc.task.create": "aigc",
    "aigc.task.create/2": "aigc",
    "aigc.task.resume": "aigc",
    "aigc.task.cancel": "aigc",
    "aigc.asset.submit": "aigc",
    "aigc.task.assets.localize/1": "aigc",
    "aigc.review.complete": "aigc",
    "aigc.guide.update": "aigc",
    "local.runtime.prepare/1": "local",
    "local.task.start/1": "local",
    "local.task.outputs.bind/1": "local",
    "local.task.cancel/1": "local",
}


class CapabilityStageError(ValueError):
    """The signed expert requested a stage or action it cannot use."""


class CapabilityStageGate:
    def __init__(self, grants: dict[str, str]) -> None:
        self.grants = dict(grants)
        self.enabled = self.grants.get("capability.stage.enter/1") == "1"
        self.stage: str | None = None
        self.transitions = 0
        self.model_calls = 0

    def enter(self, stage: str) -> None:
        if not self.enabled or stage not in STAGE_CAPABILITIES:
            raise CapabilityStageError("invalid_stage")
        if self.grants.get(STAGE_CAPABILITIES[stage]) != "1":
            raise CapabilityStageError("undeclared_stage")
        if stage == self.stage:
            return
        if self.stage is not None:
            if self.model_calls < 1 or self.transitions:
                raise CapabilityStageError("invalid_stage_transition")
            self.transitions += 1
        self.stage = stage

    def check(self, capability: str) -> None:
        if not self.enabled:
            return
        required = _ACTION_PREFIXES.get(capability)
        if required is not None and self.stage != required:
            raise CapabilityStageError("action_outside_stage")

    def model_grants(self) -> dict[str, str]:
        if not self.enabled:
            return self.grants
        if self.stage is None:
            raise CapabilityStageError("stage_required")
        return {
            key: value for key, value in self.grants.items()
            if not (key.startswith("aigc.") and self.stage != "aigc")
            and not (key.startswith("interaction.") and self.stage != "interaction")
            and not (key.startswith("local.") and self.stage != "local")
            and _ACTION_PREFIXES.get(key, self.stage) == self.stage
        }

    def record_model_call(self) -> None:
        if self.enabled and self.stage is None:
            raise CapabilityStageError("stage_required")
        self.model_calls += 1


def interaction_guide(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "owner": "dclaw.super-agent-support",
        "stage": "interaction",
        "instructions": (
            "Ask at most one customer collection question per model response. "
            "When asking, suggest one card using a component_type from this live "
            "catalog. Use single_select for one enumerated choice, multi_select "
            "for several choices, question_form for one open question, and "
            "file_selector for a local file. Match the component schema and "
            "create example exactly; the expert validates business rules, "
            "the Host validates the full component schema. If the card is "
            "rejected, return the same model response's one-question text fallback."
        ),
        "host_apis": [
            "interaction.capabilities.list/1", "interaction.card.create/1",
            "interaction.card.read/1", "interaction.card.cancel/1",
        ],
        "answer_kind_map": {
            answer_kind: [
                kind for kind in component_types
                if any(item.get("component_type") == kind for item in catalog["components"])
            ]
            for answer_kind, component_types in ANSWER_KIND_MAP.items()
        },
        "catalog": catalog,
    }


def local_guide() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1] / "devkit"
    schemas = {}
    for name, filename in (
        ("prepare_request", "local-runtime-prepare-v1/request.schema.json"),
        ("start_request", "local-task-host-v1/start-request.schema.json"),
        ("task_request", "local-task-host-v1/task-request.schema.json"),
        ("receipt", "local-task-host-v1/receipt.schema.json"),
    ):
        schemas[name] = json.loads((root / "schemas" / filename).read_text(encoding="utf-8"))
    return {
        "owner": "dclaw.super-agent-support",
        "stage": "local",
        "instructions": (
            "Use only registered and authorized Local Helper capabilities. "
            "Prepare the exact runtime before starting a task, use a stable "
            "idempotency key, and trust only the Host task receipt and later "
            "terminal status. Customer content and local paths must not enter diagnostics."
        ),
        "host_apis": [
            "local.runtime.prepare/1", "local.task.start/1",
            "local.task.read/1", "local.task.cancel/1",
        ],
        "use_when": [
            "customer-approved editing or other work must run on the paired local device",
            "a registered capability and its exact package version are available",
        ],
        "do_not_use_when": [
            "requirements are still being collected",
            "the customer has not authorized an external or local action",
        ],
        "fallback": {
            "prepare_failed": "do not start; report the missing device or package condition",
            "start_failed": "do not claim a task exists without its Host receipt",
            "task_failed": "read the terminal receipt and report only the verified outcome",
        },
        "schemas": schemas,
    }
