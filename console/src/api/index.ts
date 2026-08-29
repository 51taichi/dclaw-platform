export * from "./types";
export type { AdminUser } from "./modules/adminUsers";

export { request } from "./request";

export { getApiUrl, getApiToken } from "./config";

import { rootApi } from "./modules/root";
import { acpApi } from "./modules/acp";
import { channelApi } from "./modules/channel";
import { heartbeatApi } from "./modules/heartbeat";
import { cronJobApi } from "./modules/cronjob";
import { chatApi, sessionApi } from "./modules/chat";
import { envApi } from "./modules/env";
import { providerApi } from "./modules/provider";
import { skillApi } from "./modules/skill";
import { agentApi } from "./modules/agent";
import { agentsApi } from "./modules/agents";
import { workspaceApi } from "./modules/workspace";
import { localModelApi } from "./modules/localModel";
import { mcpApi } from "./modules/mcp";
import { tokenUsageApi } from "./modules/tokenUsage";
import { agentStatsApi } from "./modules/agentStats";
import { toolsApi } from "./modules/tools";
import { securityApi } from "./modules/security";
import { userTimezoneApi } from "./modules/userTimezone";
import { languageApi } from "./modules/language";
import { backupApi } from "./modules/backup";
import { consoleApi } from "./modules/console";
import { auditApi } from "./modules/audit";
import { adminUsersApi } from "./modules/adminUsers";
import { expertTeamsApi } from "./modules/expertTeams";
import { desktopUpdateApi } from "./modules/desktopUpdate";
import { openApiApi } from "./modules/openApi";
import { webSearchApi } from "./modules/webSearch";
import { billingApi } from "./modules/billing";

export const api = {
  // Root
  ...rootApi,

  // ACP
  ...acpApi,

  // Channels
  ...channelApi,

  // Heartbeat
  ...heartbeatApi,

  // Cron Jobs
  ...cronJobApi,

  // Chats
  ...chatApi,

  // Sessions（Legacy aliases）
  ...sessionApi,

  // Environment Variables
  ...envApi,

  // Providers
  ...providerApi,

  // Agent
  ...agentApi,

  // Skills
  ...skillApi,

  // Workspace
  ...workspaceApi,

  // Local Models
  ...localModelApi,

  // MCP Clients
  ...mcpApi,

  // Token Usage
  ...tokenUsageApi,
  // Agent Statistics
  ...agentStatsApi,
  // Tools
  ...toolsApi,

  // Security
  ...securityApi,

  // User Timezone
  ...userTimezoneApi,

  // Language
  ...languageApi,

  // Backups
  ...backupApi,

  // Console
  ...consoleApi,

  // Audit
  ...auditApi,

  // Admin Users
  ...adminUsersApi,

  // Expert Teams
  ...expertTeamsApi,

  // Desktop Updates
  ...desktopUpdateApi,

  // Open API
  ...openApiApi,

  // Shared Web Search
  ...webSearchApi,

  // Billing
  ...billingApi,
};

export default api;

// Export individual APIs for direct access
export {
  agentsApi,
  adminUsersApi,
  expertTeamsApi,
  desktopUpdateApi,
  openApiApi,
  webSearchApi,
  billingApi,
};
