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

    assert "某个 Agent 的名称、拼音缩写或行业缩写只属于该业务" in text
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


def test_standard_does_not_fix_any_agent_project_identity():
    text = PLAYBOOK.read_text(encoding="utf-8")

    forbidden = (
        "luyu-dclaw-vlog-agent",
        "陆羽 AI Vlog创作",
        "video-agent-V3-Windows-x64-PRIVATE-with-keys-20261023.zip",
        "/Users/moxi/",
    )
    for value in forbidden:
        assert value not in text

    assert "标准不得固定任何开发者姓名、机器目录或某个 Agent 的项目路径" in text
    assert "不得写入本通用标准" in text


def test_porting_requires_explicitly_approved_behavior_equivalence():
    text = PLAYBOOK.read_text(encoding="utf-8")

    required = (
        "行为等价迁移铁律",
        "真实可执行行为为唯一业务基线",
        "严禁删除、合并、重排、增加或自动跳过源业务步骤",
        "不得改成模型推断、自动绑定、静默补值或隐式默认",
        "不得删除步骤、降级语义、伪造成功或以替代流程绕过",
        "取得用户对每项差异的明确批准",
        "未记录的差异一律视为未批准",
        "逐步行为等价对照",
    )
    for phrase in required:
        assert phrase in text

    assert "当前版本：`2.1`" in text
