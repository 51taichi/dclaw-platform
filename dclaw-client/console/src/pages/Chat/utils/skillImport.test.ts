import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  importSkillFromContent,
  parseSkillMetadataFromContent,
} from "./skillImport";

const {
  createSkillPoolSkill,
  downloadSkillPoolSkill,
  enableSkill,
  invalidateSkillCache,
} = vi.hoisted(() => ({
  createSkillPoolSkill: vi.fn(),
  downloadSkillPoolSkill: vi.fn(),
  enableSkill: vi.fn(),
  invalidateSkillCache: vi.fn(),
}));

vi.mock("../../../api/modules/skill", () => ({
  skillApi: {
    createSkillPoolSkill,
    downloadSkillPoolSkill,
    enableSkill,
  },
  invalidateSkillCache,
}));

const skillContent = `---
name: short_drama_workshop
description: "短剧创作技能"
config:
  display_name: "短剧创作工坊"
---

# 短剧创作工坊
`;

describe("skillImport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createSkillPoolSkill.mockResolvedValue({
      created: true,
      name: "short_drama_workshop",
    });
    downloadSkillPoolSkill.mockResolvedValue(undefined);
    enableSkill.mockResolvedValue(undefined);
  });

  it("parses skill metadata from frontmatter content", () => {
    expect(parseSkillMetadataFromContent(skillContent)).toEqual({
      name: "short_drama_workshop",
      description: "短剧创作技能",
      content: skillContent.trim(),
      config: {
        display_name: "短剧创作工坊",
      },
    });
  });

  it("imports a generated skill into the selected workspace only", async () => {
    const onImported = vi.fn();
    const dispatchEvent = vi.spyOn(window, "dispatchEvent");

    const result = await importSkillFromContent(skillContent, {
      targetAgentId: "user-agent",
      onImported,
    });

    expect(result).toEqual({
      name: "short_drama_workshop",
      description: "短剧创作技能",
      renamed: false,
    });
    expect(createSkillPoolSkill).toHaveBeenCalledWith({
      name: "short_drama_workshop",
      content: skillContent.trim(),
      config: {
        display_name: "短剧创作工坊",
      },
      visibility: "private",
    });
    expect(downloadSkillPoolSkill).toHaveBeenCalledWith({
      skill_name: "short_drama_workshop",
      targets: [{ workspace_id: "user-agent" }],
      overwrite: true,
    });
    expect(enableSkill).toHaveBeenCalledWith("short_drama_workshop");
    expect(invalidateSkillCache).toHaveBeenCalledOnce();
    expect(onImported).toHaveBeenCalledWith({
      name: "short_drama_workshop",
      description: "短剧创作技能",
      renamed: false,
    });
    expect(dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "qwenpaw-skill-imported",
        detail: {
          name: "short_drama_workshop",
          description: "短剧创作技能",
          renamed: false,
        },
      }),
    );
  });

  it("uses backend conflict suggestions and rewrites the frontmatter name", async () => {
    createSkillPoolSkill
      .mockRejectedValueOnce(
        new Error(
          '409 Conflict - {"detail":{"reason":"conflict","suggested_name":"short_drama_workshop_2"}}',
        ),
      )
      .mockResolvedValueOnce({
        created: true,
        name: "short_drama_workshop_2",
      });

    const result = await importSkillFromContent(skillContent);

    expect(result).toEqual({
      name: "short_drama_workshop_2",
      description: "短剧创作技能",
      renamed: true,
    });
    expect(createSkillPoolSkill).toHaveBeenNthCalledWith(2, {
      name: "short_drama_workshop_2",
      content: expect.stringContaining("name: short_drama_workshop_2"),
      config: {
        display_name: "短剧创作工坊",
      },
      visibility: "private",
    });
    expect(enableSkill).toHaveBeenCalledWith("short_drama_workshop_2");
  });

  it("rejects content without skill frontmatter", async () => {
    await expect(importSkillFromContent("# plain markdown")).rejects.toThrow(
      "未能识别出有效的技能 YAML Metadata",
    );
  });
});
