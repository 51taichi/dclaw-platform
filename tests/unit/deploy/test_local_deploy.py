from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).parents[3]
MODULE_PATH = ROOT / "deploy/local/dclaw_local.py"


def load_module():
    spec = importlib.util.spec_from_file_location("dclaw_local", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_config_uses_production_names_and_lan_bind(tmp_path):
    module = load_module()
    config = module.DeploymentConfig(
        deploy_root=tmp_path / "deploy",
        server_root=tmp_path / "server",
        client_root=tmp_path / "client",
        luyu_root=tmp_path / "luyu",
        bind_host="0.0.0.0",
        host_port=18088,
        image="dclaw-local:test",
    )

    assert config.project_name == "dclaw-production"
    assert config.app_container == "dclaw"
    assert config.postgres_container == "dclaw-postgres"
    assert config.redis_container == "dclaw-redis"
    assert config.local_url == "http://127.0.0.1:18088"


def test_config_rejects_public_database_and_weak_secrets(tmp_path):
    module = load_module()
    config = module.DeploymentConfig(
        deploy_root=tmp_path,
        server_root=tmp_path,
        client_root=tmp_path,
        luyu_root=tmp_path,
    )

    with pytest.raises(module.DeploymentError, match="administrator password"):
        module.validate_secret_values(
            config,
            {
                "DCLAW_ADMIN_PASSWORD": "admin",
                "DCLAW_POSTGRES_PASSWORD": "change-me",
            },
        )


def test_redaction_never_exposes_secret_values():
    module = load_module()
    values = {
        "DCLAW_ADMIN_PASSWORD": "correct-horse-battery-staple",
        "DCLAW_POSTGRES_PASSWORD": "database-secret-value",
        "VOLCANO_API_KEY": "volcano-secret-value",
        "MXAPI_API_KEY": "mxapi-secret-value",
        "DCLAW_STT_INTERNAL_TOKEN": "speech-secret-value",
        "DCLAW_HOST_PORT": "18088",
    }

    rendered = module.redacted_environment(values)

    assert rendered["DCLAW_HOST_PORT"] == "18088"
    assert rendered["DCLAW_ADMIN_PASSWORD"] == "<redacted>"
    assert rendered["DCLAW_STT_INTERNAL_TOKEN"] == "<redacted>"
    assert "secret-value" not in repr(rendered)


def test_compose_command_is_explicit_and_platform_independent(tmp_path):
    module = load_module()
    config = module.DeploymentConfig(
        deploy_root=tmp_path / "deploy root",
        server_root=tmp_path / "server root",
        client_root=tmp_path / "client root",
        luyu_root=tmp_path / "luyu root",
    )

    command = module.compose_command(config, "up", "-d")

    assert command[:3] == ["docker", "compose", "--project-name"]
    assert command[3] == "dclaw-production"
    assert "--env-file" in command
    assert str(config.env_file) in command
    assert str(config.compose_file) in command
    assert command[-2:] == ["up", "-d"]


def test_source_identity_changes_for_dirty_content(tmp_path):
    module = load_module()
    root = tmp_path / "source"
    root.mkdir()
    (root / "tracked.txt").write_text("first", encoding="utf-8")

    first = module.content_fingerprint(root)
    (root / "tracked.txt").write_text("second", encoding="utf-8")
    second = module.content_fingerprint(root)

    assert first != second
    assert len(first) == 12


def test_build_context_combines_server_and_client_without_generated_files(tmp_path):
    module = load_module()
    server = tmp_path / "server"
    client = tmp_path / "client"
    target = tmp_path / "context"
    (server / "deploy").mkdir(parents=True)
    (server / "src").mkdir()
    (server / "deploy/Dockerfile").write_text("FROM scratch\n")
    (server / "src/app.py").write_text("APP = True\n")
    (server / ".git").mkdir()
    (server / ".git/secret").write_text("no")
    (client / "console/node_modules/pkg").mkdir(parents=True)
    (client / "console/src-tauri/target/release").mkdir(parents=True)
    (client / "console/src").mkdir()
    (client / "console/package.json").write_text("{}")
    (client / "console/src/index.ts").write_text("export {}")
    (client / "console/node_modules/pkg/index.js").write_text("no")
    (client / "console/src-tauri/target/release/app").write_text("no")
    (client / "website/public/docs").mkdir(parents=True)
    (client / "website/public/docs/index.md").write_text("docs")

    module.assemble_build_context(server, client, target)

    assert (target / "src/app.py").is_file()
    assert (target / "console/src/index.ts").is_file()
    assert (target / "website/public/docs/index.md").is_file()
    assert not (target / ".git").exists()
    assert not (target / "console/node_modules").exists()
    assert not (target / "console/src-tauri").exists()


def test_generated_env_enables_auth_and_complete_backends(tmp_path):
    module = load_module()
    config = module.DeploymentConfig(
        deploy_root=tmp_path,
        server_root=tmp_path,
        client_root=tmp_path,
        luyu_root=tmp_path,
    )

    values = module.initial_environment(config, random_password=lambda: "x" * 32)

    assert values["QWENPAW_AUTH_ENABLED"] == "true"
    assert values["QWENPAW_DATABASE_BACKEND"] == "postgres"
    assert values["QWENPAW_RUNTIME_BACKEND"] == "redis"
    assert values["DCLAW_BIND_HOST"] == "0.0.0.0"
    assert values["DCLAW_HOST_PORT"] == "18088"
    assert values["DCLAW_ADMIN_PASSWORD"] == "x" * 32
    assert values["DCLAW_REALTIME_STT_ENABLED"] == "true"
    assert values["DCLAW_STT_INTERNAL_TOKEN"] == "x" * 32
    assert values["DCLAW_STT_MODEL"] == "base"
    assert values["DCLAW_OPEN_API_MAX_RUNNING_TASKS_GLOBAL"] == "100"
    assert values["DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION"] == "60"
    assert values["DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY"] == "20"
    assert values["QWENPAW_MAX_RUNNING_TASKS"] == "150"
    assert values["QWENPAW_LLM_MAX_CONCURRENT"] == "999"


def test_compose_passes_capacity_settings_to_local_container():
    compose = (ROOT / "deploy/local/compose.local.yml").read_text(encoding="utf-8")

    assert "DCLAW_OPEN_API_MAX_RUNNING_TASKS_GLOBAL" in compose
    assert "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION" in compose
    assert "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY" in compose
    assert "QWENPAW_MAX_RUNNING_TASKS" in compose
    assert "QWENPAW_LLM_MAX_CONCURRENT" in compose


def test_compose_public_url_is_optional_for_lan_request_origin():
    compose = (ROOT / "deploy/local/compose.local.yml").read_text(encoding="utf-8")

    assert "QWENPAW_PUBLIC_BASE_URL: ${DCLAW_PUBLIC_BASE_URL:-}" in compose
    assert "PUBLIC_BASE_URL: ${DCLAW_PUBLIC_BASE_URL:-}" in compose
    assert "QWENPAW_PUBLIC_BASE_URL: http://127.0.0.1" not in compose


def test_compose_keeps_realtime_stt_private_and_resource_bounded():
    compose = (ROOT / "deploy/local/compose.local.yml").read_text(encoding="utf-8")
    service = compose.split("  dclaw-stt:", 1)[1].split("  dclaw-postgres:", 1)[0]

    assert "DCLAW_REALTIME_STT_ENABLED" in compose
    assert "DCLAW_STT_UPSTREAM_URL" in compose
    assert "DCLAW_STT_INTERNAL_TOKEN" in compose
    assert "ports:" not in service
    assert "mem_limit:" in service
    assert "cpus:" in service
    assert "dclaw-stt-models:/models" in service


def test_stt_image_reuses_the_local_dclaw_base_without_docker_hub():
    dockerfile = (ROOT / "deploy/realtime_stt/Dockerfile").read_text(
        encoding="utf-8",
    )

    assert "ARG DCLAW_BASE_IMAGE" in dockerfile
    assert "FROM ${DCLAW_BASE_IMAGE}" in dockerfile
    assert "FROM python:" not in dockerfile
