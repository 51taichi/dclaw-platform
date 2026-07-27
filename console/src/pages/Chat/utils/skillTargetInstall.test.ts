import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ensureSkillInstalledForAgent,
  resolveSkillInstallAgentId,
} from "./skillTargetInstall";

const {
  downloadSkillPoolSkill,
  enableSkill,
  invalidateSkillCache,
  importSelectedPoolBuiltins,
  listSkillPoolSkills,
  refreshSkills,
} = vi.hoisted(() => ({
  downloadSkillPoolSkill: vi.fn(),
  enableSkill: vi.fn(),
  invalidateSkillCache: vi.fn(),
  importSelectedPoolBuiltins: vi.fn(),
  listSkillPoolSkills: vi.fn(),
  refreshSkills: vi.fn(),
}));

vi.mock("../../../api/modules/skill", () => ({
  skillApi: {
    downloadSkillPoolSkill,
    enableSkill,
    importSelectedPoolBuiltins,
    listSkillPoolSkills,
    refreshSkills,
  },
  invalidateSkillCache,
}));

const selectedSkill = {
  id: "short_drama_workshop",
  name: "短剧创作工坊",
};

describe("skillTargetInstall", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    refreshSkills.mockResolvedValue([]);
    listSkillPoolSkills.mockResolvedValue([]);
    downloadSkillPoolSkill.mockResolvedValue({ downloaded: [] });
    importSelectedPoolBuiltins.mockResolvedValue({
      imported: [],
      updated: [],
      unchanged: [],
      conflicts: [],
    });
    enableSkill.mockResolvedValue(undefined);
  });

  it("uses the expert team leader as the only install target", () => {
    const expertTeam = {
      id: "video-team",
      leader_agent_id: "content_creation",
      members: [{ agent_id: "data_analysis" }, { agent_id: "fullstack_dev" }],
    };

    const agentId = resolveSkillInstallAgentId({
      selectedAgent: "default",
      expertTeam,
    });

    expect(agentId).toBe("content_creation");
  });

  it("downloads a missing selected skill into the target agent and enables it", async () => {
    await ensureSkillInstalledForAgent(selectedSkill, "content_creation");

    expect(refreshSkills).toHaveBeenCalledWith("content_creation");
    expect(downloadSkillPoolSkill).toHaveBeenCalledWith({
      skill_name: "short_drama_workshop",
      targets: [{ workspace_id: "content_creation" }],
      overwrite: false,
    });
    expect(enableSkill).toHaveBeenCalledWith(
      "short_drama_workshop",
      "content_creation",
    );
    expect(invalidateSkillCache).toHaveBeenCalledWith({
      agentId: "content_creation",
    });
  });

  it("does not reinstall a skill that is already enabled in the target agent", async () => {
    refreshSkills.mockResolvedValue([
      { name: "short_drama_workshop", enabled: true },
    ]);

    await ensureSkillInstalledForAgent(selectedSkill, "content_creation");

    expect(downloadSkillPoolSkill).not.toHaveBeenCalled();
    expect(enableSkill).not.toHaveBeenCalled();
  });

  it("updates an outdated builtin selected from the chat toolbar before running it", async () => {
    refreshSkills.mockResolvedValue([
      {
        name: "editable-ppt-visual-builder",
        enabled: true,
        source: "builtin",
        version_text: "2.0",
      },
    ]);
    listSkillPoolSkills.mockResolvedValue([
      {
        name: "editable-ppt-visual-builder",
        description: "可编辑 PPT 视觉设计师",
        content: "",
        source: "builtin",
        protected: false,
        version_text: "2.0",
        sync_status: "outdated",
        latest_version_text: "2.1",
      },
    ]);

    await ensureSkillInstalledForAgent(
      {
        id: "editable-ppt-visual-builder",
        name: "可编辑 PPT 视觉设计师",
      },
      "default",
    );

    expect(importSelectedPoolBuiltins).toHaveBeenCalledWith({
      imports: [{ skill_name: "editable-ppt-visual-builder", language: "zh" }],
      overwrite_conflicts: true,
    });
    expect(downloadSkillPoolSkill).toHaveBeenCalledWith({
      skill_name: "editable-ppt-visual-builder",
      targets: [{ workspace_id: "default" }],
      overwrite: true,
    });
    expect(enableSkill).not.toHaveBeenCalled();
  });

  it("overwrites an older workspace builtin when the pool copy is already current", async () => {
    refreshSkills.mockResolvedValue([
      {
        name: "editable-ppt-visual-builder",
        enabled: true,
        source: "builtin",
        version_text: "2.0",
      },
    ]);
    listSkillPoolSkills.mockResolvedValue([
      {
        name: "editable-ppt-visual-builder",
        description: "可编辑 PPT 视觉设计师",
        content: "",
        source: "builtin",
        protected: false,
        version_text: "2.1",
        sync_status: "synced",
        latest_version_text: "",
      },
    ]);

    await ensureSkillInstalledForAgent(
      {
        id: "editable-ppt-visual-builder",
        name: "可编辑 PPT 视觉设计师",
      },
      "default",
    );

    expect(importSelectedPoolBuiltins).not.toHaveBeenCalled();
    expect(downloadSkillPoolSkill).toHaveBeenCalledWith({
      skill_name: "editable-ppt-visual-builder",
      targets: [{ workspace_id: "default" }],
      overwrite: true,
    });
  });
});
