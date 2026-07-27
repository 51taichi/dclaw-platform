import type { PoolSkillSpec } from "../../../api/types";

export type SkillPublishScope = "private" | "public" | "default";

export function normalizeSkillPublishScope(
  value: unknown,
): SkillPublishScope {
  return value === "private" || value === "default" ? value : "public";
}

export function getSkillPublishScope(skill: PoolSkillSpec): SkillPublishScope {
  if (skill.config?.is_default === true) return "default";
  return skill.visibility === "private" ? "private" : "public";
}

export function applyPublishScope(
  scope: SkillPublishScope,
  config: Record<string, unknown>,
): { visibility: "private" | "public"; config: Record<string, unknown> } {
  const nextConfig = { ...config };

  if (scope === "default") {
    nextConfig.is_default = true;
    return { visibility: "public", config: nextConfig };
  }

  delete nextConfig.is_default;
  return {
    visibility: scope === "private" ? "private" : "public",
    config: nextConfig,
  };
}

export function isPrivateSkillPromotion(
  skill: PoolSkillSpec,
  nextScope: SkillPublishScope,
): boolean {
  return getSkillPublishScope(skill) === "private" && nextScope !== "private";
}

export function formatPrivateOwnerLabel(
  privateLabel: string,
  ownerUserId?: string,
): string {
  const owner = String(ownerUserId || "").trim();
  return owner ? `${privateLabel}: ${owner}` : privateLabel;
}
