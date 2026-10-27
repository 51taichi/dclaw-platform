import React, { useState, useEffect, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { useNavigate, useLocation } from "react-router-dom";
import { message, Popover } from "antd";
import {
  FileText,
  ChevronDown,
  ChevronRight,
  Zap,
  Sparkles,
  Link2,
  Check,
  Database,
  Mail,
  MessageSquare,
  Github,
  Settings,
  Package,
  Bot,
  GraduationCap,
  Terminal,
  ClipboardList,
  Info,
} from "lucide-react";
import { LoadingOutlined } from "@ant-design/icons";
import { agentsApi } from "../../../api/modules/agents";
import { providerApi } from "../../../api/modules/provider";
import type { ProviderInfo } from "../../../api/types";
import type { AgentListResponse } from "../../../api/types/agents";
import { useAgentStore, type ActiveMode } from "../../../stores/agentStore";
import { skillApi } from "../../../api/modules/skill";
import {
  buildToolbarSkillItems,
  matchesSkillSearch,
  type ToolbarSkillItem,
} from "./skillToolbarModel";
import {
  buildChatToolbarModelOptions,
  type ChatToolbarModelOption,
} from "./chatToolbarModelOptions";
import { buildAutoRoutingModelSlotRequest } from "./chatToolbarModelSelection";
import { getRouteChatId } from "../routeSession";
import styles from "./ChatToolbar.module.less";
import LocalAccessSelector from "./LocalAccessSelector";

function getSkillUIProps(name: string) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const h = Math.abs(hash % 360);
  const s = 70 + Math.abs(hash % 15);
  const l = 50 + Math.abs(hash % 10);
  const color = `hsl(${h}, ${s}%, ${l}%)`;
  const icon = name ? name.charAt(0).toUpperCase() : "S";
  return { color, icon };
}

// ── Types ─────────────────────────────────────────────────────────

import { clientVisibleAgents } from "../../Experts/visibility";
import { expertAvatar } from "../../../utils/expertIdentity";
import SuperExpertBadge from "../../../components/SuperExpertBadge";

interface ExpertOption {
  id: string;
  name: string;
  description?: string;
  avatar?: string | null;
  agent_type?: "standard" | "sealed";
}

type SkillItem = ToolbarSkillItem;

interface ConnectorItem {
  id: string;
  name: string;
  nameKey: string;
  icon: React.ReactNode;
  color: string;
}

// ── Preset Data ───────────────────────────────────────────────────

const DEFAULT_EXPERT: ExpertOption = {
  id: "craft",
  name: "Craft",
  description: "Default mode — direct execution",
};

const PLAN_EXPERT: ExpertOption = {
  id: "plan",
  name: "Plan",
  description: "Planning and reasoning mode",
};

const ASK_EXPERT: ExpertOption = {
  id: "ask",
  name: "Ask",
  description: "Q&A and consultation mode",
};

/** These are UI modes, NOT real backend agent IDs */
const DEFAULT_MODES = [DEFAULT_EXPERT, PLAN_EXPERT, ASK_EXPERT];
const MODE_IDS = new Set(DEFAULT_MODES.map((m) => m.id));

const PRESET_CONNECTORS: ConnectorItem[] = [
  {
    id: "github",
    name: "GitHub",
    nameKey: "chatToolbar.connectorNames.github",
    icon: <Github size={16} />,
    color: "#24292e",
  },
  {
    id: "feishu",
    name: "飞书",
    nameKey: "chatToolbar.connectorNames.feishu",
    icon: <MessageSquare size={16} />,
    color: "#3370ff",
  },
  {
    id: "dingtalk",
    name: "钉钉",
    nameKey: "chatToolbar.connectorNames.dingtalk",
    icon: <MessageSquare size={16} />,
    color: "#0089ff",
  },
  {
    id: "wechat-work",
    name: "企业微信",
    nameKey: "chatToolbar.connectorNames.wecom",
    icon: <MessageSquare size={16} />,
    color: "#07c160",
  },
  {
    id: "notion",
    name: "Notion",
    nameKey: "chatToolbar.connectorNames.notion",
    icon: <FileText size={16} />,
    color: "#000",
  },
  {
    id: "mysql",
    name: "MySQL",
    nameKey: "chatToolbar.connectorNames.mysql",
    icon: <Database size={16} />,
    color: "#00758f",
  },
  {
    id: "smtp",
    name: "邮件服务",
    nameKey: "chatToolbar.connectorNames.email",
    icon: <Mail size={16} />,
    color: "#ea4335",
  },
];

// ── Hook: Click outside ──────────────────────────────────────────

function useClickOutside(
  ref: React.RefObject<HTMLElement | null>,
  onClose: () => void,
) {
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ref, onClose]);
}

// ── Component ────────────────────────────────────────────────────

const renderModePopover = (modeId: string, t: TFunction) => {
  let title = "";
  let desc = "";
  let features: string[] = [];
  let isRecommended = false;

  if (modeId === "craft") {
    title = "Craft";
    isRecommended = true;
    desc = t("chatToolbar.modeDetails.craft.description");
    features = [
      t("chatToolbar.modeDetails.craft.fileAccess"),
      t("chatToolbar.modeDetails.craft.terminal"),
      t("chatToolbar.modeDetails.craft.webSearch"),
    ];
  } else if (modeId === "plan") {
    title = "Plan";
    desc = t("chatToolbar.modeDetails.plan.description");
    features = [
      t("chatToolbar.modeDetails.plan.reasoning"),
      t("chatToolbar.modeDetails.plan.architecture"),
      t("chatToolbar.modeDetails.plan.breakdown"),
    ];
  } else if (modeId === "ask") {
    title = "Ask";
    desc = t("chatToolbar.modeDetails.ask.description");
    features = [
      t("chatToolbar.modeDetails.ask.consulting"),
      t("chatToolbar.modeDetails.ask.codeAnalysis"),
      t("chatToolbar.modeDetails.ask.frameworkKnowledge"),
    ];
  } else {
    return null;
  }

  return (
    <div
      style={{ maxWidth: 220, fontSize: 13, color: "#333", padding: "4px 2px" }}
    >
      <div
        style={{
          fontWeight: 600,
          fontSize: 14,
          marginBottom: 4,
          color: "#111",
        }}
      >
        {title}
      </div>
      {isRecommended && (
        <div
          style={{
            color: "#10b981",
            fontSize: 12,
            marginBottom: 6,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          <Sparkles size={14} />
          <span>{t("chatToolbar.recommended")}</span>
        </div>
      )}
      <div style={{ color: "#666", lineHeight: 1.5, marginBottom: 8 }}>
        {desc}
      </div>
      <div style={{ height: 1, background: "#f0f0f0", margin: "8px 0" }} />
      <div style={{ color: "#888", fontSize: 12, marginBottom: 6 }}>
        Tools - Built-in
      </div>
      <ul
        style={{
          margin: 0,
          paddingLeft: 18,
          color: "#555",
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        {features.map((f, i) => (
          <li key={i} style={{ paddingLeft: 2 }}>
            {f}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default function ChatToolbar({
  disabled = false,
  isClawMode = false,
  onSkillSelect,
  overrideSelectedAgent,
  overrideActiveMode,
  onAgentChange,
  onModeChange,
}: {
  disabled?: boolean;
  isClawMode?: boolean;
  onSkillSelect?: (skill: SkillItem) => void;
  overrideSelectedAgent?: string;
  overrideActiveMode?: ActiveMode;
  onAgentChange?: (agentId: string) => void;
  onModeChange?: (mode: ActiveMode) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (!disabled) return;
    setShowExpertMenu(false);
    setShowModelMenu(false);
    setShowSkills(false);
    setShowConnectors(false);
  }, [disabled]);

  const store = useAgentStore();
  const selectedExpertTeam = !isClawMode ? store.selectedExpertTeam : null;
  const selectedAgent =
    overrideSelectedAgent !== undefined
      ? overrideSelectedAgent
      : isClawMode
      ? store.clawSelectedAgent
      : store.selectedAgent;
  const setStoreAgent =
    overrideSelectedAgent !== undefined
      ? (id: string) => onAgentChange?.(id)
      : isClawMode
      ? store.setClawSelectedAgent
      : store.setSelectedAgent;
  const activeMode =
    overrideActiveMode !== undefined
      ? overrideActiveMode
      : isClawMode
      ? store.clawActiveMode
      : store.activeMode;
  const setActiveMode =
    overrideActiveMode !== undefined
      ? (mode: ActiveMode) => onModeChange?.(mode)
      : isClawMode
      ? store.setClawActiveMode
      : store.setActiveMode;
  const [experts, setExperts] = useState<ExpertOption[]>(DEFAULT_MODES);
  const [showExpertMenu, setShowExpertMenu] = useState(false);
  const [showSummonSubMenu, setShowSummonSubMenu] = useState(false);

  // Skills dynamic loading
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [loadingSkills, setLoadingSkills] = useState(false);

  const selectSkill = useCallback(
    (skill: SkillItem) => {
      if (onSkillSelect) {
        onSkillSelect(skill);
      } else {
        const setStoreSkill = isClawMode
          ? store.setClawSelectedSkill
          : store.setSelectedSkill;
        setStoreSkill(skill);
      }
    },
    [
      isClawMode,
      onSkillSelect,
      store.setClawSelectedSkill,
      store.setSelectedSkill,
    ],
  );

  const fetchSkills = useCallback(
    (selectImportedSkillId?: string) => {
      setLoadingSkills(true);

      // Load both workspace skills and pool skills in parallel
      Promise.all([
        skillApi.listSkills(selectedAgent).catch(() => []),
        skillApi.listSkillPoolSkills().catch(() => []),
      ])
        .then(([wsData, poolData]) => {
          const nextSkills = buildToolbarSkillItems(
            wsData || [],
            poolData || [],
            getSkillUIProps,
          );
          setSkills(nextSkills);

          if (selectImportedSkillId) {
            const importedSkill = nextSkills.find(
              (skill) => skill.id === selectImportedSkillId,
            );
            if (importedSkill) {
              selectSkill(importedSkill);
            }
          }
        })
        .finally(() => {
          setLoadingSkills(false);
        });
    },
    [selectSkill, selectedAgent],
  );

  useEffect(() => {
    fetchSkills();
    const handleRefresh = () => {
      fetchSkills();
    };
    const handleSkillImported = (event: Event) => {
      const detail = (event as CustomEvent<{ name?: string }>).detail;
      fetchSkills(detail?.name);
    };
    window.addEventListener("refresh-chat-skills", handleRefresh);
    window.addEventListener("qwenpaw-skill-imported", handleSkillImported);
    return () => {
      window.removeEventListener("refresh-chat-skills", handleRefresh);
      window.removeEventListener("qwenpaw-skill-imported", handleSkillImported);
    };
  }, [fetchSkills]);

  // Other menus
  const [showModelMenu, setShowModelMenu] = useState(false);
  const [showSkills, setShowSkills] = useState(false);
  const [showConnectors, setShowConnectors] = useState(false);
  const [skillSearch, setSkillSearch] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [loadingModelSwitch, setLoadingModelSwitch] = useState(false);
  const [availableModels, setAvailableModels] = useState<
    ChatToolbarModelOption[]
  >([]);

  const chatId = React.useMemo(
    () => getRouteChatId(location.pathname),
    [location.pathname],
  );

  const expertRef = useRef<HTMLDivElement>(null);
  const modelRef = useRef<HTMLDivElement>(null);
  const skillRef = useRef<HTMLDivElement>(null);
  const connRef = useRef<HTMLDivElement>(null);

  // Load client-callable agents, including API-enabled super experts.
  useEffect(() => {
    let cancelled = false;
    const refresh = () =>
      agentsApi
        .listAgents({ excludeOpenApi: true })
        .then((res: AgentListResponse) => {
          const agentList: ExpertOption[] = [];
          if (res?.agents && Array.isArray(res.agents)) {
            clientVisibleAgents(res.agents).forEach((a) => {
              if (a.enabled !== false) {
                agentList.push({
                  id: a.id,
                  name: a.name || a.id,
                  description: a.description || "",
                  avatar: a.avatar,
                  agent_type: a.agent_type,
                });
              }
            });
          }

          if (!cancelled) setExperts(agentList);
        })
        .catch(() => {
          if (!cancelled) setExperts(DEFAULT_MODES);
        });
    void refresh();
    window.addEventListener("expert-avatar-updated", refresh);
    return () => {
      cancelled = true;
      window.removeEventListener("expert-avatar-updated", refresh);
    };
  }, []);

  // Load available models from authorized providers
  useEffect(() => {
    providerApi
      .listProviders()
      .then((providers: ProviderInfo[]) => {
        setAvailableModels(buildChatToolbarModelOptions(providers));
      })
      .catch(() => {
        setAvailableModels([]);
      });
  }, []);

  // Fetch active model from backend
  const fetchActiveModel = useCallback(async () => {
    try {
      const activeData = await providerApi.getActiveModels({
        scope: chatId ? "chat" : "effective",
        agent_id: selectedAgent,
        chat_id: chatId,
      });
      if (
        activeData?.active_llm?.provider_id &&
        activeData?.active_llm?.model
      ) {
        const candidate = `${activeData.active_llm.provider_id}/${activeData.active_llm.model}`;
        setSelectedModel(
          availableModels.some((option) => option.id === candidate)
            ? candidate
            : "",
        );
      } else {
        setSelectedModel(""); // Auto
      }
    } catch (err) {
      console.error("ChatToolbar: failed to load active model", err);
    }
  }, [availableModels, chatId, selectedAgent]);

  useEffect(() => {
    fetchActiveModel();
  }, [fetchActiveModel]);

  // Re-sync active model whenever the route switches back
  const prevPathRef = useRef(location.pathname);
  useEffect(() => {
    const prev = prevPathRef.current;
    const curr = location.pathname;
    prevPathRef.current = curr;
    if (curr !== prev) {
      fetchActiveModel();
    }
  }, [location.pathname, fetchActiveModel]);

  useClickOutside(expertRef, () => setShowExpertMenu(false));
  useClickOutside(modelRef, () => setShowModelMenu(false));
  useClickOutside(skillRef, () => setShowSkills(false));
  useClickOutside(connRef, () => setShowConnectors(false));

  const filteredSkills = skills.filter((skill) =>
    matchesSkillSearch(skill, skillSearch),
  );

  // Determine current display: if activeMode is a known mode, show that; otherwise show the agent
  const currentModeOption = DEFAULT_MODES.find((m) => m.id === activeMode);
  const currentExpertAgent = experts.find((e) => e.id === selectedAgent);
  const currentExpert: ExpertOption =
    currentModeOption ||
    (selectedExpertTeam
      ? {
          id: selectedExpertTeam.id,
          name: selectedExpertTeam.name,
          description: selectedExpertTeam.description,
        }
      : currentExpertAgent) ||
    DEFAULT_MODES[0];

  const recentAgents = store.recentAgents || [];
  let recentExperts = recentAgents
    .map((id) => experts.find((e) => e.id === id))
    .filter(Boolean) as ExpertOption[];
  if (recentExperts.length === 0) {
    recentExperts = experts.slice(0, 3);
  }
  const visibleSelectedModel = availableModels.some(
    (model) => model.id === selectedModel,
  )
    ? selectedModel
    : "";

  return (
    <div
      className={`${styles.chatToolbar} qwenpaw-chat-toolbar ${
        disabled ? styles.chatToolbarDisabled : ""
      }`}
      aria-disabled={disabled}
      onClickCapture={
        disabled
          ? (event) => {
              event.preventDefault();
              event.stopPropagation();
            }
          : undefined
      }
      onKeyDownCapture={
        disabled
          ? (event) => {
              event.preventDefault();
              event.stopPropagation();
            }
          : undefined
      }
    >
      {/* ── Expert / Mode Selector (default: Craft) ── */}
      <div ref={expertRef} style={{ position: "relative" }}>
        <button
          className={`${styles.toolbarBtn} ${styles.toolbarBtnActive}`}
          onClick={() => {
            setShowExpertMenu(!showExpertMenu);
            setShowModelMenu(false);
            setShowSkills(false);
            setShowConnectors(false);
          }}
        >
          <span className={styles.toolbarBtnIcon}>
            {MODE_IDS.has(currentExpert.id) ? (
              <FileText size={14} className={styles.expertAvatar} />
            ) : selectedExpertTeam &&
              currentExpert.id === selectedExpertTeam.id ? (
              <GraduationCap size={14} className={styles.expertAvatar} />
            ) : (
              <img
                src={expertAvatar(currentExpert)}
                className={styles.expertAvatar}
                alt=""
              />
            )}
          </span>
          <span className={styles.expertName}>{currentExpert.name}</span>
          {currentExpert.agent_type === "sealed" && <SuperExpertBadge />}
          <ChevronDown size={12} className={styles.toolbarChevron} />
        </button>

        {showExpertMenu && (
          <div
            className={styles.dropdownOverlay}
            style={{ overflowY: "visible" }}
          >
            <div className={styles.dropdownTitle}>
              {t("chatToolbar.selectMode", "选择专家 / 模式")}
            </div>

            {/* Render Default Modes (Craft, Plan, Ask) */}
            {DEFAULT_MODES.map((mode) => (
              <button
                key={mode.id}
                className={`${styles.dropdownItem} ${
                  currentExpert.id === mode.id ? styles.dropdownItemActive : ""
                }`}
                onClick={() => {
                  setActiveMode(mode.id as ActiveMode);
                  setShowExpertMenu(false);
                }}
              >
                <span className={styles.dropdownItemIcon}>
                  {mode.id === "craft" ? (
                    <Terminal size={16} />
                  ) : mode.id === "plan" ? (
                    <ClipboardList size={16} />
                  ) : (
                    <MessageSquare size={16} />
                  )}
                </span>
                <div style={{ flex: 1, textAlign: "left" }}>
                  <div className={styles.dropdownItemLabel}>{mode.name}</div>
                </div>
                <Popover
                  content={renderModePopover(mode.id, t)}
                  placement="right"
                  overlayInnerStyle={{ borderRadius: 8 }}
                >
                  <span
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      width: 24,
                      height: 24,
                      borderRadius: 12,
                      zIndex: 2,
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Info size={14} style={{ color: "#aaa", opacity: 0.6 }} />
                  </span>
                </Popover>
                {activeMode === mode.id && (
                  <Check size={14} className={styles.dropdownItemCheck} />
                )}
              </button>
            ))}

            <div className={styles.dropdownDivider} />

            {/* Summon Expert with Submenu */}
            <div
              className={styles.summonExpertWrapper}
              onMouseEnter={() => setShowSummonSubMenu(true)}
              onMouseLeave={() => setShowSummonSubMenu(false)}
            >
              <button className={styles.dropdownItem}>
                <span
                  className={styles.dropdownItemIcon}
                  style={{ color: "#6366f1" }}
                >
                  <GraduationCap size={16} />
                </span>
                <div style={{ flex: 1, textAlign: "left" }}>
                  <div className={styles.dropdownItemLabel}>
                    {t("chatToolbar.summonExpert", "召唤专家团")}
                  </div>
                </div>
                <ChevronRight size={14} className={styles.summonChevron} />
              </button>

              {showSummonSubMenu && (
                <div className={styles.summonSubMenu}>
                  <div className={styles.dropdownTitle}>
                    {t("chatToolbar.recentExperts", "最近使用智能体")}
                  </div>
                  {recentExperts.map((expert) => {
                    const { color } = getSkillUIProps(expert.name);
                    return (
                      <button
                        key={expert.id}
                        className={`${styles.dropdownItem} ${
                          currentExpert.id === expert.id
                            ? styles.dropdownItemActive
                            : ""
                        }`}
                        onClick={() => {
                          setStoreAgent(expert.id);
                          setActiveMode("");
                          setShowExpertMenu(false);
                          setShowSummonSubMenu(false);
                          message.info(
                            t("chatToolbar.summonedExpert", {
                              name: expert.name,
                            }),
                          );
                        }}
                      >
                        <div
                          className={styles.dropdownItemIconCircle}
                          style={{
                            background:
                              currentExpert.id === expert.id
                                ? "rgba(37, 99, 235, 0.08)"
                                : expert.id === "default" ||
                                  expert.id === "craft"
                                ? "#f97316"
                                : color,
                            color:
                              currentExpert.id === expert.id
                                ? "#2563eb"
                                : "#fff",
                            overflow: "hidden",
                          }}
                        >
                          <img
                            src={
                              expert.avatar ||
                              (expert.agent_type === "sealed"
                                ? expertAvatar(expert)
                                : expert.id === "default" ||
                                  expert.id === "craft"
                                ? "/dclaw.png"
                                : `/avatars/${expert.id}.png`)
                            }
                            onError={(e) => {
                              e.currentTarget.style.display = "none";
                              const nextSibling = e.currentTarget
                                .nextElementSibling as HTMLElement;
                              if (nextSibling)
                                nextSibling.style.display = "flex";
                            }}
                            style={{
                              width: "100%",
                              height: "100%",
                              objectFit: "cover",
                            }}
                            alt=""
                          />
                          <span
                            style={{
                              display: "none",
                              width: "100%",
                              height: "100%",
                              alignItems: "center",
                              justifyContent: "center",
                              fontWeight: "bold",
                            }}
                          >
                            {expert.name.charAt(0).toUpperCase()}
                          </span>
                        </div>
                        <div
                          style={{ flex: 1, textAlign: "left", minWidth: 0 }}
                        >
                          <div className={styles.dropdownItemLabel}>
                            {expert.name}
                          </div>
                          {expert.name !== "Default" && (
                            <div className={styles.dropdownItemDesc}>
                              {expert.id}
                            </div>
                          )}
                        </div>
                        {expert.agent_type === "sealed" && (
                          <span
                            style={{ alignSelf: "flex-start", marginTop: 4 }}
                          >
                            <SuperExpertBadge />
                          </span>
                        )}
                        {currentExpert.id === expert.id && (
                          <Check
                            size={14}
                            className={styles.dropdownItemCheck}
                          />
                        )}
                      </button>
                    );
                  })}
                  <div className={styles.dropdownDivider} />
                  <button
                    className={styles.dropdownItem}
                    onClick={() => {
                      setShowExpertMenu(false);
                      setShowSummonSubMenu(false);
                      navigate("/experts", {
                        state: { from: location.pathname },
                      });
                    }}
                  >
                    <div
                      style={{
                        width: 32,
                        display: "flex",
                        justifyContent: "center",
                        color: "#6366f1",
                        flexShrink: 0,
                      }}
                    >
                      <GraduationCap size={16} />
                    </div>
                    <div
                      className={styles.dropdownItemLabel}
                      style={{ color: "#6366f1", flex: 1, textAlign: "left" }}
                    >
                      {t("chatToolbar.summonOtherExperts", "打开专家中心")}
                    </div>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <span className={styles.toolbarDivider} />

      {/* ── Auto / Model Selector ── */}
      <div ref={modelRef} style={{ position: "relative" }}>
        <button
          className={styles.toolbarBtn}
          onClick={() => {
            setShowModelMenu(!showModelMenu);
            setShowExpertMenu(false);
            setShowSkills(false);
            setShowConnectors(false);
          }}
          disabled={loadingModelSwitch}
        >
          <span className={styles.toolbarBtnIcon}>
            {loadingModelSwitch ? (
              <LoadingOutlined style={{ fontSize: 14, color: "#FF7F16" }} />
            ) : (
              <Zap size={14} />
            )}
          </span>
          {availableModels.find((m) => m.id === visibleSelectedModel)?.name ||
            t("chatToolbar.auto")}
          <ChevronDown size={12} className={styles.toolbarChevron} />
        </button>

        {showModelMenu && (
          <div className={styles.dropdownOverlay}>
            <div className={styles.dropdownTitle}>
              {t("chatToolbar.modelLabel")}
            </div>
            {/* Auto option */}
            <button
              className={`${styles.dropdownItem} ${
                !visibleSelectedModel ? styles.dropdownItemActive : ""
              }`}
              onClick={async () => {
                setLoadingModelSwitch(true);
                setShowModelMenu(false);
                try {
                  await providerApi.setActiveLlm(
                    buildAutoRoutingModelSlotRequest({
                      selectedAgent,
                      chatId,
                    }),
                  );
                  setSelectedModel("");
                  message.info(t("chatToolbar.switchedToAuto"));
                  window.dispatchEvent(new CustomEvent("model-switched"));
                } catch {
                  message.error(t("chatToolbar.switchFailed"));
                } finally {
                  setLoadingModelSwitch(false);
                }
              }}
            >
              <div
                className={styles.dropdownItemIconCircle}
                style={{
                  background: !visibleSelectedModel
                    ? "rgba(37, 99, 235, 0.08)"
                    : "rgba(0, 0, 0, 0.04)",
                  color: !visibleSelectedModel ? "#2563eb" : "#9ca3af",
                }}
              >
                <Zap size={14} />
              </div>
              <div
                className={styles.dropdownItemContent}
                style={{
                  flex: 1,
                  minWidth: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: "2px",
                  alignItems: "flex-start",
                  textAlign: "left",
                }}
              >
                <div className={styles.dropdownItemLabel}>Auto</div>
                <div className={styles.dropdownItemDesc}>
                  {t("chatToolbar.smartRouting")}
                </div>
              </div>
              {!visibleSelectedModel && (
                <Check size={14} className={styles.dropdownItemCheck} />
              )}
            </button>
            {/* Dynamic models from backend */}
            {availableModels.map((model) => {
              const isSelected = visibleSelectedModel === model.id;
              return (
                <button
                  key={model.id}
                  className={`${styles.dropdownItem} ${
                    isSelected ? styles.dropdownItemActive : ""
                  }`}
                  onClick={async () => {
                    setLoadingModelSwitch(true);
                    setShowModelMenu(false);
                    try {
                      const [provider_id, ...modelParts] = model.id.split("/");
                      const model_id = modelParts.join("/");
                      await providerApi.setActiveLlm({
                        provider_id: provider_id,
                        model: model_id,
                        scope: chatId ? "chat" : "agent",
                        agent_id: selectedAgent,
                        chat_id: chatId,
                      });
                      setSelectedModel(model.id);
                      message.info(
                        t("chatToolbar.switchedToModel", {
                          model: model.name,
                        }),
                      );
                      window.dispatchEvent(new CustomEvent("model-switched"));
                    } catch {
                      message.error(t("chatToolbar.switchFailed"));
                    } finally {
                      setLoadingModelSwitch(false);
                    }
                  }}
                >
                  <div
                    className={styles.dropdownItemIconCircle}
                    style={{
                      background: isSelected
                        ? "rgba(37, 99, 235, 0.08)"
                        : "rgba(0, 0, 0, 0.04)",
                      color: isSelected ? "#2563eb" : "#9ca3af",
                    }}
                  >
                    <Bot size={15} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className={styles.dropdownItemLabel}>{model.name}</div>
                    <div className={styles.dropdownItemDesc}>
                      {model.provider || "LM Studio"}
                    </div>
                  </div>
                  {isSelected && (
                    <Check size={14} className={styles.dropdownItemCheck} />
                  )}
                </button>
              );
            })}
            {availableModels.length === 0 && (
              <div style={{ padding: "8px 12px", color: "#999", fontSize: 12 }}>
                {t(
                  "chatToolbar.noModels",
                  "暂无可用模型，请先在设置中配置 Provider",
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <LocalAccessSelector
        chatId={chatId}
        agentId={selectedExpertTeam?.leader_agent_id || selectedAgent}
        disabled={disabled}
        onOpen={() => {
          setShowExpertMenu(false);
          setShowModelMenu(false);
          setShowSkills(false);
          setShowConnectors(false);
        }}
      />

      <span className={styles.toolbarDivider} />

      {/* ── Skills Button ── */}
      <div ref={skillRef} style={{ position: "relative" }}>
        <button
          className={styles.toolbarBtn}
          onClick={() => {
            setShowSkills(!showSkills);
            setShowExpertMenu(false);
            setShowModelMenu(false);
            setShowConnectors(false);
          }}
        >
          <span className={styles.toolbarBtnIcon}>
            <Sparkles size={14} />
          </span>
          {t("chatToolbar.skills")}
        </button>

        {showSkills && (
          <div className={styles.popoverPanel}>
            <input
              className={styles.popoverSearch}
              placeholder={t("chatToolbar.searchSkills")}
              value={skillSearch}
              onChange={(e) => setSkillSearch(e.target.value)}
              autoFocus
            />
            {loadingSkills ? (
              <div
                style={{
                  padding: "16px",
                  textAlign: "center",
                  color: "#8b5cf6",
                }}
              >
                <div
                  className="animate-spin"
                  style={{ display: "inline-block", marginRight: "8px" }}
                >
                  🔮
                </div>
                {t("chatToolbar.loadingSkills")}
              </div>
            ) : filteredSkills.length === 0 ? (
              <div
                style={{
                  padding: "16px",
                  textAlign: "center",
                  color: "#999",
                  fontSize: "12px",
                }}
              >
                {t("chatToolbar.noSkills")}
              </div>
            ) : (
              (() => {
                // Group skills: default vs private vs installed
                const defaultItems = filteredSkills.filter((s) => s.isDefault);
                const privateItems = filteredSkills.filter(
                  (s) => !s.isDefault && s.isPrivate,
                );
                const installedItems = filteredSkills.filter(
                  (s) => !s.isDefault && !s.isPrivate,
                );

                const renderSkillItem = (skill: SkillItem) => (
                  <div
                    key={skill.id}
                    className={styles.popoverItem}
                    onClick={() => {
                      selectSkill(skill);
                      setShowSkills(false);
                    }}
                  >
                    <div
                      className={styles.popoverItemIcon}
                      style={{
                        background: skill.color,
                        color: "#fff",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: "bold",
                      }}
                    >
                      {skill.icon}
                    </div>
                    <div className={styles.popoverItemInfo}>
                      <div className={styles.popoverItemName}>
                        {skill.name}
                        {skill.isPrivate && !skill.isDefault && (
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              marginLeft: 6,
                              padding: "1px 5px",
                              borderRadius: 8,
                              background:
                                "linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%)",
                              color: "#fff",
                              fontSize: 9,
                              fontWeight: 600,
                            }}
                          >
                            {t("chatToolbar.privateSkill")}
                          </span>
                        )}
                        {skill.isDefault && (
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              marginLeft: 6,
                              padding: "1px 5px",
                              borderRadius: 8,
                              background:
                                "linear-gradient(135deg, #f59e0b 0%, #d97706 100%)",
                              color: "#fff",
                              fontSize: 9,
                              fontWeight: 600,
                            }}
                          >
                            {t("chatToolbar.defaultSkillBadge")}
                          </span>
                        )}
                      </div>
                      <div className={styles.popoverItemDesc}>{skill.desc}</div>
                    </div>
                  </div>
                );

                return (
                  <>
                    {defaultItems.length > 0 && (
                      <>
                        <div
                          style={{
                            padding: "6px 12px 4px",
                            fontSize: 11,
                            fontWeight: 600,
                            color: "#d97706",
                            letterSpacing: 0.5,
                            textTransform: "uppercase",
                          }}
                        >
                          {t("chatToolbar.defaultSkills")}
                        </div>
                        {defaultItems.map(renderSkillItem)}
                        {(privateItems.length > 0 ||
                          installedItems.length > 0) && (
                          <div
                            style={{
                              margin: "4px 12px",
                              height: 1,
                              background: "rgba(0,0,0,0.06)",
                            }}
                          />
                        )}
                      </>
                    )}
                    {privateItems.length > 0 && (
                      <>
                        <div
                          style={{
                            padding: "6px 12px 4px",
                            fontSize: 11,
                            fontWeight: 600,
                            color: "#8b5cf6",
                            letterSpacing: 0.5,
                            textTransform: "uppercase",
                          }}
                        >
                          {t("chatToolbar.mySkills")}
                        </div>
                        {privateItems.map(renderSkillItem)}
                        {installedItems.length > 0 && (
                          <div
                            style={{
                              margin: "4px 12px",
                              height: 1,
                              background: "rgba(0,0,0,0.06)",
                            }}
                          />
                        )}
                      </>
                    )}
                    {installedItems.length > 0 && (
                      <>
                        <div
                          style={{
                            padding: "6px 12px 4px",
                            fontSize: 11,
                            fontWeight: 600,
                            color: "#64748b",
                            letterSpacing: 0.5,
                            textTransform: "uppercase",
                          }}
                        >
                          {t("chatToolbar.installedSkills")}
                        </div>
                        {installedItems.map(renderSkillItem)}
                      </>
                    )}
                  </>
                );
              })()
            )}
            <div className={styles.popoverFooter}>
              <button
                className={styles.popoverFooterBtn}
                onClick={() => {
                  setShowSkills(false);
                  navigate("/skill-market");
                }}
              >
                <Package size={13} />
                {t("chatToolbar.importSkill")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Connectors Button ── */}
      <div ref={connRef} style={{ position: "relative" }}>
        <button
          className={styles.toolbarBtn}
          onClick={() => {
            setShowConnectors(!showConnectors);
            setShowExpertMenu(false);
            setShowModelMenu(false);
            setShowSkills(false);
          }}
        >
          <span className={styles.toolbarBtnIcon}>
            <Link2 size={14} />
          </span>
        </button>

        {showConnectors && (
          <div className={styles.popoverPanel}>
            {PRESET_CONNECTORS.map((conn) => {
              const connectorName = t(conn.nameKey, conn.name);
              return (
                <div key={conn.id} className={styles.popoverItem}>
                  <div
                    className={styles.popoverItemIcon}
                    style={{ background: `${conn.color}15`, color: conn.color }}
                  >
                    {conn.icon}
                  </div>
                  <div className={styles.popoverItemInfo}>
                    <div className={styles.popoverItemName}>
                      {connectorName}
                    </div>
                  </div>
                  <span
                    className={styles.popoverItemAction}
                    onClick={() => {
                      message.success(
                        t("chatToolbar.connectorConnected", {
                          name: connectorName,
                        }),
                      );
                    }}
                  >
                    {t("chatToolbar.connect")}
                  </span>
                </div>
              );
            })}
            <div className={styles.popoverFooter}>
              <button
                className={styles.popoverFooterBtn}
                onClick={() => {
                  setShowConnectors(false);
                  navigate("/connectors");
                }}
              >
                <Settings size={13} />
                {t("chatToolbar.manageConnectors")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
