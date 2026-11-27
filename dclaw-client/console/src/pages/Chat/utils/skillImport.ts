import { skillApi, invalidateSkillCache } from "../../../api/modules/skill";

export interface ParsedSkillMetadata {
  name: string;
  description: string;
  content: string;
  config?: Record<string, unknown>;
}

export interface ImportedSkillResult {
  name: string;
  description: string;
  renamed: boolean;
}

interface ImportSkillOptions {
  targetAgentId?: string;
  onImported?: (result: ImportedSkillResult) => void;
}

export function parseSkillMetadataFromContent(
  content: string,
): ParsedSkillMetadata | null {
  const fmRegex =
    /---[\s\S]*?name:\s*([^\r\n]+)[\s\S]*?description:\s*([^\r\n]+)[\s\S]*?---/i;
  const match = content.match(fmRegex);
  if (!match) return null;

  const displayNameMatch = content.match(
    /config:\s*(?:\r?\n[ \t]+[^\r\n]*)*?\r?\n[ \t]+display_name:\s*([^\r\n]+)/i,
  );
  const displayName = displayNameMatch?.[1]?.trim().replace(/['"]/g, "");
  const config = displayName ? { display_name: displayName } : undefined;

  return {
    name: match[1].trim().replace(/['"]/g, ""),
    description: match[2].trim().replace(/['"]/g, ""),
    content: content.trim(),
    ...(config ? { config } : {}),
  };
}

function extractConflictSuggestion(error: unknown): string | null {
  const rawMessage =
    error instanceof Error
      ? error.message
      : typeof error === "string"
      ? error
      : "";
  if (!rawMessage) return null;

  const possibleJson = rawMessage.includes(" - ")
    ? rawMessage.split(" - ")[1]
    : rawMessage;

  try {
    const parsed = JSON.parse(possibleJson);
    const detail = parsed?.detail;
    if (
      detail?.reason === "conflict" &&
      typeof detail.suggested_name === "string"
    ) {
      return detail.suggested_name;
    }
  } catch {
    return null;
  }

  return null;
}

function rewriteFrontmatterName(content: string, name: string): string {
  return content.replace(
    /(---[\s\S]*?name:\s*)([^\r\n]+)([\s\S]*?---)/i,
    `$1${name}$3`,
  );
}

export async function importSkillFromContent(
  content: string,
  options: ImportSkillOptions = {},
): Promise<ImportedSkillResult> {
  const parsed = parseSkillMetadataFromContent(content);
  if (!parsed) {
    throw new Error("未能识别出有效的技能 YAML Metadata");
  }

  let targetName = parsed.name;
  let finalContent = parsed.content;
  let renamed = false;

  try {
    const created = await skillApi.createSkillPoolSkill({
      name: targetName,
      content: finalContent,
      config: parsed.config,
      visibility: "private",
    });
    if (created.name) targetName = created.name;
  } catch (error) {
    const suggestedName = extractConflictSuggestion(error);
    if (!suggestedName) throw error;

    targetName = suggestedName;
    finalContent = rewriteFrontmatterName(finalContent, targetName);
    renamed = true;

    const created = await skillApi.createSkillPoolSkill({
      name: targetName,
      content: finalContent,
      config: parsed.config,
      visibility: "private",
    });
    if (created.name) targetName = created.name;
  }

  await skillApi.downloadSkillPoolSkill({
    skill_name: targetName,
    targets: [{ workspace_id: options.targetAgentId || "default" }],
    overwrite: true,
  });
  await skillApi.enableSkill(targetName);
  invalidateSkillCache();
  window.dispatchEvent(new CustomEvent("refresh-chat-skills"));

  const result: ImportedSkillResult = {
    name: targetName,
    description: parsed.description,
    renamed,
  };
  window.dispatchEvent(
    new CustomEvent("qwenpaw-skill-imported", { detail: result }),
  );
  options.onImported?.(result);
  return result;
}
