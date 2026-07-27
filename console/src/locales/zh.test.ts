import { describe, expect, it } from "vitest";
import zh from "./zh.json";

describe("zh locale navigation labels", () => {
  it("labels the admin agents navigation item as experts", () => {
    expect(zh.nav.agents).toBe("专家");
  });
});
