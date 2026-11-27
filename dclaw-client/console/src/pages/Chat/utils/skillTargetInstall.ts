import { skillApi, invalidateSkillCache } from "../../../api/modules/skill";
import type { PoolSkillSpec, SkillSpec } from "../../../api/types";
import {
  getSkillInvocationName,
  type ToolbarSkillItem,
} from "../components/skillToolbarModel";

const MODE_AGENT_IDS = new Set(["craft", "plan", "ask"]);

interface ExpertTeamLike {
  leader_agent_id?: string | null;
}

export function resolveSkillInstallAgentId({
  selectedAgent,
  expertTeam,
}: {
  selectedAgent?: string | null;
  expertTeam?: ExpertTeamLike | null;
}): string {
  const leaderAgentId = expertTeam?.leader_agent_id?.trim();
  if (leaderAgentId) return leaderAgentId;

  const agentId = selectedAgent?.trim();
  if (!agentId || MODE_AGENT_IDS.has(agentId)) return "default";
  return agentId;
}

function isBuiltinSkillVersionBehind(
  existing: SkillSpec | undefined,
  poolSkill: PoolSkillSpec | undefined,
): boolean {
  if (!existing || !poolSkill) return false;
  if (existing.source !== "builtin" || poolSkill.source !== "builtin") {
    return false;
  }

  const currentVersion = (existing.version_text || "").trim();
  const targetVersion = (
    poolSkill.latest_version_text ||
    poolSkill.version_text ||
    ""
  ).trim();

  if (poolSkill.sync_status === "outdated") {
    return !currentVersion || !targetVersion || currentVersion !== targetVersion;
  }

  return Boolean(
    currentVersion && targetVersion && currentVersion !== targetVersion,
  );
}

export async function ensureSkillInstalledForAgent(
  skill: Pick<ToolbarSkillItem, "id" | "name">,
  targetAgentId: string,
): Promise<void> {
  const skillName = getSkillInvocationName(skill).trim();
  if (!skillName) return;

  const agentId = resolveSkillInstallAgentId({ selectedAgent: targetAgentId });
  const [workspaceSkills, poolSkills] = await Promise.all([
    skillApi.refreshSkills(agentId),
    skillApi.listSkillPoolSkills().catch(() => []),
  ]);
  const existing = workspaceSkills.find((item) => item.name === skillName);
  const poolSkill = poolSkills.find((item) => item.name === skillName);
  const poolBuiltinNeedsRefresh =
    poolSkill?.source === "builtin" && poolSkill.sync_status === "outdated";
  const workspaceBuiltinNeedsOverwrite = isBuiltinSkillVersionBehind(
    existing,
    poolSkill,
  );

  if (poolBuiltinNeedsRefresh) {
    await skillApi.importSelectedPoolBuiltins({
      imports: [{ skill_name: skillName, language: "zh" }],
      overwrite_conflicts: true,
    });
    invalidateSkillCache({ pool: true });
  }

  if (!existing || workspaceBuiltinNeedsOverwrite) {
    await skillApi.downloadSkillPoolSkill({
      skill_name: skillName,
      targets: [{ workspace_id: agentId }],
      overwrite: workspaceBuiltinNeedsOverwrite,
    });
  }

  if (!existing?.enabled) {
    await skillApi.enableSkill(skillName, agentId);
  }

  invalidateSkillCache({
    agentId,
    pool: poolBuiltinNeedsRefresh || undefined,
  });
}
