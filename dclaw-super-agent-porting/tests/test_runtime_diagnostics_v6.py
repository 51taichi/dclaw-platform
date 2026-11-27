import copy
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import runtime_diagnostics_with_login as diagnostics  # noqa: E402
import summarize_runtime_diagnostics as summary  # noqa: E402


DEVKIT = Path(os.environ.get("DCLAW_DEVKIT_ROOT", ""))
SCHEMA_PATH = DEVKIT / "schemas" / "runtime-diagnostics-v6" / "by-reference-response.schema.json"
REFERENCE_ID = "a" * 32
TASK_ID = "b" * 32
RESPONSE = {
    "contract": summary.REFERENCE_CONTRACT_V6,
    "status": "found", "retention_days": 30, "invocation_id": REFERENCE_ID,
    "runtime_evidence": "found", "local_task_evidence": "available",
    "release_id": "release-1", "installation_id": "installation-1",
    "runtime_outcome": "completed", "transaction_status": "committed",
    "task_acceptance": "accepted", "diagnosis_status": "multiple_failures",
    "local_tasks": [{
        "task_id": TASK_ID, "capability": "local.task.start/1", "task_status": "failed",
        "release_id": "release-1", "installation_id": "installation-1",
        "host_dispatched": True, "helper_received": True, "helper_version": "1.4.7",
        "first_failure_phase": "helper_execute", "phase_evidence": "recorded",
        "exception_category": "io_error", "category_evidence": "recorded",
        "error_code": "LOCAL_TASK_FAILED", "responsibility": "environment",
        "recovery_action": "check_local_task",
    }],
    "findings": [{
        "layer": "host", "task_id": None, "capability": "local.task.start/1",
        "phase": "host_operation", "category": "host_exception",
        "error_code": "HOST_INTERNAL_ERROR", "field_path": None,
        "constraint": None, "responsibility": "platform",
        "recovery_action": "contact_platform_with_invocation_id",
        "evidence": "first_observed_only", "observed_at": "2026-11-17T01:00:00Z",
    }, {
        "layer": "helper", "task_id": TASK_ID, "capability": "local.task.start/1",
        "phase": "helper_execute", "category": "io_error",
        "error_code": "LOCAL_TASK_FAILED", "field_path": None,
        "constraint": None, "responsibility": "environment",
        "recovery_action": "check_local_task",
        "evidence": "specific_recorded", "observed_at": "2026-11-17T01:01:00Z",
    }],
}


@unittest.skipUnless(SCHEMA_PATH.is_file(), "set DCLAW_DEVKIT_ROOT to verified DevKit 1.9.30+")
class DiagnosticsV6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.devkit = Path(self.directory.name) / "devkit"
        schema_dir = self.devkit / "schemas" / "runtime-diagnostics-v6"
        schema_dir.mkdir(parents=True)
        for name in ("by-reference-request.schema.json", "by-reference-response.schema.json",
                     "error.schema.json"):
            shutil.copyfile(SCHEMA_PATH.parent / name, schema_dir / name)
        catalog = json.loads((DEVKIT / "operation-catalog.json").read_text(encoding="utf-8"))
        (self.devkit / "operation-catalog.json").write_text(
            json.dumps({"developer_reference_diagnostics_v6":
                        catalog["developer_reference_diagnostics_v6"]}), encoding="utf-8")
        self.output = Path(self.directory.name) / "receipt.json"
        self.report = Path(self.directory.name) / "summary.md"
        self.argv = ["runtime_diagnostics_with_login.py", "--base-url", "https://example.invalid",
                     "--devkit-root", str(self.devkit), "--agent-id", "my_agent",
                     "--invocation-id", REFERENCE_ID, "--output", str(self.output),
                     "--summary-output", str(self.report)]

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

    def test_v6_uses_official_route_and_keeps_all_findings_and_task_terminal(self):
        calls, printed = self.run_main(RESPONSE)
        self.assertIn("/v6/references/" + REFERENCE_ID, calls[-1].args[0])
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), RESPONSE)
        report = self.report.read_text(encoding="utf-8")
        for expected in ("发现 #1", "发现 #2", "HOST_INTERNAL_ERROR", "LOCAL_TASK_FAILED",
                         "first_observed_only", "check_local_task", "任务 #1", "（终态）",
                         "回合完成后本地任务仍可能失败", "数组第一项不是唯一根因"):
            self.assertIn(expected, report)
        self.assertIn("turns=1", str(printed))
        self.assertNotIn("private-token", str(printed) + report)

    def test_historical_detail_and_no_record_do_not_invent_cause(self):
        response = copy.deepcopy(RESPONSE)
        response["diagnosis_status"] = "historical_detail_not_recorded"
        response["findings"] = [response["findings"][0]]
        response["findings"][0]["error_code"] = None
        response["findings"][0]["evidence"] = "historical_detail_not_recorded"
        response["local_tasks"] = []
        report = summary.render_reference_summary(response, self.schema, "my_agent", REFERENCE_ID)
        self.assertIn("历史具体失败细节未留存", report)
        self.assertIn("保持具体首错未知", report)
        no_record = {"contract": summary.REFERENCE_CONTRACT_V6,
                     "status": "no_record", "retention_days": 30}
        report = summary.render_reference_summary(no_record, self.schema, "my_agent", REFERENCE_ID)
        self.assertIn("不能推定从未失败", report)

    def test_no_failure_and_unavailable_task_evidence_keep_unknowns(self):
        response = copy.deepcopy(RESPONSE)
        response.update({"runtime_evidence": "no_record", "local_task_evidence": "unavailable",
                         "runtime_outcome": "not_recorded", "transaction_status": "not_recorded",
                         "task_acceptance": "not_recorded", "diagnosis_status": "no_failure_recorded",
                         "local_tasks": [], "findings": []})
        report = summary.render_reference_summary(response, self.schema, "my_agent", REFERENCE_ID)
        self.assertIn("运行 trace 未取得", report)
        self.assertIn("本地任务证据不可用", report)
        self.assertIn("不证明客户业务结果", report)
        self.assertNotIn("本地任务仍可能失败", report)

    def test_nested_v6_schema_is_closed_and_offline_summary_uses_v6(self):
        invalid = copy.deepcopy(RESPONSE)
        invalid["findings"][0]["customer_text"] = "private"
        with self.assertRaisesRegex(ValueError, "Draft 2020-12"):
            summary.render_reference_summary(invalid, self.schema, "my_agent", REFERENCE_ID)
        self.output.write_text(json.dumps(RESPONSE), encoding="utf-8")
        argv = ["summarize_runtime_diagnostics.py", "--receipt", str(self.output),
                "--devkit-root", str(self.devkit), "--agent-id", "my_agent",
                "--invocation-id", REFERENCE_ID, "--output", str(self.report)]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            summary.main()
        self.assertIn("发现 #2", self.report.read_text(encoding="utf-8"))

    def test_http_404_and_503_do_not_fall_back_or_write_receipt(self):
        for code in (404, 503):
            denied = urllib.error.HTTPError("https://example.invalid", code, "Unavailable", {}, None)
            with self.subTest(code=code), mock.patch.object(sys, "argv", self.argv), \
                    mock.patch.object(diagnostics.sys, "stdin") as stdin, \
                    mock.patch("builtins.input", return_value="developer"), \
                    mock.patch.object(diagnostics.getpass, "getpass", return_value="secret"), \
                    mock.patch.object(diagnostics, "request_json",
                                      side_effect=[{"token": "private-token"}, {}, denied]) as request:
                stdin.isatty.return_value = True
                with self.assertRaises(urllib.error.HTTPError):
                    diagnostics.main()
                self.assertEqual(request.call_count, 3)
                self.assertIn("/v6/references/", request.call_args.args[0])
                self.assertFalse(self.output.exists())

    def test_missing_v6_error_schema_fails_before_login(self):
        (self.devkit / "schemas" / "runtime-diagnostics-v6" / "error.schema.json").unlink()
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", self.argv), \
                mock.patch("builtins.input") as prompt, contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                diagnostics.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("no v6 error schema", stderr.getvalue())
        prompt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
