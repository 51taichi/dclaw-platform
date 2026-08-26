import { Suspense } from "react";
import { Layout, Spin } from "antd";
import { Routes, Route, useLocation, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "../Sidebar";
import Header from "../Header";
import ConsolePollService from "../../components/ConsolePollService";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { usePlugins } from "../../plugins/PluginContext";
import styles from "../index.module.less";
import { useAgentStore } from "../../stores/agentStore";
import { canInspectAgent } from "../../utils/agentCapabilities";

// All other pages are lazily loaded with automatic retry on chunk failure
const AgentConfigPage = lazyImportWithRetry("../../pages/Agent/Config");
const ModelsPage = lazyImportWithRetry("../../pages/Settings/Models");
const WebSearchPage = lazyImportWithRetry("../../pages/Settings/WebSearch");
const EnvironmentsPage = lazyImportWithRetry(
  "../../pages/Settings/Environments",
);
const ObjectStoragePage = lazyImportWithRetry(
  "../../pages/Settings/ObjectStorage",
);
const MindspaceCloudSettingsPage = lazyImportWithRetry(
  "../../pages/Settings/MindspaceCloud",
);
const EnterpriseKnowledgePage = lazyImportWithRetry(
  "../../pages/Settings/EnterpriseKnowledge",
);
const SecurityPage = lazyImportWithRetry("../../pages/Settings/Security");
const TokenUsagePage = lazyImportWithRetry("../../pages/Settings/TokenUsage");
const AuditChatsPage = lazyImportWithRetry("../../pages/Settings/AuditChats");
const AgentStatsPage = lazyImportWithRetry("../../pages/Settings/AgentStats");
const VoiceTranscriptionPage = lazyImportWithRetry(
  "../../pages/Settings/VoiceTranscription",
);
const AgentsPage = lazyImportWithRetry("../../pages/Settings/Agents");
const DebugPage = lazyImportWithRetry("../../pages/Settings/Debug");
const UsersPage = lazyImportWithRetry("../../pages/Settings/Users");
const BackupsPage = lazyImportWithRetry("../../pages/Settings/Backups");
const PluginManagerPage = lazyImportWithRetry(
  "../../pages/Settings/PluginManager",
);
const OpenApiPage = lazyImportWithRetry("../../pages/Settings/OpenApi");
const SealedAgentsPage = lazyImportWithRetry(
  "../../pages/Settings/SealedAgents",
);

const ChannelsPage = lazyImportWithRetry("../../pages/Control/Channels");
const SessionsPage = lazyImportWithRetry("../../pages/Control/Sessions");
const InboxPage = lazyImportWithRetry("../../pages/Inbox");
const CronJobsPage = lazyImportWithRetry("../../pages/Control/CronJobs");
const HeartbeatPage = lazyImportWithRetry("../../pages/Control/Heartbeat");

const SkillPoolPage = lazyImportWithRetry("../../pages/Settings/SkillPool");
const ExpertTeamsPage = lazyImportWithRetry("../../pages/Settings/ExpertTeams");
const ToolsPage = lazyImportWithRetry("../../pages/Agent/Tools");
const WorkspacePage = lazyImportWithRetry("../../pages/Agent/Workspace");
const MCPPage = lazyImportWithRetry("../../pages/Agent/MCP");
const ACPPage = lazyImportWithRetry("../../pages/Agent/ACP");

// ── Ecosystem pages (WorkBuddy-style) ─────────────────────────────────────────

const { Content } = Layout;

function InspectableAgentRoute({ children }: { children: React.ReactNode }) {
  const { selectedAgent, agents } = useAgentStore();
  return canInspectAgent(agents.find((agent) => agent.id === selectedAgent)) ? (
    <>{children}</>
  ) : (
    <Navigate to="/workbench" replace />
  );
}

const pathToKey: Record<string, string> = {
  "/workbench": "workbench",
  "/claw": "claw",
  "/experts": "experts",
  "/skill-market": "skill-market",
  "/explore": "explore",
  "/connectors": "connectors",
  "/automations": "automations",
  "/tencent-doc": "tencent-doc",
  "/admin/channels": "channels",
  "/admin/sessions": "sessions",
  "/admin/inbox": "inbox",
  "/admin/cron-jobs": "cron-jobs",
  "/admin/heartbeat": "heartbeat",

  "/admin/skill-pool": "skill-pool",
  "/admin/expert-teams": "expert-teams",
  "/admin/tools": "tools",
  "/admin/mcp": "mcp",
  "/admin/acp": "acp",
  "/admin/workspace": "workspace",
  "/admin/agents": "agents",
  "/admin/models": "models",
  "/admin/web-search": "web-search",
  "/admin/environments": "environments",
  "/admin/object-storage": "object-storage",
  "/admin/mindspace-cloud": "mindspace-cloud",
  "/admin/enterprise-knowledge": "enterprise-knowledge",
  "/admin/agent-config": "agent-config",
  "/admin/security": "security",
  "/admin/token-usage": "token-usage",
  "/admin/audit-chats": "audit-chats",
  "/admin/agent-stats": "agent-stats",
  "/admin/users": "users",
  "/admin/voice-transcription": "voice-transcription",
  "/admin/debug": "debug",
  "/admin/backups": "backups",
  "/admin/plugin-manager": "plugin-manager",
  "/admin/open-api": "open-api",
  "/admin/sealed-agents": "sealed-agents",
};

export default function AdminLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const currentPath = location.pathname;
  const { pluginRoutes } = usePlugins();

  // Resolve selected key: check static routes first, then plugin routes
  let selectedKey = pathToKey[currentPath] || "";
  if (currentPath.startsWith("/task/")) {
    selectedKey = `task-${currentPath.split("/")[2]}`;
  } else if (!selectedKey) {
    const matchedPlugin = pluginRoutes.find(
      (route) => currentPath === route.path,
    );
    selectedKey = matchedPlugin
      ? matchedPlugin.path.replace(/^\//, "")
      : "workbench";
  }

  return (
    <Layout className={styles.mainLayout}>
      <Header />
      <Layout>
        <Sidebar selectedKey={selectedKey} />
        <Content className="page-container">
          <ConsolePollService />
          <div className="page-content">
            <ChunkErrorBoundary resetKey={currentPath}>
              <Suspense
                fallback={
                  <Spin
                    tip={t("common.loading")}
                    style={{ display: "block", margin: "20vh auto" }}
                  />
                }
              >
                <Routes>
                  <Route
                    path="/"
                    element={<Navigate to="/admin/agents" replace />}
                  />
                  {/* Admin Routes */}
                  <Route path="agents" element={<AgentsPage />} />
                  <Route path="models" element={<ModelsPage />} />
                  <Route path="web-search" element={<WebSearchPage />} />
                  <Route path="environments" element={<EnvironmentsPage />} />
                  <Route
                    path="object-storage"
                    element={<ObjectStoragePage />}
                  />
                  <Route
                    path="mindspace-cloud"
                    element={<MindspaceCloudSettingsPage />}
                  />
                  <Route
                    path="enterprise-knowledge"
                    element={<EnterpriseKnowledgePage />}
                  />
                  <Route
                    path="agent-config"
                    element={
                      <InspectableAgentRoute>
                        <AgentConfigPage />
                      </InspectableAgentRoute>
                    }
                  />
                  <Route path="security" element={<SecurityPage />} />
                  <Route path="token-usage" element={<TokenUsagePage />} />
                  <Route path="audit-chats" element={<AuditChatsPage />} />
                  <Route path="users" element={<UsersPage />} />
                  <Route path="agent-stats" element={<AgentStatsPage />} />
                  <Route
                    path="voice-transcription"
                    element={<VoiceTranscriptionPage />}
                  />
                  <Route path="debug" element={<DebugPage />} />
                  <Route path="backups" element={<BackupsPage />} />
                  <Route
                    path="plugin-manager"
                    element={<PluginManagerPage />}
                  />
                  <Route path="open-api" element={<OpenApiPage />} />
                  <Route path="sealed-agents" element={<SealedAgentsPage />} />

                  <Route
                    path="channels"
                    element={
                      <InspectableAgentRoute>
                        <ChannelsPage />
                      </InspectableAgentRoute>
                    }
                  />
                  <Route path="sessions" element={<SessionsPage />} />
                  <Route path="inbox" element={<InboxPage />} />
                  <Route
                    path="cron-jobs"
                    element={
                      <InspectableAgentRoute>
                        <CronJobsPage />
                      </InspectableAgentRoute>
                    }
                  />
                  <Route
                    path="heartbeat"
                    element={
                      <InspectableAgentRoute>
                        <HeartbeatPage />
                      </InspectableAgentRoute>
                    }
                  />

                  <Route path="skill-pool" element={<SkillPoolPage />} />
                  <Route path="expert-teams" element={<ExpertTeamsPage />} />
                  <Route
                    path="tools"
                    element={
                      <InspectableAgentRoute>
                        <ToolsPage />
                      </InspectableAgentRoute>
                    }
                  />
                  <Route
                    path="mcp"
                    element={
                      <InspectableAgentRoute>
                        <MCPPage />
                      </InspectableAgentRoute>
                    }
                  />
                  <Route
                    path="acp"
                    element={
                      <InspectableAgentRoute>
                        <ACPPage />
                      </InspectableAgentRoute>
                    }
                  />
                  <Route
                    path="workspace"
                    element={
                      <InspectableAgentRoute>
                        <WorkspacePage />
                      </InspectableAgentRoute>
                    }
                  />

                  {/* Plugin routes — dynamically injected at runtime */}
                  {pluginRoutes.map((route) => (
                    <Route
                      key={route.path}
                      path={route.path}
                      element={<route.component />}
                    />
                  ))}
                </Routes>
              </Suspense>
            </ChunkErrorBoundary>
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
