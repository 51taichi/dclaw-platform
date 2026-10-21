from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_runtime_image_installs_frozen_dependency_lock() -> None:
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(
        encoding="utf-8",
    )

    assert "COPY pyproject.toml uv.lock setup.py README.md ./" in dockerfile
    assert "uv export --frozen --no-dev --no-emit-project" in dockerfile
    assert "uv pip install" in dockerfile
    assert "--no-deps ." in dockerfile


def test_dependency_lock_is_included_in_docker_context() -> None:
    assert (ROOT / "uv.lock").is_file()
    docker_ignores = (ROOT / ".dockerignore").read_text(
        encoding="utf-8",
    ).splitlines()
    git_ignores = (ROOT / ".gitignore").read_text(
        encoding="utf-8",
    ).splitlines()

    assert "uv.lock" not in docker_ignores
    assert "uv.lock" not in git_ignores


def test_runtime_image_has_no_sealed_entrypoint_mode_or_bubblewrap() -> None:
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(
        encoding="utf-8",
    )

    assert "QWENPAW_SEALED_ENTRYPOINT_EXECUTION_MODE" not in dockerfile
    assert "bubblewrap" not in dockerfile


def test_runtime_image_autoloads_only_super_agent_support() -> None:
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text(
        encoding="utf-8",
    )

    assert (
        "ENV QWENPAW_BUNDLED_PLUGINS_DIR=/app/plugins/auto-load"
        in dockerfile
    )
    assert (
        "COPY plugins/bundle/super-agent-support "
        "./plugins/auto-load/super-agent-support"
    ) in dockerfile
    assert "COPY plugins/bundle ./plugins/bundle" not in dockerfile
    assert "COPY plugins/bundle/cloudpaw" not in dockerfile
