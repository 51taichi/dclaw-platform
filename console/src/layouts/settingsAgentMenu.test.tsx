import { describe, expect, it } from "vitest";

import { getAgentManagementMenuItems } from "./settingsAgentMenu";

describe("settings agent management menu", () => {
  it("places 密封/Agent immediately above 专家/Agents", () => {
    const items = getAgentManagementMenuItems(false, (key) =>
      key === "nav.agents" ? "专家/Agents" : key,
    );

    expect(items.map((item) => [item.key, item.label])).toEqual([
      ["sealed-agents", "密封/Agent"],
      ["agents", "专家/Agents"],
    ]);
  });
});
