import { Layout, Space } from "antd";
import { BriefcaseBusiness, Gauge } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import LanguageSwitcher from "../components/LanguageSwitcher/index";
import { useAuth } from "../contexts/AuthContext";
import { useTheme } from "../contexts/ThemeContext";
import ThemeToggleButton from "../components/ThemeToggleButton";
import BalanceBadge from "../features/billing/BalanceBadge";
import ConcurrencyMonitorButton from "../features/concurrency/ConcurrencyMonitorButton";
import styles from "./index.module.less";
import { DesktopVersion } from "../components/DesktopVersion";
import type { ClientScene } from "../api/modules/auth";
import { SceneIcon } from "../features/scenes/sceneIcons";

const { Header: AntHeader } = Layout;

interface HeaderProps {
  showSceneTabs?: boolean;
  scenes?: ClientScene[];
  activeSceneKey?: string;
  onSceneChange?: (key: string) => void;
}

export default function Header({
  showSceneTabs = false,
  scenes = [],
  activeSceneKey = "workbench",
  onSceneChange,
}: HeaderProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const { role } = useAuth();
  const isAdminRole = role === "admin";
  const isAdminMode = location.pathname.startsWith("/admin");
  const shouldShowSceneTabs = showSceneTabs || isAdminRole;

  return (
    <AntHeader className={styles.header}>
      <div className={styles.logoWrapper}>
        <img
          src={isDark ? "/dclaw-logo-dark.svg" : "/dclaw-logo-light.svg"}
          alt="DClaw"
          className={styles.logoImg}
          draggable={false}
        />
        <DesktopVersion />
      </div>
      {shouldShowSceneTabs && (
        <nav
          className={styles.sceneTabs}
          aria-label={t("scenes.label", "场景")}
        >
          <button
            type="button"
            role="tab"
            aria-selected={activeSceneKey === "workbench"}
            className={`${styles.sceneTab}${
              activeSceneKey === "workbench" ? ` ${styles.sceneTabActive}` : ""
            }`}
            onClick={() => onSceneChange?.("workbench")}
          >
            <BriefcaseBusiness size={16} />
            <span>{t("scenes.workbench", "工作台")}</span>
          </button>
          {scenes.map((scene) => (
            <button
              key={scene.key}
              type="button"
              role="tab"
              aria-selected={activeSceneKey === scene.key}
              className={`${styles.sceneTab}${
                activeSceneKey === scene.key ? ` ${styles.sceneTabActive}` : ""
              }`}
              onClick={() => onSceneChange?.(scene.key)}
            >
              <SceneIcon name={scene.icon} />
              <span>{scene.title}</span>
            </button>
          ))}
          {isAdminRole && (
            <button
              type="button"
              role="tab"
              aria-selected={isAdminMode || activeSceneKey === "admin"}
              className={`${styles.sceneTab}${
                isAdminMode || activeSceneKey === "admin"
                  ? ` ${styles.sceneTabActive}`
                  : ""
              }`}
              onClick={() => navigate("/admin/agents")}
            >
              <Gauge size={16} />
              <span>{t("header.adminConsole", "管理后台")}</span>
            </button>
          )}
        </nav>
      )}
      <Space size="middle" className={styles.headerActions}>
        {!isAdminMode && <BalanceBadge />}
        {isAdminRole && isAdminMode && <ConcurrencyMonitorButton />}
        <LanguageSwitcher />
        <ThemeToggleButton />
      </Space>
    </AntHeader>
  );
}
