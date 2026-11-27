# Mobile Mini Program V1 Mapping

Last verified: 2026-06-17

## Goal

Define the business and API mapping for the first mobile mini-program prototype.
The V1 target is ordinary employees, not administrators. The mobile surface is a
WeChat mini-program or native app path, not mobile Web.

The current Pencil prototype covers these screens:

- Brand/style board
- Workbench
- Create Task
- Task List
- Task Detail
- Pending Confirmation
- Knowledge Search
- Result Detail
- Me
- Static Asset Slots

## Scope

### In V1

- Employee workbench
- Create an AI task
- View employee-owned tasks
- Continue a task conversation
- Confirm or reject Tool Guard pending operations
- Search accessible enterprise or personal knowledge
- View task artifacts and result files
- Personal account, workspace, reminder, and help entry points

### Out Of Scope

- Admin console
- User and role management
- Model provider configuration
- MCP, plugin, or tool management
- Security rule configuration
- Enterprise knowledge connector setup
- Full AIGC Studio editing
- Mobile Web

## Core Business Objects

### ChatSpec

Source: `console/src/api/types/chat.ts`

Used by: task list, task detail, workbench recent tasks.

Key fields:

| Field | Meaning | Mobile use |
| --- | --- | --- |
| `id` | Chat UUID and task route key | `taskId`, detail page route |
| `session_id` | Runtime session id | Runtime events, approval routing |
| `name` | User-facing task title | Task list title |
| `status` | Runtime status, currently `idle` or `running` | Running indicator |
| `task_status` | Business task status | Completed, failed, planning, etc. |
| `meta.mode` | Existing task mode marker | Should be `task` for mobile-created tasks |
| `meta.agent_id` | Selected assistant/workspace | Create task context |
| `meta.expert_team_id` | Optional expert team | Create task context |

### PendingApproval

Source: `console/src/api/modules/console.ts`

Used by: pending confirmation list, confirmation detail, task badge.

Key fields:

| Field | Meaning | Mobile use |
| --- | --- | --- |
| `request_id` | Approval request id | Confirm/reject action |
| `session_id` | Executing session | Show sub-session context if needed |
| `root_session_id` | Root task session | Access check and task association |
| `agent_id` | Agent requesting tool execution | Confirmation detail |
| `tool_name` | Tool to execute | Main confirmation title |
| `severity` | Tool Guard risk level | Risk badge |
| `findings_count` | Number of findings | Risk summary |
| `findings_summary` | Human-readable finding summary | Confirmation copy |
| `tool_params` | Tool parameters | Parameter preview |
| `created_at` | Request time | Sort and display |
| `timeout_seconds` | Auto-timeout window | Countdown |

### Artifact

Source: `console/src/api/modules/workspace.ts`

Used by: result detail, task detail artifact card.

The current UI consumes `MdFileInfo` from `/workspace/artifacts?session_id=...`.
Mobile should treat result files as a list first. Rich previews are a post-MVP
enhancement after the first task-result loop is stable.

### KnowledgeHit

Source: `/workspace/knowledge/search`.

Used by: knowledge search results and task prompt suggestions. Mobile must show
only accessible results returned by the backend. Do not fabricate cloud-document
content when a connector cannot return real content.

## Existing APIs To Reuse

| Purpose | Existing endpoint | Notes |
| --- | --- | --- |
| List current user's tasks | `GET /chats?channel=console` | Backend ignores client-supplied `user_id` and uses current user. |
| Create task shell | `POST /chats` | Creates `ChatSpec`; server owns `user_id`. |
| Send or continue task | `POST /console/chat` | SSE streaming endpoint used by web task/chat. |
| Stop task | `POST /console/chat/stop?chat_id=...` | Already checks chat access. |
| Get task history | `GET /chats/{chat_id}` | Detail page messages. |
| Get task status | `GET /chats/{chat_id}/status` | Runtime status and message count. |
| Poll session messages and approvals | `GET /console/push-messages?session_id=...` | Session-scoped hot path. |
| List approvals | `GET /approval/list?session_id=...` or `GET /approval/list` | Non-admin global list filters to accessible approvals. |
| Approve or reject | `POST /approval/approve`, `POST /approval/deny` | Body: `request_id`, `session_id`, optional `reason`. |
| Runtime events | `GET /runtime/events/stream?session_id=...` | Session-scoped SSE. Mini-program compatibility must be checked. |
| Knowledge search | `GET /workspace/knowledge/search?q=...&scope=all&top_k=5` | Returns hits plus search capabilities. |
| Knowledge capabilities | `GET /workspace/knowledge/capabilities` | Use to show keyword/semantic search status if needed. |
| Artifact list | `GET /workspace/artifacts?session_id=...` | Result detail source. |

## Recommended Mobile Facade APIs

These are not required for the prototype, but they make the mini-program much
cleaner than stitching together desktop-web calls.

| New endpoint | Purpose | Backing services |
| --- | --- | --- |
| `GET /mobile/workbench` | Workbench summary: running tasks, recent artifacts, pending confirmation count | `list_chats`, approval service, artifact list |
| `POST /mobile/tasks` | Create a task and submit the first prompt in one mobile-friendly call | `POST /chats`, `POST /console/chat` semantics |
| `GET /mobile/tasks` | Task list with derived `display_status` and pending confirmation count | `GET /chats`, approval metadata |
| `GET /mobile/tasks/{chat_id}` | Task detail bundle: chat history, status, pending approvals, artifacts | `GET /chats/{id}`, status, approvals, artifacts |
| `GET /mobile/confirmations` | All current user's pending Tool Guard confirmations | `GET /approval/list`, access-filtered |
| `GET /mobile/results/{chat_id}` | Artifact list plus lightweight file preview metadata | `/workspace/artifacts` |

## Page Mapping

### 1. Workbench

Primary job: let an employee start work and notice pending confirmations.

| UI block | Data source | Notes |
| --- | --- | --- |
| Greeting and employee label | Auth/session user profile | Need login/account binding in implementation plan. |
| Hero create-task button | Local navigation to Create Task | Carries current `agent_id` and optional `expert_team_id`. |
| Shortcut: My Tasks | `GET /mobile/tasks` or `GET /chats` | Filter to current user. |
| Shortcut: Knowledge Search | `GET /workspace/knowledge/search` | Search page. |
| Shortcut: AI Confirm | `GET /mobile/confirmations` | Label should be `确认`, not `工具`. |
| Shortcut: Pending Confirmations | Approval metadata | Badge count derived from pending approvals. |
| My Tasks list | Task list summary | Status derived as described below. |

### 2. Create Task

Primary job: create a task with explicit execution context.

| UI block | Data source | Notes |
| --- | --- | --- |
| Current assistant/workspace | Current selected `agent_id` | Default can be DClaw enterprise workspace. |
| Expert team | `meta.expert_team_id` if selected | V1 may default to one team and expose the switch in a following version. |
| Prompt input | User input | Text first; voice/file/image can be staged behind capability checks. |
| Attachment actions | Upload and channel capability checks | V1 can show but disable unavailable actions. |
| Common scenarios | Local template list | Templates produce prompt text, not new backend concepts. |
| Submit | `POST /mobile/tasks` recommended | Fallback: `POST /chats` then `POST /console/chat`. |

Create payload should preserve the web semantics:

```json
{
  "name": "整理上周项目进展",
  "session_id": "<client-generated-or-server-generated>",
  "channel": "console",
  "meta": {
    "mode": "task",
    "agent_id": "default",
    "active_mode": "task",
    "expert_team_id": "sales-support"
  }
}
```

### 3. Task List

Primary job: show the employee's own task queue.

| UI status | Derivation |
| --- | --- |
| `运行中` | `ChatSpec.status === "running"` |
| `待确认` | At least one pending approval where `root_session_id` or `session_id` maps to the task |
| `已完成` | `task_status === "completed"` or idle task with artifacts and no pending confirmation |
| `失败` | `task_status === "failed"` |

The mobile task list should not rely on an independent `pending` task status if
the state really comes from Tool Guard approvals.

### 4. Task Detail

Primary job: continue the conversation and expose task outputs.

| UI block | Data source | Notes |
| --- | --- | --- |
| Message timeline | `GET /chats/{chat_id}` | Use existing message content rendering rules where possible. |
| Runtime state | `GET /chats/{chat_id}/status` and runtime events | Polling fallback if SSE is not reliable in mini-program. |
| Prompt input | `POST /console/chat` or mobile facade | Preserve `session_id`, `agent_id`, and `root_session_id`. |
| File cards | Artifact scanner / explicit artifact list | Tap leads to Result Detail. |
| Pending confirmation card | Approval metadata | Inline card can deep-link to confirmation detail. |

### 5. Pending Confirmation

Primary job: let employees confirm only their own Tool Guard operations.

This is not OA approval. Do not use leave, reimbursement, travel, or admin
approval language.

| UI block | Data source |
| --- | --- |
| Title | `tool_name` plus friendly label |
| Risk badge | `severity` |
| Finding summary | `findings_summary`, `findings_count` |
| Parameter preview | `tool_params` |
| Agent/session context | `agent_id`, `session_id`, `root_session_id` |
| Countdown | `created_at + timeout_seconds` |
| Reject | `POST /approval/deny` |
| Confirm execute | `POST /approval/approve` |

Access rule: backend must continue to enforce root-session ownership through
`ensure_chat_access`. Mobile should never trust a local task id alone.

### 6. Knowledge Search

Primary job: find accessible knowledge and source snippets.

| UI block | Data source | Notes |
| --- | --- | --- |
| Search input | User query | Debounce or explicit submit. |
| Hot queries | Local recent queries or static V1 list | No backend dependency required. |
| Results | `/workspace/knowledge/search` | Use returned hits only. |
| Search capability badge | `/workspace/knowledge/capabilities` | Optional; useful for semantic-search availability. |

If a cloud connector has no real content path, the UI should show unavailable or
keyword-only states instead of placeholder content.

### 7. Result Detail

Primary job: show task artifacts first, rich summaries second.

| UI block | Data source | Notes |
| --- | --- | --- |
| Result title | Task name or selected artifact title | Prefer task/artifact metadata. |
| File list | `/workspace/artifacts?session_id=...` | Primary V1 view. |
| Preview | `loadArtifactFile(path, chatId)` | Text/Markdown first. |
| Download/share | Existing artifact download behavior or mobile facade | Mini-program file-share constraints need checking. |
| Continue asking | Route back to Task Detail with prompt input focused | No new backend concept. |

### 8. Me

Primary job: employee account and simple preferences.

| UI block | Source | Notes |
| --- | --- | --- |
| User profile | Auth/session user profile | Requires WeChat binding decision. |
| Workspace label | Current `agent_id`/workspace | Read-only in V1 unless switch is ready. |
| Today's counts | Mobile workbench summary | Completed results, pending confirmations, knowledge visits. |
| Notifications | Mini-program subscribe-message settings | V1: task completed and pending confirmation. |
| Confirmation records | Approval history if exposed | If no history endpoint, hide or mark as future. |
| Help/feedback | Static link or feedback form | No admin configuration. |

## Static Asset Slots

These slots are placeholders in the prototype and should be replaced before
production development finishes.

| Slot | Use | Suggested size |
| --- | --- | --- |
| `brand-board-mascot` | Style board mascot | 180 x 230 |
| `home-hero-mascot` | Workbench hero | 136 x 154 |
| `tab-center-mascot` | Bottom nav center mascot | 40 x 40 |
| `task-card-sticker` | Task row sticker | 34 x 36 |
| `confirm-banner-mascot` | Confirmation banner | 98 x 120 |
| `empty-state-mascot` | Empty states | 160 x 120 |
| `create-helper-mascot` | Create task helper card | 82 x 106 |
| `result-cover-mascot` | Result cover card | 82 x 112 |
| `profile-avatar` | Employee avatar fallback | 64 x 64 |

## Implementation Risks

- WeChat mini-program login and existing user binding are not specified yet.
- `POST /console/chat` is streaming-first; mini-program compatibility and
  reconnection behavior need validation.
- Workbench needs aggregate pending-confirmation counts across tasks. A mobile
  facade is cleaner than polling every task.
- Result file sharing/downloading must follow WeChat mini-program file rules.
- Push notifications require WeChat subscribe-message templates and explicit
  user consent.

## Acceptance Flows

1. Employee opens Workbench and sees only their own tasks and confirmations.
2. Employee creates a task with a visible assistant/workspace context.
3. Task appears in Task List and opens Task Detail.
4. A Tool Guard pending operation appears as `待确认操作`.
5. Employee rejects or confirms; backend enforces root-session ownership.
6. Task continues or stops based on the decision.
7. Employee opens Result Detail and sees artifacts from the task session.
8. Employee searches knowledge and sees only backend-returned accessible hits.

## Next Step

Create an implementation plan for the mini-program MVP. The recommended plan
should start with backend/mobile facade contract tests, then scaffold the Taro
mini-program, then implement screens in this order:

1. Auth shell and API client
2. Workbench and Create Task
3. Task List and Task Detail
4. Pending Confirmation
5. Knowledge Search and Result Detail
6. Me page and notification settings
