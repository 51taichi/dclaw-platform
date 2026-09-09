import type { AgentSummary } from "../api/types/agents";

export interface ExpertIdentity {
  name: string;
  avatar: string;
  isSuperExpert: boolean;
}

export function expertAvatar(
  agent: Pick<AgentSummary, "id" | "name" | "avatar" | "agent_type">,
): string {
  if (agent.avatar) return agent.avatar;
  if (agent.agent_type !== "sealed") return "/dclaw.png";
  const initial = Array.from(agent.name || agent.id)[0].replace(/[<>&"']/g, "");
  return `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" rx="32" fill="#b7791f"/><text x="32" y="43" text-anchor="middle" font-size="32" fill="white">${initial}</text></svg>`,
  )}`;
}

export function expertIdentity(agent?: AgentSummary | null): ExpertIdentity {
  if (agent?.agent_type !== "sealed")
    return { name: "DClaw", avatar: "/mascot.png", isSuperExpert: false };
  return { name: agent.name, avatar: expertAvatar(agent), isSuperExpert: true };
}
