class AgentRuntime:
    async def handle(self, request, host):
        context = await host.call("session.context", {})
        await host.call(
            "runtime.trace",
            {"event": "agent.turn.started", "session_id": context["session_id"]},
        )
        candidate = await host.call(
            "agent.execute",
            {
                "messages": request.normalized_input["messages"],
                "execution_mode": "agent_loop",
            },
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
                "diagnostics": {"runtime": "{{AGENT_ID}}"},
            },
        )


def create_runtime():
    return AgentRuntime()
