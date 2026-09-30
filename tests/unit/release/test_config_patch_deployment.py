from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = ROOT / "deploy" / "config-patch.Dockerfile"
ENTRYPOINT = ROOT / "deploy" / "config-patch-entrypoint.sh"
COMPOSE = ROOT / "deploy" / "config-patch.compose.yaml"
RUNBOOK = ROOT / "docs" / "config-patch-service-phase1-runbook.md"


def _compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_config_patch_image_has_an_independent_non_root_entrypoint() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    assert "USER configpatch" in dockerfile
    assert "config-patch-entrypoint.sh" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "http://127.0.0.1:8788/health" in dockerfile
    assert "deploy/entrypoint.sh" not in dockerfile
    assert "qwenpaw init" not in dockerfile
    assert "dclaw-config-patch" in entrypoint
    assert "qwenpaw" not in entrypoint
    assert "uvicorn qwenpaw" not in entrypoint


def test_config_patch_compose_is_explicit_and_owns_only_its_data() -> None:
    rendered = _compose()
    assert set(rendered["services"]) == {"config-patch"}
    service = rendered["services"]["config-patch"]
    assert service["build"]["dockerfile"] == "deploy/config-patch.Dockerfile"
    assert service["volumes"] == [
        "config-patch-data:/var/lib/dclaw-config-patch"
    ]
    assert service["healthcheck"]["test"][-1] == (
        "http://127.0.0.1:8788/health"
    )
    assert rendered["volumes"] == {"config-patch-data": {}}

    existing = yaml.safe_load(
        (ROOT / "deploy" / "production" / "compose.production.yml").read_text(
            encoding="utf-8"
        )
    )
    assert "config-patch" not in existing["services"]


def test_config_patch_compose_requires_every_credential_without_defaults() -> (
    None
):
    environment = _compose()["services"]["config-patch"]["environment"]
    required = {
        "CONFIG_PATCH_TOKEN_PEPPER",
        "CONFIG_PATCH_ADMIN_SECRET",
        "DCLAW_CONFIG_PATCH_INTERNAL_SECRET",
        "OMNICHANNEL_CONFIG_PATCH_INTERNAL_SECRET",
        "OMNICHANNEL_CONFIG_PATCH_BASE_URL",
    }
    assert required <= set(environment)
    for name in required:
        assert environment[name] == f"${{{name}:?{name} is required}}"

    serialized = COMPOSE.read_text(encoding="utf-8")
    for forbidden in (
        "change-me",
        "development-secret",
        "test-secret",
        "token-pepper-value",
    ):
        assert forbidden not in serialized


def test_phase_one_runbook_covers_operations_and_safe_shutdown() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for heading in (
        "## 环境变量",
        "## 启动与健康检查",
        "## 本地 Smoke Test",
        "## 密钥轮换",
        "## 备份与恢复",
        "## 审计查询",
        "## ADMIN_BOOTSTRAP_REQUIRED 排查",
        "## 停用与回滚",
    ):
        assert heading in text
    assert "Authorization: Bearer <员工_TOKEN>" in text
    assert "docker compose -f deploy/config-patch.compose.yaml stop" in text
    assert "无需回滚 DClaw 或 AI 客服业务数据" in text
