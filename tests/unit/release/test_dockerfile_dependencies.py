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
