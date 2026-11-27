import { describe, expect, it } from "vitest";
import {
  buildSkillMarketItems,
  filterSkillMarketItems,
  getSkillMarketActionState,
} from "./skillMarketModel";
import type { PoolSkillSpec } from "../../api/types";

describe("skillMarketModel", () => {
  it("uses pool display metadata while keeping the backend skill name", () => {
    const skills: PoolSkillSpec[] = [
      {
        name: "editable-ppt-visual-builder",
        description: "设计公司级可编辑 PPT 生成技能",
        content: "",
        source: "builtin",
        protected: false,
        visibility: "public",
        config: {
          display_name: "可编辑 PPT 视觉设计师",
          market_category: "office",
          icon: "presentation",
        },
        tags: ["PPT", "GPT Image2"],
      },
    ];

    const [item] = buildSkillMarketItems(skills);

    expect(item.name).toBe("可编辑 PPT 视觉设计师");
    expect(item.backendSkillName).toBe("editable-ppt-visual-builder");
    expect(item.category).toBe("office");
    expect(item.tags).toEqual(["PPT", "GPT Image2"]);
  });

  it("keeps builtin sync status so outdated skills can be updated", () => {
    const [item] = buildSkillMarketItems([
      {
        name: "editable-ppt-visual-builder",
        description: "设计公司级可编辑 PPT 生成技能",
        content: "",
        source: "builtin",
        protected: false,
        visibility: "public",
        version_text: "2.0",
        sync_status: "outdated",
        latest_version_text: "2.1",
        config: { display_name: "可编辑 PPT 视觉设计师" },
        tags: ["PPT", "GPT Image2"],
      },
    ]);

    expect(item.syncStatus).toBe("outdated");
    expect(item.version).toBe("2.0");
    expect(item.latestVersion).toBe("2.1");
    expect(getSkillMarketActionState(item, true, false)).toBe("update");
  });

  it("does not turn already-current installed skills into update actions", () => {
    const [item] = buildSkillMarketItems([
      {
        name: "browser_visible",
        description: "Browser control",
        content: "",
        source: "builtin",
        protected: false,
        visibility: "public",
        sync_status: "synced",
        config: {},
      },
    ]);

    expect(getSkillMarketActionState(item, true, false)).toBe("installed");
    expect(getSkillMarketActionState(item, false, false)).toBe("install");
    expect(getSkillMarketActionState(item, false, true)).toBe("operating");
  });

  it("searches top-level pool tags from imported builtin skills", () => {
    const items = buildSkillMarketItems([
      {
        name: "editable-ppt-visual-builder",
        description: "设计公司级可编辑 PPT 生成技能",
        content: "",
        source: "builtin",
        protected: false,
        visibility: "public",
        config: { display_name: "可编辑 PPT 视觉设计师" },
        tags: ["PPT", "GPT Image2"],
      },
    ]);

    expect(filterSkillMarketItems(items, "all", "GPT Image2")).toHaveLength(1);
    expect(filterSkillMarketItems(items, "all", "editable-ppt")).toHaveLength(
      1,
    );
  });

  it("only exposes visible public non-default skills as marketplace installs", () => {
    const items = buildSkillMarketItems([
      {
        name: "public_tool",
        description: "Install from market",
        content: "",
        source: "customized",
        protected: false,
        visibility: "public",
        client_visible: true,
        config: { display_name: "公共工具" },
      },
      {
        name: "default_tool",
        description: "Already default installed",
        content: "",
        source: "customized",
        protected: false,
        visibility: "public",
        client_visible: true,
        config: { is_default: true },
      },
      {
        name: "private_tool",
        description: "Owned by one user",
        content: "",
        source: "customized",
        protected: false,
        visibility: "private",
        client_visible: true,
        config: {},
      },
      {
        name: "hidden_tool",
        description: "Hidden from clients",
        content: "",
        source: "customized",
        protected: false,
        visibility: "public",
        client_visible: false,
        config: {},
      },
    ]);

    expect(items.map((item) => item.backendSkillName)).toEqual(["public_tool"]);
  });
});
