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


REFERENCE_ID = "a" * 32
V3_RESPONSE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {
        "detail": {
            "type": "object", "required": ["status", "error_code", "field_path", "constraint",
                                            "recovery_action", "contract"],
            "properties": {
                "status": {"enum": ["recorded", "not_recorded", "not_applicable"]},
                "error_code": {"type": ["string", "null"]},
                "field_path": {"type": ["string", "null"]},
                "constraint": {"type": ["string", "null"]},
                "recovery_action": {"type": ["string", "null"]},
                "contract": {"type": ["string", "null"]},
            }, "additionalProperties": False,
        },
    },
    "oneOf": [
        {"type": "object", "required": ["contract", "status", "retention_days"],
         "properties": {"contract": {"const": summary.REFERENCE_CONTRACT_V3},
                        "status": {"const": "no_record"}, "retention_days": {"const": 30}},
         "additionalProperties": False},
        {"type": "object", "required": ["contract", "status", "retention_days", "task_id",
                                        "invocation_id", "installation_id", "release_id", "started_at",
                                        "failed_at", "transaction_status", "final_blocker",
                                        "host_failure_detail"],
         "properties": {
             "contract": {"const": summary.REFERENCE_CONTRACT_V3},
             "status": {"const": "found"}, "retention_days": {"const": 30},
             "task_id": {"type": "string"}, "invocation_id": {"type": "string"},
             "installation_id": {"type": "string"}, "release_id": {"type": "string"},
             "started_at": {"type": ["string", "null"], "format": "date-time"},
             "failed_at": {"type": "string", "format": "date-time"},
             "transaction_status": {"const": "discarded"},
             "final_blocker": {"type": "object", "required": ["status", "phase", "category",
                                                               "attempt", "responsibility", "reason"],
                               "properties": {
                                   "status": {"const": "recorded"}, "phase": {"type": "string"},
                                   "category": {"type": "string"},
                                   "attempt": {"type": ["integer", "null"]},
                                   "responsibility": {"type": "string"}, "reason": {"type": "string"},
                               }, "additionalProperties": False},
             "host_failure_detail": {"$ref": "#/$defs/detail"},
         }, "additionalProperties": False},
    ],
}
V3_RESPONSE = {
    "contract": summary.REFERENCE_CONTRACT_V3, "status": "found", "retention_days": 30,
    "task_id": "task-1", "invocation_id": REFERENCE_ID,
    "installation_id": "installation-1", "release_id": "release-1",
    "started_at": "2026-11-11T04:40:00Z", "failed_at": "2026-11-11T04:41:00Z",
    "transaction_status": "discarded",
    "final_blocker": {"status": "recorded", "phase": "interaction_operation",
                      "category": "InteractionError", "attempt": None,
                      "responsibility": "host_or_tool", "reason": "host_call_failed"},
    "host_failure_detail": {"status": "recorded", "error_code": "IDEMPOTENCY_CONFLICT",
                            "field_path": "not_recorded", "constraint": "IDEMPOTENCY_CONFLICT",
                            "recovery_action": "correct_request_or_resolve_conflict",
                            "contract": "interaction.card.create/1"},
}
SEARCH_REQUEST_SCHEMA = {
    "type": "object", "required": ["agent_id", "start", "end"],
    "properties": {"agent_id": {"type": "string", "minLength": 1},
                   "start": {"type": "string", "format": "date-time"},
                   "end": {"type": "string", "format": "date-time"},
                   "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                   "cursor": {"type": "string", "pattern": "^[0-9a-f]{32}$"}},
    "additionalProperties": False,
}
SEARCH_RESPONSE_SCHEMA = {
    "type": "object", "required": ["contract", "status", "retention_days", "failures",
                                   "has_more", "next_cursor"],
    "properties": {
        "contract": {"const": summary.SEARCH_CONTRACT},
        "status": {"enum": ["found", "no_record"]}, "retention_days": {"const": 30},
        "failures": {"type": "array", "maxItems": 50, "items": {
            "type": "object", "required": ["task_id", "invocation_id", "failed_at", "release_id"],
            "properties": {"task_id": {"type": "string"}, "invocation_id": {"type": "string"},
                           "failed_at": {"type": "string", "format": "date-time"},
                           "release_id": {"type": "string"}}, "additionalProperties": False}},
        "has_more": {"type": "boolean"}, "next_cursor": {"type": ["string", "null"]},
    }, "additionalProperties": False,
}
SEARCH_RESPONSE = {
    "contract": summary.SEARCH_CONTRACT, "status": "found", "retention_days": 30,
    "failures": [{"task_id": "task-1", "invocation_id": REFERENCE_ID,
                  "failed_at": "2026-11-11T04:41:00Z", "release_id": "release-1"}],
    "has_more": True, "next_cursor": REFERENCE_ID,
}


class DiagnosticsV3Tests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.devkit = self.root / "devkit"
        self.output = self.root / "project" / "receipt.json"
        self.argv = ["runtime_diagnostics_with_login.py", "--base-url", "https://example.invalid",
                     "--devkit-root", str(self.devkit), "--agent-id", "my_agent",
                     "--invocation-id", REFERENCE_ID, "--output", str(self.output)]
        self.write_contract("runtime-diagnostics-v3", V3_RESPONSE_SCHEMA,
                            {"type": "object", "required": ["agent_id", "invocation_id"],
                             "properties": {"agent_id": {"type": "string"},
                                            "invocation_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"}},
                             "additionalProperties": False}, "by-reference-")
        self.write_contract("runtime-diagnostics-search-v1", SEARCH_RESPONSE_SCHEMA,
                            SEARCH_REQUEST_SCHEMA, "")
        catalog = {
            "developer_reference_diagnostics_v3": {
                "contract": summary.REFERENCE_CONTRACT_V3, "method": "GET",
                "path_template": diagnostics.REFERENCE_RESOURCE_V3
                                 + "{invocation_id}?agent_id={agent_id}"},
            "developer_diagnostic_search": {
                "contract": summary.SEARCH_CONTRACT, "method": "GET",
                "path_template": diagnostics.SEARCH_RESOURCE
                                 + "?agent_id={agent_id}&start={start}&end={end}"},
        }
        (self.devkit / "operation-catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

    def write_contract(self, directory, response, request, prefix):
        path = self.devkit / "schemas" / directory
        path.mkdir(parents=True)
        (path / f"{prefix}response.schema.json").write_text(json.dumps(response), encoding="utf-8")
        (path / f"{prefix}request.schema.json").write_text(json.dumps(request), encoding="utf-8")

    def run_main(self, response):
        with mock.patch.object(sys, "argv", self.argv), \
                mock.patch.object(diagnostics.sys, "stdin") as stdin, \
                mock.patch("builtins.input", return_value="developer"), \
                mock.patch.object(diagnostics.getpass, "getpass", return_value="secret"), \
                mock.patch.object(diagnostics, "request_json",
                                  side_effect=[{"token": "private-token"}, {}, response]) as request, \
                mock.patch("builtins.print") as printed:
            stdin.isatty.return_value = True
            diagnostics.main()
        return request.call_args_list, printed.call_args_list

    def test_v3_lookup_uses_official_route_and_saves_safe_summary(self):
        report = self.root / "project" / "summary.md"
        self.argv += ["--summary-output", str(report)]
        calls, printed = self.run_main(V3_RESPONSE)
        self.assertIn("/v3/references/" + REFERENCE_ID, calls[-1].args[0])
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), V3_RESPONSE)
        self.assertIn("IDEMPOTENCY_CONFLICT", report.read_text(encoding="utf-8"))
        self.assertIn("不能仅凭错误码指定碰撞对象", report.read_text(encoding="utf-8"))
        self.assertNotIn("private-token", str(printed) + report.read_text(encoding="utf-8"))

    def test_v3_full_schema_rejects_invalid_format_and_ref_detail(self):
        invalid = copy.deepcopy(V3_RESPONSE)
        invalid["failed_at"] = "not-a-date"
        with self.assertRaisesRegex(ValueError, "Draft 2020-12"):
            summary.render_reference_summary(invalid, V3_RESPONSE_SCHEMA, "my_agent", REFERENCE_ID)
        invalid = copy.deepcopy(V3_RESPONSE)
        invalid["host_failure_detail"]["customer_text"] = "private"
        with self.assertRaisesRegex(ValueError, "Draft 2020-12"):
            summary.render_reference_summary(invalid, V3_RESPONSE_SCHEMA, "my_agent", REFERENCE_ID)

    def test_v3_no_record_and_historical_unknown_do_not_infer_cause(self):
        no_record = {"contract": summary.REFERENCE_CONTRACT_V3,
                     "status": "no_record", "retention_days": 30}
        self.assertIn("不能推定从未失败", summary.render_reference_summary(
            no_record, V3_RESPONSE_SCHEMA, "my_agent", REFERENCE_ID))
        unknown = copy.deepcopy(V3_RESPONSE)
        unknown["host_failure_detail"] = {**unknown["host_failure_detail"],
                                          "status": "not_recorded", "error_code": None}
        content = summary.render_reference_summary(unknown, V3_RESPONSE_SCHEMA,
                                                   "my_agent", REFERENCE_ID)
        self.assertIn("不能由泛化错误推断", content)

    def test_search_is_bounded_and_requires_explicit_page_cursor(self):
        self.argv[self.argv.index("--invocation-id")] = "--start"
        self.argv[self.argv.index(REFERENCE_ID)] = "2026-11-11T00:00:00Z"
        self.argv += ["--end", "2026-11-11T01:00:00Z", "--cursor", REFERENCE_ID]
        report = self.root / "project" / "search.md"
        self.argv += ["--summary-output", str(report)]
        calls, _ = self.run_main(SEARCH_RESPONSE)
        self.assertIn("/v1/search?", calls[-1].args[0])
        self.assertIn("cursor=" + REFERENCE_ID, calls[-1].args[0])
        self.assertEqual(len(calls), 3)
        self.assertIn("下一页 cursor", report.read_text(encoding="utf-8"))

    def test_search_rejects_long_window_before_login(self):
        self.argv[self.argv.index("--invocation-id")] = "--start"
        self.argv[self.argv.index(REFERENCE_ID)] = "2026-11-11T00:00:00Z"
        self.argv += ["--end", "2026-11-12T01:00:00Z"]
        with mock.patch.object(sys, "argv", self.argv), \
                mock.patch.object(diagnostics, "request_json") as request:
            with self.assertRaises(SystemExit):
                diagnostics.main()
        request.assert_not_called()

    def test_search_schema_rejects_invalid_cursor_and_timestamp(self):
        self.argv[self.argv.index("--invocation-id")] = "--start"
        self.argv[self.argv.index(REFERENCE_ID)] = "2026-11-11T00:00:00Z"
        self.argv += ["--end", "2026-11-11T01:00:00Z", "--cursor", "invalid"]
        with mock.patch.object(sys, "argv", self.argv), \
                mock.patch.object(diagnostics, "request_json") as request:
            with self.assertRaisesRegex(ValueError, "Draft 2020-12"):
                diagnostics.main()
        request.assert_not_called()
        invalid = copy.deepcopy(SEARCH_RESPONSE)
        invalid["failures"][0]["failed_at"] = "not-a-date"
        with self.assertRaisesRegex(ValueError, "Draft 2020-12"):
            summary.render_search_summary(invalid, SEARCH_RESPONSE_SCHEMA, "my_agent",
                                          "2026-11-11T00:00:00Z", "2026-11-11T01:00:00Z")

    def test_v3_denied_does_not_fallback_to_v2(self):
        denied = urllib.error.HTTPError("https://example.invalid", 404, "Not Found", {}, None)
        with mock.patch.object(sys, "argv", self.argv), \
                mock.patch.object(diagnostics.sys, "stdin") as stdin, \
                mock.patch("builtins.input", return_value="developer"), \
                mock.patch.object(diagnostics.getpass, "getpass", return_value="secret"), \
                mock.patch.object(diagnostics, "request_json",
                                  side_effect=[{"token": "private-token"}, {}, denied]) as request:
            stdin.isatty.return_value = True
            with self.assertRaises(urllib.error.HTTPError):
                diagnostics.main()
        self.assertEqual(request.call_count, 3)
        self.assertIn("/v3/references/", request.call_args.args[0])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
