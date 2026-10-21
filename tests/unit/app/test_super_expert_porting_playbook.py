from pathlib import Path


DOCS_ROOT = Path(__file__).parents[3] / "docs"
PLAYBOOK = DOCS_ROOT / "super-agent-development-standard-v1.zh-CN.md"


def test_super_expert_porting_playbook_is_a_complete_task_entrypoint():
    text = PLAYBOOK.read_text(encoding="utf-8")

    required = (
        "新建任务会话",
        "WorkBuddy",
        "豆包",
        "PORTING_RECORD.md",
        "SOURCE_BEHAVIOR_SPEC.md",
        "职责映射",
        "package_type` 为 `super_expert",
        "local_capability_gateway",
        "local_environment_status",
        "local_task_result",
        "trace_id",
        "连续完成至少三个",
        "source-complete",
        "源码完成不等于已部署或已验收",
        "%LocalAppData%\\DClawLocalTool",
        "本地助手不得再次要求登录",
    )
    for phrase in required:
        assert phrase in text

    assert "`dzb` 只代表大字报业务" in text
    assert "`%LocalAppData%\\<AgentName>Runner`" in text


def test_porting_playbook_references_existing_machine_and_platform_contracts():
    devkit = (
        Path(__file__).parents[3]
        / "plugins"
        / "bundle"
        / "super-agent-support"
        / "devkit"
    )
    expected_paths = (
        devkit / "dclaw_agent_devkit.py",
        devkit / "capability-catalog.json",
        devkit / "schemas/super-expert-manifest.schema.json",
        devkit / "schemas/agent-profile.schema.json",
        devkit / "schemas/local-execution-v1/tool-call.schema.json",
        devkit / "schemas/local-execution-v1/tool-response.schema.json",
        devkit / "schemas/local-execution-v1/error-envelope.schema.json",
        devkit / "templates/minimal/manifest.template.json",
        devkit / "templates/minimal/agent/runtime.py",
    )

    for path in expected_paths:
        assert path.exists(), path
