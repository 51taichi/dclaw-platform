import { request } from "./api";

export interface MobileAgentOption {
  id: string;
  name: string;
  description?: string;
}

export type MobileTaskMode = "craft" | "plan" | "ask" | "";

export interface MobileExpertModeOption {
  id: string;
  name: string;
  description?: string;
  badge?: string;
  tools?: string[];
  kind: "mode" | "agent";
  mode?: Exclude<MobileTaskMode, "">;
  agentId?: string;
}

export interface MobileSkillOption {
  id: string;
  name: string;
  description?: string;
  isDefault?: boolean;
  isPrivate?: boolean;
}

interface AgentListItem {
  id: string;
  name?: string;
  description?: string;
  enabled?: boolean;
}

interface AgentListResponse {
  agents?: AgentListItem[];
}

interface WorkspaceSkillSpec {
  name: string;
  description?: string;
  enabled?: boolean;
  visibility?: string;
  emoji?: string;
  client_visible?: boolean;
}

interface PoolSkillSpec {
  name: string;
  description?: string;
  visibility?: string;
  emoji?: string;
  client_visible?: boolean;
  config?: {
    display_name?: string;
    is_default?: boolean;
  };
}

export const TASK_MODE_OPTIONS: MobileExpertModeOption[] = [
  {
    id: "mode:craft",
    name: "Craft",
    badge: "推荐",
    description:
      "最强大的全自动执行模式。不仅能解答问题，还能读写文件、执行命令，完成端到端开发。",
    tools: ["文件读写操作", "终端命令执行", "自动化网页搜索"],
    kind: "mode",
    mode: "craft",
  },
  {
    id: "mode:plan",
    name: "Plan",
    description:
      "专注深度逻辑推理与全局架构设计。在编写代码前，提供清晰详尽的方案规划与任务拆解。",
    tools: ["深度逻辑推理", "架构方案设计", "开发任务拆解"],
    kind: "mode",
    mode: "plan",
  },
  {
    id: "mode:ask",
    name: "Ask",
    description:
      "专注纯粹的技术问答。响应迅速，绝对安全，不会对任何本地文件产生修改。",
    tools: ["快速技术咨询", "代码逻辑分析", "框架库知识检索"],
    kind: "mode",
    mode: "ask",
  },
];

function displayNameFor(skillName: string, poolSkill?: PoolSkillSpec): string {
  const displayName = poolSkill?.config?.display_name;
  return typeof displayName === "string" && displayName.trim()
    ? displayName.trim()
    : skillName;
}

function displayNameForAgent(agent: AgentListItem): string {
  const rawName = (agent.name || agent.id).trim();
  return rawName || agent.id;
}

function toSkillOption(
  skillName: string,
  description: string | undefined,
  poolSkill?: PoolSkillSpec,
  visibility?: string,
): MobileSkillOption {
  return {
    id: skillName,
    name: displayNameFor(skillName, poolSkill),
    description: description || poolSkill?.description || "",
    isDefault: poolSkill?.config?.is_default === true,
    isPrivate: (visibility || poolSkill?.visibility || "public") === "private",
  };
}

export function toSkillOptions(
  workspaceSkills: WorkspaceSkillSpec[],
  poolSkills: PoolSkillSpec[],
): MobileSkillOption[] {
  const poolByName = new Map(poolSkills.map((skill) => [skill.name, skill]));
  const enabledWorkspaceSkills = workspaceSkills.filter(
    (skill) =>
      skill.enabled !== false &&
      skill.client_visible !== false &&
      poolByName.get(skill.name)?.client_visible !== false,
  );
  const enabledNames = new Set(
    enabledWorkspaceSkills.map((skill) => skill.name),
  );

  const installed = enabledWorkspaceSkills.map((skill) =>
    toSkillOption(
      skill.name,
      skill.description,
      poolByName.get(skill.name),
      skill.visibility,
    ),
  );
  const defaultPool = poolSkills
    .filter(
      (skill) =>
        skill.client_visible !== false &&
        skill.config?.is_default === true &&
        !enabledNames.has(skill.name),
    )
    .map((skill) =>
      toSkillOption(skill.name, skill.description, skill, skill.visibility),
    );

  return [...installed, ...defaultPool];
}

export function formatTaskPrompt(
  prompt: string,
  selectedSkill?: MobileSkillOption | null,
  activeMode: MobileTaskMode = "craft",
): string {
  let normalizedPrompt = prompt.trim();
  if (activeMode === "plan") {
    normalizedPrompt = `/plan ${normalizedPrompt}`;
  } else if (activeMode === "ask") {
    normalizedPrompt = `[Ask Mode: 仅回答问题，不要执行任何文件操作、命令执行或工具调用]\n${normalizedPrompt}`;
  }
  if (!selectedSkill) {
    return normalizedPrompt;
  }
  return `/[${selectedSkill.id}]\n\n${normalizedPrompt}`;
}

export function isTaskMode(
  value: string,
): value is Exclude<MobileTaskMode, ""> {
  return value === "craft" || value === "plan" || value === "ask";
}

export function toExpertModeOptions(
  agents: MobileAgentOption[],
): MobileExpertModeOption[] {
  const expertOptions = agents
    .filter((agent) => agent.id !== "default")
    .map((agent) => ({
      id: `agent:${agent.id}`,
      name: agent.name,
      description: agent.description || agent.id,
      kind: "agent" as const,
      agentId: agent.id,
    }));
  return [...TASK_MODE_OPTIONS, ...expertOptions];
}

export function expertModeOptionIdFor(
  activeMode: MobileTaskMode,
  agentId: string,
): string {
  return activeMode ? `mode:${activeMode}` : `agent:${agentId}`;
}

export function parseExpertModeOptionId(optionId: string): {
  mode?: Exclude<MobileTaskMode, "">;
  agentId?: string;
} {
  if (optionId.startsWith("mode:")) {
    const mode = optionId.slice("mode:".length);
    return isTaskMode(mode) ? { mode } : {};
  }
  if (optionId.startsWith("agent:")) {
    return { agentId: optionId.slice("agent:".length) };
  }
  return {};
}

export async function listAgentOptions(): Promise<MobileAgentOption[]> {
  const response = await request<AgentListResponse>("/agents");
  const agents = Array.isArray(response.agents) ? response.agents : [];
  return agents
    .filter((agent) => agent.enabled !== false)
    .map((agent) => ({
      id: agent.id,
      name: displayNameForAgent(agent),
      description: agent.description || "",
    }));
}

async function fetchSkillOptions(
  agentId: string,
  refresh = false,
): Promise<MobileSkillOption[]> {
  const [workspaceSkills, poolSkills] = await Promise.all([
    request<WorkspaceSkillSpec[]>(refresh ? "/skills/refresh" : "/skills", {
      method: refresh ? "POST" : "GET",
      header: {
        "X-Agent-Id": agentId,
      },
    }).catch(() => []),
    request<PoolSkillSpec[]>(
      refresh ? "/skills/pool/refresh" : "/skills/pool",
      refresh ? { method: "POST" } : {},
    ).catch(() => []),
  ]);
  return toSkillOptions(workspaceSkills, poolSkills);
}

export async function listSkillOptions(
  agentId: string,
): Promise<MobileSkillOption[]> {
  const initial = await fetchSkillOptions(agentId);
  if (initial.length) {
    return initial;
  }
  return fetchSkillOptions(agentId, true);
}

export function getExpertModeSelectionUnavailableMessage(
  _options: MobileAgentOption[],
): string {
  return "";
}

export function getSkillSelectionUnavailableMessage(
  options: MobileSkillOption[],
): string {
  return options.length === 0 ? "暂无可选技能" : "";
}
