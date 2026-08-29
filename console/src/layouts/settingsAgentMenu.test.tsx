import { describe, expect, it } from "vitest";

import { getAgentManagementMenuItems } from "./settingsAgentMenu";

describe("settings agent management menu", () => {
  it("places 超级专家 immediately below 专家/Agents", () => {
    const items = getAgentManagementMenuItems(false, (key) =>
      key === "nav.agents" ? "专家/Agents" : key,
    );

    expect(items.map((item) => [item.key, item.label])).toEqual([
      ["agents", "专家/Agents"],
      ["sealed-agents", "超级专家"],
    ]);
  });
});
