import { describe, expect, it } from "vitest";
import { expertIdentity } from "./expertIdentity";

describe("expertIdentity", () => {
  it("uses a super expert avatar and falls back to an initial before upload", () => {
    const agent = {
      id: "luyu",
      name: "陆羽",
      description: "",
      enabled: true,
      agent_type: "sealed" as const,
      open_api_enabled: true,
    };
    expect(expertIdentity(agent)).toMatchObject({
      name: "陆羽",
      isSuperExpert: true,
    });
    expect(expertIdentity(agent).avatar).toMatch(/^data:image\/svg\+xml,/);
    expect(
      expertIdentity({ ...agent, avatar: "data:image/png;base64,new" }).avatar,
    ).toBe("data:image/png;base64,new");
    expect(expertIdentity().name).toBe("DClaw");
    expect(
      expertIdentity({ ...agent, agent_type: "standard" }).isSuperExpert,
    ).toBe(false);
  });
});
