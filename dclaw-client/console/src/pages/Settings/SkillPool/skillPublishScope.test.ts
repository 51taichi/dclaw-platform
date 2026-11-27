import { describe, expect, it } from "vitest";
import type { PoolSkillSpec } from "../../../api/types";
import {
  applyPublishScope,
  getSkillPublishScope,
  isPrivateSkillPromotion,
} from "./skillPublishScope";

const skill = (overrides: Partial<PoolSkillSpec>): PoolSkillSpec =>
  ({
    name: "demo",
    description: "demo",
    content: "",
    source: "builtin",
    protected: false,
    tags: [],
    visibility: "public",
    config: {},
    ...overrides,
  }) as PoolSkillSpec;

describe("skill publish scope", () => {
  it("treats default/public/private as one exclusive publish scope", () => {
    expect(
      getSkillPublishScope(
        skill({ visibility: "public", config: { is_default: true } }),
      ),
    ).toBe("default");
    expect(getSkillPublishScope(skill({ visibility: "private" }))).toBe(
      "private",
    );
    expect(getSkillPublishScope(skill({ visibility: "public" }))).toBe(
      "public",
    );
  });

  it("maps default scope to public visibility with persisted default config", () => {
    expect(
      applyPublishScope("default", { retained: true, is_default: false }),
    ).toEqual({
      visibility: "public",
      config: { retained: true, is_default: true },
    });
  });

  it("removes default config when scope is public or private", () => {
    expect(applyPublishScope("public", { is_default: true, kept: 1 })).toEqual({
      visibility: "public",
      config: { kept: 1 },
    });
    expect(applyPublishScope("private", { is_default: true, kept: 1 })).toEqual({
      visibility: "private",
      config: { kept: 1 },
    });
  });

  it("detects irreversible promotion from private to public or default", () => {
    const privateSkill = skill({
      visibility: "private",
      owner_user_id: "user-a",
    });

    expect(isPrivateSkillPromotion(privateSkill, "public")).toBe(true);
    expect(isPrivateSkillPromotion(privateSkill, "default")).toBe(true);
    expect(isPrivateSkillPromotion(privateSkill, "private")).toBe(false);
    expect(
      isPrivateSkillPromotion(skill({ visibility: "public" }), "default"),
    ).toBe(false);
  });
});
