# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ASSEMBLER = REPO_ROOT / "scripts" / "release" / "assemble_context.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "release-test@example.invalid")
    _git(repo, "config", "user.name", "Release Test")
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    return _git(repo, "rev-parse", "HEAD")


def _make_inputs(
    tmp_path: Path,
    *,
    include_docs: bool = True,
) -> tuple[Path, Path, str, str]:
    server = tmp_path / "server"
    client = tmp_path / "client"
    server_sha = _commit(
        server,
        {
            "deploy/Dockerfile": "FROM scratch\n",
            "server.txt": "server-source\n",
        },
    )
    client_files = {
        "console/package-lock.json": "{}\n",
        "console/package.json": '{"scripts":{"build":"true"}}\n',
        "console/src/index.ts": "export {};\n",
    }
    if include_docs:
        client_files["website/public/docs/intro.zh.md"] = "# DClaw\n"
    client_sha = _commit(client, client_files)
    return server, client, server_sha, client_sha


def _fake_npm(tmp_path: Path, *, fail_build: bool = False) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npm = bin_dir / "npm"
    npm.write_text(
        "#!/bin/sh\n"
        'printf \'%s|%s\\n\' "${NODE_OPTIONS:-}" "$*" >>"$NPM_CALLS"\n'
        + (
            'case "$*" in *run\\ build*) exit 23;; esac\n'
            if fail_build
            else ""
        )
        + "exit 0\n",
    )
    npm.chmod(0o755)
    return bin_dir


def _run(
    tmp_path: Path,
    server: Path,
    client: Path,
    output: Path,
    server_sha: str,
    client_sha: str,
    *,
    fail_build: bool = False,
) -> subprocess.CompletedProcess[str]:
    calls = tmp_path / "npm-calls.txt"
    env = os.environ.copy()
    env["PATH"] = f"{_fake_npm(tmp_path, fail_build=fail_build)}:{env['PATH']}"
    env["NPM_CALLS"] = str(calls)
    return subprocess.run(
        [
            "bash",
            str(ASSEMBLER),
            str(server),
            str(client),
            str(output),
            server_sha,
            client_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_assembler_rejects_missing_client_docs(tmp_path: Path) -> None:
    server, client, server_sha, client_sha = _make_inputs(
        tmp_path,
        include_docs=False,
    )

    result = _run(
        tmp_path,
        server,
        client,
        tmp_path / "out",
        server_sha,
        client_sha,
    )

    assert result.returncode != 0
    assert "website/public/docs" in result.stderr
    assert not (tmp_path / "out").exists()


def test_assembler_rejects_head_mismatch(tmp_path: Path) -> None:
    server, client, _, client_sha = _make_inputs(tmp_path)

    result = _run(
        tmp_path,
        server,
        client,
        tmp_path / "out",
        "0" * 40,
        client_sha,
    )

    assert result.returncode != 0
    assert "server HEAD does not match" in result.stderr
    assert not (tmp_path / "out").exists()


def test_frontend_build_failure_does_not_publish_partial_context(
    tmp_path: Path,
) -> None:
    server, client, server_sha, client_sha = _make_inputs(tmp_path)

    result = _run(
        tmp_path,
        server,
        client,
        tmp_path / "out",
        server_sha,
        client_sha,
        fail_build=True,
    )

    assert result.returncode == 23
    assert not (tmp_path / "out").exists()


def test_assembler_copies_exact_sources_and_builds_console(
    tmp_path: Path,
) -> None:
    server, client, server_sha, client_sha = _make_inputs(tmp_path)
    output = tmp_path / "out"

    result = _run(
        tmp_path,
        server,
        client,
        output,
        server_sha,
        client_sha,
    )

    assert result.returncode == 0, result.stderr
    assert (output / "server.txt").read_text() == "server-source\n"
    assert (output / "console/src/index.ts").is_file()
    assert (output / "website/public/docs/intro.zh.md").is_file()
    assert (tmp_path / "npm-calls.txt").read_text().splitlines() == [
        "|ci --include=dev",
        "--max-old-space-size=4096|run build",
    ]
