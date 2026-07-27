# Task Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add soft archive and restore behavior to the sidebar task list while preventing active running/generating tasks from being archived.

**Architecture:** Store archive state in existing `ChatSpec.meta` as `archived` and `archived_at`. Keep filtering and local state patching in small task-list helpers, then wire those helpers into `Sidebar.tsx` without changing backend schema or routes.

**Tech Stack:** React 18, TypeScript, Ant Design menu/dropdown, Vitest, existing `chatApi.updateChat` endpoint.

---

### File Structure

- Modify: `console/src/layouts/taskListFilters.ts`
  - Owns task visibility helpers and the archive-view predicate.
- Modify: `console/src/layouts/taskListFilters.test.ts`
  - Covers archived detection, active/archive filtering, and metadata merge behavior.
- Modify: `console/src/layouts/Sidebar.tsx`
  - Adds archive mode state, filter UI entry, archive/restore handlers, and menu actions.

### Task 1: Task Archive Helpers

**Files:**
- Modify: `console/src/layouts/taskListFilters.ts`
- Test: `console/src/layouts/taskListFilters.test.ts`

- [ ] **Step 1: Write the failing helper tests**

Add these tests to `console/src/layouts/taskListFilters.test.ts`:

```ts
import {
  buildTaskArchiveMeta,
  isArchivedTaskChat,
  matchesTaskArchiveView,
} from "./taskListFilters";

it("detects archived tasks only when meta.archived is true", () => {
  expect(
    isArchivedTaskChat({
      ...baseTask,
      meta: { archived: true },
    }),
  ).toBe(true);
  expect(
    isArchivedTaskChat({
      ...baseTask,
      meta: { archived: false },
    }),
  ).toBe(false);
  expect(isArchivedTaskChat({ ...baseTask, meta: {} })).toBe(false);
});

it("matches active and archived task views", () => {
  const activeTask = { ...baseTask, meta: { archived: false } };
  const archivedTask = { ...baseTask, meta: { archived: true } };

  expect(matchesTaskArchiveView(activeTask, "active")).toBe(true);
  expect(matchesTaskArchiveView(activeTask, "archived")).toBe(false);
  expect(matchesTaskArchiveView(archivedTask, "active")).toBe(false);
  expect(matchesTaskArchiveView(archivedTask, "archived")).toBe(true);
});

it("builds archive metadata while preserving existing meta fields", () => {
  expect(
    buildTaskArchiveMeta(
      { agent_id: "agent-1", active_mode: "team" },
      true,
      "2026-06-25T10:00:00.000Z",
    ),
  ).toEqual({
    agent_id: "agent-1",
    active_mode: "team",
    archived: true,
    archived_at: "2026-06-25T10:00:00.000Z",
  });

  expect(
    buildTaskArchiveMeta(
      { agent_id: "agent-1", archived: true, archived_at: "old" },
      false,
    ),
  ).toEqual({
    agent_id: "agent-1",
    archived: false,
    archived_at: null,
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd console && npm test -- taskListFilters.test.ts --run`

Expected: FAIL because `buildTaskArchiveMeta`, `isArchivedTaskChat`, and `matchesTaskArchiveView` are not exported.

- [ ] **Step 3: Add minimal helper implementation**

Add these exports to `console/src/layouts/taskListFilters.ts`:

```ts
export type TaskArchiveView = "active" | "archived";

export function isArchivedTaskChat(chat: TaskListChat): boolean {
  return chat.meta?.archived === true;
}

export function matchesTaskArchiveView(
  chat: TaskListChat,
  archiveView: TaskArchiveView,
): boolean {
  const archived = isArchivedTaskChat(chat);
  return archiveView === "archived" ? archived : !archived;
}

export function buildTaskArchiveMeta(
  currentMeta: Record<string, unknown> | undefined,
  archived: boolean,
  archivedAt?: string,
): Record<string, unknown> {
  return {
    ...(currentMeta ?? {}),
    archived,
    archived_at: archived ? archivedAt ?? new Date().toISOString() : null,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd console && npm test -- taskListFilters.test.ts --run`

Expected: PASS.

### Task 2: Sidebar Archive Actions

**Files:**
- Modify: `console/src/layouts/Sidebar.tsx`

- [ ] **Step 1: Wire archive helper imports and icon imports**

Update the imports so `Sidebar.tsx` imports `Archive` and `ArchiveRestore` from `lucide-react`, and imports `buildTaskArchiveMeta`, `isArchivedTaskChat`, `matchesTaskArchiveView`, and `TaskArchiveView` from `taskListFilters`.

- [ ] **Step 2: Add archive view state**

Add:

```ts
const [taskArchiveView, setTaskArchiveView] =
  useState<TaskArchiveView>("active");
```

- [ ] **Step 3: Add archive and restore handlers**

Add handlers beside the existing rename/status/delete handlers:

```ts
const handleArchiveTask = async (task: ChatSpec) => {
  if (isTaskGenerating(task as TaskListChat)) {
    message.warning(t("nav.archiveRunningTaskBlocked", "运行中的任务不能归档"));
    return;
  }
  const archivedAt = new Date().toISOString();
  const taskAgentId = task.meta?.agent_id as string | undefined;
  const meta = buildTaskArchiveMeta(task.meta, true, archivedAt);
  await api.updateChat(task.id, { meta }, taskAgentId);
  setTaskList((prev) =>
    prev.map((item) => (item.id === task.id ? { ...item, meta } : item)),
  );
  message.success(t("nav.archiveSuccess", "已归档"));
  if (selectedKey === `task-${task.id}`) {
    navigate("/workbench");
  }
};

const handleRestoreTask = async (task: ChatSpec) => {
  const taskAgentId = task.meta?.agent_id as string | undefined;
  const meta = buildTaskArchiveMeta(task.meta, false);
  await api.updateChat(task.id, { meta }, taskAgentId);
  setTaskList((prev) =>
    prev.map((item) => (item.id === task.id ? { ...item, meta } : item)),
  );
  message.success(t("nav.restoreSuccess", "已恢复"));
};
```

Wrap each handler body in the same try/catch style used by rename/status/delete, with error messages `归档失败` and `恢复失败`.

- [ ] **Step 4: Filter task list by archive view**

In `filteredTaskList`, before status/date/search checks, add:

```ts
if (!matchesTaskArchiveView(task, taskArchiveView)) return false;
```

- [ ] **Step 5: Add archive mode to the filter popover**

Add `{ key: "archive", label: t("filter.archive", "归档") }` to the left menu. When `filterTab === "archive"`, render a right menu with:

```ts
items={[
  { key: "active", label: t("filter.activeTasks", "当前任务") },
  { key: "archived", label: t("filter.archivedTasks", "归档任务") },
]}
```

Set `taskArchiveView` from the click handler.

- [ ] **Step 6: Add archive/restore menu item**

For each task row, compute:

```ts
const isArchived = isArchivedTaskChat(task);
```

Before the delete menu item, insert either:

```ts
{
  key: "restore",
  icon: <ArchiveRestore size={14} />,
  label: t("nav.restoreTask", "恢复任务"),
  onClick: ({ domEvent }: any) => {
    domEvent.stopPropagation();
    void handleRestoreTask(task);
  },
}
```

or:

```ts
{
  key: "archive",
  icon: <Archive size={14} />,
  label: isGenerating
    ? t("nav.archiveRunningTaskBlocked", "运行中的任务不能归档")
    : t("nav.archiveTask", "归档任务"),
  disabled: isGenerating,
  onClick: ({ domEvent }: any) => {
    domEvent.stopPropagation();
    void handleArchiveTask(task);
  },
}
```

- [ ] **Step 7: Run targeted tests**

Run: `cd console && npm test -- taskListFilters.test.ts taskListState.test.ts --run`

Expected: PASS.

### Task 3: Type Check and Diff Review

**Files:**
- Review all modified files.

- [ ] **Step 1: Run TypeScript check**

Run: `cd console && npx tsc -b --noEmit`

Expected: exit 0.

- [ ] **Step 2: Run whitespace diff check**

Run: `git diff --check -- console/src/layouts/taskListFilters.ts console/src/layouts/taskListFilters.test.ts console/src/layouts/Sidebar.tsx docs/superpowers/plans/2026-06-25-task-archive.md`

Expected: exit 0.

- [ ] **Step 3: Review final diff**

Run: `git diff -- console/src/layouts/taskListFilters.ts console/src/layouts/taskListFilters.test.ts console/src/layouts/Sidebar.tsx docs/superpowers/plans/2026-06-25-task-archive.md`

Expected: changes only implement archive/restore behavior and the plan.
