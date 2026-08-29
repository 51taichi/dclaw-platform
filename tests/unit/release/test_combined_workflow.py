# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dclaw-combined-image.yml"


def _load_workflow() -> dict[str, Any]:
    return yaml.load(WORKFLOW.read_text(), Loader=yaml.BaseLoader)


def _steps() -> list[dict[str, Any]]:
    workflow = _load_workflow()
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["build-and-publish"]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    return steps


def _step(step_id: str) -> dict[str, Any]:
    return next(step for step in _steps() if step.get("id") == step_id)


def _step_index(step_id: str) -> int:
    return next(
        index
        for index, step in enumerate(_steps())
        if step.get("id") == step_id
    )


def test_combined_workflow_has_all_three_entry_points() -> None:
    workflow = _load_workflow()
    events = workflow["on"]
    assert isinstance(events, dict)
    assert events["push"] == {"branches": ["main"]}
    assert events["repository_dispatch"] == {"types": ["dclaw_client_main"]}
    assert "workflow_dispatch" in events


def test_combined_workflow_has_minimal_permissions_and_concurrency() -> None:
    workflow = _load_workflow()
    assert workflow["permissions"] == {"contents": "read", "packages": "write"}
    concurrency = workflow["concurrency"]
    assert isinstance(concurrency, dict)
    assert concurrency["cancel-in-progress"] == "true"


def test_workflow_checks_out_both_exact_resolved_revisions() -> None:
    server = _step("checkout-server")
    client = _step("checkout-client")
    assert server["with"]["ref"] == "${{ steps.release.outputs.server_sha }}"
    assert client["with"]["ref"] == "${{ steps.release.outputs.client_sha }}"
    assert client["with"]["repository"] == "51taichi/dclaw-client"
    assert "DCLAW_CLIENT_READ_TOKEN" not in str(server)
    assert "DCLAW_CLIENT_READ_TOKEN" in str(client)


def test_main_is_published_only_after_immutable_image_verification() -> None:
    assert _step_index("build-immutable-image") < _step_index(
        "verify-image-labels",
    )
    assert _step_index("verify-image-labels") < _step_index("publish-main-tag")
    verify = str(_step("verify-image-labels")["run"])
    assert "cn.deepmega.dclaw.server-revision" in verify
    assert "cn.deepmega.dclaw.client-revision" in verify


def test_workflow_never_pushes_main_in_build_step() -> None:
    build = _step("build-immutable-image")
    assert ":main" not in str(build)
    assert "${{ steps.release.outputs.pair_tag }}" in str(build)


def test_workflow_uses_assembler_and_verifies_frontend_before_build() -> None:
    assemble = _step("assemble-context")
    assert "scripts/release/assemble_context.sh" in str(assemble["run"])
    assert _step_index("assemble-context") < _step_index(
        "build-immutable-image",
    )


def test_workflow_uses_github_token_only_for_ghcr_write() -> None:
    login = _step("login-ghcr")
    assert login["with"]["password"] == "${{ secrets.GITHUB_TOKEN }}"
    assert login["with"]["registry"] == "ghcr.io"
