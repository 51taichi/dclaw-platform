import {
  Layout,
  Menu,
  Button,
  Modal,
  Input,
  Form,
  Tooltip,
  Badge,
  Dropdown,
  Popover,
  type MenuProps,
} from "antd";
import { useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../hooks/useAppMessage";
import {
  SparkChatTabFill,
  SparkWifiLine,
  SparkUserGroupLine,
  SparkDateLine,
  SparkVoiceChat01Line,
  SparkMagicWandLine,
  SparkLocalFileLine,
  SparkModePlazaLine,
  SparkInternetLine,
  SparkModifyLine,
  SparkBrowseLine,
  SparkMcpMcpLine,
  SparkScanLine,
  SparkToolLine,
  SparkDataLine,
  SparkMicLine,
  SparkAgentLine,
  SparkMenuExpandLine,
  SparkMenuFoldLine,
  SparkOtherLine,
  SparkBarChartLine,
  SparkEmailLine,
  SparkHistoryLine,
  SparkRightArrowLine,
} from "@agentscope-ai/icons";
import {
  Archive,
  ArchiveRestore,
  Package,
  FolderOpen,
  Edit2,
  Save,
  Trash2,
  MoreHorizontal,
  Search,
  SlidersHorizontal,
  WandSparkles,
  CloudUpload,
  KeyRound,
  CreditCard,
} from "lucide-react";
import { clearAuthToken } from "../api/config";
import { authApi } from "../api/modules/auth";
import api from "../api";
import type { ChatSpec } from "../api";
import { usePlugins } from "../plugins/PluginContext";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { KEY_TO_PATH, DEFAULT_OPEN_KEYS } from "./constants";
import { useAgentStore } from "../stores/agentStore";
import { useAuth } from "../contexts/AuthContext";
import {
  buildTaskArchiveMeta,
  isArchivedTaskChat,
  isVisibleTaskChat,
  matchesTaskArchiveView,
  type TaskArchiveView,
  type TaskListChat,
} from "./taskListFilters";
import { sortTasksForSidebar } from "./taskListOrdering";
import { isTaskGenerating } from "./taskListState";
import { canInspectAgent } from "../utils/agentCapabilities";
import { getAgentManagementMenuItems } from "./settingsAgentMenu";
import SidebarAccountMenu from "../features/account/SidebarAccountMenu";

// ── Layout ────────────────────────────────────────────────────────────────

const { Sider } = Layout;
const MOBILE_SIDEBAR_QUERY = "(max-width: 768px)";

function isMobileSidebarViewport() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(MOBILE_SIDEBAR_QUERY).matches
  );
}
const INBOX_BADGE_POLLING_MS = 6000;

// ── Types ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  selectedKey: string;
}

// ── Sidebar ───────────────────────────────────────────────────────────────

function getTimeAgo(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin}分钟前`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}小时前`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}天前`;
}

export default function Sidebar({ selectedKey }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const isAdminMode = location.pathname.startsWith("/admin");
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const { isDark } = useTheme();
  const { pluginRoutes } = usePlugins();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountForm] = Form.useForm();
  const [collapsed, setCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(isMobileSidebarViewport);
  const [hasInboxUnread, setHasInboxUnread] = useState(false);
  const [taskList, setTaskList] = useState<TaskListChat[]>([]);
  const [earlierTasksOpen, setEarlierTasksOpen] = useState(false);
  const [taskListLoading, setTaskListLoading] = useState(false);
  const [renamingTaskId, setRenamingTaskId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const { selectedAgent, setSelectedAgent, agents } = useAgentStore();
  const canInspectSelectedAgent = canInspectAgent(
    agents.find((agent) => agent.id === selectedAgent),
  );
  const { username, role, logout } = useAuth();
  const isAdminRole = role === "admin";

  // Task filter states
  const [taskSearchQuery, setTaskSearchQuery] = useState("");
  const [taskFilterStatus, setTaskFilterStatus] = useState("all");
  const [filterTab, setFilterTab] = useState("status");
  const [taskFilterDate, setTaskFilterDate] = useState("all");
  const [taskArchiveView, setTaskArchiveView] =
    useState<TaskArchiveView>("active");

  // ── Effects ──────────────────────────────────────────────────────────────

  useEffect(() => {
    authApi
      .getStatus()
      .then((res) => setAuthEnabled(res.enabled))
      .catch(() => {});
  }, []);

  // Load task list from chatApi
  useEffect(() => {
    let cancelled = false;
    const loadTasks = async () => {
      setTaskListLoading(true);
      try {
        const chats = await api.listAllChats();
        if (!cancelled && Array.isArray(chats)) {
          const filteredChats = (chats as TaskListChat[]).filter(
            isVisibleTaskChat,
          );
          setTaskList(sortTasksForSidebar(filteredChats));
        }
      } catch {
        // silently ignore
      } finally {
        if (!cancelled) setTaskListLoading(false);
      }
    };
    loadTasks();
    const interval = setInterval(loadTasks, 15000);
    window.addEventListener("refresh-task-list", loadTasks);
    return () => {
      cancelled = true;
      clearInterval(interval);
      window.removeEventListener("refresh-task-list", loadTasks);
    };
  }, []);

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    ) {
      return;
    }

    const mediaQuery = window.matchMedia(MOBILE_SIDEBAR_QUERY);
    const syncMobileSidebar = () => {
      setIsMobile(mediaQuery.matches);
      if (mediaQuery.matches) {
        setCollapsed(true);
      }
    };

    syncMobileSidebar();
    mediaQuery.addEventListener("change", syncMobileSidebar);

    return () => {
      mediaQuery.removeEventListener("change", syncMobileSidebar);
    };
  }, []);
  useEffect(() => {
    const loadUnreadState = async () => {
      try {
        const [inboxRes, pushRes] = await Promise.all([
          api.getInboxEvents({
            unread_only: true,
            limit: 1,
          }),
          api.getPushMessages(),
        ]);
        const hasUnreadEvents = (inboxRes?.events?.length || 0) > 0;
        const hasPendingApprovals =
          (pushRes?.pending_approvals?.length || 0) > 0;
        setHasInboxUnread(hasUnreadEvents || hasPendingApprovals);
      } catch {
        // Keep previous state when polling fails.
      }
    };
    void loadUnreadState();
    const timer = window.setInterval(() => {
      void loadUnreadState();
    }, INBOX_BADGE_POLLING_MS);
    return () => window.clearInterval(timer);
  }, []);

  const inboxLabel = collapsed ? null : (
    <Badge dot={hasInboxUnread} color="rgba(255, 157, 77, 1)" offset={[5, 7]}>
      <span>{t("nav.inbox")}</span>
    </Badge>
  );
  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleRenameSubmit = async (task: ChatSpec) => {
    if (!renameValue.trim() || renameValue === task.name) {
      setRenamingTaskId(null);
      return;
    }
    try {
      const taskAgentId = task.meta?.agent_id as string | undefined;
      await api.updateChat(task.id, { name: renameValue }, taskAgentId);
      message.success(t("nav.renameSuccess", "重命名成功"));
      setTaskList(
        taskList.map((t) =>
          t.id === task.id ? { ...t, name: renameValue } : t,
        ),
      );
    } catch {
      message.error(t("nav.renameFailed", "重命名失败"));
    } finally {
      setRenamingTaskId(null);
    }
  };

  const handleChangeStatus = async (task: ChatSpec, newStatus: string) => {
    try {
      const taskAgentId = task.meta?.agent_id as string | undefined;
      await api.updateChat(task.id, { task_status: newStatus }, taskAgentId);
      message.success(t("common.updateSuccess", "状态更新成功"));
      setTaskList(
        taskList.map((t) =>
          t.id === task.id ? { ...t, task_status: newStatus } : t,
        ),
      );
    } catch {
      message.error(t("common.updateFailed", "状态更新失败"));
    }
  };

  const handleArchiveTask = async (task: ChatSpec) => {
    if (isTaskGenerating(task as TaskListChat)) {
      message.warning(
        t("nav.archiveRunningTaskBlocked", "运行中的任务不能归档"),
      );
      return;
    }
    try {
      const archivedAt = new Date().toISOString();
      const taskAgentId = task.meta?.agent_id as string | undefined;
      const meta = buildTaskArchiveMeta(task.meta, true, archivedAt);
      await api.updateChat(task.id, { meta }, taskAgentId);
      message.success(t("nav.archiveSuccess", "已归档"));
      setTaskList((prev) =>
        prev.map((item) => (item.id === task.id ? { ...item, meta } : item)),
      );
      if (selectedKey === `task-${task.id}`) {
        navigate("/workbench");
      }
    } catch {
      message.error(t("nav.archiveFailed", "归档失败"));
    }
  };

  const handleRestoreTask = async (task: ChatSpec) => {
    try {
      const taskAgentId = task.meta?.agent_id as string | undefined;
      const meta = buildTaskArchiveMeta(task.meta, false);
      await api.updateChat(task.id, { meta }, taskAgentId);
      message.success(t("nav.restoreSuccess", "已恢复"));
      setTaskList((prev) =>
        prev.map((item) => (item.id === task.id ? { ...item, meta } : item)),
      );
    } catch {
      message.error(t("nav.restoreFailed", "恢复失败"));
    }
  };

  const handleDeleteTask = (task: ChatSpec) => {
    Modal.confirm({
      title: t("nav.deleteTaskTitle", "删除任务"),
      content: t("nav.deleteTaskConfirm", "确定要删除任务吗？此操作不可恢复。"),
      okText: t("common.confirm", "确定"),
      okButtonProps: { danger: true },
      cancelText: t("common.cancel", "取消"),
      onOk: async () => {
        try {
          const taskAgentId = task.meta?.agent_id as string | undefined;
          await api.deleteChat(task.id, taskAgentId);
          message.success(t("nav.deleteSuccess", "删除成功"));
          setTaskList(taskList.filter((t) => t.id !== task.id));
          if (selectedKey === `task-${task.id}`) {
            navigate("/workbench");
          }
        } catch {
          message.error(t("nav.deleteFailed", "删除失败"));
        }
      },
    });
  };

  const handleUpdateProfile = async (values: {
    currentPassword: string;
    newUsername?: string;
    newPassword?: string;
  }) => {
    const trimmedUsername = values.newUsername?.trim() || undefined;
    const trimmedPassword = values.newPassword?.trim() || undefined;

    if (values.newPassword && !trimmedPassword) {
      message.error(t("account.passwordEmpty"));
      return;
    }

    if (values.newUsername && !trimmedUsername) {
      message.error(t("account.usernameEmpty"));
      return;
    }

    if (!trimmedUsername && !trimmedPassword) {
      message.warning(t("account.nothingToUpdate"));
      return;
    }

    setAccountLoading(true);
    try {
      await authApi.updateProfile(
        values.currentPassword,
        trimmedUsername,
        trimmedPassword,
      );
      message.success(t("account.updateSuccess"));
      setAccountModalOpen(false);
      accountForm.resetFields();
      clearAuthToken();
      window.location.href = "/login";
    } catch (err: unknown) {
      const raw = err instanceof Error ? err.message : "";
      let msg = t("account.updateFailed");
      if (raw.includes("password is incorrect")) {
        msg = t("account.wrongPassword");
      } else if (raw.includes("Nothing to update")) {
        msg = t("account.nothingToUpdate");
      } else if (raw.includes("cannot be empty")) {
        msg = t("account.nothingToUpdate");
      } else if (raw) {
        msg = raw;
      }
      message.error(msg);
    } finally {
      setAccountLoading(false);
    }
  };

  // ── Collapsed nav items (WorkBuddy-style primary nav) ──────────────────

  const collapsedNavItems = [
    {
      key: "experts",
      icon: <SparkAgentLine size={18} />,
      path: "/experts",
      label: t("nav.experts"),
    },
    {
      key: "skill-market",
      icon: <SparkMagicWandLine size={18} />,
      path: "/skill-market",
      label: t("nav.skillMarket"),
    },
    {
      key: "aigc-studio",
      icon: <WandSparkles size={18} />,
      path: "/aigc-studio",
      label: t("nav.aigcStudio", "AIGC"),
    },
    {
      key: "connectors",
      icon: <SparkMcpMcpLine size={18} />,
      path: "/connectors",
      label: t("nav.connectors"),
    },
    {
      key: "tencent-doc",
      icon: <SparkLocalFileLine size={18} />,
      path: "/tencent-doc",
      label: t("nav.tencentDoc", "云文档"),
    },
    {
      key: "automations",
      icon: <SparkDateLine size={18} />,
      path: "/automations",
      label: t("nav.automations"),
    },
    ...(isAdminRole
      ? [
          {
            key: "agents",
            icon: <SparkAgentLine size={18} />,
            path: "/admin/agents",
            label: t("nav.agents"),
          },
          {
            key: "workspace",
            icon: <SparkLocalFileLine size={18} />,
            path: "/admin/workspace",
            label: t("nav.workspace", "文件"),
          },
          {
            key: "models",
            icon: <SparkModePlazaLine size={18} />,
            path: "/admin/models",
            label: t("nav.models"),
          },
          {
            key: "web-search",
            icon: <SparkInternetLine size={18} />,
            path: "/admin/web-search",
            label: t("nav.webSearch", "Web 检索"),
          },
          // Append plugin nav items dynamically
          ...pluginRoutes.map((route) => ({
            key: route.path.replace(/^\//, ""),
            icon: <span style={{ fontSize: 18 }}>{route.icon}</span>,
            path: route.path,
            label: route.label,
          })),
        ]
      : []),
  ];

  // ── Menu items — agent-scoped (Chat + Control + Workspace) ──────────────

  // ── WorkBuddy-style primary navigation ────────────────────────────────

  const agentMenuItems: MenuProps["items"] = [
    {
      key: "wallet",
      label: collapsed ? null : t("nav.wallet", "积分钱包"),
      icon: <CreditCard size={16} />,
    },
    {
      key: "experts",
      label: collapsed ? null : t("nav.experts"),
      icon: <SparkAgentLine size={16} />,
    },
    {
      key: "skill-market",
      label: collapsed ? null : t("nav.skillMarket"),
      icon: <SparkMagicWandLine size={16} />,
    },
    {
      key: "aigc-studio",
      label: collapsed ? null : t("nav.aigcStudio", "AIGC"),
      icon: <WandSparkles size={16} />,
    },
    {
      key: "connectors",
      label: collapsed ? null : t("nav.connectors"),
      icon: <SparkMcpMcpLine size={16} />,
    },
    {
      key: "tencent-doc",
      label: collapsed ? null : t("nav.tencentDoc", "云文档"),
      icon: <SparkLocalFileLine size={16} />,
    },
    {
      key: "automations",
      label: collapsed ? null : t("nav.automations"),
      icon: <SparkDateLine size={16} />,
    },
  ];

  // ── Advanced / Settings (collapsed under a group) ─────────────────────

  const settingsMenuItems: MenuProps["items"] = [
    {
      key: "settings-group",
      label: collapsed ? null : t("nav.settings"),
      children: [
        ...getAgentManagementMenuItems(collapsed, (key, fallback) =>
          t(key, { defaultValue: fallback ?? key }),
        ).map((item) => ({
          ...item,
          icon:
            item.key === "sealed-agents" ? (
              <KeyRound size={16} />
            ) : (
              <SparkAgentLine size={16} />
            ),
        })),
        {
          key: "expert-teams",
          label: collapsed ? null : t("nav.expertTeams", "专家团"),
          icon: <SparkAgentLine size={16} />,
        },
        ...(canInspectSelectedAgent
          ? [
              {
                key: "workspace",
                label: collapsed ? null : t("nav.workspace", "文件"),
                icon: <SparkLocalFileLine size={16} />,
              },
            ]
          : []),
        {
          key: "models",
          label: collapsed ? null : t("nav.models"),
          icon: <SparkModePlazaLine size={16} />,
        },
        {
          key: "web-search",
          label: collapsed ? null : t("nav.webSearch", "Web 检索"),
          icon: <SparkInternetLine size={16} />,
        },
        {
          key: "skill-pool",
          label: collapsed ? null : t("nav.skillPool", "Skill Pool"),
          icon: <SparkOtherLine size={16} />,
        },
        {
          key: "object-storage",
          label: collapsed ? null : t("nav.objectStorage", "对象存储"),
          icon: <CloudUpload size={16} />,
        },
        {
          key: "enterprise-knowledge",
          label: collapsed ? null : t("nav.enterpriseKnowledge", "企业智库"),
          icon: <SparkDataLine size={16} />,
        },
        {
          key: "mindspace-cloud",
          label: collapsed ? null : t("nav.mindspaceCloud", "云文档应用"),
          icon: <SparkMcpMcpLine size={16} />,
        },
        {
          key: "security",
          label: collapsed ? null : t("nav.security"),
          icon: <SparkBrowseLine size={16} />,
        },
        {
          key: "users",
          label: collapsed ? null : t("nav.users", "Users"),
          icon: <SparkUserGroupLine size={16} />,
        },
        {
          key: "token-usage",
          label: collapsed ? null : t("nav.tokenUsage"),
          icon: <SparkDataLine size={16} />,
        },
        {
          key: "billing",
          label: collapsed ? null : t("nav.billing", "积分与计费"),
          icon: <CreditCard size={16} />,
        },
        {
          key: "plugin-manager",
          label: collapsed ? null : t("nav.pluginManager", "Plugin Manager"),
          icon: <Package size={16} />,
        },
        {
          key: "open-api",
          label: collapsed ? null : t("nav.openApi", "Open API"),
          icon: <KeyRound size={16} />,
        },
      ],
    },
    {
      key: "advanced-group",
      label: collapsed ? null : t("nav.advanced"),
      children: [
        ...(canInspectSelectedAgent
          ? [
              {
                key: "channels",
                label: collapsed ? null : t("nav.channels"),
                icon: <SparkWifiLine size={16} />,
              },
            ]
          : []),
        {
          key: "sessions",
          label: collapsed ? null : t("nav.sessions"),
          icon: <SparkUserGroupLine size={16} />,
        },

        ...(canInspectSelectedAgent
          ? [
              {
                key: "tools",
                label: collapsed ? null : t("nav.tools"),
                icon: <SparkToolLine size={16} />,
              },
              {
                key: "mcp",
                label: collapsed ? null : t("nav.mcp"),
                icon: <SparkMcpMcpLine size={16} />,
              },
              {
                key: "acp",
                label: collapsed ? null : t("nav.acp"),
                icon: <SparkScanLine size={16} />,
              },
              {
                key: "agent-config",
                label: collapsed ? null : t("nav.agentConfig"),
                icon: <SparkModifyLine size={16} />,
              },
            ]
          : []),
        {
          key: "inbox",
          label: inboxLabel,
          icon: <SparkEmailLine size={16} />,
        },
        ...(canInspectSelectedAgent
          ? [
              {
                key: "heartbeat",
                label: collapsed ? null : t("nav.heartbeat"),
                icon: <SparkVoiceChat01Line size={16} />,
              },
              {
                key: "cron-jobs",
                label: collapsed ? null : t("nav.cronJobs"),
                icon: <SparkDateLine size={16} />,
              },
            ]
          : []),
        {
          key: "voice-transcription",
          label: collapsed ? null : t("nav.voiceTranscription"),
          icon: <SparkMicLine size={16} />,
        },
        {
          key: "agent-stats",
          label: collapsed ? null : t("nav.agentStats"),
          icon: <SparkBarChartLine size={16} />,
        },
      ],
    },
  ];

  // Append plugin menu items as a group (only when there are plugins)
  if (pluginRoutes.length > 0) {
    settingsMenuItems.push({
      key: "plugins-group",
      label: collapsed ? null : t("nav.plugins"),
      children: pluginRoutes.map((route) => ({
        key: route.path.replace(/^\//, ""),
        label: collapsed ? null : route.label,
        icon: <span style={{ fontSize: 16 }}>{route.icon}</span>,
      })),
    } as any);
  }

  const filteredTaskList = taskList.filter((task) => {
    if (!matchesTaskArchiveView(task, taskArchiveView)) return false;
    if (taskFilterStatus !== "all") {
      const status = task.task_status || "pending";
      if (status !== taskFilterStatus) return false;
    }
    if (taskFilterDate !== "all") {
      const taskDate = new Date(
        task.updated_at || task.created_at || Date.now(),
      );
      const now = new Date();
      if (taskFilterDate === "today") {
        const startOfToday = new Date(
          now.getFullYear(),
          now.getMonth(),
          now.getDate(),
        );
        if (taskDate < startOfToday) return false;
      } else if (taskFilterDate === "7days") {
        const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
        if (taskDate < sevenDaysAgo) return false;
      } else if (taskFilterDate === "30days") {
        const thirtyDaysAgo = new Date(
          now.getTime() - 30 * 24 * 60 * 60 * 1000,
        );
        if (taskDate < thirtyDaysAgo) return false;
      }
    }
    if (!taskSearchQuery) return true;
    const title = task.name || task.session_id || "Untitled";
    return title.toLowerCase().includes(taskSearchQuery.toLowerCase());
  });

  const renderTasks = (tasks: TaskListChat[], numbered = false) =>
    tasks.map((task, index) => {
      const title = task.name || task.session_id || "Untitled";
      const timeAgo = task.created_at ? getTimeAgo(task.created_at) : "";
      const isActive = selectedKey === `task-${task.id}`;
      const isRenaming = renamingTaskId === task.id;
      const isGenerating = isTaskGenerating(task);
      const isArchived = isArchivedTaskChat(task);

      const menuItems = [
        {
          key: "open-folder",
          icon: <FolderOpen size={14} />,
          label: t("nav.openFolder", "打开文件夹"),
          onClick: ({ domEvent }: any) => {
            domEvent.stopPropagation();
            message.info(t("common.comingSoon", "功能开发中"));
          },
        },
        {
          key: "rename",
          icon: <Edit2 size={14} />,
          label: t("nav.rename", "重命名"),
          onClick: ({ domEvent }: any) => {
            domEvent.stopPropagation();
            setRenamingTaskId(task.id);
            setRenameValue(title);
          },
        },
        {
          key: "change-status",
          icon: <SlidersHorizontal size={14} />,
          label: t("nav.changeStatus", "修改状态"),
          children: [
            {
              key: "status-in_progress",
              label: "进行中",
              onClick: ({ domEvent }: any) => {
                domEvent.stopPropagation();
                handleChangeStatus(task, "in_progress");
              },
            },
            {
              key: "status-completed",
              label: "已完成",
              onClick: ({ domEvent }: any) => {
                domEvent.stopPropagation();
                handleChangeStatus(task, "completed");
              },
            },
            {
              key: "status-failed",
              label: "失败",
              onClick: ({ domEvent }: any) => {
                domEvent.stopPropagation();
                handleChangeStatus(task, "failed");
              },
            },
            {
              key: "status-pending",
              label: "待处理",
              onClick: ({ domEvent }: any) => {
                domEvent.stopPropagation();
                handleChangeStatus(task, "pending");
              },
            },
            {
              key: "status-planning",
              label: "规划中",
              onClick: ({ domEvent }: any) => {
                domEvent.stopPropagation();
                handleChangeStatus(task, "planning");
              },
            },
          ],
        },
        {
          key: "save-workspace",
          icon: <Save size={14} />,
          label: t("nav.saveToWorkspace", "保存到工作空间"),
          onClick: ({ domEvent }: any) => {
            domEvent.stopPropagation();
            message.info(t("common.comingSoon", "功能开发中"));
          },
        },
        isArchived
          ? {
              key: "restore",
              icon: <ArchiveRestore size={14} />,
              label: t("nav.restoreTask", "恢复任务"),
              onClick: ({ domEvent }: any) => {
                domEvent.stopPropagation();
                void handleRestoreTask(task);
              },
            }
          : {
              key: "archive",
              icon: <Archive size={14} />,
              label: isGenerating
                ? t("nav.archiveRunningTaskBlocked", "运行中的任务不能归档")
                : t("nav.archiveTask", "归档任务"),
              disabled: isGenerating,
              onClick: ({ domEvent }: any) => {
                domEvent.stopPropagation();
                void handleArchiveTask(task);
              },
            },
        {
          key: "delete",
          icon: <Trash2 size={14} />,
          label: t("nav.deleteTask", "删除任务"),
          danger: true,
          onClick: ({ domEvent }: any) => {
            domEvent.stopPropagation();
            handleDeleteTask(task);
          },
        },
      ];

      return (
        <Dropdown
          key={task.id}
          menu={{ items: menuItems }}
          trigger={["contextMenu"]}
          placement="bottomRight"
        >
          <button
            className={`${styles.taskItem}${
              isActive ? ` ${styles.taskItemActive}` : ""
            }${isGenerating ? ` ${styles.taskItemGenerating}` : ""}`}
            onClick={() => {
              if (!isRenaming) {
                setEarlierTasksOpen(false);
                const taskAgentId = task.meta?.agent_id;
                if (taskAgentId && (taskAgentId as string) !== selectedAgent) {
                  setSelectedAgent(taskAgentId as string);
                }
                const taskMode = task.meta?.active_mode;
                if (
                  typeof taskMode === "string" &&
                  taskMode !== useAgentStore.getState().activeMode
                ) {
                  useAgentStore.getState().setActiveMode(taskMode as any);
                }
                navigate(`/task/${task.id}`);
              }
            }}
            style={{ position: "relative" }}
          >
            <span className={styles.taskNumberBadge}>
              {numbered ? index + 1 : <SparkHistoryLine />}
              {(isGenerating || task.task_status === "failed") && (
                <span
                  className={`${styles.taskStateDot} ${
                    isGenerating
                      ? styles.taskStateRunning
                      : styles.taskStateFailed
                  }`}
                  aria-label={isGenerating ? "生成中" : "失败"}
                />
              )}
            </span>
            <span className={styles.taskItemContent}>
              {isRenaming ? (
                <Input
                  size="small"
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onPressEnter={() => handleRenameSubmit(task)}
                  onBlur={() => handleRenameSubmit(task)}
                  autoFocus
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <>
                  <span className={styles.taskItemTitle}>{title}</span>
                  {timeAgo && (
                    <span className={styles.taskItemTime}>{timeAgo}</span>
                  )}
                </>
              )}
            </span>

            {!isRenaming && (
              <span
                className={styles.taskItemMoreBtn}
                onClick={(e) => {
                  e.stopPropagation();
                }}
              >
                <Dropdown
                  menu={{ items: menuItems }}
                  trigger={["click"]}
                  placement="bottomRight"
                >
                  <MoreHorizontal size={14} />
                </Dropdown>
              </span>
            )}
          </button>
        </Dropdown>
      );
    });

  const filterContent = (
    <div
      style={{
        display: "flex",
        width: 220,
        padding: "4px 0",
        margin: "-12px -16px",
      }}
    >
      <Menu
        mode="inline"
        style={{
          width: 100,
          borderRight: "1px solid #f0f0f0",
          borderInlineEnd: "none",
        }}
        selectedKeys={[filterTab]}
        onClick={(e) => setFilterTab(e.key)}
        items={[
          { key: "status", label: t("filter.status", "状态") },
          { key: "date", label: t("filter.date", "日期") },
          { key: "archive", label: t("filter.archive", "归档") },
        ]}
      />
      <div style={{ width: 1, background: "#f0f0f0", margin: "8px 0" }} />
      {filterTab === "status" ? (
        <Menu
          mode="inline"
          style={{ width: 120, borderInlineEnd: "none" }}
          selectedKeys={[taskFilterStatus]}
          onClick={(e) => setTaskFilterStatus(e.key)}
          items={[
            { key: "all", label: "All" },
            { key: "in_progress", label: "进行中" },
            { key: "completed", label: "已完成" },
            { key: "failed", label: "失败" },
            { key: "pending", label: "待处理" },
            { key: "planning", label: "规划中" },
            { type: "divider" },
            {
              key: "reset",
              label: "重置",
              onClick: () => setTaskFilterStatus("all"),
            },
          ]}
        />
      ) : filterTab === "date" ? (
        <Menu
          mode="inline"
          style={{ width: 120, borderInlineEnd: "none" }}
          selectedKeys={[taskFilterDate]}
          onClick={(e) => setTaskFilterDate(e.key)}
          items={[
            { key: "all", label: "All" },
            { key: "today", label: "今天" },
            { key: "7days", label: "最近 7 天" },
            { key: "30days", label: "最近 30 天" },
            { type: "divider" },
            {
              key: "reset",
              label: "重置",
              onClick: () => setTaskFilterDate("all"),
            },
          ]}
        />
      ) : (
        <Menu
          mode="inline"
          style={{ width: 120, borderInlineEnd: "none" }}
          selectedKeys={[taskArchiveView]}
          onClick={(e) => setTaskArchiveView(e.key as TaskArchiveView)}
          items={[
            { key: "active", label: t("filter.activeTasks", "当前任务") },
            { key: "archived", label: t("filter.archivedTasks", "归档任务") },
          ]}
        />
      )}
    </div>
  );

  // ── Render ────────────────────────────────────────────────────────────────

  const siderWidth = collapsed ? (isMobile ? 56 : 72) : 240;

  return (
    <Sider
      width={siderWidth}
      className={`${styles.sider}${
        collapsed ? ` ${styles.siderCollapsed}` : ""
      }${isDark ? ` ${styles.siderDark}` : ""}`}
    >
      <div className={styles.siderInner}>
        {collapsed ? (
          <nav className={styles.collapsedNav}>
            {collapsedNavItems.map((item) => {
              const isActive = selectedKey === item.key;
              return (
                <Tooltip
                  key={item.key}
                  title={item.label}
                  placement="right"
                  overlayInnerStyle={{
                    background: "rgba(0,0,0,0.75)",
                    color: "#fff",
                  }}
                >
                  <button
                    className={`${styles.collapsedNavItem} ${
                      isActive ? styles.collapsedNavItemActive : ""
                    }`}
                    onClick={() => navigate(item.path)}
                  >
                    {item.icon}
                  </button>
                </Tooltip>
              );
            })}
          </nav>
        ) : (
          <>
            {/* Client mode section: Chat + Control + Workspace */}
            {!isAdminMode && (
              <div className={styles.agentScopedSection}>
                <div
                  className={styles.agentSelectorContainer}
                  style={{
                    display: "flex",
                    flexDirection: "row",
                    gap: 8,
                    marginBottom: 8,
                  }}
                >
                  <Input
                    placeholder={t("nav.searchTasks", "搜索任务")}
                    prefix={<Search size={14} style={{ color: "#bfbfbf" }} />}
                    value={taskSearchQuery}
                    onChange={(e) => setTaskSearchQuery(e.target.value)}
                    style={{ flex: 1, borderRadius: 6 }}
                    variant="outlined"
                  />
                  <Popover
                    content={filterContent}
                    trigger="click"
                    placement="bottomRight"
                    arrow={false}
                    overlayInnerStyle={{ padding: 0 }}
                  >
                    <Button
                      icon={<SlidersHorizontal size={14} />}
                      style={{
                        borderRadius: 6,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    />
                  </Popover>
                </div>
                <div className={styles.agentSelectorContainer}>
                  {/* + New Task entry — navigates to Workbench scene selector */}
                  <button
                    className={`${styles.stickyChatButton}${
                      selectedKey === "workbench"
                        ? ` ${styles.stickyChatButtonActive}`
                        : ""
                    }`}
                    onClick={() => navigate("/workbench")}
                  >
                    <SparkChatTabFill size={16} />
                    <span>{t("nav.newTask")}</span>
                  </button>
                </div>
                <Menu
                  mode="inline"
                  selectedKeys={[selectedKey]}
                  openKeys={DEFAULT_OPEN_KEYS}
                  onClick={({ key }) => {
                    const path = KEY_TO_PATH[String(key)];
                    if (path) navigate(path);
                  }}
                  items={agentMenuItems}
                  theme={isDark ? "dark" : "light"}
                  className={styles.sideMenu}
                />

                {/* Task list section — shows recent tasks from chatApi */}
                {!collapsed && (
                  <div className={styles.taskListSection}>
                    <div className={styles.taskListTitle}>
                      {taskArchiveView === "archived"
                        ? t("nav.archivedTasks", "归档任务")
                        : t("nav.tasks", "任务")}
                    </div>
                    {filteredTaskList.length === 0 && !taskListLoading && (
                      <div className={styles.taskListEmpty}>
                        {taskArchiveView === "archived"
                          ? t("nav.noArchivedTasks", "暂无归档任务")
                          : t("nav.noTasks", "暂无任务")}
                      </div>
                    )}
                    <div className={styles.taskListItems}>
                      {renderTasks(filteredTaskList.slice(0, 3), true)}
                    </div>
                    {filteredTaskList.length > 3 && (
                      <Popover
                        trigger="click"
                        placement="rightBottom"
                        open={earlierTasksOpen}
                        onOpenChange={setEarlierTasksOpen}
                        title="选择更早任务"
                        content={
                          <div
                            className={styles.earlierTaskList}
                            role="region"
                            aria-label="更早任务"
                          >
                            {renderTasks(filteredTaskList.slice(3))}
                          </div>
                        }
                      >
                        <button
                          type="button"
                          className={styles.earlierTasksButton}
                          aria-expanded={earlierTasksOpen}
                        >
                          <SparkHistoryLine />
                          <span>选择更早任务</span>
                          <SparkRightArrowLine />
                        </button>
                      </Popover>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Global settings section (Admin mode) */}
            {isAdminRole && isAdminMode && (
              <Menu
                mode="inline"
                selectedKeys={[selectedKey]}
                openKeys={[
                  ...DEFAULT_OPEN_KEYS,
                  ...(pluginRoutes.length > 0 ? ["plugins-group"] : []),
                ]}
                onClick={({ key }) => {
                  const path = KEY_TO_PATH[String(key)] ?? `/${String(key)}`;
                  navigate(path);
                }}
                items={settingsMenuItems}
                theme={isDark ? "dark" : "light"}
                className={`${styles.sideMenu} ${styles.settingsSideMenu}`}
              />
            )}
          </>
        )}

        <div className={styles.siderFooter}>
          {authEnabled && username ? (
            <SidebarAccountMenu
              username={username}
              role={role}
              collapsed={collapsed}
              onOpenAccount={() => {
                accountForm.resetFields();
                setAccountModalOpen(true);
              }}
              onOpenWallet={() => navigate("/wallet")}
              onOpenAdmin={() => navigate("/admin/agents")}
              onLogout={() => {
                logout();
                window.location.href = "/login";
              }}
            />
          ) : null}

          <div className={styles.collapseToggleContainer}>
            <Button
              type="text"
              icon={
                collapsed ? (
                  <SparkMenuExpandLine size={20} />
                ) : (
                  <SparkMenuFoldLine size={20} />
                )
              }
              onClick={() => setCollapsed(!collapsed)}
              className={styles.collapseToggle}
            />
          </div>
        </div>

        <Modal
          open={accountModalOpen}
          onCancel={() => setAccountModalOpen(false)}
          title={t("account.title")}
          footer={null}
          destroyOnHidden
          centered
        >
          <Form
            form={accountForm}
            layout="vertical"
            onFinish={handleUpdateProfile}
          >
            <Form.Item
              name="currentPassword"
              label={t("account.currentPassword")}
              rules={[
                {
                  required: true,
                  message: t("account.currentPasswordRequired"),
                },
              ]}
            >
              <Input.Password />
            </Form.Item>
            <Form.Item name="newUsername" label={t("account.newUsername")}>
              <Input placeholder={t("account.newUsernamePlaceholder")} />
            </Form.Item>
            <Form.Item name="newPassword" label={t("account.newPassword")}>
              <Input.Password
                placeholder={t("account.newPasswordPlaceholder")}
              />
            </Form.Item>
            <Form.Item
              name="confirmPassword"
              label={t("account.confirmPassword")}
              dependencies={["newPassword"]}
              rules={[
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value && !getFieldValue("newPassword")) {
                      return Promise.resolve();
                    }
                    if (value === getFieldValue("newPassword")) {
                      return Promise.resolve();
                    }
                    return Promise.reject(
                      new Error(t("account.passwordMismatch")),
                    );
                  },
                }),
              ]}
            >
              <Input.Password
                placeholder={t("account.confirmPasswordPlaceholder")}
              />
            </Form.Item>
            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                loading={accountLoading}
                block
              >
                {t("account.save")}
              </Button>
            </Form.Item>
          </Form>
        </Modal>
      </div>
    </Sider>
  );
}
