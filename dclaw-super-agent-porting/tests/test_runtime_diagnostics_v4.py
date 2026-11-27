import copy
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
SCHEMA_PATH = DEVKIT / "schemas" / "runtime-diagnostics-v4" / "by-reference-response.schema.json"
REFERENCE_ID = "a" * 32
RESPONSE = {
    "contract": summary.REFERENCE_CONTRACT_V4,
    "status": "found", "retention_days": 30,
    "task_id": "task-1", "invocation_id": REFERENCE_ID,
    "installation_id": "installation-1", "release_id": "release-1",
    "started_at": "2026-11-13T01:00:00Z", "ended_at": "2026-11-13T01:01:00Z",
    "runtime_outcome": "completed", "transaction_status": "committed",
    "first_failure": {"phase": "aigc_asset_localize", "category": "host_or_input", "attempt": 1},
    "first_failure_source": "agent_trace",
    "task_acceptance": "not_accepted", "task_evidence": "available",
    "tasks": [], "host_operations": [], "stages": [],
}


@unittest.skipUnless(SCHEMA_PATH.is_file(), "set DCLAW_DEVKIT_ROOT to verified DevKit 1.9.19+")
class DiagnosticsV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.directory.cleanup)
        self.devkit = Path(self.directory.name) / "devkit"
        schema_dir = self.devkit / "schemas" / "runtime-diagnostics-v4"
        schema_dir.mkdir(parents=True)
        for name in ("by-reference-request.schema.json", "by-reference-response.schema.json"):
            shutil.copyfile(SCHEMA_PATH.parent / name, schema_dir / name)
        catalog = json.loads((DEVKIT / "operation-catalog.json").read_text(encoding="utf-8"))
        (self.devkit / "operation-catalog.json").write_text(
            json.dumps({"developer_reference_diagnostics_v4":
                        catalog["developer_reference_diagnostics_v4"]}), encoding="utf-8")
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

    def test_completed_turn_uses_v4_and_keeps_task_table_boundary(self):
        calls, printed = self.run_main(RESPONSE)
        self.assertIn("/v4/references/" + REFERENCE_ID, calls[-1].args[0])
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8")), RESPONSE)
        report = self.report.read_text(encoding="utf-8")
        self.assertIn("`completed`", report)
        self.assertIn("`not_accepted`", report)
        self.assertIn("本次关联回合的本地任务表无新任务受理记录", report)
        self.assertIn("不能据此断言能力未调用", report)
        self.assertIn("turns=1", str(printed))
        self.assertNotIn("failures=1", str(printed))
        self.assertNotIn("private-token", str(printed) + report)

    def test_not_recorded_task_table_does_not_infer_no_task(self):
        response = {**RESPONSE, "task_acceptance": "not_recorded",
                    "task_evidence": "not_recorded"}
        report = summary.render_reference_summary(response, self.schema, "my_agent", REFERENCE_ID)
        self.assertIn("本地任务表不可读", report)
        self.assertNotIn("本次关联回合的本地任务表无新任务受理记录", report)

    def test_no_record_and_invalid_shape_fail_closed(self):
        no_record = {"contract": summary.REFERENCE_CONTRACT_V4,
                     "status": "no_record", "retention_days": 30}
        report = summary.render_reference_summary(no_record, self.schema, "my_agent", REFERENCE_ID)
        self.assertIn("不能推定从未失败、未调用或未创建任务", report)
        invalid = copy.deepcopy(RESPONSE)
        invalid["customer_text"] = "private"
        with self.assertRaisesRegex(ValueError, "unexpected fields|Draft 2020-12"):
            summary.render_reference_summary(invalid, self.schema, "my_agent", REFERENCE_ID)

    def test_v4_404_does_not_fallback(self):
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
        self.assertIn("/v4/references/", request.call_args.args[0])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
