"""AIGC-owned instructions for the current workflow capability catalog."""

from __future__ import annotations

from typing import Any

from .workflow_contract import WorkflowBlueprint


def build_aigc_guide(catalog: dict[str, Any]) -> dict[str, Any]:
    workflow_schema = WorkflowBlueprint.model_json_schema()
    definitions = workflow_schema.pop("$defs", {})
    return {
        "owner": "qwenpaw.aigc",
        "stage": "aigc",
        "instructions": (
            "Use the current catalog's available nodes, models, parameter schemas "
            "and workflow constraints. Create or resume a workflow only after "
            "customer requirements are sufficient and the required authorization "
            "is verified. A request or model assertion is not a created task; "
            "check the Host receipt and task snapshot. Keep task identity stable "
            "for retries and increment content revision when the plan changes. "
            "If customer feedback reveals missing requirements, return to "
            "collection on the next turn and retain prior assets as an older revision."
        ),
        "host_apis": [
            "aigc.workflow.capabilities.list/1", "aigc.workflow.create/1",
            "aigc.task.binding.resolve/1", "aigc.task.snapshot/1",
            "aigc.task.assets.list/1", "aigc.task.assets.localize/1",
        ],
        "create_request_schema": {
            "type": "object",
            "$defs": definitions,
            "required": ["task_key", "content_revision", "workflow"],
            "properties": {
                "task_key": {"type": "string", "minLength": 1, "maxLength": 160},
                "content_revision": {"type": "integer", "minimum": 1},
                "workflow": workflow_schema,
            },
            "additionalProperties": False,
        },
        "fallback": {
            "catalog_unavailable": "state that creation did not start; retry later",
            "create_rejected": "keep the same task identity for unchanged input and report the rejection",
            "unsupported": "offer a manual path only when the live catalog confirms absence",
        },
        "catalog": catalog,
    }
