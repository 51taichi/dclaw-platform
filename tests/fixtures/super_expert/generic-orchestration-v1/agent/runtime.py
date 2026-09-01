from pathlib import Path


class GenericRuntime:
    async def handle(self, request, host):
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
            },
        )


def create_runtime():
    return GenericRuntime()
