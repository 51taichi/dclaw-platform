from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app import _app
from qwenpaw.config.config import Config


def test_startup_reconciliation_saves_only_when_profiles_change(
    monkeypatch,
    tmp_path,
):
    config = Config()
    saved = []
    expected = SimpleNamespace(
        config_changed=True,
        reconciled=("luyu",),
        unavailable=(),
    )
    monkeypatch.setattr(_app, "load_config", lambda _path: config)
    monkeypatch.setattr(
        _app,
        "save_config",
        lambda value, path: saved.append((value, path)),
    )
    monkeypatch.setattr(_app, "get_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(
        _app,
        "get_sealed_agent_registry",
        lambda: object(),
        raising=False,
    )
    monkeypatch.setattr(
        _app,
        "reconcile_active_sealed_profiles",
        lambda current, registry, root: expected,
        raising=False,
    )

    result = _app._reconcile_sealed_agent_profiles()

    assert result is expected
    assert saved == [(config, tmp_path / "config.json")]


def test_startup_reconciliation_failure_isolated_from_agent_startup(
    monkeypatch,
):
    monkeypatch.setattr(
        _app,
        "load_config",
        lambda _path: (_ for _ in ()).throw(RuntimeError("broken registry")),
    )

    assert _app._reconcile_sealed_agent_profiles() is None
