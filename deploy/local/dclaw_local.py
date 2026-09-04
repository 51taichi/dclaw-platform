#!/usr/bin/env python3
"""Cross-platform local DClaw Docker deployment CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


MODULE_DIR = Path(__file__).resolve().parent
SECRET_NAMES = frozenset(
    {
        "DCLAW_ADMIN_PASSWORD",
        "DCLAW_POSTGRES_PASSWORD",
        "VOLCANO_API_KEY",
        "MXAPI_API_KEY",
        "DCLAW_LUYU_SIGNING_PRIVATE_KEY",
        "DCLAW_STT_INTERNAL_TOKEN",
    }
)
COPY_EXCLUDES = frozenset(
    {
        ".git",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "src-tauri",
        "outputs",
        "__pycache__",
    }
)


class DeploymentError(RuntimeError):
    """Sanitized local deployment failure."""


@dataclass(frozen=True)
class DeploymentConfig:
    deploy_root: Path
    server_root: Path
    client_root: Path
    luyu_root: Path
    bind_host: str = "0.0.0.0"
    host_port: int = 18088
    image: str = "dclaw-local:current"
    stt_image: str = "dclaw-stt-local:current"
    project_name: str = "dclaw-production"
    app_container: str = "dclaw"
    postgres_container: str = "dclaw-postgres"
    redis_container: str = "dclaw-redis"

    def __post_init__(self) -> None:
        for name in ("deploy_root", "server_root", "client_root", "luyu_root"):
            object.__setattr__(self, name, Path(getattr(self, name)).resolve())
        if not (1 <= int(self.host_port) <= 65535):
            raise DeploymentError("host port is invalid")

    @property
    def env_file(self) -> Path:
        return self.deploy_root / "local.env"

    @property
    def release_file(self) -> Path:
        return self.deploy_root / "release.env"

    @property
    def compose_file(self) -> Path:
        return MODULE_DIR / "compose.local.yml"

    @property
    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.host_port}"


def default_config() -> DeploymentConfig:
    server = Path(__file__).resolve().parents[2]
    workspace = server.parent
    return DeploymentConfig(
        deploy_root=Path(
            os.environ.get("DCLAW_LOCAL_ROOT", Path.home() / ".dclaw-local")
        ),
        server_root=Path(os.environ.get("DCLAW_SERVER_ROOT", server)),
        client_root=Path(
            os.environ.get("DCLAW_CLIENT_ROOT", workspace / "dclaw-client")
        ),
        luyu_root=Path(
            os.environ.get(
                "DCLAW_LUYU_ROOT",
                workspace
                / "agent create/agents/luyu-traffic-operator-agent",
            )
        ),
        bind_host=os.environ.get("DCLAW_BIND_HOST", "0.0.0.0"),
        host_port=int(os.environ.get("DCLAW_HOST_PORT", "18088")),
        image=os.environ.get("DCLAW_IMAGE", "dclaw-local:current"),
        stt_image=os.environ.get("DCLAW_STT_IMAGE", "dclaw-stt-local:current"),
    )


def random_password() -> str:
    return secrets.token_urlsafe(32)


def initial_environment(
    config: DeploymentConfig,
    *,
    random_password: Callable[[], str] = random_password,
) -> dict[str, str]:
    return {
        "DCLAW_IMAGE": config.image,
        "DCLAW_BIND_HOST": config.bind_host,
        "DCLAW_HOST_PORT": str(config.host_port),
        "DCLAW_PUBLIC_BASE_URL": "",
        "DCLAW_ADMIN_USERNAME": "admin",
        "DCLAW_ADMIN_PASSWORD": random_password(),
        "DCLAW_POSTGRES_PASSWORD": random_password(),
        "QWENPAW_AUTH_ENABLED": "true",
        "QWENPAW_DATABASE_BACKEND": "postgres",
        "QWENPAW_RUNTIME_BACKEND": "redis",
        "QWENPAW_KNOWLEDGE_WORKERS": "2",
        "VOLCANO_API_KEY": "",
        "MXAPI_API_KEY": "",
        "DCLAW_REALTIME_STT_ENABLED": "true",
        "DCLAW_STT_IMAGE": config.stt_image,
        "DCLAW_STT_INTERNAL_TOKEN": random_password(),
        "DCLAW_STT_MODEL": "base",
        "DCLAW_STT_DEVICE": "cpu",
        "DCLAW_STT_COMPUTE_TYPE": "int8",
        "DCLAW_STT_MAX_SESSIONS": "10",
        "DCLAW_STT_INFERENCE_CONCURRENCY": "2",
    }


def validate_secret_values(
    config: DeploymentConfig,
    values: Mapping[str, str],
) -> None:
    del config
    admin = values.get("DCLAW_ADMIN_PASSWORD", "")
    database = values.get("DCLAW_POSTGRES_PASSWORD", "")
    if len(admin) < 16 or admin.lower() in {"admin", "password", "change-me"}:
        raise DeploymentError("administrator password is weak")
    if len(database) < 16 or database.lower() in {
        "postgres",
        "password",
        "change-me",
    }:
        raise DeploymentError("database password is weak")


def redacted_environment(values: Mapping[str, str]) -> dict[str, str]:
    return {
        name: "<redacted>" if name in SECRET_NAMES and value else value
        for name, value in values.items()
    }


def parse_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        result[name.strip()] = value.strip()
    return result


def write_env(path: Path, values: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(f"{name}={value}\n" for name, value in sorted(values.items())),
        encoding="utf-8",
    )
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)


def compose_command(config: DeploymentConfig, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        config.project_name,
        "--env-file",
        str(config.env_file),
        "--file",
        str(config.compose_file),
        *args,
    ]


def _excluded(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in COPY_EXCLUDES}


def _copy_tree(source: Path, target: Path) -> None:
    if not source.is_dir():
        raise DeploymentError("source repository is unavailable")
    shutil.copytree(source, target, ignore=_excluded, dirs_exist_ok=True)


def assemble_build_context(server: Path, client: Path, target: Path) -> None:
    server, client, target = Path(server), Path(client), Path(target)
    required = (
        server / "deploy/Dockerfile",
        client / "console/package.json",
        client / "website/public/docs",
    )
    if not all(path.exists() for path in required):
        raise DeploymentError("source repositories are incomplete")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    _copy_tree(server, target)
    _copy_tree(client / "console", target / "console")
    _copy_tree(client / "website/public/docs", target / "website/public/docs")


def content_fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    root = Path(root)
    files: list[Path] = []
    for current, directories, names in os.walk(root):
        directories[:] = sorted(
            name for name in directories if name not in COPY_EXCLUDES
        )
        files.extend(Path(current) / name for name in sorted(names))
    for path in sorted(files):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()[:12]


def git_revision(root: Path) -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DeploymentError("source revision is unavailable") from exc
    if len(value) != 40:
        raise DeploymentError("source revision is invalid")
    return value


def image_identity(config: DeploymentConfig) -> tuple[str, str, str]:
    server_sha = git_revision(config.server_root)
    client_sha = git_revision(config.client_root)
    fingerprint = hashlib.sha256(
        (
            content_fingerprint(config.server_root)
            + content_fingerprint(config.client_root)
        ).encode()
    ).hexdigest()[:12]
    tag = f"dclaw-local:s{server_sha[:8]}-c{client_sha[:8]}-{fingerprint}"
    return tag, server_sha, client_sha


def run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            check=True,
            text=True,
            capture_output=capture,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DeploymentError(f"command failed: {command[0]}") from exc


def require_environment(config: DeploymentConfig) -> dict[str, str]:
    values = parse_env(config.env_file)
    if not values:
        raise DeploymentError("local environment is not initialized")
    defaults = initial_environment(config)
    changed = False
    for name, value in defaults.items():
        if name not in values:
            values[name] = value
            changed = True
    if changed:
        write_env(config.env_file, values)
    validate_secret_values(config, values)
    return values


def command_init(config: DeploymentConfig) -> None:
    config.deploy_root.mkdir(parents=True, exist_ok=True)
    if config.env_file.exists():
        values = require_environment(config)
    else:
        values = initial_environment(config)
        write_env(config.env_file, values)
    (config.deploy_root / "backups").mkdir(exist_ok=True)
    print(f"environment={config.env_file}")
    print(f"url={config.local_url}")
    print(json.dumps(redacted_environment(values), ensure_ascii=False, indent=2))


def command_build(config: DeploymentConfig) -> None:
    require_environment(config)
    tag, server_sha, client_sha = image_identity(config)
    stt_fingerprint = content_fingerprint(
        config.server_root / "deploy/realtime_stt",
    )
    stt_tag = f"dclaw-stt-local:s{server_sha[:8]}-{stt_fingerprint}"
    with tempfile.TemporaryDirectory(prefix="dclaw-local-build-") as temporary:
        context = Path(temporary) / "context"
        assemble_build_context(config.server_root, config.client_root, context)
        run(
            [
                "docker",
                "build",
                "--label",
                f"cn.deepmega.dclaw.server-revision={server_sha}",
                "--label",
                f"cn.deepmega.dclaw.client-revision={client_sha}",
                "--label",
                "cn.deepmega.dclaw.local-source=true",
                "--tag",
                tag,
                "--file",
                str(context / "deploy/Dockerfile"),
                str(context),
            ]
        )
    run(
        [
            "docker",
            "build",
            "--label",
            f"cn.deepmega.dclaw.server-revision={server_sha}",
            "--label",
            "cn.deepmega.dclaw.component=realtime-stt",
            "--tag",
            stt_tag,
            "--file",
            str(config.server_root / "deploy/realtime_stt/Dockerfile"),
            str(config.server_root),
        ],
    )
    values = parse_env(config.env_file)
    values["DCLAW_IMAGE"] = tag
    values["DCLAW_STT_IMAGE"] = stt_tag
    write_env(config.env_file, values)
    write_env(
        config.release_file,
        {
            "DCLAW_IMAGE": tag,
            "SERVER_SHA": server_sha,
            "CLIENT_SHA": client_sha,
            "SOURCE_FINGERPRINT": tag.rsplit("-", 1)[-1],
            "DCLAW_STT_IMAGE": stt_tag,
        },
    )
    print(f"image={tag}")
    print(f"stt_image={stt_tag}")


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return 200 <= response.status < 500
    except (OSError, urllib.error.URLError):
        return False


def wait_for_health(config: DeploymentConfig, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    url = f"{config.local_url}/api/version"
    while time.monotonic() < deadline:
        if _http_ok(url):
            return
        time.sleep(3)
    raise DeploymentError("DClaw health check timed out")


def command_start(config: DeploymentConfig) -> None:
    require_environment(config)
    run(compose_command(config, "up", "-d"))
    wait_for_health(config)
    print(f"local_url={config.local_url}")
    for address in lan_addresses():
        print(f"lan_url=http://{address}:{config.host_port}")


def command_stop(config: DeploymentConfig) -> None:
    require_environment(config)
    run(compose_command(config, "stop"))


def command_restart(config: DeploymentConfig) -> None:
    require_environment(config)
    run(compose_command(config, "restart"))
    wait_for_health(config)


def command_status(config: DeploymentConfig) -> None:
    require_environment(config)
    run(compose_command(config, "ps"))


def command_logs(config: DeploymentConfig) -> None:
    require_environment(config)
    run(compose_command(config, "logs", "--tail", "200", "-f"))


def lan_addresses() -> list[str]:
    result: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None):
            address = item[4][0]
            if ":" not in address and not address.startswith("127."):
                result.add(address)
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        result.add(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    return sorted(result)


def command_doctor(config: DeploymentConfig) -> None:
    values = require_environment(config)
    checks: list[tuple[str, bool]] = []
    checks.append(("docker", shutil.which("docker") is not None))
    checks.append(("compose_file", config.compose_file.is_file()))
    checks.append(("server_source", (config.server_root / "deploy/Dockerfile").is_file()))
    checks.append(("client_source", (config.client_root / "console/package.json").is_file()))
    checks.append(("luyu_source", (config.luyu_root / "runtime.py").is_file()))
    checks.append(("auth_enabled", values.get("QWENPAW_AUTH_ENABLED") == "true"))
    checks.append(("http", _http_ok(f"{config.local_url}/api/version")))
    for name, passed in checks:
        print(f"{name}={'PASS' if passed else 'FAIL'}")
    if not all(passed for _, passed in checks):
        raise DeploymentError("deployment doctor found failures")


COMMANDS = {
    "init": command_init,
    "build": command_build,
    "start": command_start,
    "stop": command_stop,
    "restart": command_restart,
    "status": command_status,
    "logs": command_logs,
    "doctor": command_doctor,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args(argv)
    try:
        COMMANDS[args.command](default_config())
    except DeploymentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
