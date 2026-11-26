class AgentRuntime:
    async def handle(self, request, host):
        context = await host.call("session.context", {})
        await host.call(
            "runtime.trace",
            {"event": "agent.turn.started", "session_id": context["session_id"]},
        )
        reply = await host.call(
            "agent.execute",
            {
                "messages": request.normalized_input["messages"],
            },
        )
        await host.call(
            "runtime.complete",
            {
                "invocation_id": request.invocation_id,
                "message": {
                    "name": "assistant",
                    "role": "assistant",
                    "content": reply["text"],
                },
                "diagnostics": {"runtime": "{{AGENT_ID}}"},
            },
        )


def create_runtime():
    return AgentRuntime()
