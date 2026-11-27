# Task Archive Design

## Context

The client sidebar currently loads recent chats through `api.listAllChats()`,
filters them with `isVisibleTaskChat`, sorts them with `sortTasksForSidebar`,
and shows the first 20 task-like chats. Each task already supports rename,
status changes, and delete actions from the overflow menu.

The problem is that the task list can grow noisy. Deleting is too destructive
for cleanup because the user may need the task history or artifacts later.

## Goal

Add a Codex-like archive workflow for tasks:

- Archive removes a task from the default task list without deleting it.
- Archived tasks can be searched, opened, and restored.
- Running or generating tasks cannot be archived.
- Delete remains available as the destructive action.

## Non-Goals

- No hard deletion changes.
- No separate archive table or database migration in the first version.
- No batch archive or retention policy.
- No broad sidebar redesign.

## Recommended Approach

Use soft archive metadata on the existing chat record.

Archived tasks are marked by merging these fields into `chat.meta`:

- `archived: true`
- `archived_at: <ISO timestamp>`

Restoring a task merges:

- `archived: false`
- `archived_at: null`

The existing `updateChat` endpoint already accepts partial `meta` updates, and
the server merges metadata instead of replacing the whole object. This keeps the
first version small and avoids schema churn.

## User Experience

The task overflow menu gains an "Archive task" action near delete. If a task is
running or generating, the action is disabled and should explain that active
tasks cannot be archived.

The task filter popover gains an archive mode. In normal mode, archived tasks
are hidden. In archive mode, only archived tasks are shown. Search should work
in both modes.

Archived task rows remain openable so a user can inspect old work. In archive
mode, the overflow menu shows "Restore task". Restoring moves the task back to
the normal task list.

If the currently open task is archived, navigate back to `/workbench` so the
sidebar and main view do not disagree about the default active list.

## Frontend Shape

Add small task-list helpers instead of embedding archive checks in JSX:

- `isArchivedTaskChat(task)` reads `task.meta.archived === true`.
- `isVisibleTaskChat(chat)` continues to remove invalid, claw, and ghost chats.
- The sidebar applies archive-mode filtering after visibility filtering.

The sidebar keeps the existing `updateChat` API:

- Archive: `api.updateChat(task.id, { meta: { archived: true, archived_at } })`
- Restore: `api.updateChat(task.id, { meta: { archived: false, archived_at: null } })`

Local state should be patched immediately after success so the list updates
without waiting for the next polling interval.

## Edge Cases

- Running/generating tasks: archive action is disabled.
- Invalid legacy rows: still filtered by `isVisibleTaskChat`.
- Archived empty ghost tasks: remain hidden because the ghost filter still
  applies before archive mode.
- Metadata merge: preserve existing fields such as `agent_id` and
  `active_mode`.

## Testing

Frontend unit tests:

- `taskListFilters.test.ts` covers archive detection and default visibility.
- `Sidebar` behavior can be covered where practical by asserting archive and
  restore calls use `updateChat` with merged `meta`.
- Existing task ordering and generating-state tests should keep passing.

Verification commands:

- `npm test -- taskListFilters.test.ts --run`
- `npm test -- Sidebar --run` if a sidebar test exists or is added
- `npx tsc -b --noEmit`

For local browser-facing verification after implementation, rebuild/restart the
Dockerized local service and probe `http://127.0.0.1:18088`.
