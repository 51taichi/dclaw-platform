from pathlib import Path


DOCS_ROOT = Path(__file__).parents[3] / "docs"
PLAYBOOK = DOCS_ROOT / "super-expert-porting-playbook-v1.zh-CN.md"


def test_super_expert_porting_playbook_is_a_complete_task_entrypoint():
    text = PLAYBOOK.read_text(encoding="utf-8")

    required = (
        "新建任务会话",
        "WorkBuddy",
        "豆包",
        "PORTING_RECORD.md",
        "SOURCE_BEHAVIOR_SPEC.md",
        "职责映射",
        'package_type` 为 `super_expert',
        "local_capability_gateway",
        "local_environment_status",
        "local_task_result",
        "trace_id",
        "连续完成至少三个",
        "implemented-in-source",
        "源码完成不等于已部署",
        "%LocalAppData%\\DClawLocalTool",
        "本地助手不得再次要求登录",
    )
    for phrase in required:
        assert phrase in text

    assert "`dzb` 只属于大字报，不是公共命名规则" in text
    assert "新 Agent 不得创建 `%LocalAppData%\\<AgentName>Runner`" in text


def test_porting_playbook_references_existing_machine_and_platform_contracts():
    expected_paths = (
        DOCS_ROOT / "sealed-agents.md",
        DOCS_ROOT / "super-expert-interaction-agent-tools.md",
        DOCS_ROOT / "local-execution-standard-v1.zh-CN.md",
        DOCS_ROOT / "contracts/local-execution/v1/tool-call.schema.json",
        DOCS_ROOT / "contracts/local-execution/v1/tool-response.schema.json",
        DOCS_ROOT / "contracts/local-execution/v1/error-envelope.schema.json",
        Path(__file__).parents[3]
        / "tests/fixtures/super_expert/generic-orchestration-v1",
    )

    for path in expected_paths:
        assert path.exists(), path
