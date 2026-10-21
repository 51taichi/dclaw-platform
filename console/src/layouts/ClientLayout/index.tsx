import { Suspense, useMemo } from "react";
import { Layout, Spin } from "antd";
import {
  Routes,
  Route,
  useLocation,
  useNavigate,
  Navigate,
} from "react-router-dom";
import { useTranslation } from "react-i18next";
import Sidebar from "../Sidebar";
import Header from "../Header";
import ConsolePollService from "../../components/ConsolePollService";
import { ChunkErrorBoundary } from "../../components/ChunkErrorBoundary";
import { lazyImportWithRetry } from "../../utils/lazyWithRetry";
import { usePlugins } from "../../plugins/PluginContext";
import styles from "../index.module.less";

import ClawPage from "../../pages/Claw";
import WorkbenchPage from "../../pages/Workbench";
import TaskPage from "../../pages/Task";
import TaskConversationRoute from "../../pages/Task/TaskConversationRoute";
import AigcStudioPage from "../../pages/AigcStudio";
import WalletPage from "../../pages/Wallet";
import CreditAlertBanner from "../../features/billing/CreditAlertBanner";
import { useAuth } from "../../contexts/AuthContext";
import { isDesktopApp } from "../../utils/env";
import { isSafeSceneUrl, openSceneInExternalBrowser } from "./sceneNavigation";

// ── Ecosystem pages (WorkBuddy-style) ─────────────────────────────────────────
const ExpertsPage = lazyImportWithRetry("../../pages/Experts");
const SkillMarketPage = lazyImportWithRetry("../../pages/SkillMarket");
const ExplorePage = lazyImportWithRetry("../../pages/Explore");
const ConnectorsPage = lazyImportWithRetry("../../pages/Connectors");
const AutomationsPage = lazyImportWithRetry("../../pages/Automations");
const TencentDocPage = lazyImportWithRetry(
  "../../pages/Library/TencentDocPage",
);

const { Content } = Layout;

const pathToKey: Record<string, string> = {
  "/workbench": "workbench",
  "/aigc-studio": "aigc-studio",
  "/claw": "claw",
  "/experts": "experts",
  "/skill-market": "skill-market",
  "/explore": "explore",
  "/connectors": "connectors",
  "/automations": "automations",
  "/tencent-doc": "tencent-doc",
  "/wallet": "wallet",
};

export default function ClientLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const { pluginRoutes } = usePlugins();
  const { scenes } = useAuth();
  const showSceneTabs = isDesktopApp();
  const availableScenes = useMemo(
    () =>
      showSceneTabs ? scenes.filter((scene) => isSafeSceneUrl(scene.url)) : [],
    [scenes, showSceneTabs],
  );
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
      <Header
        showSceneTabs={showSceneTabs}
        scenes={availableScenes}
        activeSceneKey="workbench"
        onSceneChange={(key) => {
          if (key === "workbench") {
            navigate("/workbench");
            return;
          }
          openSceneInExternalBrowser(availableScenes, key);
        }}
      />
      <Layout>
        <Sidebar selectedKey={selectedKey} />
        <Content className="page-container">
          <ConsolePollService />
          <div className={styles.creditAlertSlot}>
            <CreditAlertBanner />
          </div>
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
                    element={<Navigate to="/workbench" replace />}
                  />
                  <Route path="/workbench" element={<WorkbenchPage />} />
                  <Route path="/aigc-studio" element={<AigcStudioPage />} />
                  <Route path="/claw/*" element={<ClawPage />} />
                  <Route
                    path="/task/*"
                    element={
                      <TaskConversationRoute>
                        <TaskPage />
                      </TaskConversationRoute>
                    }
                  />
                  <Route path="/experts" element={<ExpertsPage />} />
                  <Route path="/skill-market" element={<SkillMarketPage />} />
                  <Route path="/explore" element={<ExplorePage />} />
                  <Route path="/connectors" element={<ConnectorsPage />} />
                  <Route path="/automations" element={<AutomationsPage />} />
                  <Route path="/tencent-doc" element={<TencentDocPage />} />
                  <Route path="/wallet" element={<WalletPage />} />

                  {/* Admin Routes have been moved to AdminLayout */}

                  {/* Plugin routes — dynamically injected at runtime */}
                  {pluginRoutes.map((route) => (
                    <Route
                      key={route.path}
                      path={route.path}
                      element={<route.component />}
                    />
                  ))}
                  <Route
                    path="*"
                    element={<Navigate to="/workbench" replace />}
                  />
                </Routes>
              </Suspense>
            </ChunkErrorBoundary>
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
