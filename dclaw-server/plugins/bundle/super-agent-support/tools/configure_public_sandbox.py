#!/usr/bin/env python3
"""Add the plugin-owned sandbox sidecar to an existing Compose project."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import tempfile

import yaml


SOCKET = "/app/working/super-agent-sandbox/runtime.sock"
SERVICE = "dclaw-super-agent-sandbox"


def configure(
    compose_path: Path,
    *,
    backup_path: Path,
    sandbox_image: str,
    working_host_path: Path,
) -> dict[str, str]:
    if not sandbox_image or any(char.isspace() for char in sandbox_image):
        raise ValueError("sandbox image tag is invalid")
    if backup_path.exists():
        raise FileExistsError("Compose backup already exists")
    content = compose_path.read_text(encoding="utf-8")
    document = yaml.safe_load(content)
    if not isinstance(document, dict):
        raise ValueError("Compose document is invalid")
    services = document.get("services")
    if not isinstance(services, dict) or "dclaw-server" not in services:
        raise ValueError("DClaw Server service is missing")
    if SERVICE in services:
        raise ValueError("sandbox service is already configured")
    server = services["dclaw-server"]
    environment = server.get("environment")
    if not isinstance(environment, dict):
        raise ValueError("Server environment must be a mapping")
    if "DCLAW_SUPER_AGENT_SANDBOX_SOCKET" in environment:
        raise ValueError("sandbox socket is already configured")
    host = working_host_path.resolve(strict=True)
    for name in (
        "plugins", "plugins/dclaw.super-agent-support", "sealed_agents",
        "workspace_runtime_state", "super-agent-sandbox",
    ):
        if not (host / name).is_dir():
            raise ValueError(f"required sandbox mount is missing: {name}")
    environment["DCLAW_SUPER_AGENT_SANDBOX_SOCKET"] = SOCKET
    services[SERVICE] = {
        "image": sandbox_image,
        "container_name": SERVICE,
        "restart": "unless-stopped",
        "network_mode": "none",
        "read_only": True,
        "tmpfs": ["/tmp:rw,nosuid,nodev,size=64m"],
        "cap_add": ["SYS_ADMIN"],
        "security_opt": [
            "seccomp:unconfined", "apparmor:unconfined",
            "no-new-privileges:true",
        ],
        "volumes": [
            f"{host}/plugins:/app/working/plugins:ro",
            f"{host}/sealed_agents:/app/working/sealed_agents:ro",
            f"{host}/workspace_runtime_state:"
            "/app/working/workspace_runtime_state:rw",
            f"{host}/super-agent-sandbox:"
            "/app/working/super-agent-sandbox:rw",
        ],
        "entrypoint": "/usr/bin/python3",
        "command": [
            "/app/working/plugins/dclaw.super-agent-support/"
            "super_agent/public_sandbox_server.py",
            "--socket", SOCKET, "--shared-root", "/app/working",
        ],
    }
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(compose_path, backup_path)
    fd, temporary = tempfile.mkstemp(
        prefix=".compose-public-sandbox-", dir=compose_path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yaml.safe_dump(document, stream, sort_keys=False, allow_unicode=True)
        original_stat = compose_path.stat()
        os.chmod(temporary, stat.S_IMODE(original_stat.st_mode))
        os.chown(temporary, original_stat.st_uid, original_stat.st_gid)
        os.replace(temporary, compose_path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {
        "server_image": str(server.get("image")),
        "sandbox_image": sandbox_image,
        "backup_path": str(backup_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--sandbox-image", required=True)
    parser.add_argument("--working-host-path", type=Path, required=True)
    args = parser.parse_args()
    print(configure(
        args.compose,
        backup_path=args.backup,
        sandbox_image=args.sandbox_image,
        working_host_path=args.working_host_path,
    ))


if __name__ == "__main__":
    main()
