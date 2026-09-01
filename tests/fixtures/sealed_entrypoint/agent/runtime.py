from __future__ import annotations

from pathlib import Path


class FixtureRuntime:
    def handshake(self):
        return {
            "adapter": "sealed_entrypoint",
            "contract_version": "1",
        }

    def handle(self, request, host):
        resource = Path("/release/agent/resource.txt")
        if not resource.exists():
            resource = Path(__file__).with_name("resource.txt")
        release_value = resource.read_text(encoding="utf-8").strip()

        session_root = Path("/session")
        if not session_root.exists():
            session_root = Path.cwd()
        counter_path = session_root / "counter.txt"
        turn = int(counter_path.read_text() if counter_path.exists() else "0") + 1
        counter_path.write_text(str(turn), encoding="utf-8")

        result = host.call(
            "agent.execute",
            {
                "messages": [
                    {"role": "user", "content": request["input"]["content"]},
                ],
                "instruction": f"resource={release_value}",
            },
        )
        return {
            "reply": f"{result['reply']} / turn {turn}",
            "artifacts": [],
            "diagnostics": {
                "release_resource": release_value,
                "turn": turn,
            },
        }


def create_runtime():
    return FixtureRuntime()
