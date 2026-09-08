import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { agentsApi } from "./agents";

describe("agentsApi", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => "admin-token"),
      removeItem: vi.fn(),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        json: async () => ({ agents: [] }),
        text: async () => '{"agents":[]}',
      })) as unknown as typeof fetch,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("requests a client-visible agent list when OpenAPI agents are excluded", async () => {
    await agentsApi.listAgents({ excludeOpenApi: true });

    expect(fetch).toHaveBeenCalledWith(
      "/api/user/agents?exclude_open_api=true",
      expect.any(Object),
    );
  });

  it("keeps the complete agent list as the default for administration", async () => {
    await agentsApi.listAgents();

    expect(fetch).toHaveBeenCalledWith("/api/user/agents", expect.any(Object));
  });
});
