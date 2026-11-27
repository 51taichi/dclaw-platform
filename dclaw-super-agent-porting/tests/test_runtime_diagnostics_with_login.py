import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import runtime_diagnostics_with_login as diagnostics  # noqa: E402
import summarize_runtime_diagnostics as summary  # noqa: E402


SCHEMA = {
    "type": "object",
    "required": ["contract", "status", "retention_days", "failures", "history_readback"],
    "properties": {
        "contract": {"const": diagnostics.CONTRACT},
        "status": {"enum": ["found", "no_record"]},
        "failures": {
            "type": "array", "maxItems": 50,
            "items": {
                "type": "object",
                "required": [
                    "invocation_id", "installation_id", "release_id", "started_at",
                    "failed_at", "first_failure", "first_failure_source", "error_code",
                    "transaction_status", "message_status",
                ],
                "properties": {
                    "invocation_id": {"type": "string"},
                    "installation_id": {"type": "string"},
                    "release_id": {"type": "string"},
                    "started_at": {"type": ["string", "null"]},
                    "failed_at": {"type": "string"},
                    "first_failure": {
                        "type": "object",
                        "required": ["phase", "category", "attempt"],
                        "properties": {
                            "phase": {"type": ["string", "null"]},
                            "category": {"type": ["string", "null"]},
                            "attempt": {"type": ["integer", "null"], "minimum": 1},
                        },
                        "additionalProperties": False,
                    },
                    "first_failure_source": {
                        "enum": ["agent_trace", "platform_preflight", "not_recorded"],
                    },
                    "error_code": {"type": ["string", "null"]},
                    "transaction_status": {"const": "discarded"},
                    "message_status": {"enum": ["persisted", "missing", "unknown"]},
                },
                "additionalProperties": False,
            },
        },
        "retention_days": {"const": 30},
        "history_readback": {
            "type": "object",
            "required": ["messages_table_count", "agent_memory_count"],
            "properties": {
                "messages_table_count": {"type": "integer", "minimum": 0},
                "agent_memory_count": {"type": ["integer", "null"], "minimum": 0},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}
RESPONSE = {
    "contract": diagnostics.CONTRACT,
    "status": "found",
    "retention_days": 30,
    "failures": [{
        "invocation_id": "abc", "installation_id": "installation-1",
        "release_id": "release-1", "started_at": "2026-11-07T01:00:00Z",
        "failed_at": "2026-11-07T01:01:00Z",
        "first_failure": {"phase": "model_validation", "category": "json_parse", "attempt": 1},
        "first_failure_source": "agent_trace", "error_code": "INVALID_TURN_RESULT",
        "transaction_status": "discarded", "message_status": "persisted",
    }],
    "history_readback": {"messages_table_count": 0, "agent_memory_count": 10},
}
REFERENCE_ID = "a" * 32
REFERENCE_SCHEMA = {
    "oneOf": [
        {
            "type": "object", "required": ["contract", "status", "retention_days"],
            "properties": {
                "contract": {"const": summary.REFERENCE_CONTRACT},
                "status": {"const": "no_record"}, "retention_days": {"const": 30},
            }, "additionalProperties": False,
        },
        {
            "type": "object",
            "required": ["contract", "status", "retention_days", "task_id", "invocation_id",
                         "installation_id", "release_id", "started_at", "failed_at",
                         "first_failure", "first_failure_source", "error_code",
                         "transaction_status", "stages"],
            "properties": {
                "contract": {"const": summary.REFERENCE_CONTRACT},
                "status": {"const": "found"}, "retention_days": {"const": 30},
                "task_id": {"type": "string"}, "invocation_id": {"type": "string"},
                "installation_id": {"type": "string"}, "release_id": {"type": "string"},
                "started_at": {"type": ["string", "null"]}, "failed_at": {"type": "string"},
                "first_failure": {
                    "type": "object", "required": ["phase", "category", "attempt"],
                    "properties": {
                        "phase": {"type": ["string", "null"]},
                        "category": {"type": ["string", "null"]},
                        "attempt": {"type": ["integer", "null"]},
                    }, "additionalProperties": False,
                },
                "first_failure_source": {"enum": ["agent_trace", "host_stage", "platform_preflight", "not_recorded"]},
                "error_code": {"type": ["string", "null"]},
                "transaction_status": {"const": "discarded"},
                "stages": {
                    "type": "array", "maxItems": 100,
                    "items": {
                        "type": "object", "required": ["event", "source", "at", "duration_ms"],
                        "properties": {
                            "event": {"type": "string"}, "source": {"enum": ["host", "agent"]},
                            "at": {"type": "string"}, "duration_ms": {"type": ["integer", "null"]},
                            "call_number": {"type": "integer"},
                            "has_text": {"type": "boolean"},
                            "complete_json_object": {"type": "boolean"},
                        }, "additionalProperties": False,
                    },
                },
            }, "additionalProperties": False,
        },
    ],
}
REFERENCE_RESPONSE = {
    "contract": summary.REFERENCE_CONTRACT, "status": "found", "retention_days": 30,
    "task_id": "task-123", "invocation_id": REFERENCE_ID,
    "installation_id": "installation-1", "release_id": "release-1",
    "started_at": "2026-11-08T08:00:00Z", "failed_at": "2026-11-08T08:01:00Z",
    "first_failure": {"phase": "model_validation", "category": "json_parse", "attempt": 1},
    "first_failure_source": "agent_trace", "error_code": "INVALID_TURN_RESULT",
    "transaction_status": "discarded", "stages": [{
        "event": "agent.execute", "source": "host", "at": "2026-11-08T08:00:30Z",
        "duration_ms": 50, "has_text": False, "complete_json_object": False,
    }],
}
V2_SCHEMA = copy.deepcopy(REFERENCE_SCHEMA)
for branch in V2_SCHEMA["oneOf"]:
    branch["properties"]["contract"]["const"] = summary.REFERENCE_CONTRACT_V2
found_v2 = V2_SCHEMA["oneOf"][1]
found_v2["required"] += ["failure_events", "final_blocker", "unrecorded_fields"]
found_v2["properties"]["stages"]["items"]["properties"].update({
    "field_path": {"type": "string"}, "constraint": {"type": "string"},
})
found_v2["properties"].update({
    "failure_events": {"type": "array", "maxItems": 50, "items": {
        "type": "object", "required": ["phase", "category", "attempt", "source", "at",
                                     "status_code", "provider_code", "provider_param", "outcome"],
        "properties": {
            "phase": {"type": "string"}, "category": {"type": "string"},
            "attempt": {"type": ["integer", "null"]},
            "source": {"enum": ["host", "agent", "platform_preflight"]},
            "at": {"type": "string"}, "status_code": {"type": ["integer", "null"]},
            "provider_code": {"type": ["string", "null"]},
            "provider_param": {"type": ["string", "null"]},
            "outcome": {"enum": ["recovered", "terminal", "not_recorded"]},
            "field_path": {"type": ["string", "null"]},
            "constraint": {"type": ["string", "null"]},
            "contract": {"type": ["string", "null"]},
        }, "additionalProperties": False,
    }},
    "final_blocker": {"type": "object", "required": ["status", "phase", "category",
                                                     "attempt", "responsibility", "reason"],
                      "properties": {
                          "status": {"enum": ["recorded", "not_recorded"]},
                          "phase": {"type": "string"}, "category": {"type": "string"},
                          "attempt": {"type": ["integer", "null"]},
                          "responsibility": {"enum": ["model_provider", "agent", "not_recorded"]},
                          "reason": {"enum": ["provider_rejected_request", "agent_reported_failure", "not_recorded"]},
                           "field_path": {"type": "string"},
                           "constraint": {"type": "string"},
                      }, "additionalProperties": False},
    "unrecorded_fields": {"type": "array", "uniqueItems": True,
                          "items": {"enum": ["provider_code", "provider_param"]}},
})
V2_RESPONSE = {
    **REFERENCE_RESPONSE, "contract": summary.REFERENCE_CONTRACT_V2,
    "failure_events": [
        {"phase": "model", "category": "provider_timeout", "attempt": 1,
         "source": "host", "at": "2026-11-08T08:00:30Z", "status_code": None,
         "provider_code": None, "provider_param": None, "outcome": "recovered"},
        {"phase": "agent_validation", "category": "invalid_result", "attempt": 2,
         "source": "agent", "at": "2026-11-08T08:01:00Z", "status_code": None,
         "provider_code": None, "provider_param": None, "outcome": "terminal"},
    ],
    "final_blocker": {"status": "recorded", "phase": "agent_validation",
                      "category": "invalid_result", "attempt": 2,
                      "responsibility": "agent", "reason": "agent_reported_failure"},
    "unrecorded_fields": ["provider_code"],
}


class DiagnosticsTests(unittest.TestCase):
    def test_legacy_receipts_do_not_require_v3_schema_dependency(self):
        with mock.patch.object(summary, "validate_full_schema", side_effect=AssertionError("v3 only")):
            summary.validate_response(RESPONSE, SCHEMA)
            summary.validate_reference_response(REFERENCE_RESPONSE, REFERENCE_SCHEMA)
            summary.validate_reference_response(V2_RESPONSE, V2_SCHEMA)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        schema_path = self.root / "devkit" / "schemas" / "runtime-diagnostics-v1" / "response.schema.json"
        schema_path.parent.mkdir(parents=True)
        schema_path.write_text(json.dumps(SCHEMA), encoding="utf-8")
        self.output = self.root / "project" / "diagnostics.json"
        self.argv = [
            "runtime_diagnostics_with_login.py", "--base-url", "https://example.invalid",
            "--devkit-root", str(self.root / "devkit"), "--agent-id", "my_agent",
            "--task-id", "task-123", "--output", str(self.output),
        ]

    def run_main(self, replies):
        with mock.patch.object(sys, "argv", self.argv), \
                mock.patch.object(diagnostics.sys, "stdin") as stdin, \
                mock.patch("builtins.input", return_value="developer"), \
                mock.patch.object(diagnostics.getpass, "getpass", return_value="secret"), \
                mock.patch.object(diagnostics, "request_json", side_effect=replies) as request, \
                mock.patch("builtins.print") as printed:
            stdin.isatty.return_value = True
            diagnostics.main()
        return request.call_args_list, printed.call_args_list

    def test_authorized_read_saves_unmodified_receipt_without_printing_token(self):
        calls, printed = self.run_main([{"token": "private-token"}, {}, RESPONSE])
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), RESPONSE)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2].args[0],
                         "https://example.invalid/api/user/super-expert-platform/"
                         "runtime-diagnostics/v1/tasks/task-123?agent_id=my_agent")
        self.assertEqual(calls[2].kwargs["token"], "private-token")
        self.assertNotIn("private-token", str(printed))
        self.assertNotIn("invocation_id", str(printed))

    def test_authorized_read_can_save_redacted_summary(self):
        report = self.root / "project" / "diagnostics-summary.md"
        self.argv += ["--summary-output", str(report)]
        _, printed = self.run_main([{"token": "private-token"}, {}, RESPONSE])
        content = report.read_text(encoding="utf-8")
        self.assertIn("model_validation", content)
        self.assertIn("json_parse", content)
        self.assertIn("候选解析入口", content)
        self.assertIn("不能证明任何旧消息已恢复或永久丢失", content)
        self.assertNotIn("private-token", content + str(printed))
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), RESPONSE)

    def test_reference_lookup_uses_official_owner_scoped_route(self):
        schema_path = self.root / "devkit" / "schemas" / "runtime-diagnostics-v1" / "by-reference-response.schema.json"
        schema_path.write_text(json.dumps(REFERENCE_SCHEMA), encoding="utf-8")
        self.argv[self.argv.index("--task-id")] = "--invocation-id"
        self.argv[self.argv.index("task-123")] = REFERENCE_ID
        report = self.root / "project" / "reference-summary.md"
        self.argv += ["--summary-output", str(report)]
        calls, printed = self.run_main([{"token": "private-token"}, {}, REFERENCE_RESPONSE])
        self.assertEqual(calls[2].args[0],
                         "https://example.invalid/api/user/super-expert-publishing/"
                         f"runtime-diagnostics/v1/references/{REFERENCE_ID}?agent_id=my_agent")
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), REFERENCE_RESPONSE)
        self.assertIn("model_validation", report.read_text(encoding="utf-8"))
        self.assertNotIn("private-token", report.read_text(encoding="utf-8") + str(printed))

    def test_reference_no_record_and_invalid_payload(self):
        no_record = {"contract": summary.REFERENCE_CONTRACT, "status": "no_record", "retention_days": 30}
        content = summary.render_reference_summary(no_record, REFERENCE_SCHEMA, "my_agent", REFERENCE_ID)
        self.assertIn("不能推定从未失败", content)
        self.assertNotIn("任务：`task-123`", content)
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            summary.render_reference_summary({**no_record, "customer_text": "private"},
                                             REFERENCE_SCHEMA, "my_agent", REFERENCE_ID)
        with self.assertRaisesRegex(ValueError, "task_id is missing"):
            invalid = dict(REFERENCE_RESPONSE)
            invalid.pop("task_id")
            summary.render_reference_summary(invalid, REFERENCE_SCHEMA, "my_agent", REFERENCE_ID)
        with self.assertRaisesRegex(ValueError, "has_text has the wrong type"):
            invalid = {**REFERENCE_RESPONSE, "stages": [
                {**REFERENCE_RESPONSE["stages"][0], "has_text": "false"}
            ]}
            summary.render_reference_summary(invalid, REFERENCE_SCHEMA, "my_agent", REFERENCE_ID)

    def test_reference_summary_separates_earlier_error_from_later_call_failure(self):
        response = {**REFERENCE_RESPONSE, "stages": [
            {"event": "agent.execute.safe_completed", "source": "host",
             "at": "2026-11-08T08:00:30Z", "duration_ms": 50, "call_number": 3},
            {"event": "agent.execute.safe_failed", "source": "host",
             "at": "2026-11-08T08:00:31Z", "duration_ms": 80, "call_number": 4},
        ]}
        content = summary.render_reference_summary(response, REFERENCE_SCHEMA, "my_agent", REFERENCE_ID)
        self.assertIn("首错检查线索", content)
        self.assertIn("agent.execute.safe_failed", content)
        self.assertIn("call_number `4`", content)
        self.assertIn("不能把首错当作终止原因", content)
        self.assertIn("最终阻断的阶段和类别", content)

    def test_reference_offline_summary(self):
        schema_path = self.root / "devkit" / "schemas" / "runtime-diagnostics-v1" / "by-reference-response.schema.json"
        schema_path.write_text(json.dumps(REFERENCE_SCHEMA), encoding="utf-8")
        self.output.parent.mkdir(parents=True)
        self.output.write_text(json.dumps(REFERENCE_RESPONSE), encoding="utf-8")
        report = self.root / "project" / "offline-reference.md"
        argv = ["summarize_runtime_diagnostics.py", "--receipt", str(self.output),
                "--devkit-root", str(self.root / "devkit"), "--agent-id", "my_agent",
                "--invocation-id", REFERENCE_ID, "--output", str(report)]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            summary.main()
        self.assertIn("关联 ID 诊断摘要", report.read_text(encoding="utf-8"))

    def test_existing_summary_refuses_before_login(self):
        report = self.root / "project" / "diagnostics-summary.md"
        report.parent.mkdir(parents=True)
        report.write_text("original", encoding="utf-8")
        self.argv += ["--summary-output", str(report)]
        with mock.patch.object(sys, "argv", self.argv), mock.patch.object(diagnostics, "request_json") as request:
            with self.assertRaises(SystemExit):
                diagnostics.main()
        request.assert_not_called()
        self.assertEqual(report.read_text(encoding="utf-8"), "original")

    def test_offline_summary_uses_existing_receipt_without_login(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_text(json.dumps(RESPONSE), encoding="utf-8")
        report = self.root / "project" / "offline-summary.md"
        argv = [
            "summarize_runtime_diagnostics.py", "--receipt", str(self.output),
            "--devkit-root", str(self.root / "devkit"), "--agent-id", "my_agent",
            "--task-id", "task-123", "--output", str(report),
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            summary.main()
        self.assertIn("Invocation", report.read_text(encoding="utf-8"))

    def test_no_record_does_not_claim_no_historical_failure(self):
        receipt = {**RESPONSE, "status": "no_record", "failures": []}
        content = summary.render_summary(receipt, SCHEMA, "my_agent", "task-123")
        self.assertIn("不能证明任务从未失败", content)
        self.assertIn("未取得 invocation、installation、Release、首错、事务", content)
        self.assertNotIn("已有证据：上述 invocation", content)
        self.assertNotIn("message_status=persisted", content)

    def test_unrecorded_and_unsafe_category_remain_unattributed(self):
        failure = {
            **RESPONSE["failures"][0],
            "first_failure": {"phase": None, "category": None, "attempt": None},
            "first_failure_source": "not_recorded",
        }
        content = summary.render_summary(
            {**RESPONSE, "failures": [failure]}, SCHEMA, "my_agent", "task-123"
        )
        self.assertIn("不能猜根因", content)
        failure["first_failure"] = {"phase": "model_validation", "category": "secret\nvalue", "attempt": 1}
        failure["first_failure_source"] = "agent_trace"
        content = summary.render_summary(
            {**RESPONSE, "failures": [failure]}, SCHEMA, "my_agent", "task-123"
        )
        self.assertNotIn("secret", content)

    def test_schema_rejects_unexpected_or_missing_failure_fields(self):
        failure = {**RESPONSE["failures"][0], "customer_text": "private"}
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            summary.render_summary(
                {**RESPONSE, "failures": [failure]}, SCHEMA, "my_agent", "task-123"
            )
        failure = dict(RESPONSE["failures"][0])
        failure.pop("release_id")
        with self.assertRaisesRegex(ValueError, "release_id is missing"):
            summary.render_summary(
                {**RESPONSE, "failures": [failure]}, SCHEMA, "my_agent", "task-123"
            )

    def test_wrong_contract_does_not_write_receipt(self):
        invalid = {**RESPONSE, "contract": "other"}
        with self.assertRaisesRegex(ValueError, "contract has the wrong constant"):
            self.run_main([{"token": "private-token"}, {}, invalid])
        self.assertFalse(self.output.exists())

    def test_existing_receipt_refuses_before_login(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_text("original", encoding="utf-8")
        with mock.patch.object(sys, "argv", self.argv), mock.patch.object(diagnostics, "request_json") as request:
            with self.assertRaises(SystemExit):
                diagnostics.main()
        request.assert_not_called()
        self.assertEqual(self.output.read_text(encoding="utf-8"), "original")

    def test_unauthorized_http_error_does_not_write_receipt(self):
        denied = urllib.error.HTTPError("https://example.invalid", 404, "Not Found", {}, None)
        with self.assertRaises(urllib.error.HTTPError):
            self.run_main([{"token": "private-token"}, {}, denied])
        self.assertFalse(self.output.exists())

    def test_v2_read_uses_new_route_and_final_blocker(self):
        schema_path = self.root / "devkit" / "schemas" / "runtime-diagnostics-v2" / "by-reference-response.schema.json"
        schema_path.parent.mkdir(parents=True)
        schema_path.write_text(json.dumps(V2_SCHEMA), encoding="utf-8")
        self.argv[7:9] = ["--invocation-id", REFERENCE_ID]
        self.argv += ["--summary-output", str(self.root / "project" / "summary.md")]
        requests, _ = self.run_main([{"token": "private-token"}, {}, V2_RESPONSE])
        self.assertIn("/v2/references/", requests[-1].args[0])
        content = (self.root / "project" / "summary.md").read_text(encoding="utf-8")
        self.assertIn("outcome `recovered`", content)
        self.assertIn("最终阻断：`agent_validation/invalid_result`", content)
        self.assertIn("历史未留存字段：provider_code", content)

    def test_v2_summary_prioritizes_terminal_rejection_over_recovered_first_error(self):
        response = copy.deepcopy(V2_RESPONSE)
        response["first_failure"] = {"phase": "model", "category": "provider_timeout", "attempt": 1}
        response["failure_events"][1] = {
            **response["failure_events"][1], "phase": "agent_execute",
            "category": "BadRequestError", "source": "host",
        }
        response["final_blocker"] = {
            "status": "recorded", "phase": "agent_execute", "category": "BadRequestError",
            "attempt": 2, "responsibility": "model_provider",
            "reason": "provider_rejected_request",
        }
        response["stages"] = [{"event": "agent.execute.safe_failed", "source": "host",
                               "at": "2026-11-08T08:01:00Z", "duration_ms": 50}]
        content = summary.render_reference_summary(response, V2_SCHEMA, "my_agent", REFERENCE_ID)
        self.assertIn("首错状态：已在本轮恢复", content)
        self.assertIn("最终阻断：`agent_execute/BadRequestError`", content)
        self.assertIn("提供方拒绝请求不等于已确定请求由 Agent、Host 或模型提供方哪一层构造错误", content)
        self.assertNotIn("该阶段未提供失败类别", content)

    def test_v2_summary_groups_repeated_validation_and_reports_schema_limits(self):
        response = copy.deepcopy(V2_RESPONSE)
        repeated = {**response["failure_events"][0],
                    "phase": "interaction_tool_validation",
                    "category": "INVALID_INTERACTION_REQUEST",
                    "attempt": None, "source": "host", "outcome": "not_recorded",
                    "field_path": "request", "constraint": "INVALID_VALUE",
                    "contract": "interaction.card.create/1"}
        response["failure_events"] = [response["failure_events"][0]] + [
            {**repeated, "at": f"2026-11-08T08:00:{index:02d}Z"}
            for index in range(1, 48)
        ] + [response["failure_events"][1]]
        response["stages"] = [response["stages"][0]] * 100
        content = summary.render_reference_summary(response, V2_SCHEMA, "my_agent", REFERENCE_ID)
        self.assertIn("阶段记录已达到正式 Schema 的 100 条上限", content)
        self.assertIn("相邻同类合并为 3 组", content)
        self.assertIn("#2-48（47 条）", content)
        self.assertEqual(content.count("field_path `request`"), 1)
        self.assertIn("constraint `INVALID_VALUE`", content)
        self.assertIn("contract `interaction.card.create/1`", content)
        self.assertIn("#49 `agent_validation/invalid_result`", content)
        self.assertNotIn("具体参数", content)

        response["failure_events"].append(copy.deepcopy(response["failure_events"][1]))
        content = summary.render_reference_summary(response, V2_SCHEMA, "my_agent", REFERENCE_ID)
        self.assertIn("失败事件已达到正式 Schema 的 50 条上限", content)

    def test_v2_no_record_and_missing_final_blocker(self):
        no_record = {"contract": summary.REFERENCE_CONTRACT_V2,
                     "status": "no_record", "retention_days": 30}
        self.assertIn("不能推定从未失败", summary.render_reference_summary(
            no_record, V2_SCHEMA, "my_agent", REFERENCE_ID))
        unknown = {**V2_RESPONSE, "final_blocker": {
            "status": "not_recorded", "phase": "not_recorded", "category": "not_recorded",
            "attempt": None, "responsibility": "not_recorded", "reason": "not_recorded"}}
        self.assertIn("不能用首错", summary.render_reference_summary(
            unknown, V2_SCHEMA, "my_agent", REFERENCE_ID))

    def test_v2_offline_summary_selects_receipt_contract(self):
        schema_path = self.root / "devkit" / "schemas" / "runtime-diagnostics-v2" / "by-reference-response.schema.json"
        schema_path.parent.mkdir(parents=True)
        schema_path.write_text(json.dumps(V2_SCHEMA), encoding="utf-8")
        self.output.parent.mkdir(parents=True)
        self.output.write_text(json.dumps(V2_RESPONSE), encoding="utf-8")
        report = self.root / "project" / "offline-v2.md"
        argv = ["summarize_runtime_diagnostics.py", "--receipt", str(self.output),
                "--devkit-root", str(self.root / "devkit"), "--agent-id", "my_agent",
                "--invocation-id", REFERENCE_ID, "--output", str(report)]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            summary.main()
        self.assertIn("最终阻断：`agent_validation/invalid_result`", report.read_text(encoding="utf-8"))

    def test_v2_rejects_unknown_or_duplicate_fields(self):
        invalid = copy.deepcopy(V2_RESPONSE)
        invalid["failure_events"][0]["customer_text"] = "private"
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            summary.render_reference_summary(invalid, V2_SCHEMA, "my_agent", REFERENCE_ID)
        invalid = {**V2_RESPONSE, "unrecorded_fields": ["provider_code", "provider_code"]}
        with self.assertRaisesRegex(ValueError, "duplicate items"):
            summary.render_reference_summary(invalid, V2_SCHEMA, "my_agent", REFERENCE_ID)

    def test_v2_denied_does_not_fallback_to_v1(self):
        schema_path = self.root / "devkit" / "schemas" / "runtime-diagnostics-v2" / "by-reference-response.schema.json"
        schema_path.parent.mkdir(parents=True)
        schema_path.write_text(json.dumps(V2_SCHEMA), encoding="utf-8")
        self.argv[7:9] = ["--invocation-id", REFERENCE_ID]
        denied = urllib.error.HTTPError("https://example.invalid", 404, "Not Found", {}, None)
        with mock.patch.object(sys, "argv", self.argv), \
                mock.patch.object(diagnostics.sys, "stdin") as stdin, \
                mock.patch("builtins.input", return_value="developer"), \
                mock.patch.object(diagnostics.getpass, "getpass", return_value="secret"), \
                mock.patch.object(diagnostics, "request_json", side_effect=[
                    {"token": "private-token"}, {}, denied]) as request:
            stdin.isatty.return_value = True
            with self.assertRaises(urllib.error.HTTPError):
                diagnostics.main()
        self.assertEqual(request.call_count, 3)
        self.assertIn("/v2/references/", request.call_args.args[0])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
