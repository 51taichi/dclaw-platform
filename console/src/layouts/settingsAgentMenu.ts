export type TranslateMenuLabel = (key: string, fallback?: string) => string;

export interface AgentManagementMenuItem {
  key: "agents" | "sealed-agents";
  label: string | null;
}

export function getAgentManagementMenuItems(
  collapsed: boolean,
  t: TranslateMenuLabel,
): AgentManagementMenuItem[] {
  return [
    {
      key: "sealed-agents",
      label: collapsed ? null : "密封/Agent",
    },
    {
      key: "agents",
      label: collapsed ? null : t("nav.agents"),
    },
  ];
}
