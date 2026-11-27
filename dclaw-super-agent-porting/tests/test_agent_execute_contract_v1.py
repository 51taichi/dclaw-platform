import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker


DEVKIT = Path(os.environ.get("DCLAW_DEVKIT_ROOT", ""))
SCHEMAS = DEVKIT / "schemas"
CARD_EXAMPLE = DEVKIT / "examples" / "interaction-host-v1" / "single-select-success.json"


@unittest.skipUnless(
    (SCHEMAS / "agent-execute-v1" / "request.schema.json").is_file()
    and (SCHEMAS / "runtime-fail-v1" / "request.schema.json").is_file()
    and CARD_EXAMPLE.is_file(),
    "set DCLAW_DEVKIT_ROOT to verified DevKit 1.9.31+",
)
class AgentExecuteContractV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def validator(contract, kind):
            schema = json.loads(
                (SCHEMAS / contract / f"{kind}.schema.json").read_text(encoding="utf-8")
            )
            Draft202012Validator.check_schema(schema)
            return Draft202012Validator(schema, format_checker=FormatChecker())

        cls.execute_request = validator("agent-execute-v1", "request")
        cls.execute_response = validator("agent-execute-v1", "response")
        cls.fail_request = validator("runtime-fail-v1", "request")
        cls.fail_response = validator("runtime-fail-v1", "response")
        cls.card_response = validator("interaction-card-create-v1", "response")
        cls.card_example = json.loads(CARD_EXAMPLE.read_text(encoding="utf-8"))
        cls.messages = [{"role": "user", "content": "test"}]

    def test_three_legal_execute_modes(self):
        requests = [
            {"messages": self.messages},
            {"messages": self.messages, "recover_empty_reply": True},
            {"messages": self.messages, "response_format": "json_object"},
            {"messages": self.messages, "response_format": "json_object",
             "recover_empty_reply": True},
            {
                "messages": self.messages,
                "execution_mode": "agent_loop",
                "instruction": "Use the authorized tool for this task.",
                "require_interaction": False,
                "public_stream": False,
            },
        ]
        for request in requests:
            with self.subTest(request=request):
                self.execute_request.validate(request)

    def test_illegal_mode_mixes_and_missing_instruction(self):
        requests = [
            {"messages": self.messages, "public_stream": False},
            {"messages": self.messages, "response_format": "json_object", "public_stream": False},
            {"messages": self.messages, "instruction": "Use a tool"},
            {"messages": self.messages, "require_interaction": False},
            {
                "messages": self.messages,
                "execution_mode": "agent_loop",
                "instruction": "Use a tool",
                "response_format": "json_object",
            },
            {"messages": self.messages, "execution_mode": "agent_loop"},
            {"messages": self.messages, "max_tokens": 100},
        ]
        for request in requests:
            with self.subTest(request=request):
                self.assertTrue(list(self.execute_request.iter_errors(request)))

    def test_execute_response_shape_does_not_require_visible_text(self):
        self.execute_response.validate({"message": {}, "text": ""})
        self.assertTrue(list(self.execute_response.iter_errors({"message": {}})))

    def test_runtime_fail_legacy_and_stable_codes(self):
        for code in ("runtime_failed", "invalid_completion", "HOST.AGENT_EXECUTE_FAILED"):
            with self.subTest(code=code):
                self.fail_request.validate({"invocation_id": "inv-1", "error_code": code})
        for code in ("host.agent_execute_failed", "HOST..FAILED", "A" * 65):
            with self.subTest(code=code):
                self.assertTrue(list(self.fail_request.iter_errors(
                    {"invocation_id": "inv-1", "error_code": code}
                )))
        self.fail_response.validate({"accepted": True})
        self.assertTrue(list(self.fail_response.iter_errors({"accepted": False})))

    def test_created_receipt_matches_persisted_card(self):
        example = self.card_example
        request = example["create_call"]["arguments"]["request"]
        result = example["create_result"]
        self.card_response.validate(result)

        spec = importlib.util.spec_from_file_location(
            "official_interaction_card_api_demo", DEVKIT / "interaction_card_api_demo.py"
        )
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(DEVKIT.parent))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)

        self.assertEqual(
            module.verify_created(result, request), result["interaction"]["interaction_id"]
        )
        mismatched = copy.deepcopy(result)
        mismatched["receipt"]["event_id"] = "different-event"
        with self.assertRaises(module.CardContractError):
            module.verify_created(mismatched, request)


if __name__ == "__main__":
    unittest.main()
