# LuYu latency and empty-reply safeguards

The Agent's per-file Skill reads added model round trips. Agent-only S0–S15 packets include the current node, complete owner/support instructions, business rules and required method definitions with source hashes. They do not mark stages complete, remove gates or replace AIGC tools. Conditional references stay on demand; the original read path remains the fallback.

An isolated same-input (`开始`) server comparison observed five model calls / 7.89 seconds before and two calls / 4.96 seconds after. This single sample is not a whole-flow performance guarantee. Neither probe touched an existing conversation or submitted AIGC work.

The existing public-stream and background-title changes are included so an opted-in workspace can emit public text without waiting for the final workspace result. Ordinary Agent behavior retains its existing path.

`agent.execute` now records content-free empty-reply shapes. Explicit `recover_empty_reply: true` allows one text-only completion using the existing in-memory context, with `tools=None` and `tool_choice=none`; it never reruns the Agent or repeats AIGC effects. A pending tool-use result is not recovered as a completed turn. Failed recovery remains a failure. This is a safeguard, not proof of the historical provider failure's root cause: historical raw response data was not enabled.

Agent 1.0.14 also accepts native message text when the convenience `text` field is absent, and handles named pure greetings without a model call. Mixed business messages and media still use the full Agent path.

Rollout must preserve the active model, grants and previous release. Do not restart during active user turns. Check source/package hashes, native Skill loading, regression tests, server readiness and actual stream events before reporting live completion.

Live verification found an inherited provider `response_format=json_object`, so text arrived inside a JSON envelope and the public stream correctly withheld its raw fragments. The opt-in public-text call now wraps the request with an explicit `NOT_GIVEN` override for that inherited default only. Provider settings remain untouched; explicit per-call structured formats and tools are preserved, and the original model is restored on completion/cancellation. Non-JSON defaults keep their original model path.
