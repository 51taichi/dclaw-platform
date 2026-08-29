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
      key: "agents",
      label: collapsed ? null : t("nav.agents"),
    },
    {
      key: "sealed-agents",
      label: collapsed ? null : "超级专家",
    },
  ];
}
