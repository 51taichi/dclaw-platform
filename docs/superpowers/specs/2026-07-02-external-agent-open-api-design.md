# External Agent Open API Design

## Goal

External business systems should be able to call selected QwenPaw experts and expert teams through a stable Open API. The current admin-created expert is the single-agent asset. The current expert team is the multi-agent orchestration asset. This design adds publishing, API-key authentication, quota, and audit layers without replacing the existing agent creation and expert-team management flows.

## Current Product Model

- Expert: an existing QwenPaw agent identified by `agent_id`. It owns workspace files, model configuration, skills, tools, memory, and chat execution.
- Expert team: an existing orchestration template identified by `team_id`. It stores `leader_agent_id`, member agents, and workflow stages. It is not a new agent; it is a callable composition of agents.
- Chat/task persistence: user-facing calls already persist through `chats`, `messages`, and `session_states`, with ownership guarded by the authenticated server-side user.
- Console chat runtime: `/api/user/console/chat` already creates or reuses chats, binds calls to the authenticated user, applies task concurrency limits, streams results, and supports reconnect and stop.

## Scope

- Add an Open API layer for external application calls.
- Support publishing either one expert or one expert team as the callable target.
- Add API-key authentication and authorization for external applications.
- Preserve current admin expert creation, expert-team creation, chat persistence, and runner behavior.
- Keep the first customer-service use case text-first. File upload, tool approval callbacks, browser control, shell, and other high-risk tool exposure are out of scope for the first slice.

## Non-Goals

- Do not create a second "customer service agent" entity.
- Do not let external callers choose arbitrary `agent_id`, `team_id`, `user_id`, or admin routes.
- Do not expose web-console login tokens to external systems.
- Do not bypass existing chat ownership and session persistence.

## Recommended Architecture

Introduce a new Open API surface under `/api/open/v1`.

The Open API router authenticates an external application key, resolves the key to a published target, and then runs the existing internal agent/team flow under a fixed owner user. The external caller can provide external customer identity and session IDs, but those values are stored as metadata rather than trusted QwenPaw user identity.

```text
External app
  -> /api/open/v1/targets/{public_id}/messages
  -> Open API key verification
  -> publication lookup: target_type + target_id + owner_user_id
  -> server-selected agent/team context
  -> existing console chat and expert-team orchestration
  -> stream or JSON response
  -> invocation audit and quota accounting
```

## Publishing Model

Use one publication abstraction for experts and expert teams:

- `target_type`: `agent` or `expert_team`
- `target_id`: `agent_id` for an expert, `team_id` for an expert team
- `public_id`: stable external identifier used in URLs
- `owner_user_id`: the QwenPaw user who owns the published target and all generated chat rows
- `name`, `description`, `status`, `created_at`, `updated_at`
- `default_channel`: `open`
- `allowed_scopes`: for example `messages:create`, `messages:read`, `runs:stop`

Admin pages should show a "Publish to external apps" action on both an expert detail page and an expert-team detail page. The existing creation pages remain the source of truth for configuring expert behavior.

## External App And Key Model

Add external application records:

- `external_apps`: app name, owner user, status, optional IP allowlist, quota policy, timestamps
- `external_api_keys`: app ID, publication ID, hashed key, visible prefix and suffix, scopes, expiration, revoked state, last-used metadata
- `open_api_invocations`: app ID, publication ID, target type, target ID, chat ID, external session ID, external user ID, status code, latency, token summary when available, and error summary

API keys are generated once and shown once. The database stores only a hash plus non-sensitive display fields. Key rotation creates a new key before revoking the old one.

## Authentication And Authorization

Open API authentication must be separate from the current web-console Bearer token.

Accepted request format:

```http
Authorization: Bearer qp_live_...
```

Add an explicit `/api/open/` branch to `AuthMiddleware` for Open API requests. This branch verifies the external API key and must not use the existing public-route skip path that assigns an admin fallback user. It checks app status, key status, expiration, IP allowlist, and scopes. On success it sets request state similar to:

- `request.state.open_app_id`
- `request.state.open_publication_id`
- `request.state.user_id = owner_user_id`
- `request.state.role = "open_app"`
- `request.state.agent_id` only after publication resolution

Open API callers must not be allowed to override `X-Agent-Id`, query `agent_id`, `user_id`, or target IDs in the body. The resolved publication decides the runnable target.

Authorization rules:

- A key can call only its bound publication.
- A key can only use scopes granted to it.
- Disabled publications fail with 403.
- Missing or invalid keys fail with 401.
- Unknown publications return 404 without exposing whether a private expert exists.
- Rate-limit failures return 429.

## API Shape

First-slice endpoints:

- `POST /api/open/v1/targets/{public_id}/messages`
- `GET /api/open/v1/targets/{public_id}/sessions/{external_session_id}`
- `POST /api/open/v1/targets/{public_id}/sessions/{external_session_id}/stop`

Message request:

```json
{
  "external_user_id": "customer-123",
  "external_session_id": "ticket-456",
  "message": "How do I reset my password?",
  "stream": true,
  "metadata": {
    "source": "customer-service-widget"
  }
}
```

For an expert publication, the router runs the selected `agent_id` through the existing console chat path.

For an expert-team publication, the router creates or reuses a root chat, attaches the expert-team run to that chat, and streams team progress plus final output using the existing expert-team orchestration.

Response headers should include internal IDs for support and debugging:

- `X-QwenPaw-Chat-Id`
- `X-QwenPaw-Session-Id`
- `X-QwenPaw-Open-Invocation-Id`

## Session Mapping

External session IDs are not QwenPaw ownership IDs. The Open API layer should normalize them into a server-owned session key:

```text
open:{app_id}:{public_id}:{external_session_id}
```

Chat rows use:

- `user_id = owner_user_id`
- `agent_id = resolved agent_id` for expert calls
- `agent_id = leader_agent_id` for expert-team root chats
- `channel = open:{app_id}`
- `meta.external_user_id`
- `meta.external_session_id`
- `meta.publication_id`
- `meta.target_type`
- `meta.target_id`

This preserves existing ownership checks while keeping external customer identity queryable for audit and support.

## Customer-Service Agent Behavior

A customer-service expert is just a normal expert configured with:

- service identity and answer style in its system prompt
- enterprise knowledge sources through existing knowledge and mindspace capabilities
- limited tools suitable for customer service
- handoff guidance for low-confidence answers or policy-sensitive requests

The first-slice output contract should support:

- answer text
- confidence or handoff signal
- optional citations or source hints
- optional structured action suggestion

The user-visible text can stay natural-language first. Structured fields can be added to the final SSE event or JSON response so external apps can route unresolved cases to humans.

## Error Handling

- Invalid key: 401
- Valid key without scope: 403
- Disabled app or publication: 403
- Unknown public target: 404
- Target agent disabled: 403
- Target expert team disabled: 404, matching existing user-facing hiding behavior
- Too many running tasks: 429
- Runtime failure: 500 with a stable error code and a short safe message

Every failed call should write an invocation record unless authentication fails before an app can be identified.

## Security Requirements

- Store only hashed API keys.
- Never log full API keys or full Authorization headers.
- Ignore caller-provided internal IDs.
- Keep admin configuration endpoints under existing admin auth.
- Keep Open API keys unable to call `/api/user` and `/api/admin`.
- Apply per-key, per-app, per-publication, and existing global task concurrency limits.
- Default high-risk tools to disabled for externally published targets unless explicitly allowed later.
- Return 404 on ownership-sensitive mismatches when the caller should not learn whether another resource exists.

## Admin UI

Add an admin section for "External Apps" or "Open API":

- list published targets
- publish or unpublish an expert
- publish or unpublish an expert team
- create external app
- bind app keys to a published target
- rotate or revoke keys
- show last-used time, failure counts, and recent invocations

The expert and expert-team pages can link into this section instead of duplicating all key-management controls.

## Tests

Backend tests:

- API keys are hashed and full keys are returned only at creation time.
- Invalid, expired, revoked, disabled, and scope-missing keys are rejected.
- A key bound to one publication cannot call another publication.
- Caller-provided `agent_id`, `team_id`, and `user_id` are ignored.
- Expert publication creates chat rows under the owner user and `open:{app_id}` channel.
- Expert-team publication creates a root chat and attached expert-team run under the owner user.
- Session lookups require the same key/publication.
- Rate-limit failures return 429.
- Invocation records are written for success and runtime failures.

Frontend tests:

- Admin can publish an expert and expert team.
- Admin can create, rotate, revoke, and copy-once keys.
- The UI never displays a stored full key after creation.
- Invocation table shows target, app, status, time, and error summary.

## Rollout Plan

1. Add database schema and repositories for publications, external apps, API keys, and invocations.
2. Add Open API key dependency and route tests.
3. Add expert publication message endpoint.
4. Add expert-team publication message endpoint.
5. Add admin Open API management UI.
6. Add production defaults for rate limits, logging redaction, and disabled high-risk tool exposure.

## Acceptance Criteria

- An admin-created expert can be published and called by an external app key.
- An admin-created expert team can be published and called by an external app key.
- External callers cannot call unpublished targets or switch targets by passing internal IDs.
- Calls are owned by the publication owner and visible in existing chat/audit flows.
- Each external call has an invocation record with enough data for support and billing analysis.
- Revoking a key immediately prevents further calls.
