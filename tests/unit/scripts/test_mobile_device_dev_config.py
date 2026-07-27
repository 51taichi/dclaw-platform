from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_saas_compose_allows_lan_bind_for_physical_device_preview() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text()

    assert (
        "${QWENPAW_SAAS_BIND_HOST:-127.0.0.1}:"
        "${QWENPAW_SAAS_HOST_PORT:-18088}:8088"
    ) in compose
