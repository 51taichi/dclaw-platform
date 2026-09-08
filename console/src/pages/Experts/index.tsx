import { useState } from "react";
import { message } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate, useLocation } from "react-router-dom";
import { useAgentStore } from "../../stores/agentStore";
import { Star, ArrowRight, Users } from "lucide-react";
import styles from "../shared/ecoPage.module.less";
import { CATEGORIES, EXPERT_UI_CONFIGS, TEAM_COLORS } from "./data";
import { expertTeamsApi } from "../../api/modules/expertTeams";
import type { ExpertTeamTemplate } from "../../api/types/expertTeams";
import { agentsApi } from "../../api/modules/agents";
import type { AgentSummary } from "../../api/types/agents";
import { useEffect } from "react";
import sessionApi from "../Chat/sessionApi";
import { resolveExpertSummonTarget } from "./navigation";
import { clientVisibleAgents } from "./visibility";

type ExpertCardItem = {
  id: string;
  name: string;
  description?: string;
  icon: React.ReactNode;
  color: string;
  members: string[];
  tags: string[];
  usageCount: number;
  category: string;
  badge?: "hot" | "new";
  kind: "agent" | "team";
  agentId: string;
  team?: ExpertTeamTemplate;
};

const TEAM_CATEGORY_MAP: Record<string, string> = {
  engineering: "dev",
  content: "content",
  business: "business",
  data: "data",
  finance: "finance",
  research: "research",
};

export default function ExpertsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const { setSelectedAgent, setActiveMode, setSelectedExpertTeam } =
    useAgentStore();
  const [activeCategory, setActiveCategory] = useState("all");
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [teams, setTeams] = useState<ExpertTeamTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      agentsApi.listAgents({ excludeOpenApi: true }),
      expertTeamsApi.listExpertTeams(),
    ])
      .then(([agentRes, teamRes]) => {
        setAgents(clientVisibleAgents(agentRes.agents || []));
        setTeams(teamRes || []);
      })
      .catch(() => message.error(t("common.fetchFailed", "获取专家失败")))
      .finally(() => setLoading(false));
  }, [t]);

  const agentCards: ExpertCardItem[] = agents.map((agent) => {
    const uiConf = EXPERT_UI_CONFIGS.find((item) => item.id === agent.id);
    return {
      id: `agent:${agent.id}`,
      name: uiConf?.name || agent.name,
      description: agent.description || uiConf?.desc,
      icon: uiConf?.icon || <Users size={22} />,
      color: uiConf?.color || "#6b7280",
      members: uiConf?.members || [],
      tags: uiConf?.tags || [],
      usageCount: uiConf?.usageCount || 0,
      category: uiConf?.category || "business",
      badge: uiConf?.badge,
      kind: "agent",
      agentId: agent.id,
    };
  });

  const teamCards: ExpertCardItem[] = teams.map((team, index) => {
    const color = TEAM_COLORS[index % TEAM_COLORS.length];
    const mappedCategory = team.category
      ? TEAM_CATEGORY_MAP[team.category]
      : undefined;
    return {
      id: `team:${team.id}`,
      name: team.name,
      description: team.description,
      icon: <span aria-hidden>{team.icon || "👥"}</span>,
      color,
      members: team.members.map((member) => member.display_name),
      tags: team.tags || [],
      usageCount: team.usage_count || 0,
      category: mappedCategory || team.category || "business",
      badge: team.source === "builtin" ? "hot" : undefined,
      kind: "team",
      agentId: team.leader_agent_id || "default",
      team,
    };
  });

  const filteredTeamCards = teamCards.filter(
    (expert) => activeCategory === "all" || expert.category === activeCategory,
  );
  const filteredAgentCards = agentCards.filter(
    (expert) => activeCategory === "all" || expert.category === activeCategory,
  );
  const hasAnyResult =
    filteredTeamCards.length > 0 || filteredAgentCards.length > 0;

  const renderExpertCard = (expert: ExpertCardItem) => (
    <div key={expert.id} className={styles.card}>
      {expert.badge && (
        <span
          className={`${styles.badge} ${
            expert.badge === "hot" ? styles.badgeHot : styles.badgeNew
          }`}
        >
          {expert.badge === "hot" ? "🔥 热门" : "✨ 新上"}
        </span>
      )}

      <div className={styles.cardHeader}>
        <div
          className={styles.cardIcon}
          style={{ background: `${expert.color}15`, color: expert.color }}
        >
          {expert.icon}
        </div>
        <div className={styles.cardInfo}>
          <div className={styles.cardName}>{expert.name}</div>
          <div className={styles.cardMeta}>
            {expert.kind === "team"
              ? `${expert.members.length} 位协作成员`
              : "智能体专家"}
          </div>
        </div>
      </div>

      <div className={styles.cardDesc}>
        {expert.description || "一个全能的 AI 专家。"}
      </div>

      <div className={styles.cardTags}>
        {expert.kind === "team" && (
          <span className={styles.cardTag}>专家团</span>
        )}
        {(expert.tags || []).map((tag) => (
          <span key={tag} className={styles.cardTag}>
            {tag}
          </span>
        ))}
        {expert.members.slice(0, 2).map((m) => (
          <span
            key={m}
            className={styles.cardTag}
            style={{
              background: "rgba(0,0,0,0.03)",
              color: "rgba(0,0,0,0.45)",
            }}
          >
            {m}
          </span>
        ))}
      </div>

      <div className={styles.cardFooter}>
        <span className={styles.cardStat}>
          <Star size={12} />
          {expert.usageCount.toLocaleString()} 次使用
        </span>
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            className={`${styles.cardAction} ${styles.cardActionPrimary}`}
            onClick={() => {
              const currentAgent = useAgentStore.getState().selectedAgent;
              const rawFrom =
                (location.state as { from?: string } | null)?.from ||
                "/workbench";
              const from = rawFrom.startsWith("/chat/")
                ? rawFrom.replace(/^\/chat/, "/task")
                : rawFrom;
              const isFromTask = from.match(/^\/task\/[^/]+$/);
              const isTeam = expert.kind === "team";

              const handleSwitch = (startNewChat: boolean) => {
                setSelectedAgent(expert.agentId);
                setActiveMode("");
                setSelectedExpertTeam(isTeam ? expert.team || null : null);
                sessionApi.reset();
                message.success(`已召唤「${expert.name}」，进入任务编排`);

                const lastChatId =
                  !isTeam && isFromTask && !startNewChat
                    ? useAgentStore.getState().getLastChatId(expert.agentId)
                    : undefined;
                const targetUrl = resolveExpertSummonTarget({
                  from,
                  isTeam,
                  startNewChat,
                  lastChatId,
                });
                navigate(targetUrl, {
                  state: {
                    selectedAgent: expert.agentId,
                    selectedExpertTeam: expert.team?.id,
                    activeMode: "",
                  },
                });
              };

              if (isTeam) {
                handleSwitch(false);
                return;
              }

              if (isFromTask && currentAgent !== expert.agentId) {
                import("antd").then(({ Modal }) => {
                  Modal.confirm({
                    title: "切换专家将开启新对话",
                    content:
                      "当前对话正在使用其他专家能力，切换后需要开启新对话。",
                    okText: "确认",
                    cancelText: "取消",
                    centered: true,
                    onOk: () => handleSwitch(true),
                  });
                });
              } else {
                handleSwitch(false);
              }
            }}
          >
            召唤 <ArrowRight size={12} />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className={styles.ecoPage}>
      <div className={styles.pageHeader}>
        <div className={styles.pageTitle}>
          <span className={styles.pageTitleIcon}>
            <Users size={18} />
          </span>
          专家中心
        </div>
        <div className={styles.pageSubtitle}>
          选择单个专家处理清晰任务，或召唤专家团协作解决复杂问题。
        </div>
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

      <div className={styles.expertSections}>
        {loading ? (
          <div className={styles.inlineEmpty}>加载中...</div>
        ) : !hasAnyResult ? (
          <div className={styles.inlineEmpty}>暂无专家</div>
        ) : (
          <>
            <section className={styles.expertSection}>
              <div className={styles.sectionHeader}>
                <div>
                  <div className={styles.sectionTitle}>专家团</div>
                  <div className={styles.sectionSubtitle}>
                    多智能体协作，适合复杂任务和分阶段交付。
                  </div>
                </div>
                <span className={styles.sectionCount}>
                  {filteredTeamCards.length} 个
                </span>
              </div>
              {filteredTeamCards.length > 0 ? (
                <div className={styles.cardGrid}>
                  {filteredTeamCards.map(renderExpertCard)}
                </div>
              ) : (
                <div className={styles.sectionEmpty}>当前分类暂无专家团</div>
              )}
            </section>

            <section className={styles.expertSection}>
              <div className={styles.sectionHeader}>
                <div>
                  <div className={styles.sectionTitle}>专家</div>
                  <div className={styles.sectionSubtitle}>
                    单个智能体专家，适合目标明确、路径清晰的任务。
                  </div>
                </div>
                <span className={styles.sectionCount}>
                  {filteredAgentCards.length} 个
                </span>
              </div>
              {filteredAgentCards.length > 0 ? (
                <div className={styles.cardGrid}>
                  {filteredAgentCards.map(renderExpertCard)}
                </div>
              ) : (
                <div className={styles.sectionEmpty}>当前分类暂无专家</div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
