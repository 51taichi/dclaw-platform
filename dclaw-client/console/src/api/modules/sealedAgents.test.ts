import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { sealedAgentsApi } from "./sealedAgents";

describe("sealedAgentsApi", () => {
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
        json: async () => [],
        text: async () => "[]",
      })) as unknown as typeof fetch,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("routes every sealed-agent operation through the admin namespace", async () => {
    await sealedAgentsApi.list();
    await sealedAgentsApi.uploadRelease(new File(["release"], "agent.zip"));
    await sealedAgentsApi.uploadAvatar(
      "agent/one",
      new File(["image"], "avatar.png"),
    );
    await sealedAgentsApi.uploadBanner(
      "agent/one",
      new File(["banner"], "banner.png"),
    );
    await sealedAgentsApi.activate("agent/one", "release/one");
    await sealedAgentsApi.setEnabled("agent/one", true);
    await sealedAgentsApi.setEnabled("agent/one", false);

    expect(vi.mocked(fetch).mock.calls.map(([input]) => String(input))).toEqual(
      [
        "/api/admin/sealed-agents",
        "/api/admin/sealed-agents/releases",
        "/api/admin/sealed-agents/agent%2Fone/avatar",
        "/api/admin/sealed-agents/agent%2Fone/banner",
        "/api/admin/sealed-agents/agent%2Fone/releases/release%2Fone/activate",
        "/api/admin/sealed-agents/agent%2Fone/enable",
        "/api/admin/sealed-agents/agent%2Fone/disable",
      ],
    );
  });
});
