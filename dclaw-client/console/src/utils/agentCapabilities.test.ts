import { describe, expect, it } from "vitest";
import { canInspectAgent, capabilitiesForAgent } from "./agentCapabilities";

describe("agent capability policy", () => {
  it("denies inspection for sealed agents even without a workspace path", () => {
    const agent = {
      id: "luyu",
      name: "陆羽",
      description: "茶学助手",
      enabled: true,
      agent_type: "sealed" as const,
    };
    expect(canInspectAgent(agent)).toBe(false);
    expect(capabilitiesForAgent(agent).invoke).toBe(true);
  });

  it("keeps standard agents fully manageable for backward compatibility", () => {
    const agent = {
      id: "writer",
      name: "Writer",
      description: "",
      workspace_dir: "/tmp/writer",
      enabled: true,
    };
    expect(canInspectAgent(agent)).toBe(true);
    expect(capabilitiesForAgent(agent).export).toBe(true);
  });
});
