import json
import os
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


DEVKIT = Path(os.environ.get("DCLAW_DEVKIT_ROOT", ""))
SCHEMA = DEVKIT / "schemas" / "agent-execute-v2" / "request.schema.json"


@unittest.skipUnless(SCHEMA.is_file(), "set DCLAW_DEVKIT_ROOT to a verified v2 DevKit")
class AgentExecuteContractV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)
        cls.messages = [{"role": "user", "content": "test"}]

    def test_default_loop_and_explicit_candidate(self):
        for request in (
            {"messages": self.messages},
            {"messages": self.messages, "execution_mode": "agent_loop"},
            {"messages": self.messages, "execution_mode": "candidate"},
            {
                "messages": self.messages,
                "execution_mode": "candidate",
                "response_format": "json_object",
            },
        ):
            with self.subTest(request=request):
                self.validator.validate(request)

    def test_json_candidate_must_be_explicit(self):
        for request in (
            {"messages": self.messages, "response_format": "json_object"},
            {"messages": self.messages, "execution_mode": "agent_loop",
             "response_format": "json_object"},
            {"messages": self.messages, "execution_mode": "candidate",
             "instruction": "use a tool"},
        ):
            with self.subTest(request=request):
                self.assertTrue(list(self.validator.iter_errors(request)))


if __name__ == "__main__":
    unittest.main()
