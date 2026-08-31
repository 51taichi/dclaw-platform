from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from qwenpaw.app.sealed_agents.harness_protocol import (
    HarnessProcess,
    HarnessProtocolError,
    HarnessStageRequest,
    HarnessStageResponse,
    minimal_worker_environment,
)
from qwenpaw.app.sealed_agents.runtime import PinnedSealedRuntime


def _pinned(tmp_path: Path) -> PinnedSealedRuntime:
    release = tmp_path / "release"
    (release / "agent").mkdir(parents=True)
    source = (
        Path(__file__).parents[3]
        / "fixtures"
        / "sealed_harness"
        / "agent"
        / "runtime.py"
    )
    (release / "agent/runtime.py").write_bytes(source.read_bytes())
    return PinnedSealedRuntime(
        agent_id="sealed",
        release_id="release-1",
        version="1.0.0",
        content_digest=f"sha256:{'a' * 64}",
        release_root=release,
        entrypoint="agent/runtime.py",
        adapter_key=("sealed_harness", "1"),
        failure_policy="fail_closed",
    )


def test_protocol_models_reject_extra_fields():
    request = HarnessStageRequest(
        request_id="request-1",
        stage="handshake",
        payload={},
    )
    response = HarnessStageResponse(
        request_id=request.request_id,
        ok=True,
        payload={"contract_version": "1"},
    )

    assert response.payload["contract_version"] == "1"


def test_worker_environment_does_not_inherit_secrets(monkeypatch):
    monkeypatch.setenv("QWENPAW_DATABASE_URL", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    environment = minimal_worker_environment()

    assert "QWENPAW_DATABASE_URL" not in environment
    assert "OPENAI_API_KEY" not in environment


@pytest.mark.asyncio
async def test_worker_handshake_reports_contract(tmp_path):
    pinned = _pinned(tmp_path)
    worker = Path(__file__).parents[4] / "src/qwenpaw/app/sealed_agents/harness_worker.py"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(worker),
        "--release-root",
        str(pinned.release_root),
        "--session-root",
        str(tmp_path),
        "--entrypoint",
        pinned.entrypoint,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    request = HarnessStageRequest(
        request_id="request-1",
        stage="handshake",
        payload={},
    )
    process.stdin.write((request.model_dump_json() + "\n").encode())
    await process.stdin.drain()
    response = HarnessStageResponse.model_validate_json(await process.stdout.readline())
    process.stdin.close()
    await process.wait()

    assert response.ok is True
    assert response.payload["adapter"] == "sealed_harness"
    assert response.payload["contract_version"] == "1"
    assert "commit" in response.payload["stages"]


@pytest.mark.asyncio
async def test_process_refuses_to_fallback_without_bubblewrap(tmp_path):
    process = HarnessProcess(_pinned(tmp_path), bwrap_path="/missing/bwrap")

    with pytest.raises(HarnessProtocolError, match="isolation"):
        await process.start()


def test_stage_request_serializes_as_single_json_object():
    request = HarnessStageRequest(
        request_id="request-1",
        stage="commit",
        payload={"message": "ok"},
    )

    assert json.loads(request.model_dump_json())["stage"] == "commit"
