import asyncio
import importlib.util
from pathlib import Path
import unittest


class Request:
    invocation_id = "invocation-test"
    normalized_input = {"messages": [{"role": "user", "content": "hello"}]}


class Host:
    def __init__(self):
        self.calls = []

    async def call(self, name, payload):
        self.calls.append((name, payload))
        if name == "session.context":
            return {"session_id": "session-test"}
        if name == "agent.execute":
            return {"text": "hello"}
        return {"ok": True}


class RuntimeTest(unittest.TestCase):
    def test_runtime_completes_once(self):
        path = Path(__file__).parents[1] / "agent" / "runtime.py"
        spec = importlib.util.spec_from_file_location("agent_runtime", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        host = Host()
        asyncio.run(module.create_runtime().handle(Request(), host))
        self.assertEqual([name for name, _ in host.calls].count("runtime.complete"), 1)
        self.assertEqual([name for name, _ in host.calls].count("runtime.fail"), 0)


if __name__ == "__main__":
    unittest.main()
