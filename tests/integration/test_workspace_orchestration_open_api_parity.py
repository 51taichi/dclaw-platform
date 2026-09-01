from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_generic_fixture_uses_only_the_public_workspace_contract():
    runtime = (ROOT / "fixtures/super_expert/generic-orchestration-v1/agent/runtime.py").read_text(encoding="utf-8")
    assert "session.context" in runtime
    assert "runtime.trace" in runtime
    assert "runtime.complete" in runtime
    assert "S9" not in runtime and "luyu" not in runtime.lower()


def test_platform_and_runner_have_no_luyu_specific_branch():
    sources = [
        ROOT.parents[0] / "src/qwenpaw/app/workspace/orchestration.py",
        ROOT.parents[0] / "src/qwenpaw/app/routers/super_expert_platform.py",
    ]
    for source in sources:
        text = source.read_text(encoding="utf-8").lower()
        assert "luyu_traffic_operator" not in text
        assert "s9_production" not in text
