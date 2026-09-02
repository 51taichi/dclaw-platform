# OpenAPI Isolated Attempt Design

## Goal

Add an explicit, opt-in `isolated_attempt` execution mode to **Agent-target OpenAPI message requests only**. Each isolated request starts without prior runner session state or Agent long-term memory while retaining the published Agent's configuration, prompt identity, knowledge base, skills, configured built-in tools, MCP tools, and normal artifact delivery behavior.

The default remains `persistent`. Omitted mode and explicit `persistent` mode are identical to current behavior. Console traffic, non-OpenAPI Agent calls, persistent Agent OpenAPI calls, expert-team OpenAPI calls, scheduled tasks, background tasks, and every other entry point retain their current behavior and do not enter the new isolation branch.

## Verified Current Data Flow

`POST /api/open/v1/targets/{public_id}/messages` validates `OpenMessageRequest`, creates the billing invocation, and calls `prepare_open_agent_chat` or `prepare_open_expert_team_chat`. The preparation layer builds a stable session ID from app, publication, external user, and external session IDs; resolves the server-owned Agent `Workspace`; creates the chat; and emits a native ConsoleChannel payload containing trusted target, identity, and knowledge-base metadata.

ConsoleChannel converts that payload to an `AgentRequest` and invokes the shared workspace's `AgentRunner`. The runner creates a fresh `QwenPawAgent` for the turn but currently always:

- passes the workspace's shared `MemoryManager` into the Agent;
- uses the workspace's `ContextManager` to create the turn context;
- loads persisted runner session state before execution;
- saves runner session state in `finally`;
- creates/touches a chat record.

`QwenPawAgent` reads identity prompt files and skills from the configured Agent workspace root. Its writable runtime directory is normally `<agent-workspace>/sessions_data/<root_session_id>`. Knowledge tools use the server-derived `knowledge_base_id`. Built-in and plugin/MCP tools are registered from the Agent configuration.

File delivery has two existing paths:

- `send_file_to_user` resolves a file in the active workspace and returns an image/audio/video/file block. ConsoleChannel converts the file URL back to a local artifact reference in the SSE response.
- ConsoleChannel snapshots the active session workspace before and after execution. New or modified user-task files cause an automatic `qwenpaw-artifact-card-trigger` SSE message.

Therefore isolated attempts do not require a new artifact publication mechanism. Their artifacts must remain in the unique attempt workspace long enough for the caller to consume the returned SSE file blocks or artifact card.

Current OpenAPI preparation and runner code both call `get_or_create_chat`, and the runner later calls `touch_chat`. OpenAPI chats are excluded from the cross-Agent recent-chat repository by both `session_id LIKE 'open:%'` and `channel LIKE 'open:%'`, so they do not appear in the normal recent-task list. They are nevertheless durable chat rows and can be returned by the per-Agent `/chats` API when it is queried without a channel filter. Creating one random chat row per isolated attempt would therefore create avoidable internal history records and is not part of the isolation design below.

## Protocol

Extend `OpenMessageRequest` with:

```json
{
  "execution_mode": "isolated_attempt"
}
```

Allowed values are `persistent` and `isolated_attempt`; the field defaults to `persistent`. Caller metadata cannot override the resolved mode or execution identifiers. `isolated_attempt` is valid only when the resolved publication target type is `agent`. An expert-team publication that explicitly requests it receives a clear 400 response before runtime preparation.

For an omitted mode or explicit `persistent`, session ID construction, native payload shape, runner decisions, workspace selection, memory behavior, tools, chat persistence, and all downstream behavior remain compatible with the current implementation. The preparation layer must not add isolation metadata to persistent payloads.

For `isolated_attempt`, the server derives a unique execution session ID by adding a fixed-length SHA-256 digest of the server-generated billing invocation ID to the existing namespaced OpenAPI session ID. Different invocations therefore receive different attempt workspaces, while an idempotent replay of the same invocation resolves to the same active execution. The external session ID remains unchanged in invocation records and trusted metadata, preserving billing, auditing, and caller correlation.

### Cross-service attempt contract

DClaw does not infer retry ordinals and does not decide whether a call is the first, second, or third candidate. For one AIBot customer request, the caller is responsible for sending **every** main-Agent candidate call, including the first call, with `execution_mode: "isolated_attempt"`. The caller must reuse the same frozen business input for all candidates. Each request independently receives a different server-generated execution session ID.

Using `persistent` for the first candidate and `isolated_attempt` only for later candidates is invalid orchestration because the candidates would start with different memory conditions. DClaw guarantees per-call isolation when explicitly requested; it does not coordinate or group the three calls. The caller-owned `external_session_id` and existing invocation audit fields remain the cross-service correlation mechanism. DClaw stores the unchanged external value and does not rewrite it to the internal execution session ID.

## Runtime Isolation

For an Agent OpenAPI request explicitly using `isolated_attempt`, the OpenAPI preparation layer places a trusted execution policy in the native payload metadata. The runner accepts the policy only when all of the following are true: the channel has the server-generated `open:` prefix, the trusted target type is `agent`, and the server-created top-level policy is exactly `isolated_attempt`. Untrusted `payload.metadata` remains nested and cannot enable it.

No generic runner flag is exposed to other callers. Non-OpenAPI Agent requests cannot opt in through `request_context`, channel metadata, or user metadata. In addition to the typed fields, the trusted policy carries a process-local object-identity capability that cannot be constructed by a JSON request. The capability is produced only by the Agent OpenAPI preparation function; the expert-team preparation function never produces it.

When the policy is `isolated_attempt`, the runner:

- creates the normal fresh per-turn Agent;
- passes `memory_manager=None`, removing memory prompts, memory tools, automatic memory retrieval, compaction-to-memory, and automatic memory writes;
- skips runner session-state preflight reads and `load_session_state`;
- skips `save_session_state` in all completion, failure, and cancellation paths;
- skips both OpenAPI preparation-time and runner-time chat creation and skips `touch_chat`;
- continues using the normal ContextManager to obtain a fresh in-memory turn context;
- uses the unique execution session ID as `root_session_id`, so existing per-session filesystem and browser-profile boundaries continue to select a unique attempt directory.

No shared `Workspace`, runner, memory-manager, or channel object is mutated. The policy is held in request-local data, so concurrent persistent and isolated Agent OpenAPI executions cannot overwrite each other's mode or workspace selection. Other entry points never create the trusted policy and therefore remain on the existing runner path.

The isolated run uses an ephemeral tracker key/chat identifier derived from the OpenAPI invocation rather than a durable chat row. This identifier is sufficient for TaskTracker attachment, cancellation, billing finalization, and the live SSE stream, but is not inserted into `chats` and has no session-state row. Durable audit remains in `open_api_invocations`, including app, publication, target, external user, external session, status, timing, and billing fields. Consequently isolated candidate outputs do not appear in ordinary console history or the per-Agent chat list and cannot become AIBot conversation history through DClaw chat APIs.

## Preserved Capabilities

This change does not filter or globally disable tools. The isolated Agent receives the same:

- Agent profile, model settings, identity prompt, and system files;
- skills loaded from the Agent root workspace;
- publication-bound knowledge base and knowledge tools;
- configured built-in tools;
- configured plugin and MCP tools;
- file-generation tools and existing SSE artifact delivery behavior.

The isolation contract does not claim to make arbitrary business tools side-effect-free. An explicitly configured tool may still call an external system. Tool-wide side-effect classification is outside this change and must not be silently introduced here.

## Artifact Lifecycle

Attempt workspaces are not deleted synchronously at request completion. A successful attempt's generated files remain addressable through the SSE media blocks and artifact card exactly as on the first persistent request.

This change will not add automatic failed-attempt cleanup until DClaw has a durable success/consumer-acknowledgement signal and a retention policy. Immediate cleanup in a stream finalizer could invalidate file references before AIBot downloads them, and terminal billing status alone does not prove the caller has consumed artifacts. Failed attempts are naturally separated and can be cleaned later by a retention job designed with explicit age and invocation-status rules.

## Explicitly Excluded Entry Points

Expert teams are outside this feature. Their omitted/default and explicit `persistent` requests remain unchanged. An expert-team OpenAPI request explicitly using `isolated_attempt` is rejected with HTTP 400 and does not prepare or start a run.

Console sessions, internal/ordinary Agent calls, scheduled tasks, background tasks, inter-Agent calls, channel traffic, mission execution, and workspace orchestration do not receive the trusted isolation policy and must never enter the new branch. This feature does not add isolation support to any of those paths.

Within an isolated Agent OpenAPI request, slash-style runner control commands and mission commands are treated as ordinary model input rather than entering command handlers that can access durable session or mission state. This does not change control-command or mission behavior for any existing persistent or non-OpenAPI entry point. Configured workspace orchestration and business tools otherwise remain available because they are part of the Agent's business capability; their external side effects are covered by the non-transactional tool boundary.

## Security Boundaries

- Default mode is `persistent`; omission and explicit `persistent` are equivalent.
- Only the typed top-level field of an Agent OpenAPI message request can request isolation.
- Nested caller metadata cannot forge the execution policy, attempt ID, Agent ID, owner user ID, publication ID, or knowledge-base binding.
- Expert-team OpenAPI requests cannot enter isolated execution.
- Non-OpenAPI entry points cannot activate isolation through generic request or channel metadata.
- A forged `open:*` channel plus matching string metadata cannot activate isolation without the server-local capability marker.
- Isolated attempts create no durable chat, message-history, or session-state record; only the existing OpenAPI invocation/audit record remains durable.
- Unique attempt IDs are generated server-side and sanitized before filesystem use.
- The implementation never changes global/current workspace state outside existing request-local `ContextVar` usage.
- Existing configured tool side effects remain possible and are explicitly not represented as isolated transactional behavior.

## Test Matrix

1. Request schema accepts omitted mode, explicit `persistent`, and explicit `isolated_attempt`, and rejects unknown values.
2. An omitted mode and explicit `persistent` produce the current stable session ID and the same prepared native payload shape, with no isolation metadata.
3. Persistent Agent OpenAPI execution still performs every existing session-state read/load/update/save operation and receives the shared MemoryManager.
4. Three isolated Agent OpenAPI requests with identical frozen business input and identical caller correlation fields receive three distinct execution session IDs and writable workspace roots while preserving the input and external IDs unchanged.
5. An isolated Agent OpenAPI execution performs no session-state preflight read, load, update, or save and constructs the Agent without a MemoryManager.
6. Isolated Agent execution retains the same Agent profile/model configuration, identity prompt root, skills root, publication knowledge-base ID, configured built-in tools, plugin tools, and MCP clients as persistent execution.
7. Memory tools, automatic memory retrieval, compaction-to-memory, and automatic memory writes are absent only in isolated Agent OpenAPI mode.
8. Caller-controlled nested metadata cannot enable isolation or replace the trusted mode, attempt ID, Agent ID, owner identity, publication binding, external IDs, or knowledge-base binding.
9. An expert-team OpenAPI request with omitted mode or explicit `persistent` follows the current path without isolation metadata.
10. An expert-team OpenAPI request with explicit `isolated_attempt` returns HTTP 400 before chat/run preparation.
11. Console, ordinary Agent, scheduled-task, background-task, channel, mission, orchestration, and inter-Agent requests cannot activate isolation even if their generic metadata contains similarly named values.
12. Three sequential isolated requests prove that attempt 2 and attempt 3 cannot observe an earlier attempt's model output, session state, long-term-memory read/write, or temporary files; all three expose identical non-memory capability configuration.
13. A concurrent persistent Agent OpenAPI request remains on its stable session/workspace and is not affected by an isolated request.
14. `send_file_to_user` and ConsoleChannel artifact scanning continue to return artifacts from an isolated attempt directory.
15. Successful attempt artifacts are not deleted when the stream finishes.
16. Existing tool registration and availability are identical between persistent and isolated Agent OpenAPI execution except that long-term-memory tools disappear with the absent MemoryManager.
17. Existing OpenAPI billing, idempotency, cancellation, streaming, identity attribution, and invocation audit behavior remains unchanged apart from recording the caller-supplied request body as it already does.
18. Isolated attempts create no durable chat row, message-history row, or session-state row; their live tracker identifier remains usable during execution, and their `open_api_invocations` rows retain the original `external_session_id` for audit correlation.
19. Existing persistent OpenAPI chat creation, history, touch behavior, and artifact recovery remain unchanged.
20. Cross-Agent recent task lists and per-Agent chat lists contain no isolated-attempt records; existing persistent OpenAPI visibility behavior remains unchanged.

## End-to-End Acceptance Scenario

For one frozen AIBot request payload, issue three sequential Agent OpenAPI calls with the same business message, external user ID, external session correlation value, publication, knowledge-base binding, and configured Agent, and with `execution_mode: "isolated_attempt"` on all three calls.

Acceptance requires:

- three different internal execution session IDs and workspace roots;
- identical model/profile configuration, prompt/skills roots, knowledge-base binding, configured business tools, plugin tools, and MCP clients;
- no prior attempt model response in a later attempt's in-memory context;
- no session-state load or save on any attempt;
- no long-term-memory retrieval, memory tool exposure, compaction write, or automatic memory write on any attempt;
- no earlier attempt file visible from a later attempt's writable workspace;
- unchanged caller business input and unchanged `external_session_id` in all three invocation audit rows;
- no isolated chat/history rows exposed through console or per-Agent chat APIs;
- successful attempt file/media blocks and artifact card remain consumable by AIBot;
- a concurrently executed persistent Agent OpenAPI request retains its stable session ID, chat/history behavior, session state, memory manager, and workspace without receiving isolated metadata.

## Compatibility and Rollout

No database migration or environment flag is required. Existing clients omit `execution_mode` and remain persistent. Explicit `persistent` is the same path. The new behavior is activated only for Agent-target OpenAPI requests that explicitly send `execution_mode: "isolated_attempt"`. Documentation will describe the non-transactional tool boundary and artifact retention caveat so callers do not interpret memory/session isolation as rollback of external tool effects.

## Remaining Risks and Deliberate Non-goals

- Because isolated attempts do not create durable chat/session history, artifact delivery is tied to the live OpenAPI SSE response. If AIBot disconnects before consuming a successful file block or artifact card, the current chat-history API cannot reconstruct that isolated response. A future artifact manifest keyed by invocation ID would be a separate feature.
- Attempt directories are retained so successful artifacts remain downloadable. Without a later retention job, failed and abandoned attempt files can accumulate.
- Session and memory isolation does not roll back external effects from configured MCP or business tools. This release preserves those capabilities intentionally.
- The contract depends on AIBot marking all candidate calls, including candidate one, as isolated and keeping business input frozen. DClaw cannot detect a mixed persistent/isolated retry set because it intentionally does not own retry orchestration.
- The internal execution ID must remain available to the running TaskTracker and stop/cancellation path without becoming a durable chat ID. Implementation tests must cover disconnect, cancellation, and billing finalization to avoid regressions in the streaming lifecycle.
