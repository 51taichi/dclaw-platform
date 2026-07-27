import { DashboardOutlined, DesktopOutlined } from "@ant-design/icons";
import { Button } from "@agentscope-ai/design";
import { Layout, Space } from "antd";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import LanguageSwitcher from "../components/LanguageSwitcher/index";
import { useAuth } from "../contexts/AuthContext";
import { useTheme } from "../contexts/ThemeContext";
import ThemeToggleButton from "../components/ThemeToggleButton";
import styles from "./index.module.less";

const { Header: AntHeader } = Layout;

export default function Header() {
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
      </div>
      <Space size="middle">
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
        <LanguageSwitcher />
        <ThemeToggleButton />
      </Space>
    </AntHeader>
  );
}
