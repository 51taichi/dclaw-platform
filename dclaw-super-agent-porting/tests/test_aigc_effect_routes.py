import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_aigc_effect_routes.py"


ADAPTER = '''import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--runtime", type=Path, required=True)
parser.add_argument("--entry", required=True)
parser.add_argument("--case", required=True)
args = parser.parse_args()
spec = importlib.util.spec_from_file_location("current_runtime", args.runtime)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if args.entry != "bad_no_runtime":
    module.route_under_test()
sha = hashlib.sha256(args.runtime.read_bytes()).hexdigest()
catalog = {"capability": "aigc_workflow_catalog", "outcome": "completed"}
create = {"capability": "aigc_workflow_create", "outcome": "completed"}
result = {
    "runtime_sha256": sha,
    "invocations": 2 if args.case == "replay" else 1,
    "calls": [catalog, create],
    "state": {"created": True, "attempt": "verified", "key_preserved": True,
              "revision_preserved": True, "blueprint_preserved": True},
    "evidence": {"create": "completed", "binding": "found", "snapshot": "matched"},
    "terminal": {"status": "created", "code": "CREATED"},
    "model_text_kind": "none" if args.case == "created_no_text" else "plain",
}
if args.case == "catalog_only":
    result.update(calls=[catalog], model_text_kind="receipt_like",
                  evidence={"create": "not_observed", "binding": "not_found",
                            "snapshot": "not_read"},
                  terminal={"status": "blocked", "code": "CREATE_NOT_OBSERVED"})
    result["state"].update(created=False, attempt="planned")
if args.case == "unknown_result":
    result.update(calls=[catalog, {"capability": "aigc_workflow_create",
                                   "outcome": "started_unknown"}],
                  evidence={"create": "started_unknown", "binding": "unavailable",
                            "snapshot": "not_read"},
                  terminal={"status": "blocked", "code": "RESULT_UNKNOWN"})
    result["state"].update(created=False, attempt="unknown")
if args.entry == "bad_attempt" and args.case == "catalog_only":
    result["state"]["attempt"] = "unknown"
if args.entry == "bad_text" and args.case == "created_no_text":
    result["state"].update(created=False, attempt="unknown")
if args.entry == "bad_replay" and args.case == "unknown_result":
    result["calls"].append(create)
if args.entry == "bad_source":
    result["runtime_sha256"] = "0" * 64
if args.entry == "bad_no_runtime":
    result["runtime_sha256"] = sha
print(json.dumps(result))
'''


class AigcEffectRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = self.root / "runtime.py"
        self.runtime.write_text("def route_under_test():\n    return True\n", encoding="utf-8")
        self.adapter = self.root / "adapter.py"
        self.adapter.write_text(ADAPTER, encoding="utf-8")
        self.routes = self.root / "routes.json"
        self.runtime_hash = hashlib.sha256(self.runtime.read_bytes()).hexdigest()

    def run_check(self, entry="good", *, cases=None, runtime_hash=None):
        self.routes.write_text(json.dumps({
            "schema_version": "aigc-effect-routes/1",
            "runtime_sha256": runtime_hash or self.runtime_hash,
            "entries": [{"entry_id": entry, "cases": cases or [
                "success", "catalog_only", "created_no_text", "unknown_result", "replay"]}],
        }), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--runtime", str(self.runtime),
             "--routes", str(self.routes), "--adapter", str(self.adapter)],
            text=True, capture_output=True, check=False,
        )
        return result.returncode, json.loads(result.stdout)

    def test_all_fixed_scenarios_pass(self):
        code, report = self.run_check()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(report["results"]), 5)

    def test_pre_call_attempt_lock_fails(self):
        code, report = self.run_check("bad_attempt")
        self.assertEqual(code, 1)
        self.assertIn("AIGC.ATTEMPT_LOCKED", [item["code"] for item in report["results"]])

    def test_model_text_cannot_replace_created_receipt(self):
        code, report = self.run_check("bad_text")
        self.assertEqual(code, 1)
        self.assertIn("AIGC.TEXT_AS_RECEIPT", [item["code"] for item in report["results"]])

    def test_unknown_result_cannot_replay_create(self):
        code, report = self.run_check("bad_replay")
        self.assertEqual(code, 1)
        self.assertIn("AIGC.UNKNOWN_REPLAY", [item["code"] for item in report["results"]])

    def test_source_and_coverage_fail_closed(self):
        code, report = self.run_check("good", cases=["success"])
        self.assertEqual(code, 1)
        self.assertEqual(report["code"], "AIGC.ROUTE_MISSING")
        code, report = self.run_check("good", runtime_hash="0" * 64)
        self.assertEqual(code, 1)
        self.assertEqual(report["code"], "AIGC.SOURCE_MISMATCH")
        code, report = self.run_check("bad_source")
        self.assertEqual(code, 1)
        self.assertIn("AIGC.SOURCE_MISMATCH", [item["code"] for item in report["results"]])

    def test_adapter_must_call_runtime_function(self):
        code, report = self.run_check("bad_no_runtime")
        self.assertEqual(code, 1)
        self.assertIn("AIGC.OBSERVATION_UNVERIFIED", [
            item["code"] for item in report["results"]])


if __name__ == "__main__":
    unittest.main()
