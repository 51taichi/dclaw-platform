import copy
import json
import os
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_aigc_asset_localization import validate_case  # noqa: E402


class AigcAssetLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = json.loads(
            (ROOT / "tests" / "fixtures" / "aigc_asset_localization_case.json").read_text(encoding="utf-8")
        )

    def case(self):
        return copy.deepcopy(self.example)

    def test_partial_success_example(self):
        self.assertIsNone(validate_case(self.case()))

    def test_wrong_task_or_canvas_is_rejected(self):
        for field, value in (("material_task_id", "other-task"), ("canvas_id", "other-canvas")):
            with self.subTest(field=field):
                case = self.case()
                case["snapshot_response"][field] = value
                with self.assertRaises(ValueError):
                    validate_case(case)

    def test_failed_job_asset_is_rejected(self):
        case = self.case()
        case["list_response"]["assets"][0]["job_id"] = "job-pending"
        with self.assertRaisesRegex(ValueError, "successful job"):
            validate_case(case)

    def test_unknown_asset_and_duplicate_order_are_rejected(self):
        case = self.case()
        case["localize_request"]["assets"][0]["asset_id"] = "other-asset"
        with self.assertRaisesRegex(ValueError, "trusted list"):
            validate_case(case)
        case = self.case()
        case["localize_request"]["assets"][0]["order"] = 0
        with self.assertRaisesRegex(ValueError, "duplicate asset order"):
            validate_case(case)
        case = self.case()
        case["localize_request"]["assets"][0]["order"] = -1
        with self.assertRaisesRegex(ValueError, "invalid asset order"):
            validate_case(case)

    def test_destination_rule_is_rejected(self):
        case = self.case()
        case["localize_request"]["assets"][0]["destination"] = "task_root"
        with self.assertRaisesRegex(ValueError, "destination"):
            validate_case(case)
        case = self.case()
        item = case["localize_request"]["assets"][0]
        item["usage"] = "final_output"
        with self.assertRaisesRegex(ValueError, "destination"):
            validate_case(case)

    def test_unconfirmed_or_mismatched_receipt_is_rejected(self):
        case = self.case()
        case["localize_response"]["idempotency_key"] = "new-key"
        with self.assertRaisesRegex(ValueError, "key mismatch"):
            validate_case(case)
        case = self.case()
        case["read_response"]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "not complete"):
            validate_case(case)
        case = self.case()
        case["read_response"]["task_id"] = "other-task"
        with self.assertRaisesRegex(ValueError, "task mismatch"):
            validate_case(case)

    def test_schema_legal_empty_success_fields_are_accepted(self):
        case = self.case()
        for name in ("localize_response", "read_response"):
            case[name]["idempotency_key"] = None
        case["read_response"]["artifact_ids"] = []
        case["read_response"]["result_sha256"] = None
        self.assertIsNone(validate_case(case))

    def test_nonempty_receipt_identity_still_must_match(self):
        case = self.case()
        case["localize_response"]["capability_id"] = "other.capability/1"
        with self.assertRaisesRegex(ValueError, "capability mismatch"):
            validate_case(case)
        case = self.case()
        case["read_response"]["idempotency_key"] = "other-key"
        with self.assertRaisesRegex(ValueError, "finished key mismatch"):
            validate_case(case)

    def test_unavailable_assets_or_device_failure_is_rejected(self):
        case = self.case()
        case["list_response"] = {"contract": "aigc.task.assets.list/1", "status": "unavailable"}
        with self.assertRaisesRegex(ValueError, "asset list not found"):
            validate_case(case)
        case = self.case()
        case["read_response"]["status"] = "failed"
        case["read_response"]["error_code"] = "LOCAL_GATEWAY.DEVICE_NOT_READY"
        with self.assertRaisesRegex(ValueError, "not complete"):
            validate_case(case)

    @unittest.skipUnless(os.environ.get("DCLAW_DEVKIT_ROOT"), "set DCLAW_DEVKIT_ROOT to a verified DevKit")
    def test_official_schema_accepts_example_and_rejects_url(self):
        root = Path(os.environ["DCLAW_DEVKIT_ROOT"])
        self.assertIsNone(validate_case(self.case(), root))
        case = self.case()
        case["localize_response"]["idempotency_key"] = None
        case["read_response"].update(idempotency_key=None, artifact_ids=[], result_sha256=None)
        self.assertIsNone(validate_case(case, root))
        case = self.case()
        case["list_response"]["assets"][0]["source_url"] = "https://example.invalid/asset"
        with self.assertRaisesRegex(ValueError, "formal schema mismatch"):
            validate_case(case, root)


if __name__ == "__main__":
    unittest.main()
