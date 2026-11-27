import type { ReactNode } from "react";
import type { PoolSkillSpec, SkillSpec } from "../../../api/types";

export interface ToolbarSkillItem {
  /** Backend skill name used for invocation and API calls. */
  id: string;
  /** User-facing label. Kept as name for existing UI consumers. */
  name: string;
  displayName: string;
  desc: string;
  icon: ReactNode;
  color: string;
  isDefault?: boolean;
  isPrivate?: boolean;
}

export type SkillUIPropsResolver = (name: string) => {
  color: string;
  icon: ReactNode;
};

function displayNameFor(skillName: string, poolSkill?: PoolSkillSpec): string {
  const displayName = poolSkill?.config?.display_name;
  return typeof displayName === "string" && displayName.trim()
    ? displayName.trim()
    : skillName;
}

function iconFor(
  fallbackIcon: ReactNode,
  skill?: SkillSpec,
  poolSkill?: PoolSkillSpec,
): ReactNode {
  const configIcon = poolSkill?.config?.icon;
  if (configIcon && typeof configIcon !== "string") {
    return configIcon as ReactNode;
  }
  return skill?.emoji || poolSkill?.emoji || fallbackIcon;
}

export function buildToolbarSkillItems(
  workspaceSkills: SkillSpec[],
  poolSkills: PoolSkillSpec[],
  getUiProps: SkillUIPropsResolver,
): ToolbarSkillItem[] {
  const enabled = (workspaceSkills || []).filter(
    (skill) => skill.enabled !== false && skill.client_visible !== false,
  );
  const poolByName = new Map(poolSkills.map((skill) => [skill.name, skill]));

  const mapped = enabled
    .filter((skill) => poolByName.get(skill.name)?.client_visible !== false)
    .map((skill): ToolbarSkillItem => {
      const poolSkill = poolByName.get(skill.name);
      const { color, icon } = getUiProps(skill.name);
      const displayName = displayNameFor(skill.name, poolSkill);

      return {
        id: skill.name,
        name: displayName,
        displayName,
        desc: skill.description || poolSkill?.description || "",
        icon: iconFor(icon, skill, poolSkill),
        color,
        isDefault: poolSkill?.config?.is_default === true,
        isPrivate:
          (poolSkill?.visibility || skill.visibility || "public") === "private",
      };
    });

  const enabledNames = new Set(enabled.map((skill) => skill.name));
  const defaultPoolSkills = poolSkills
    .filter(
      (skill) =>
        skill.client_visible !== false &&
        skill.config?.is_default === true &&
        !enabledNames.has(skill.name),
    )
    .map((skill): ToolbarSkillItem => {
      const { color, icon } = getUiProps(skill.name);
      const displayName = displayNameFor(skill.name, skill);

      return {
        id: skill.name,
        name: displayName,
        displayName,
        desc: skill.description || "",
        icon: iconFor(icon, undefined, skill),
        color,
        isDefault: true,
        isPrivate: (skill.visibility || "public") === "private",
      };
    });

  return [...mapped, ...defaultPoolSkills];
}

export function getSkillInvocationName(
  skill: Pick<ToolbarSkillItem, "id" | "name">,
): string {
  return skill.id || skill.name;
}

export function matchesSkillSearch(
  skill: ToolbarSkillItem,
  search: string,
): boolean {
  if (!search) return true;

  const searchLower = search.toLowerCase();
  const searchNormalized = searchLower.replace(/-/g, "_");
  const candidates = [skill.name, skill.displayName, skill.id, skill.desc]
    .filter(Boolean)
    .map((value) => value.toLowerCase());

  return candidates.some((value) => {
    const normalized = value.replace(/-/g, "_");
    return value.includes(searchLower) || normalized.includes(searchNormalized);
  });
}
