import { describe, expect, it } from "vitest";
import {
  buildTaskArchiveMeta,
  isArchivedTaskChat,
  isVisibleTaskChat,
  matchesTaskArchiveView,
  type TaskListChat,
} from "./taskListFilters";

const baseTask = {
  id: "task-id",
  session_id: "session-id",
  user_id: "default",
  channel: "console",
  name: "Real task",
  created_at: null,
  updated_at: null,
  meta: {},
} as TaskListChat;

describe("isVisibleTaskChat", () => {
  it("hides empty default-name ghost tasks", () => {
    expect(
      isVisibleTaskChat({
        ...baseTask,
        name: "New Chat",
        status: "idle",
        message_count: 0,
      }),
    ).toBe(false);
  });

  it("hides legacy default-name ghost tasks before message counts are available", () => {
    expect(
      isVisibleTaskChat({
        ...baseTask,
        name: "New Chat",
        status: "idle",
      }),
    ).toBe(false);
  });

  it("keeps running default-name tasks so progress is still visible", () => {
    expect(
      isVisibleTaskChat({
        ...baseTask,
        name: "New Chat",
        status: "running",
        message_count: 0,
      }),
    ).toBe(true);
  });

  it("keeps normal task chats", () => {
    expect(isVisibleTaskChat({ ...baseTask, message_count: 2 })).toBe(true);
  });

  it("hides claw chats from the task list", () => {
    expect(isVisibleTaskChat({ ...baseTask, channel: "claw" })).toBe(false);
  });

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
});
