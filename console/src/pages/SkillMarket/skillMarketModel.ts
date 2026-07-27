import type { PoolSkillSpec, SkillSyncStatus } from "../../api/types";

export type SkillMarketActionState =
  | "operating"
  | "update"
  | "installed"
  | "install";

export interface SkillMarketItem {
  name: string;
  description: string;
  version?: string;
  latestVersion?: string;
  syncStatus?: SkillSyncStatus | "";
  author?: string;
  downloads?: number;
  tags?: string[];
  icon?: string;
  category?: string;
  backendSkillName: string;
  isBuiltin: boolean;
}

function stringConfigValue(
  config: Record<string, unknown>,
  key: string,
  fallback = "",
): string {
  const value = config[key];
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function numberConfigValue(
  config: Record<string, unknown>,
  key: string,
): number {
  const value = config[key];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function normalizeTags(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((tag) => String(tag).trim()).filter((tag) => tag.length > 0);
}

export function buildSkillMarketItems(
  poolSkills: PoolSkillSpec[],
): SkillMarketItem[] {
  return poolSkills
    .filter((skill) => {
      const visibility = skill.visibility || "public";
      const isDefault = skill.config?.is_default === true;
      return (
        visibility === "public" && skill.client_visible !== false && !isDefault
      );
    })
    .map((skill) => {
      const config = skill.config || {};
      const topLevelTags = normalizeTags(skill.tags);
      const configTags = normalizeTags(config.tags);
      const tags = topLevelTags.length
        ? topLevelTags
        : configTags.length
        ? configTags
        : [];

      return {
        name: stringConfigValue(config, "display_name", skill.name),
        description: skill.description || "",
        tags,
        icon: stringConfigValue(config, "icon", "default"),
        category: stringConfigValue(config, "market_category", "dev"),
        version: skill.version_text || "",
        latestVersion: skill.latest_version_text || "",
        syncStatus: skill.sync_status || "",
        downloads: numberConfigValue(config, "downloads"),
        author: stringConfigValue(config, "author", "Community"),
        backendSkillName: skill.name,
        isBuiltin: skill.source === "builtin",
      };
    });
}

export function isOutdatedBuiltinSkill(skill: SkillMarketItem): boolean {
  return skill.isBuiltin && skill.syncStatus === "outdated";
}

export function getSkillMarketActionState(
  skill: SkillMarketItem,
  isInstalled: boolean,
  isOperating: boolean | undefined,
): SkillMarketActionState {
  if (isOperating) return "operating";
  if (isOutdatedBuiltinSkill(skill)) return "update";
  return isInstalled ? "installed" : "install";
}

export function filterSkillMarketItems(
  items: SkillMarketItem[],
  activeCategory: string,
  searchQuery: string,
): SkillMarketItem[] {
  const query = searchQuery.trim().toLowerCase();

  return items.filter((skill) => {
    if (activeCategory !== "all" && activeCategory !== "recommended") {
      if (skill.category !== activeCategory) return false;
    }
    if (activeCategory === "recommended" && skill.category !== "recommended") {
      return false;
    }
    if (!query) return true;

    return (
      skill.name.toLowerCase().includes(query) ||
      skill.description.toLowerCase().includes(query) ||
      skill.backendSkillName.toLowerCase().includes(query) ||
      skill.tags?.some((tag) => tag.toLowerCase().includes(query))
    );
  });
}
