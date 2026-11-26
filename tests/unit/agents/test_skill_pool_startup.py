from pathlib import Path

from qwenpaw.agents.skill_system import registry


def test_default_distribution_can_be_deferred_and_runs_once(
    monkeypatch,
    tmp_path,
):
    pool_dir = tmp_path / "skill_pool"
    manifest = pool_dir / "skill.json"
    calls = []

    monkeypatch.setattr(registry, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        registry,
        "get_pool_skill_manifest_path",
        lambda: manifest,
    )
    monkeypatch.setattr(
        registry,
        "write_json_atomic",
        lambda path, payload: path.write_text("{}", encoding="utf-8"),
    )
    monkeypatch.setattr(registry, "import_builtin_skills", lambda: None)
    monkeypatch.setattr(
        registry,
        "_sync_default_skill_creator_builtin",
        lambda: None,
    )
    monkeypatch.setattr(
        registry,
        "_sync_managed_editable_ppt_builtin",
        lambda: None,
    )
    monkeypatch.setattr(registry, "_pool_initialized_for", None)
    monkeypatch.setattr(registry, "_pool_defaults_distributed_for", None)
    monkeypatch.setattr(registry, "_pool_initializing", False)

    from qwenpaw.agents.skill_system import pool_service

    class FakePoolService:
        def install_default_skills_to_all_workspaces(self, *, overwrite):
            calls.append(overwrite)

    monkeypatch.setattr(pool_service, "SkillPoolService", FakePoolService)

    assert registry.ensure_skill_pool_initialized(
        distribute_defaults=False,
    )
    assert calls == []

    assert not registry.ensure_skill_pool_initialized()
    assert calls == [True]

    assert not registry.ensure_skill_pool_initialized()
    assert calls == [True]
    assert registry._pool_initialized_for == Path(pool_dir).resolve()
    assert registry._pool_defaults_distributed_for == Path(pool_dir).resolve()


def test_migration_wrapper_forwards_deferred_distribution(monkeypatch):
    from qwenpaw.agents import builtin_product_assets
    from qwenpaw.app import migration

    calls = []
    monkeypatch.setattr(
        builtin_product_assets,
        "ensure_product_builtin_assets",
        lambda **kwargs: calls.append(kwargs),
    )

    migration.ensure_product_builtin_assets(
        distribute_default_skills=False,
    )

    assert calls == [{"distribute_default_skills": False}]
