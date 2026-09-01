from __future__ import annotations

from qwenpaw.app.runner.runner import AgentRunner
from qwenpaw.app.workspace.workspace import Workspace


def test_standard_and_sealed_workspaces_register_identical_runtime_services(
    tmp_path,
):
    ordinary = Workspace("ordinary", str(tmp_path / "ordinary"))
    sealed = Workspace(
        "sealed",
        str(tmp_path / "sealed-release" / "agent"),
    )

    ordinary_descriptors = ordinary._service_manager.descriptors
    sealed_descriptors = sealed._service_manager.descriptors
    assert set(ordinary_descriptors) == set(sealed_descriptors)
    assert ordinary_descriptors["runner"].service_class is AgentRunner
    assert sealed_descriptors["runner"].service_class is AgentRunner
