import { useState, useEffect } from "react";
import { message } from "antd";
import {
  Sparkles,
  Download,
  Package,
  Wrench,
  Globe,
  FileCode,
  Database,
  Image as ImageIcon,
  Mail,
  BarChart3,
  Bot,
  Loader2,
  Lock,
  Trash2,
  Presentation,
} from "lucide-react";
import { useAgentStore } from "../../stores/agentStore";
import api from "../../api";
import type { PoolSkillSpec, SkillSpec } from "../../api/types";
import { invalidateSkillCache } from "../../api/modules/skill";
import {
  buildSkillMarketItems,
  filterSkillMarketItems,
  getSkillMarketActionState,
  isOutdatedBuiltinSkill,
  type SkillMarketItem,
} from "./skillMarketModel";
import styles from "../shared/ecoPage.module.less";

const ICON_MAP: Record<string, React.ReactNode> = {
  web: <Globe size={22} />,
  code: <FileCode size={22} />,
  data: <Database size={22} />,
  image: <ImageIcon size={22} />,
  email: <Mail size={22} />,
  chart: <BarChart3 size={22} />,
  presentation: <Presentation size={22} />,
  bot: <Bot size={22} />,
  tool: <Wrench size={22} />,
  default: <Package size={22} />,
};

const COLOR_MAP: Record<string, string> = {
  web: "#2563EB",
  code: "#8b5cf6",
  data: "#10b981",
  image: "#ec4899",
  email: "#f59e0b",
  chart: "#0ea5e9",
  presentation: "#0ea5e9",
  bot: "#6366f1",
  tool: "#ef4444",
  default: "#64748b",
};

const CATEGORIES = [
  { key: "all", label: "全部" },
  { key: "recommended", label: "⭐ 推荐" },
  { key: "hub", label: "SkillHub" },
  { key: "opc", label: "OPC 一人公司" },
  { key: "office", label: "办公文档" },
  { key: "dev", label: "开发工具" },
  { key: "life", label: "生活服务" },
];

export default function SkillMarketPage() {
  const [activeCategory, setActiveCategory] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const { selectedAgent } = useAgentStore();

  const [agentSkills, setAgentSkills] = useState<SkillSpec[]>([]);
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);
  const [loading, setLoading] = useState(false);
  const [operatingSkills, setOperatingSkills] = useState<
    Record<string, boolean>
  >({});

  const fetchAgentSkills = async () => {
    if (!selectedAgent) return;
    try {
      const data = await api.listSkills(selectedAgent);
      setAgentSkills(data || []);
    } catch (e) {
      console.error("Failed to load agent skills", e);
    }
  };

  const fetchPoolSkills = async () => {
    try {
      const data = await api.listSkillPoolSkills();
      setPoolSkills(data || []);
    } catch (e) {
      console.error("Failed to load pool skills", e);
    }
  };

  const initData = async () => {
    setLoading(true);
    await Promise.all([fetchAgentSkills(), fetchPoolSkills()]);
    setLoading(false);
  };

  useEffect(() => {
    if (selectedAgent) {
      initData();
    }
  }, [selectedAgent]);

  const handleInstall = async (skill: SkillMarketItem) => {
    if (!selectedAgent) {
      message.warning("请先在顶部或工作区选择一个 Agent / 智能体！");
      return;
    }
    const skillName = skill.backendSkillName;
    setOperatingSkills((prev) => ({ ...prev, [skillName]: true }));
    try {
      // 1. Check if the skill is already imported in the global Skill Pool
      const inPool = poolSkills.some((s) => s.name === skillName);
      const shouldUpdateBuiltin =
        skill.isBuiltin && isOutdatedBuiltinSkill(skill);
      if (skill.isBuiltin && (!inPool || shouldUpdateBuiltin)) {
        // For builtin skills, import or update the pool copy before
        // downloading it into the current workspace.
        await api.importSelectedPoolBuiltins({
          imports: [{ skill_name: skillName, language: "zh" }],
          overwrite_conflicts: true,
        });
      } else if (!inPool) {
        // For Custom/Community skills, create them in the pool dynamically
        const mockContent = `---
name: ${skillName}
description: ${skill.description}
tags: ${JSON.stringify(skill.tags)}
---

# ${skill.name}
${skill.description}
`;
        await api.createSkillPoolSkill({
          name: skillName,
          content: mockContent,
          config: {},
        });
      }

      // 2. Check if the skill is downloaded to the current workspace (agent)
      const inAgent = agentSkills.some((s) => s.name === skillName);
      if (!inAgent || shouldUpdateBuiltin) {
        // Download the skill from pool into the agent workspace
        await api.downloadSkillPoolSkill({
          skill_name: skillName,
          targets: [{ workspace_id: selectedAgent }],
          overwrite: true,
        });
      }

      // 3. Make sure the skill is enabled in the workspace
      await api.enableSkill(skillName);

      // 4. Invalidate API caches and refresh states
      invalidateSkillCache({
        agentId: selectedAgent,
        pool: true,
        workspaces: true,
      });
      await Promise.all([fetchAgentSkills(), fetchPoolSkills()]);

      message.success(`「${skill.name}」已成功安装并启用！`);
    } catch (error) {
      console.error(error);
      message.error(
        `安装「${skill.name}」失败: ${
          error instanceof Error ? error.message : "未知错误"
        }`,
      );
    } finally {
      setOperatingSkills((prev) => ({ ...prev, [skillName]: false }));
    }
  };

  const handleUninstall = async (skill: SkillMarketItem) => {
    if (!selectedAgent) return;
    const skillName = skill.backendSkillName;
    setOperatingSkills((prev) => ({ ...prev, [skillName]: true }));
    try {
      // Delete the skill directly from the agent workspace (physically uninstall)
      await api.deleteSkill(skillName);

      // Invalidate API caches and refresh states
      invalidateSkillCache({
        agentId: selectedAgent,
        pool: true,
        workspaces: true,
      });
      await Promise.all([fetchAgentSkills(), fetchPoolSkills()]);

      message.success(`已成功卸载「${skill.name}」技能`);
    } catch (error) {
      console.error(error);
      message.error(
        `卸载「${skill.name}」失败: ${
          error instanceof Error ? error.message : "未知错误"
        }`,
      );
    } finally {
      setOperatingSkills((prev) => ({ ...prev, [skillName]: false }));
    }
  };

  const filteredSkills = filterSkillMarketItems(
    buildSkillMarketItems(poolSkills),
    activeCategory,
    searchQuery,
  );

  return (
    <div className={styles.ecoPage}>
      <style>{`
        @keyframes spin-anim {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        .custom-spin {
          animation: spin-anim 1s linear infinite;
        }
      `}</style>
      <div className={styles.pageHeader}>
        <div className={styles.pageTitle}>
          <span className={styles.pageTitleIcon}>
            <Sparkles size={18} />
          </span>
          技能市场
        </div>
        <div className={styles.pageSubtitle}>
          为你的 AI
          助手安装强大的技能扩展，让它拥有浏览网页、分析数据、生成图片等超能力。
        </div>
      </div>

      <div className={styles.searchBar}>
        <input
          className={styles.searchInput}
          placeholder="搜索技能..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      <div className={styles.categoryTabs}>
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            className={`${styles.categoryTab} ${
              activeCategory === cat.key ? styles.categoryTabActive : ""
            }`}
            onClick={() => setActiveCategory(cat.key)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            padding: "80px 0",
            color: "#6366f1",
          }}
        >
          <Loader2 className="custom-spin" size={32} />
          <span style={{ marginLeft: 12, fontSize: 16, fontWeight: 500 }}>
            正在同步技能数据...
          </span>
        </div>
      ) : (
        <div className={styles.cardGrid}>
          {filteredSkills.map((skill) => {
            const iconKey = skill.icon || "default";
            const icon = ICON_MAP[iconKey] || ICON_MAP.default;
            const color = COLOR_MAP[iconKey] || COLOR_MAP.default;
            const isPrivate = skill.category === "private";

            const isInstalled = agentSkills.some(
              (s) => s.name === skill.backendSkillName,
            );
            const isOperating = operatingSkills[skill.backendSkillName];
            const actionState = getSkillMarketActionState(
              skill,
              isInstalled,
              isOperating,
            );

            return (
              <div key={skill.backendSkillName} className={styles.card}>
                <div className={styles.cardHeader}>
                  <div
                    className={styles.cardIcon}
                    style={{ background: `${color}15`, color }}
                  >
                    {isPrivate ? <Lock size={22} /> : icon}
                  </div>
                  <div className={styles.cardInfo}>
                    <div className={styles.cardName}>
                      {skill.name}
                      {isPrivate && (
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 3,
                            marginLeft: 8,
                            padding: "2px 8px",
                            borderRadius: 12,
                            background:
                              "linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%)",
                            color: "#fff",
                            fontSize: 10,
                            fontWeight: 600,
                            letterSpacing: 0.5,
                          }}
                        >
                          <Lock size={10} />
                          私有
                        </span>
                      )}
                    </div>
                    <div className={styles.cardMeta}>{skill.author}</div>
                  </div>
                </div>

                <div className={styles.cardDesc}>{skill.description}</div>

                <div className={styles.cardTags}>
                  {skill.tags?.map((tag) => (
                    <span key={tag} className={styles.cardTag}>
                      {tag}
                    </span>
                  ))}
                </div>

                <div className={styles.cardFooter}>
                  <span className={styles.cardStat}>
                    <Download size={12} />
                    {(skill.downloads || 0).toLocaleString()}
                  </span>
                  {actionState === "operating" ? (
                    <button
                      className={styles.cardAction}
                      style={{
                        background: "rgba(0,0,0,0.02)",
                        color: "#6366f1",
                        cursor: "not-allowed",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                      }}
                      disabled
                    >
                      <Loader2 className="custom-spin" size={14} />
                      处理中
                    </button>
                  ) : actionState === "update" ? (
                    <button
                      className={`${styles.cardAction} ${styles.cardActionPrimary}`}
                      onClick={() => handleInstall(skill)}
                    >
                      更新到新版
                    </button>
                  ) : actionState === "installed" ? (
                    <button
                      className={styles.cardAction}
                      style={{ background: "rgba(0,0,0,0.04)", color: "#888" }}
                      onClick={() => handleUninstall(skill)}
                    >
                      已安装 (点击卸载)
                    </button>
                  ) : (
                    <button
                      className={`${styles.cardAction} ${styles.cardActionPrimary}`}
                      onClick={() => handleInstall(skill)}
                    >
                      安装
                    </button>
                  )}
                  {isPrivate && (
                    <button
                      className={styles.cardAction}
                      style={{
                        background: "rgba(239, 68, 68, 0.06)",
                        color: "#ef4444",
                        marginLeft: 4,
                        padding: "4px 8px",
                        minWidth: "auto",
                      }}
                      onClick={async () => {
                        try {
                          await api.deleteSkillPoolSkill(
                            skill.backendSkillName,
                          );
                          invalidateSkillCache({ pool: true });
                          await Promise.all([
                            fetchAgentSkills(),
                            fetchPoolSkills(),
                          ]);
                          message.success(`已删除私有技能「${skill.name}」`);
                        } catch (e) {
                          message.error("删除失败");
                        }
                      }}
                    >
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
