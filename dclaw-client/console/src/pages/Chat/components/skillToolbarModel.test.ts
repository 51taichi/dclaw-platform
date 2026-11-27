import { describe, expect, it } from "vitest";
import {
  buildToolbarSkillItems,
  getSkillInvocationName,
  matchesSkillSearch,
} from "./skillToolbarModel";
import type { PoolSkillSpec, SkillSpec } from "../../../api/types";

const uiProps = (name: string) => ({
  color: `color:${name}`,
  icon: `icon:${name}`,
});

describe("skillToolbarModel", () => {
  it("keeps backend skill identity separate from the display name", () => {
    const workspaceSkills: SkillSpec[] = [
      {
        name: "skill_creator",
        description: "Workspace description",
        content: "",
        source: "workspace",
        enabled: true,
      },
    ];
    const poolSkills: PoolSkillSpec[] = [
      {
        name: "skill_creator",
        description: "Pool description",
        content: "",
        source: "pool",
        protected: true,
        visibility: "public",
        config: {
          display_name: "技能生成器",
          is_default: true,
          icon: "tool",
        },
      },
    ];

    const [item] = buildToolbarSkillItems(workspaceSkills, poolSkills, uiProps);

    expect(item.id).toBe("skill_creator");
    expect(item.name).toBe("技能生成器");
    expect(item.displayName).toBe("技能生成器");
    expect(getSkillInvocationName(item)).toBe("skill_creator");
    expect(item.desc).toBe("Workspace description");
    expect(item.isDefault).toBe(true);
  });

  it("marks private skills by backend name even when display names differ", () => {
    const workspaceSkills: SkillSpec[] = [
      {
        name: "short_drama_workshop_20260530",
        description: "",
        content: "",
        source: "workspace",
        enabled: true,
      },
    ];
    const poolSkills: PoolSkillSpec[] = [
      {
        name: "short_drama_workshop_20260530",
        description: "专注短剧创作",
        content: "",
        source: "pool",
        protected: false,
        visibility: "private",
        config: {
          display_name: "短剧创作工坊",
        },
      },
    ];

    const [item] = buildToolbarSkillItems(workspaceSkills, poolSkills, uiProps);

    expect(item.id).toBe("short_drama_workshop_20260530");
    expect(item.name).toBe("短剧创作工坊");
    expect(item.isPrivate).toBe(true);
  });

  it("keeps generated timestamp suffixes visible without an explicit display name", () => {
    const [item] = buildToolbarSkillItems(
      [
        {
          name: "短剧创作工坊-20260528055448",
          description: "",
          content: "",
          source: "workspace",
          enabled: true,
        },
      ],
      [
        {
          name: "短剧创作工坊-20260528055448",
          description: "短剧脚本创作",
          content: "",
          source: "pool",
          protected: false,
          visibility: "private",
        },
      ],
      uiProps,
    );

    expect(item.id).toBe("短剧创作工坊-20260528055448");
    expect(item.name).toBe("短剧创作工坊-20260528055448");
    expect(getSkillInvocationName(item)).toBe("短剧创作工坊-20260528055448");
  });

  it("adds default pool skills that are not enabled yet", () => {
    const poolSkills: PoolSkillSpec[] = [
      {
        name: "skill_creator",
        description: "Generate skills",
        content: "",
        source: "pool",
        protected: true,
        visibility: "public",
        config: {
          display_name: "技能生成器",
          is_default: true,
        },
      },
    ];

    const [item] = buildToolbarSkillItems([], poolSkills, uiProps);

    expect(item.id).toBe("skill_creator");
    expect(item.name).toBe("技能生成器");
    expect(item.isDefault).toBe(true);
    expect(item.isPrivate).toBe(false);
  });

  it("does not render marketplace icon names as toolbar icons", () => {
    const [item] = buildToolbarSkillItems(
      [],
      [
        {
          name: "editable-ppt-visual-builder",
          description: "Generate visual PPT decks",
          content: "",
          source: "pool",
          protected: true,
          visibility: "public",
          emoji: "📊",
          config: {
            display_name: "可编辑 PPT 视觉设计师",
            is_default: true,
            icon: "presentation",
          },
        },
      ],
      uiProps,
    );

    expect(item.icon).toBe("📊");
  });

  it("filters hidden installed and hidden default pool skills from the toolbar", () => {
    const items = buildToolbarSkillItems(
      [
        {
          name: "visible_installed",
          description: "Visible installed skill",
          content: "",
          source: "workspace",
          enabled: true,
        },
        {
          name: "hidden_installed",
          description: "Hidden installed skill",
          content: "",
          source: "workspace",
          enabled: true,
          client_visible: false,
        },
      ],
      [
        {
          name: "hidden_installed",
          description: "Hidden installed skill",
          content: "",
          source: "pool",
          protected: false,
          visibility: "public",
          client_visible: false,
        },
        {
          name: "hidden_default",
          description: "Hidden default skill",
          content: "",
          source: "pool",
          protected: false,
          visibility: "public",
          client_visible: false,
          config: { is_default: true },
        },
      ],
      uiProps,
    );

    expect(items.map((item) => item.id)).toEqual(["visible_installed"]);
  });

  it("searches display name, backend name, and description", () => {
    const item = buildToolbarSkillItems(
      [
        {
          name: "short_drama_workshop",
          description: "",
          content: "",
          source: "workspace",
          enabled: true,
        },
      ],
      [
        {
          name: "short_drama_workshop",
          description: "短剧脚本创作",
          content: "",
          source: "pool",
          protected: false,
          visibility: "private",
          config: { display_name: "短剧创作工坊" },
        },
      ],
      uiProps,
    )[0];

    expect(matchesSkillSearch(item, "短剧")).toBe(true);
    expect(matchesSkillSearch(item, "short-drama")).toBe(true);
    expect(matchesSkillSearch(item, "脚本")).toBe(true);
    expect(matchesSkillSearch(item, "spreadsheet")).toBe(false);
  });
});
