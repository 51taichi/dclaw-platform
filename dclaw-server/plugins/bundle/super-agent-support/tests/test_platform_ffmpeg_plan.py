from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[1]


def test_plan_versions_and_trim_pair_are_closed():
    platform = json.loads((
        ROOT / "platform_capabilities/ffmpeg-task-plan/0.1.0/input.schema.json"
    ).read_text(encoding="utf-8"))
    v1 = json.loads((
        ROOT / "devkit/examples/local-ffmpeg-task-plan-v1/start-request.sample.json"
    ).read_text(encoding="utf-8"))["input"]
    v2 = json.loads((
        ROOT / "devkit/examples/local-ffmpeg-task-plan-v2/start-request.sample.json"
    ).read_text(encoding="utf-8"))["input"]
    validator = Draft202012Validator(platform)
    assert validator.is_valid(v1)
    assert validator.is_valid(v2)
    for invalid in (
        v1 | {"clips": [{"slot": "clip_01"}]},
        v2 | {"clips": [{"slot": "clip_01", "trim_end_ms": 0}]},
        v2 | {"arguments": ["-i", "source.mp4"]},
    ):
        assert not validator.is_valid(invalid)
    assert validator.is_valid(v2 | {"clips": [
        {"slot": "clip_01", "trim_start_ms": 100},
        {"slot": "clip_02", "trim_end_ms": 800},
    ]})


@pytest.mark.asyncio
async def test_full_file_plan_rejects_old_helper_before_task_acceptance(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "support_full_file_plan", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    module = importlib.import_module("support_full_file_plan.service")
    service = object.__new__(module.LocalExecutionService)
    service.store = SimpleNamespace(get_task_by_idempotency=lambda *args: None)
    monkeypatch.setattr(service, "_validate_local_file_bindings",
                        lambda *args, **kwargs: ({}, "device"))
    monkeypatch.setattr(service, "_select_device",
                        lambda *args, **kwargs: {"device_id": "device", "runner_version": "1.4.9"})
    request = json.loads((
        ROOT / "devkit/examples/local-ffmpeg-task-plan-v2/start-request.sample.json"
    ).read_text(encoding="utf-8"))
    identity = {"u": "user", "a": "agent", "c": ["interaction.file.select/1"]}
    with pytest.raises(module.PublicError) as error:
        await service._local_task_start(request, identity, "trace")
    assert error.value.code == "LOCAL_GATEWAY.DEVICE_NOT_READY"
