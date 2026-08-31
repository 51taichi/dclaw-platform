from __future__ import annotations

import pytest

from qwenpaw.app.sealed_agents.adapters import (
    UnsupportedSealedRuntime,
    get_runtime_adapter,
)


def test_only_allowlisted_runtime_adapters_can_be_resolved():
    standard = get_runtime_adapter("standard", "1")
    harness = get_runtime_adapter("sealed_harness", "1")

    assert standard.key == ("standard", "1")
    assert harness.key == ("sealed_harness", "1")


def test_unknown_adapter_is_rejected():
    with pytest.raises(UnsupportedSealedRuntime):
        get_runtime_adapter("arbitrary", "1")


def test_unknown_contract_version_is_rejected():
    with pytest.raises(UnsupportedSealedRuntime):
        get_runtime_adapter("sealed_harness", "2")
