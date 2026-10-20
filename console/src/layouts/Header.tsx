import { DashboardOutlined, DesktopOutlined } from "@ant-design/icons";
import { Button } from "@agentscope-ai/design";
import { Layout, Space } from "antd";
import { BriefcaseBusiness, Headset } from "lucide-react";
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
      {showSceneTabs && (
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
              <Headset size={16} />
              <span>{scene.title}</span>
            </button>
          ))}
        </nav>
      )}
      <Space size="middle" className={styles.headerActions}>
        {!isAdminMode && <BalanceBadge />}
        {isAdminRole && (
          <Button
            type="default"
            icon={isAdminMode ? <DesktopOutlined /> : <DashboardOutlined />}
            onClick={() =>
              navigate(isAdminMode ? "/workbench" : "/admin/agents")
            }
            style={{ marginRight: 16 }}
          >
            {isAdminMode
              ? t("header.backToClient", "返回客户端")
              : t("header.adminConsole", "管理后台")}
          </Button>
        )}
        {isAdminRole && isAdminMode && <ConcurrencyMonitorButton />}
        <LanguageSwitcher />
        <ThemeToggleButton />
      </Space>
    </AntHeader>
  );
}
