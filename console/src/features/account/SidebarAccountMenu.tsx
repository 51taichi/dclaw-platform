import { useEffect, useMemo, useState } from "react";
import { Avatar, Popover } from "antd";
import {
  ChevronRight,
  CircleUserRound,
  LogOut,
  MonitorCog,
  Settings,
  WalletCards,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { billingApi } from "@/api/modules/billing";
import type { BillingWallet } from "@/api/types/billing";
import { useLocalHelperStatus } from "@/features/localHelper/LocalHelperStatusContext";
import styles from "./SidebarAccountMenu.module.less";

interface SidebarAccountMenuProps {
  username: string;
  role: string | null;
  collapsed: boolean;
  onOpenAccount: () => void;
  onOpenWallet: () => void;
  onOpenAdmin: () => void;
  onLogout: () => void;
}

function accountInitial(username: string) {
  return Array.from(username.trim())[0]?.toUpperCase() || "D";
}

export default function SidebarAccountMenu({
  username,
  role,
  collapsed,
  onOpenAccount,
  onOpenWallet,
  onOpenAdmin,
  onLogout,
}: SidebarAccountMenuProps) {
  const { t } = useTranslation();
  const {
    state: helperState,
    label: helperLabel,
    check,
  } = useLocalHelperStatus();
  const [open, setOpen] = useState(false);
  const [wallet, setWallet] = useState<BillingWallet | null>(null);
  const [walletLoading, setWalletLoading] = useState(false);
  const [walletUnavailable, setWalletUnavailable] = useState(false);
  const isAdmin = role === "admin";
  const roleLabel = isAdmin
    ? t("account.adminRole", "管理员")
    : t("account.userRole", "普通用户");
  const initial = useMemo(() => accountInitial(username), [username]);

  useEffect(() => {
    if (!open || wallet) return;
    let cancelled = false;
    setWalletLoading(true);
    billingApi
      .getWallet()
      .then((nextWallet) => {
        if (!cancelled) {
          setWallet(nextWallet);
          setWalletUnavailable(false);
          setWalletLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setWalletUnavailable(true);
          setWalletLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, wallet]);

  const closeAndRun = (action: () => void) => {
    setOpen(false);
    action();
  };

  const walletLabel = walletLoading
    ? t("common.loading", "加载中")
    : walletUnavailable
    ? t("account.pointsUnavailable", "暂时不可用")
    : wallet
    ? t("account.pointsValue", {
        defaultValue: "{{value}} 积分",
        value: wallet.available.toLocaleString(),
      })
    : "--";

  const content = (
    <div className={styles.menu} aria-label={t("account.menu", "账户菜单")}>
      <div className={styles.profileHeader}>
        <Avatar className={styles.avatar} size={42}>
          {initial}
        </Avatar>
        <div className={styles.profileText}>
          <strong title={username}>{username}</strong>
          <span>{roleLabel}</span>
        </div>
      </div>

      <div className={styles.section}>
        <button
          type="button"
          className={styles.menuRow}
          onClick={() => closeAndRun(onOpenWallet)}
        >
          <span className={styles.rowIcon}>
            <WalletCards size={17} />
          </span>
          <span className={styles.rowText}>
            <span>{t("account.pointsBalance", "积分余额")}</span>
            <small>{walletLabel}</small>
          </span>
          <ChevronRight size={15} />
        </button>

        <button
          type="button"
          className={styles.menuRow}
          disabled={helperState === "checking"}
          onClick={() => void check()}
        >
          <span className={styles.rowIcon}>
            <MonitorCog size={17} />
          </span>
          <span className={styles.rowText}>
            <span>{t("account.localHelper", "本地助手")}</span>
            <small data-state={helperState}>{helperLabel}</small>
          </span>
          <span
            className={styles.statusDot}
            data-state={helperState}
            aria-hidden="true"
          />
        </button>
      </div>

      <div className={styles.section}>
        <button
          type="button"
          className={styles.menuRow}
          onClick={() => closeAndRun(onOpenAccount)}
        >
          <span className={styles.rowIcon}>
            <CircleUserRound size={17} />
          </span>
          <span className={styles.rowText}>
            <span>{t("account.title", "账户管理")}</span>
          </span>
          <ChevronRight size={15} />
        </button>

        {isAdmin ? (
          <button
            type="button"
            className={styles.menuRow}
            onClick={() => closeAndRun(onOpenAdmin)}
          >
            <span className={styles.rowIcon}>
              <Settings size={17} />
            </span>
            <span className={styles.rowText}>
              <span>{t("header.adminConsole", "管理后台")}</span>
            </span>
            <ChevronRight size={15} />
          </button>
        ) : null}
      </div>

      <div className={styles.section}>
        <button
          type="button"
          className={`${styles.menuRow} ${styles.logoutRow}`}
          onClick={() => closeAndRun(onLogout)}
        >
          <span className={styles.rowIcon}>
            <LogOut size={17} />
          </span>
          <span className={styles.rowText}>
            <span>{t("login.logout", "退出登录")}</span>
          </span>
        </button>
      </div>
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      placement={collapsed ? "rightBottom" : "topLeft"}
      open={open}
      onOpenChange={setOpen}
      arrow={false}
      styles={{ body: { padding: 0 } }}
    >
      <button
        type="button"
        className={`${styles.trigger}${
          collapsed ? ` ${styles.triggerCollapsed}` : ""
        }`}
        aria-label={t("account.currentAccount", {
          defaultValue: "当前账户：{{username}}",
          username,
        })}
        aria-expanded={open}
      >
        <Avatar className={styles.avatar} size={collapsed ? 34 : 36}>
          {initial}
        </Avatar>
        {!collapsed ? (
          <span className={styles.triggerText}>
            <strong title={username}>{username}</strong>
            <small>{roleLabel}</small>
          </span>
        ) : null}
        <span
          className={styles.triggerStatus}
          data-state={helperState}
          title={helperLabel}
          aria-label={helperLabel}
        >
          <MonitorCog size={collapsed ? 13 : 14} />
        </span>
      </button>
    </Popover>
  );
}
