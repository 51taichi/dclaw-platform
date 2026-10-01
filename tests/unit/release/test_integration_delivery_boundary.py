from __future__ import annotations

from pathlib import Path

from qwenpaw.app.integration_delivery import router as integration_router


ROOT = Path(__file__).resolve().parents[3]


def test_dclaw_keeps_only_the_generic_delivery_integration_surface() -> None:
    paths = {route.path for route in integration_router.router.routes}

    assert paths == {
        "/internal/integrations/v1/capabilities",
        "/internal/integrations/v1/agents/{agent_id}/delivery-context",
        "/internal/integrations/v1/agents/{agent_id}/source-bundle",
    }
    assert not (ROOT / "src" / "config_patch_service").exists()
    assert not (
        ROOT / "src" / "qwenpaw" / "app" / "config_patch_participant"
    ).exists()


def test_dclaw_has_no_customer_service_patch_runtime_or_public_staff_api() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    router_registry = (
        ROOT / "src" / "qwenpaw" / "app" / "routers" / "__init__.py"
    ).read_text(encoding="utf-8")
    auth = (ROOT / "src" / "qwenpaw" / "app" / "auth.py").read_text(
        encoding="utf-8"
    )

    assert "dclaw-config-patch" not in pyproject
    assert "config_patch_service" not in pyproject
    assert "config_patch_participant" not in router_registry
    assert "/api/internal/config-patch/" not in auth

    forbidden_deploy_files = [
        path
        for path in (ROOT / "deploy").glob("config-patch*")
        if path.is_file()
    ]
    assert forbidden_deploy_files == []
    assert not (ROOT / ".github" / "workflows" / "config-patch-image.yml").exists()


def test_dclaw_runtime_sources_do_not_name_ai_customer_service_ownership() -> None:
    roots = [ROOT / "src", ROOT / "deploy"]
    forbidden = (
        "/staff/v1",
        "DCLAW_CONFIG_PATCH",
        "dclaw-config-patch",
        "worktool.deepmega.cn",
        "worktool-test.deepmega.cn",
    )

    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in forbidden:
                assert marker not in text, f"{marker!r} remains in {path}"
