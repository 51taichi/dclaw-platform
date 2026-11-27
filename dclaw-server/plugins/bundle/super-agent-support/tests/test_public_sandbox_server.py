from __future__ import annotations

from pathlib import Path

from super_agent import public_sandbox_server


def test_runtime_health_requires_files_roots_and_isolation_probe(
    tmp_path,
    monkeypatch,
):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "public_runtime.py").write_text("# broker\n", encoding="utf-8")
    worker = runtime / "public_worker.py"
    worker.write_text("# worker\n", encoding="utf-8")
    shared = tmp_path / "shared"
    (shared / "sealed_agents").mkdir(parents=True)
    (shared / "workspace_runtime_state").mkdir()
    seen = []

    def available(**kwargs):
        seen.append(kwargs)
        return True

    monkeypatch.setattr(public_sandbox_server, "isolation_available", available)
    assert public_sandbox_server._runtime_available(
        shared,
        runtime_dir=runtime,
    ) is True
    assert seen == [{"socket_path": "", "worker_path": worker}]

    worker.unlink()
    assert public_sandbox_server._runtime_available(
        shared,
        runtime_dir=runtime,
    ) is False
    assert len(seen) == 1


def test_runtime_health_fails_when_isolation_probe_fails(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name in ("public_runtime.py", "public_worker.py"):
        (runtime / name).write_text("# runtime\n", encoding="utf-8")
    shared = tmp_path / "shared"
    (shared / "sealed_agents").mkdir(parents=True)
    (shared / "workspace_runtime_state").mkdir()
    monkeypatch.setattr(
        public_sandbox_server,
        "isolation_available",
        lambda **_: False,
    )
    assert public_sandbox_server._runtime_available(
        shared,
        runtime_dir=runtime,
    ) is False
