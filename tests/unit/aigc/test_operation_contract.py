from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qwenpaw.aigc.operation_contract import (
    OperationCatalog,
    build_operation_manual,
    load_operation_catalog,
)


CONTRACT = (
    Path(__file__).parents[3]
    / "src/qwenpaw/aigc/contracts/aigc-operation-contract-v1.json"
)


def test_v1_text_to_video_contract_has_stable_unique_human_controls():
    catalog = load_operation_catalog(CONTRACT)
    operation = catalog.operation("aigc.text_to_video.create")

    assert operation.version == "1"
    assert operation.machine_executor is None
    step_ids = [step.step_id for step in operation.human_guide]
    control_ids = [step.control_id for step in operation.human_guide]
    assert len(step_ids) == len(set(step_ids))
    assert len(control_ids) == len(set(control_ids))
    assert all(step.recovery for step in operation.human_guide)
    assert all(step.success_signal for step in operation.human_guide)
    assert operation.expected_result["asset_kind"] == "video"


def test_duplicate_steps_or_controls_fail_contract_validation():
    catalog = load_operation_catalog(CONTRACT)
    payload = catalog.model_dump(mode="json")
    operation = payload["operations"][0]
    operation["human_guide"][1]["step_id"] = operation["human_guide"][0][
        "step_id"
    ]

    with pytest.raises(ValidationError, match="step"):
        OperationCatalog.model_validate(payload)

    payload = catalog.model_dump(mode="json")
    operation = payload["operations"][0]
    operation["human_guide"][1]["control_id"] = operation["human_guide"][0][
        "control_id"
    ]
    with pytest.raises(ValidationError, match="control"):
        OperationCatalog.model_validate(payload)


def test_generated_manual_and_machine_catalog_are_byte_deterministic(tmp_path):
    catalog = load_operation_catalog(CONTRACT)
    first_manual = tmp_path / "first.md"
    first_machine = tmp_path / "first.json"
    second_manual = tmp_path / "second.md"
    second_machine = tmp_path / "second.json"

    build_operation_manual(catalog, first_manual, first_machine)
    build_operation_manual(catalog, second_manual, second_machine)

    assert first_manual.read_bytes() == second_manual.read_bytes()
    assert first_machine.read_bytes() == second_machine.read_bytes()
    machine = json.loads(first_machine.read_text())
    assert machine["operations"][0]["operation_id"] == (
        "aigc.text_to_video.create"
    )
    assert "点击" in first_manual.read_text(encoding="utf-8")
