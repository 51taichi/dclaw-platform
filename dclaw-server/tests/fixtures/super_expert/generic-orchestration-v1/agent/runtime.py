from pathlib import Path


class GenericRuntime:
    async def handle(self, request, host):
        context = await host.call("session.context", {})
        await host.call(
            "runtime.trace",
            {"event": "generic.prepared", "session_id": context["session_id"]},
        )
        candidate = await host.call(
            "agent.execute",
            {"messages": request.normalized_input["messages"]},
        )
        Path(request.transaction_root, "last-turn.txt").write_text(
            candidate["text"],
            encoding="utf-8",
        )
        await host.call(
            "runtime.complete",
            {
                "invocation_id": request.invocation_id,
                "message": {
                    "name": "assistant",
                    "role": "assistant",
                    "content": f"generic:{candidate['text']}",
                },
                "diagnostics": {"fixture": "generic-orchestration-v1"},
            },
        )


def create_runtime():
    return GenericRuntime()
