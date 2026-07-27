import { describe, expect, it } from "vitest";
import { sortTasksForSidebar } from "./taskListOrdering";
import type { TaskListChat } from "./taskListFilters";

const task = (
  id: string,
  created_at: string,
  updated_at: string,
): TaskListChat =>
  ({
    id,
    name: id,
    session_id: id,
    user_id: "default",
    channel: "console",
    created_at,
    updated_at,
  }) as TaskListChat;

describe("sortTasksForSidebar", () => {
  it("keeps sidebar task order stable by creation time when older tasks are updated", () => {
    const olderButRecentlyUpdated = task(
      "older",
      "2026-05-30T01:00:00Z",
      "2026-05-30T09:00:00Z",
    );
    const newerButNotTouched = task(
      "newer",
      "2026-05-30T03:00:00Z",
      "2026-05-30T03:05:00Z",
    );

    expect(
      sortTasksForSidebar([olderButRecentlyUpdated, newerButNotTouched]).map(
        (item) => item.id,
      ),
    ).toEqual(["newer", "older"]);
  });
});
