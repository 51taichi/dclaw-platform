# Workspace public text streaming

Signed workspace runtimes may pass `public_stream: true` with `agent.execute` in `agent_loop` mode. This declares that the Agent's textual output is intended for the customer. Existing runtimes keep buffered behavior. It is a generic host option, not an expert-name condition.

The host forwards assistant text snapshots from AgentScope before execution completes, preserving message identity. Tool-use/result blocks, reasoning and metadata are not forwarded. JSON-like envelopes remain buffered so runtime decoding can finish first. The final runtime result remains authoritative and updates the last public message identity, including failures. Cancellation tears down the Agent task and restores its message queue. Ordinary Agent streaming is unchanged.

This is not an arbitrary-content confidentiality classifier: a runtime must opt in only when its Agent prose is customer-facing. Do not opt in internal candidate generation or private business-envelope output. Already displayed text cannot be retracted from the customer's observation; structured envelopes and internal execution remain buffered.

LuYu 1.0.10 opts in from its transparent runtime. Business rules, model selection and AIGC declarations are unchanged. Streaming reduces waiting for the full answer after text generation begins; it does not eliminate provider reasoning or Skill-call latency.

Validation: 255 runner/sealed/console tests passed, including real AgentScope with a scripted streaming model, opt-in isolation, stable final identity, internal-block suppression and cancellation. 18 LuYu package tests and standard workspace validation passed. No paid provider call was used for these tests.
