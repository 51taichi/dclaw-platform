import { describe, expect, it } from "vitest";
import type { AgentSummary } from "../../api/types/agents";
import { clientVisibleAgents } from "./visibility";

describe("clientVisibleAgents", () => {
  it("hides agents published through an enabled OpenAPI endpoint", () => {
    const agents: AgentSummary[] = [
      {
        id: "api-agent",
        name: "API Agent",
        description: "For external applications",
        enabled: true,
        open_api_enabled: true,
      },
      {
        id: "desktop-agent",
        name: "Desktop Agent",
        description: "For desktop users",
        enabled: true,
        open_api_enabled: false,
      },
      {
        id: "legacy-agent",
        name: "Legacy Agent",
        description: "Older server response",
        enabled: true,
      },
    ];

    expect(clientVisibleAgents(agents).map((agent) => agent.id)).toEqual([
      "desktop-agent",
      "legacy-agent",
    ]);
  });
});
