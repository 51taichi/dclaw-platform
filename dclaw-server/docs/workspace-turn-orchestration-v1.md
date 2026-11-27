# Workspace Turn Orchestration v1

`workspace.turn.orchestrate/1` is DClaw's generic deterministic workspace entrypoint for an officially signed, installed, fully granted super-expert package. It is not a sealed-only runner and contains no Luyu stage or Skill logic.

## Declaration and authorization

The package Manifest and `agent/agent.json` must agree on `runtime.py:create_runtime`, contract version `1`, and the complete host dependency set: `agent.execute`, `session.context`, `runtime.trace`, `runtime.complete`, and `runtime.fail`. Installation grants the exact immutable capability set declared by the current signed release; partial grants and administrator-edited capability sets are rejected.

Unsigned, tampered, inactive, incompatible, ungranted, wrong-tenant, or wrong-release workspaces fail before the entrypoint runs. An ordinary Agent with no orchestration declaration remains on the standard Runner path.

## Runtime contract

The runtime factory returns an object with `async handle(request, host) -> None`. The request contains server-owned release, installation, session, user, channel, normalized input, history, granted capabilities, diagnostics authorization, and copy-on-write state paths. Caller-supplied stages, routes, Skills, or authorization claims are not accepted.

Host calls are a closed set:

- `agent.execute`: returns an internal model candidate only; it cannot become a customer reply.
- `session.context`: returns server-owned context for the current session.
- `runtime.trace`: records structured runtime diagnostics.
- `runtime.complete`: accepts the single render-bound customer result and atomically commits state.
- `runtime.fail`: discards the transaction and returns a controlled failure.

Declared business capabilities are routed through the same host only after exact package and tenant authorization.

## Completion and failure

The runtime must call exactly one of `runtime.complete` or `runtime.fail`. Missing completion, repeated completion, an exception, timeout, unauthorized host call, invalid entrypoint, or invalid render-bound result fails closed. DClaw never falls back to direct model output and never commits the workspace transaction on failure.

Standard Console, Channel, OpenAPI, SSE, session, workspace, tool, knowledge, and billing behavior remains owned by the existing Runner. Orchestration changes who deterministically prepares and completes a business turn, not those public entry paths.

## Compatibility

Contract v1 requires exact versions and rejects unknown extensions at trust boundaries. Additive internal implementation changes are allowed when request, host, completion, trace, authorization, and failure semantics remain compatible. A breaking interface requires a new contract version.

