import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { request } from "../request";
import { invalidateSkillCache, skillApi } from "./skill";

describe("skillApi global pool requests", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    invalidateSkillCache();
    vi.mocked(request).mockResolvedValue([]);
  });

  it("lists the global skill pool without selected Agent context", async () => {
    await skillApi.listSkillPoolSkills();

    expect(request).toHaveBeenCalledWith("/skills/pool", {
      includeSelectedAgent: false,
    });
  });

  it("lists broadcast workspaces without selected Agent context", async () => {
    await skillApi.listSkillWorkspaces();

    expect(request).toHaveBeenCalledWith("/skills/workspaces", {
      includeSelectedAgent: false,
    });
  });
});
