import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expertTeamsApi } from "./expertTeams";

describe("expertTeamsApi billing continuation", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", { getItem: vi.fn(() => null) });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ id: "run-1", state: "running", members: [] }),
      })) as unknown as typeof fetch,
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it("uses the authenticated durable continue endpoint", async () => {
    await expertTeamsApi.continueRun("run-1");

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/api/user/expert-teams/runs/run-1/continue");
    expect(options?.method).toBe("POST");
  });
});
