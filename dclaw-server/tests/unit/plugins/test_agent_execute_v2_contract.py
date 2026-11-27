import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[3]
PLUGIN = ROOT / "plugins" / "bundle" / "super-agent-support"
SCHEMA = (
    PLUGIN
    / "devkit"
    / "schemas"
    / "agent-execute-v2"
    / "request.schema.json"
)


def test_agent_execute_v2_schema_matches_default_loop_and_explicit_candidate():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    messages = [{"role": "user", "content": "test"}]

    for request in (
        {"messages": messages},
        {"messages": messages, "execution_mode": "agent_loop"},
        {"messages": messages, "instruction": "Answer using the available tools."},
        {"messages": messages, "execution_mode": "candidate"},
        {
            "messages": messages,
            "execution_mode": "candidate",
            "response_format": "json_object",
        },
    ):
        assert validator.is_valid(request), request

    for request in (
        {"messages": messages, "response_format": "json_object"},
        {"messages": messages, "execution_mode": "candidate", "instruction": "x"},
        {"messages": messages, "execution_mode": "agent_loop", "response_format": "json_object"},
        {"messages": messages, "execution_mode": "unknown"},
    ):
        assert not validator.is_valid(request), request


def test_new_super_expert_templates_declare_execute_v2():
    for template in (
        PLUGIN / "devkit" / "templates" / "minimal",
        PLUGIN / "developer_pack" / "templates" / "project",
    ):
        manifest = json.loads(
            (template / "manifest.template.json").read_text(encoding="utf-8"),
        )
        assert {
            item["capability_id"]: item["contract_version"]
            for item in manifest["capabilities"]
        }["agent.execute"] == "2"
        runtime = (template / "agent" / "runtime.py").read_text(encoding="utf-8")
        assert "execution_mode" not in runtime
