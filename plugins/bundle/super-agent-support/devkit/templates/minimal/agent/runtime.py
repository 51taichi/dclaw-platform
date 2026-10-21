class ExampleRuntime:
    async def handle(self, request, host):
        context = await host.call("session.context", {})
        await host.call(
            "runtime.trace",
            {
                "event": "example.turn.started",
                "session_id": context["session_id"],
            },
        )
        candidate = await host.call(
            "agent.execute",
            {"messages": request.normalized_input["messages"]},
        )
        await host.call(
            "runtime.complete",
            {
                "invocation_id": request.invocation_id,
                "message": {
                    "name": "assistant",
                    "role": "assistant",
                    "content": candidate["text"],
                },
                "diagnostics": {"runtime": "example-business-agent"},
            },
        )


def create_runtime():
    return ExampleRuntime()
