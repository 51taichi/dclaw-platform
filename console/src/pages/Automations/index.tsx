import React, { useState, useEffect, useMemo } from "react";
import {
  Modal,
  Form,
  Input,
  Select,
  Switch,
  DatePicker,
  TimePicker,
  InputNumber,
  message,
  Popconfirm,
  Tooltip,
  Spin,
  Popover
} from "antd";
import {
  Zap,
  Clock,
  Newspaper,
  BookOpen,
  Briefcase,
  Bell,
  Calendar,
  Play,
  Plus,
  Edit,
  Trash2,
  Cpu,
  Sparkles,
  Layers,
  CheckCircle,
  HelpCircle,
  ChevronDown,
  Check,
  Bot
} from "lucide-react";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import styles from "./index.module.less";
import { useCronJobs } from "../Control/CronJobs/useCronJobs";
import { parseCron } from "../Control/CronJobs/components/parseCron";
import api from "../../api";
import { isChatSelectableModel } from "../Chat/utils/chatModelEligibility";
import { useAgentStore } from "../../stores/agentStore";
import { agentsApi } from "../../api/modules/agents";
import { providerApi } from "../../api/modules/provider";
import { skillApi } from "../../api/modules/skill";
import type { ProviderInfo, PoolSkillSpec } from "../../api/types";

dayjs.extend(relativeTime);

const { Option } = Select;

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

// ─── CustomModelSelector (高保真模型选择器) ───────────────────
interface CustomModelSelectorProps {
  value?: string;
  onChange?: (val: string) => void;
  providers: ProviderInfo[];
}

const CustomModelSelector: React.FC<CustomModelSelectorProps> = ({ value, onChange, providers }) => {
  const [open, setOpen] = useState(false);

  const availableModels = useMemo(() => {
    const list: Array<{ id: string; name: string; provider?: string }> = [];
    providers.forEach((p) => {
      const isAuthorized = p.api_key && p.api_key.trim().length > 0;
      const isLocal = p.name.toLowerCase().includes("lm studio") || p.name.toLowerCase().includes("ollama") || p.name.toLowerCase().includes("local");

      if (!isAuthorized && !isLocal) return;

      const allModels = [...(p.models || []), ...(p.extra_models || [])].filter(
        isChatSelectableModel,
      );
      allModels.forEach((m) => {
        const modelId = typeof m === "string" ? m : m.id;
        const modelName = typeof m === "string" ? m : (m.name || m.id);
        if (modelId) {
          list.push({
            id: modelId,
            name: modelName,
            provider: p.name,
          });
        }
      });
    });
    return list;
  }, [providers]);

  const displayValue = useMemo(() => {
    if (!value || value === "Auto (推荐智能路由)") {
      return "Auto";
    }
    const found = availableModels.find(m => m.id === value);
    return found ? found.name : value;
  }, [value, availableModels]);

  const handleSelect = (val: string) => {
    if (onChange) {
      onChange(val);
    }
    setOpen(false);
  };

  const popoverContent = (
    <div className={styles.dropdownOverlayCustom}>
      <div className={styles.dropdownTitleCustom}>模型</div>
      
      {/* Auto 选项 */}
      <button
        type="button"
        className={`${styles.dropdownItemCustom} ${
          (!value || value === "Auto (推荐智能路由)") ? styles.dropdownItemActiveCustom : ""
        }`}
        onClick={() => handleSelect("Auto (推荐智能路由)")}
      >
        <div className={styles.modelItemIconCircleCustom}>
          <Zap size={15} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className={styles.dropdownItemLabelCustom}>Auto</div>
          <div className={styles.dropdownItemDescCustom}>推荐智能路由</div>
        </div>
        {(!value || value === "Auto (推荐智能路由)") && (
          <Check size={14} className={styles.dropdownItemCheckCustom} />
        )}
      </button>

      {/* 动态模型项 */}
      {availableModels.map((model) => {
        const isSelected = value === model.id;
        return (
          <button
            key={model.id}
            type="button"
            className={`${styles.dropdownItemCustom} ${
              isSelected ? styles.dropdownItemActiveCustom : ""
            }`}
            onClick={() => handleSelect(model.id)}
          >
            <div className={styles.modelItemIconCircleCustom}>
              <Bot size={15} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className={styles.dropdownItemLabelCustom}>{model.name}</div>
              {model.provider && (
                <div className={styles.dropdownItemDescCustom}>{model.provider}</div>
              )}
            </div>
            {isSelected && (
              <Check size={14} className={styles.dropdownItemCheckCustom} />
            )}
          </button>
        );
      })}

      {availableModels.length === 0 && (
        <div style={{ padding: "8px 12px", color: "#999", fontSize: 12 }}>
          暂无可用模型，请先在设置中配置 Provider
        </div>
      )}
    </div>
  );

  return (
    <Popover
      content={popoverContent}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomLeft"
      overlayClassName={styles.popoverNoPaddingCustom}
    >
      <button type="button" className={styles.modelSelectButtonCustom}>
        <span className={styles.modelSelectButtonIconCustom}>
          <Zap size={12} style={{ color: "#eab308" }} />
        </span>
        <span className={styles.modelSelectButtonTextCustom}>{displayValue}</span>
        <ChevronDown size={12} className={styles.modelSelectChevronCustom} />
      </button>
    </Popover>
  );
};

// ─── CustomSkillPopover (高保真技能选择面板) ───────────────────
interface CustomSkillPopoverProps {
  computedPoolSkills: Array<{
    name: string;
    desc: string;
    icon: string;
    color: string;
  }>;
  onSelectSkill: (skillName: string) => void;
}

const CustomSkillPopover: React.FC<CustomSkillPopoverProps> = ({ computedPoolSkills, onSelectSkill }) => {
  const [open, setOpen] = useState(false);
  const [skillSearch, setSkillSearch] = useState("");

  const filteredSkills = useMemo(() => {
    return computedPoolSkills.filter((s) => {
      if (!skillSearch) return true;
      const searchLower = skillSearch.toLowerCase();
      const searchNormalized = searchLower.replace(/-/g, "_");
      const nameLower = s.name.toLowerCase();
      const nameNormalized = nameLower.replace(/-/g, "_");
      const descLower = s.desc.toLowerCase();
      return (
        nameLower.includes(searchLower) ||
        nameNormalized.includes(searchNormalized) ||
        descLower.includes(searchLower)
      );
    });
  }, [computedPoolSkills, skillSearch]);

  const handleSelect = (name: string) => {
    onSelectSkill(name);
    setOpen(false);
    setSkillSearch("");
  };

  const popoverContent = (
    <div className={styles.popoverPanelCustom}>
      <input
        className={styles.popoverSearchCustom}
        placeholder="搜索技能..."
        value={skillSearch}
        onChange={(e) => setSkillSearch(e.target.value)}
        autoFocus
      />
      <div className={styles.popoverListCustom}>
        {filteredSkills.length === 0 ? (
          <div style={{ padding: "16px", textAlign: "center", color: "#999", fontSize: "12px" }}>
            未找到可用技能
          </div>
        ) : (
          filteredSkills.map((skill) => (
            <div
              key={skill.name}
              className={styles.popoverItemCustom}
              onClick={() => handleSelect(skill.name)}
            >
              <div
                className={styles.popoverItemIconCustom}
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
              <div className={styles.popoverItemInfoCustom}>
                <div className={styles.popoverItemNameCustom}>{skill.name}</div>
                <div className={styles.popoverItemDescCustom}>{skill.desc}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );

  return (
    <Popover
      content={popoverContent}
      trigger="click"
      open={open}
      onOpenChange={(val) => {
        setOpen(val);
        if (!val) setSkillSearch("");
      }}
      placement="top"
      overlayClassName={styles.popoverNoPaddingCustom}
    >
      <button type="button" className={styles.skillBadgeButton}>
        <Cpu size={14} style={{ color: "#3b82f6" }} />
        <span>技能</span>
      </button>
    </Popover>
  );
};



// 12 个 WorkBuddy 经典自动化模板定义
const AUTOMATION_TEMPLATES = [
  {
    id: "daily_ai_news",
    name: "每日 AI 新闻推送",
    desc: "关注当天 AI 领域的重要动态，侧重 AI coding 与具身智能方向。筛选 3-5 条有价值的信息，简要说明事件内容及值得关注的原因。",
    icon: <Newspaper size={20} />,
    color: "#3b82f6",
    bgColor: "rgba(59, 130, 246, 0.08)",
    frequency: "每天 09:00",
    category: "efficiency",
    badge: "🔥 热门",
    defaultValues: {
      prompt: "整理今天最值得关注的科技与 AI 领域重要新闻，输出 3-5 条。每条包含：新闻标题、核心进展、为什么值得关注。最后补充一句今日科技趋势判断。",
      freqType: "cron" as const,
      cronSub: "daily",
      time: "09:00",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "daily_english_words",
    name: "每日 5 个英语单词",
    desc: "每天推荐 5 个高频实用英语单词，包含释义、例句和发音练习，帮助你利用碎片时间提升词汇量。",
    icon: <BookOpen size={20} />,
    color: "#8b5cf6",
    bgColor: "rgba(139, 92, 246, 0.08)",
    frequency: "每天 08:00",
    category: "growth",
    badge: "🔥 热门",
    defaultValues: {
      prompt: "推荐 5 个高频实用的商业/技术英语单词。每个单词需要包含：音标、词性、中文释义、精美双语例句（一个工作场景，一个日常生活场景）、记忆巧记或词根词缀解析。",
      freqType: "cron" as const,
      cronSub: "daily",
      time: "08:00",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "daily_child_story",
    name: "每日儿童睡前故事",
    desc: "生成 3-5 分钟可读的温和睡前故事，充满童趣与想象力，适合伴读，温馨治愈。",
    icon: <Sparkles size={20} />,
    color: "#ec4899",
    bgColor: "rgba(236, 72, 153, 0.08)",
    frequency: "每天 20:30",
    category: "growth",
    badge: "",
    defaultValues: {
      prompt: "为 4-8 岁儿童创作一个温和、富有童趣和启发意义的睡前小故事，时长约 3 分钟。故事里需要有一个可爱的小动物作为主角，情节平缓治愈，结局温馨，非常适合伴读。",
      freqType: "cron" as const,
      cronSub: "daily",
      time: "20:30",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "weekly_work_report",
    name: "每周工作周报",
    desc: "每周五汇总仓库 PR 与 Issue 进展，自动整理本周主要工作内容，生成格式化周报。",
    icon: <Briefcase size={20} />,
    color: "#10b981",
    bgColor: "rgba(16, 185, 129, 0.08)",
    frequency: "每周五 17:00",
    category: "efficiency",
    badge: "",
    defaultValues: {
      prompt: "分析我本周在工作空间里的所有活动记录、提交记录和文档变更。请整理并格式化输出一份周报，包含：本周完成工作、下周工作计划、遇到的技术难题与解决方案、项目整体进展评估。",
      freqType: "cron" as const,
      cronSub: "weekly",
      weekDay: "fri",
      time: "17:00",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "weekend_movie_recommend",
    name: "经典电影推荐",
    desc: "推荐一部高分经典电影，简要介绍剧情大纲、看点及适合观看的氛围，丰富周末生活。",
    icon: <Play size={20} />,
    color: "#f59e0b",
    bgColor: "rgba(245, 158, 11, 0.08)",
    frequency: "每周六 10:00",
    category: "entertainment",
    badge: "",
    defaultValues: {
      prompt: "推荐一部豆瓣 8.5 分以上的经典小众或大众电影。包含：电影名字、导演与主演、300 字左右的高能剧情大纲（不剧透关键结局）、三大核心看点、最适合观看的周末场景或环境氛围配置建议。",
      freqType: "cron" as const,
      cronSub: "weekly",
      weekDay: "sat",
      time: "10:00",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "today_in_history",
    name: "历史上的今天",
    desc: "从科技、电影、音乐等领域挑选一件发生在历史上的今天的重要事件，并附带简要的历史背景和影响分析。",
    icon: <Calendar size={20} />,
    color: "#6366f1",
    bgColor: "rgba(99, 102, 241, 0.08)",
    frequency: "每天 09:30",
    category: "growth",
    badge: "",
    defaultValues: {
      prompt: "查询并挑选一件历史上今天发生的、影响深远的重大科技、艺术或文化领域的里程碑事件。用生动有趣的语言介绍其历史背景、发生过程，以及该事件对今天世界产生的潜移默化的影响。",
      freqType: "cron" as const,
      cronSub: "daily",
      time: "09:30",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "daily_one_why",
    name: "每日一个为什么",
    desc: "每天抛出一个有趣的问题，先提问引发思考，再用通俗易懂的方式解答，拓宽知识面。",
    icon: <HelpCircle size={20} />,
    color: "#06b6d4",
    bgColor: "rgba(6, 182, 212, 0.08)",
    frequency: "每天 12:00",
    category: "growth",
    badge: "",
    defaultValues: {
      prompt: "抛出一个日常生活中常见但多数人不知道科学原理的有趣问题（例如：为什么天空是蓝色的？为什么雨后空气闻起来很清新？）。先给出一个带有悬念的提问，然后再用通俗易懂、老少咸宜、图文并茂感（用 emoji 表达）的科普语言来进行深度趣味解答。",
      freqType: "cron" as const,
      cronSub: "daily",
      time: "12:00",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "parent_call_reminder",
    name: "父母联系提醒",
    desc: "每周日 10:00 提醒你给家人打电话或发消息，送去温暖问候，保持亲密联系。",
    icon: <Bell size={20} />,
    color: "#ef4444",
    bgColor: "rgba(239, 68, 68, 0.08)",
    frequency: "每周日 10:00",
    category: "reminder",
    badge: "",
    defaultValues: {
      prompt: "小主，今天是周日啦！我已经为您准备了贴心的家人问候小贴士，快去给爸爸妈妈打个电话吧。你可以顺便聊聊本周发生的趣事，或者带上一句温暖的健康小问候。",
      freqType: "cron" as const,
      cronSub: "weekly",
      weekDay: "sun",
      time: "10:00",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "medical_booking_reminder",
    name: "体检预约提醒",
    desc: "在 2026/04/08 07:00 提醒你确认体检项目和时间，做好检查前空腹等准备工作。",
    icon: <CheckCircle size={20} />,
    color: "#14b8a6",
    bgColor: "rgba(20, 184, 166, 0.08)",
    frequency: "单次定时提醒",
    category: "reminder",
    badge: "✨ 新上",
    defaultValues: {
      prompt: "【体检特别提醒】您预约的体检即将在几小时后开始，请注意：今天晚餐后（20点以后）禁食，24点以后禁水，保证充足睡眠。请带齐身份证和体检单前往体检中心，祝您身体棒棒！",
      freqType: "once" as const,
      cronSub: "daily",
      time: "07:00",
      onceRunAt: dayjs("2026-04-08 07:00:00"),
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "interview_prep_workday",
    name: "面试准备提醒",
    desc: "工作日每 2 小时提醒你复习大模型面试题，保持最佳状态，备战技术面试。",
    icon: <Cpu size={20} />,
    color: "#4f46e5",
    bgColor: "rgba(79, 70, 229, 0.08)",
    frequency: "每 2 小时运行",
    category: "reminder",
    badge: "",
    defaultValues: {
      prompt: "【大模型面试速记】休息一下！我为你精选了一道大模型核心面试题：『请详细对比 Transformer 的 Self-Attention 和 Multi-Head Attention 的计算复杂度，以及为什么多头能提升性能？』请思考 1 分钟后查看我为您整理的黄金解答模版。",
      freqType: "interval" as const,
      cronSub: "daily",
      time: "09:00",
      onceRunAt: null,
      intervalVal: 2,
      intervalUnit: "hours"
    }
  },
  {
    id: "meeting_preparation",
    name: "会议前准备",
    desc: "在会议开始前提醒你整理议题、会议目标、所需数据和可能遇到的问题，提高会议效率。",
    icon: <Clock size={20} />,
    color: "#f43f5e",
    bgColor: "rgba(244, 63, 94, 0.08)",
    frequency: "会议前 15 分钟",
    category: "efficiency",
    badge: "",
    defaultValues: {
      prompt: "【会议高效热身】您好，您即将在 15 分钟后参加一场重要会议。请快速梳理以下三点：1. 本次会议我最需要达成的核心目标是什么？2. 我是否有已经准备好的支撑数据或文件？3. 针对对方可能提出的质疑，我该如何从容作答？祝您开会顺利！",
      freqType: "cron" as const,
      cronSub: "custom",
      cronCustom: "*/15 * * * *",
      time: "09:00",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  },
  {
    id: "pet_wallpaper_gen",
    name: "可爱萌宠手机壁纸",
    desc: "随机从 7 种不同风格中挑选一种，生成一张可爱的萌宠风格手机壁纸，带来一天好心情。",
    icon: <Layers size={20} />,
    color: "#db2777",
    bgColor: "rgba(219, 39, 119, 0.08)",
    frequency: "每天 08:30",
    category: "entertainment",
    badge: "✨ 新上",
    defaultValues: {
      prompt: "今天是一个美好的早晨！随机挑选一种萌宠风格（如：Q版柴犬、蒸汽朋克风波斯猫、毛线编织风小兔子），生成一张适合作为手机壁纸的高清精美萌宠插画。同时附带一句元气满满的早安问候语！",
      freqType: "cron" as const,
      cronSub: "daily",
      time: "08:30",
      onceRunAt: null,
      intervalVal: 1,
      intervalUnit: "hours"
    }
  }
];

const CATEGORIES = [
  { key: "all", label: "全部" },
  { key: "efficiency", label: "工作效率" },
  { key: "growth", label: "学习成长" },
  { key: "entertainment", label: "休闲娱乐" },
  { key: "reminder", label: "实用提醒" }
];

export default function AutomationsPage() {
  const {
    jobs,
    loading: jobsLoading,
    createJob,
    updateJob,
    deleteJob,
    toggleEnabled,
    executeNow
  } = useCronJobs();

  const [activeCategory, setActiveCategory] = useState("all");
  const [modalOpen, setModalOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<any>(null);
  const [userTimezone, setUserTimezone] = useState("UTC");
  const [form] = Form.useForm();
  const [freqTab, setFreqTab] = useState<"cron" | "interval" | "once">("cron");
  const [cronSubMode, setCronSubMode] = useState<string>("daily");
  const { agents, setAgents } = useAgentStore();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [poolSkills, setPoolSkills] = useState<PoolSkillSpec[]>([]);

  // 挂载时拉取 agents，以保证下拉框里有真实智能体列表
  useEffect(() => {
    if (agents.length === 0) {
      agentsApi
        .listAgents()
        .then((res) => {
          if (res && res.agents) {
            setAgents(res.agents);
          }
        })
        .catch((err) => {
          console.error("Failed to load agents in automations page:", err);
        });
    }
  }, [agents.length, setAgents]);

  // 挂载时拉取 providers 和内置技能列表
  useEffect(() => {
    providerApi
      .listProviders()
      .then((data) => {
        if (Array.isArray(data)) {
          setProviders(data);
        }
      })
      .catch((err) => console.error("Failed to load providers:", err));

    skillApi
      .listSkillPoolSkills()
      .then((data) => {
        if (Array.isArray(data)) {
          setPoolSkills(data);
        }
      })
      .catch((err) => console.error("Failed to load pool skills:", err));
  }, []);

  const [workspaceSkills, setWorkspaceSkills] = useState<any[]>([]);
  const currentWorkspace = Form.useWatch("workspace", form);

  useEffect(() => {
    const targetWs = currentWorkspace || "default";
    skillApi
      .listSkills(targetWs)
      .then((data) => {
        if (Array.isArray(data)) {
          setWorkspaceSkills(data.filter((s) => s.enabled !== false));
        }
      })
      .catch((err) => console.error("Failed to load workspace skills:", err));
  }, [currentWorkspace]);

  // 对接真实的 workspaces 列表并进行默认兜底处理
  const workspaces = useMemo(() => {
    const list = agents.map((a) => ({
      id: a.id,
      name: a.name || a.id,
    }));
    if (!list.some((w) => w.id === "default")) {
      list.unshift({
        id: "default",
        name: "默认智能体",
      });
    }
    return list;
  }, [agents]);

  const getWorkspaceName = (wsId: string) => {
    const targetId = wsId === "default_workspace" ? "default" : wsId;
    return workspaces.find((w) => w.id === targetId)?.name || wsId || "独立空间";
  };

  const computedPoolSkills = useMemo(() => {
    // Collect enabled skills from the workspace
    const workspaceMapped = workspaceSkills.map((wsSkill) => {
      const poolSkill = (poolSkills || []).find((ps: any) => ps.name === wsSkill.name);
      const { color, icon } = getSkillUIProps(wsSkill.name);
      return {
        name: (poolSkill?.config?.display_name as string) || wsSkill.name,
        desc: wsSkill.description || (poolSkill?.description as string) || "",
        icon: (poolSkill?.config?.icon as any) || wsSkill.emoji || icon,
        color,
      };
    });

    const enabledNames = new Set(workspaceSkills.map((s) => s.name));

    // Fallback if empty and no pool skills loaded yet
    if (!poolSkills || poolSkills.length === 0) {
      const defaultSkillNames = ["网页搜索引擎", "本地代码仓库分析", "RAG专属向量库", "中英翻译器", "天气预报助手"];
      const defaultDescs = [
        "网页搜索与内容提取能力，帮助快速检索最新网络公开信息",
        "深入剖析本地工作区代码文件结构，提供架构与语义级分析",
        "连接本地大模型专属的高性能知识库，执行精确语义化检索",
        "支持中英文之间的地道互译与术语纠正，保证翻译极高品质",
        "获取全球主要城市实时天气，提供出行及着装建议"
      ];
      const defaults = defaultSkillNames.map((name, idx) => {
        const { color, icon } = getSkillUIProps(name);
        return {
          name,
          desc: defaultDescs[idx] || "",
          icon,
          color,
        };
      });
      return [...workspaceMapped, ...defaults];
    }

    // Add default pool skills not already enabled
    const defaultPoolSkills = poolSkills
      .filter((ps: any) => ps.config?.is_default === true && !enabledNames.has(ps.name))
      .map((ps: any) => {
        const { color, icon } = getSkillUIProps(ps.name);
        return {
          name: (ps.config?.display_name as string) || ps.name,
          desc: (ps.description as string) || "",
          icon: (ps.config?.icon as any) || icon,
          color,
        };
      });

    return [...workspaceMapped, ...defaultPoolSkills];
  }, [poolSkills, workspaceSkills]);

  // 1. 获取系统时区并对齐
  useEffect(() => {
    api.getUserTimezone()
      .then((res) => {
        if (res?.timezone) {
          setUserTimezone(res.timezone);
        }
      })
      .catch((err) => console.error("Failed to fetch user timezone:", err));
  }, []);

  // 2. 将 Cron 表达式解析并同步到 Modal 表单状态中
  const handleEditJob = (job: any) => {
    setEditingJob(job);
    setModalOpen(true);

    const isOnce = job.schedule?.type === "once";
    const cronStr = job.schedule?.cron || "";
    
    let defaultFreqTab: "cron" | "interval" | "once" = "cron";
    let defaultCronSub = "daily";
    let defaultTime = "09:00";
    let defaultWeekDay = "mon";
    let defaultCronCustom = "0 9 * * *";
    let defaultIntervalVal = 1;
    let defaultIntervalUnit: "minutes" | "hours" | "days" = "hours";
    let defaultOnceRunAt = null;

    if (isOnce) {
      defaultFreqTab = "once";
      if (job.schedule?.run_at) {
        defaultOnceRunAt = dayjs(job.schedule.run_at);
      }
    } else if (cronStr) {
      // 检查是否是“按间隔”的形式，比如 */15 * * * * 或者 0 */2 * * * 或 0 0 */3 * *
      const minIntervalMatch = cronStr.match(/^\*\/(\d+)\s+\*\s+\*\s+\*\s+\*$/);
      const hourIntervalMatch = cronStr.match(/^0\s+\*\/(\d+)\s+\*\s+\*\s+\*$/);
      const dayIntervalMatch = cronStr.match(/^0\s+0\s+\*\/(\d+)\s+\*\s+\*$/);

      if (minIntervalMatch) {
        defaultFreqTab = "interval";
        defaultIntervalVal = parseInt(minIntervalMatch[1]);
        defaultIntervalUnit = "minutes";
      } else if (hourIntervalMatch) {
        defaultFreqTab = "interval";
        defaultIntervalVal = parseInt(hourIntervalMatch[1]);
        defaultIntervalUnit = "hours";
      } else if (dayIntervalMatch) {
        defaultFreqTab = "interval";
        defaultIntervalVal = parseInt(dayIntervalMatch[1]);
        defaultIntervalUnit = "days";
      } else {
        defaultFreqTab = "cron";
        const parts = parseCron(cronStr);
        if (parts.type === "daily") {
          defaultCronSub = "daily";
          const hStr = String(parts.hour ?? 9).padStart(2, "0");
          const mStr = String(parts.minute ?? 0).padStart(2, "0");
          defaultTime = `${hStr}:${mStr}`;
        } else if (parts.type === "weekly") {
          defaultCronSub = "weekly";
          const hStr = String(parts.hour ?? 9).padStart(2, "0");
          const mStr = String(parts.minute ?? 0).padStart(2, "0");
          defaultTime = `${hStr}:${mStr}`;
          defaultWeekDay = parts.daysOfWeek?.[0] || "mon";
        } else {
          defaultCronSub = "custom";
          defaultCronCustom = cronStr;
        }
      }
    }

    setFreqTab(defaultFreqTab);
    setCronSubMode(defaultCronSub);

    // 提取 Prompt
    let promptContent = "";
    if (job.task_type === "agent" && job.request?.input) {
      try {
        const parsedInput = JSON.parse(job.request.input);
        if (Array.isArray(parsedInput) && parsedInput[0]?.content?.[0]?.text) {
          promptContent = parsedInput[0].content[0].text;
        }
      } catch (e) {
        promptContent = String(job.request.input);
      }
    } else {
      promptContent = job.text || "";
    }

    const jobMeta = job.meta || {};

    form.setFieldsValue({
      name: job.name,
      workspace: jobMeta.workspace === "default_workspace" ? "default" : (jobMeta.workspace || "default"),
      prompt: promptContent,
      model: jobMeta.model || "Auto (推荐智能路由)",
      cronSub: defaultCronSub,
      time: dayjs(defaultTime, "HH:mm"),
      weekDay: defaultWeekDay,
      cronCustom: defaultCronCustom,
      intervalVal: defaultIntervalVal,
      intervalUnit: defaultIntervalUnit,
      onceRunAt: defaultOnceRunAt
    });
  };

  // 3. 点击模板，打开 Modal 并进行参数初始化填充
  const handleOpenTemplate = (template: typeof AUTOMATION_TEMPLATES[0]) => {
    setEditingJob(null);
    setModalOpen(true);
    
    setFreqTab(template.defaultValues.freqType);
    setCronSubMode(template.defaultValues.cronSub);

    form.resetFields();
    form.setFieldsValue({
      name: template.name,
      workspace: "default",
      prompt: template.defaultValues.prompt,
      model: "Auto (推荐智能路由)",
      cronSub: template.defaultValues.cronSub,
      time: template.defaultValues.time ? dayjs(template.defaultValues.time, "HH:mm") : dayjs("09:00", "HH:mm"),
      weekDay: (template.defaultValues as any).weekDay || "mon",
      cronCustom: (template.defaultValues as any).cronCustom || "0 9 * * *",
      intervalVal: template.defaultValues.intervalVal,
      intervalUnit: template.defaultValues.intervalUnit,
      onceRunAt: template.defaultValues.onceRunAt,
      templateId: template.id
    });
  };

  // 4. 新建自定义空白自动化任务
  const handleCreateNew = () => {
    setEditingJob(null);
    setModalOpen(true);
    setFreqTab("cron");
    setCronSubMode("daily");

    form.resetFields();
    form.setFieldsValue({
      name: "新自动化任务",
      workspace: "default",
      prompt: "",
      model: "Auto (推荐智能路由)",
      cronSub: "daily",
      time: dayjs("09:00", "HH:mm"),
      weekDay: "mon",
      cronCustom: "0 9 * * *",
      intervalVal: 1,
      intervalUnit: "hours",
      onceRunAt: null
    });
  };

  // 5. 提交表单 - 数据序列化成后端所需要的结构
  const handleFormSubmit = async () => {
    try {
      const values = await form.validateFields();
      let finalCron = "0 9 * * *";
      let isOnce = freqTab === "once";
      let runAtStr = "";

      if (freqTab === "cron") {
        if (values.cronSub === "daily") {
          const t = values.time ? dayjs(values.time) : dayjs();
          finalCron = `${t.minute()} ${t.hour()} * * *`;
        } else if (values.cronSub === "weekly") {
          const t = values.time ? dayjs(values.time) : dayjs();
          finalCron = `${t.minute()} ${t.hour()} * * ${values.weekDay}`;
        } else {
          finalCron = values.cronCustom || "0 9 * * *";
        }
      } else if (freqTab === "interval") {
        const val = values.intervalVal || 1;
        const unit = values.intervalUnit || "hours";
        if (unit === "minutes") {
          finalCron = `*/${val} * * * *`;
        } else if (unit === "hours") {
          finalCron = `0 */${val} * * *`;
        } else {
          finalCron = `0 0 */${val} * *`;
        }
      } else if (freqTab === "once") {
        if (!values.onceRunAt) {
          message.error("请选择单次执行的日期和时间");
          return;
        }
        runAtStr = dayjs(values.onceRunAt).format("YYYY-MM-DD HH:mm:ss");
      }

      // 后端所需要的完整结构体数据序列化
      const payload: any = {
        name: values.name,
        enabled: editingJob ? editingJob.enabled : true,
        task_type: "agent", // 默认定为智能代理任务，便于运行 LLM
        text: "",
        schedule: isOnce ? {
          type: "once" as const,
          timezone: userTimezone,
          run_at: runAtStr
        } : {
          type: "cron" as const,
          timezone: userTimezone,
          cron: finalCron
        },
        request: {
          input: JSON.stringify(
            [
              {
                role: "user",
                content: [
                  {
                    type: "text",
                    text: values.prompt || ""
                  }
                ]
              }
            ],
            null,
            2
          ),
          session_id: "",
          user_id: ""
        },
        dispatch: {
          type: "channel" as const,
          channel: "console",
          target: {
            user_id: "default",
            session_id: "cron_job"
          },
          mode: "final" as const
        },
        runtime: {
          share_session: true,
          max_concurrency: 1,
          timeout_seconds: 120,
          misfire_grace_seconds: 60
        },
        meta: {
          template_id: values.templateId || (editingJob?.meta?.template_id || "custom"),
          template_source: "builtin",
          show_in_calendar: true,
          workspace: values.workspace,
          model: values.model
        }
      };

      if (editingJob) {
        payload.id = editingJob.id;
        const success = await updateJob(editingJob.id, payload);
        if (success) setModalOpen(false);
      } else {
        const success = await createJob(payload);
        if (success) setModalOpen(false);
      }
    } catch (e) {
      console.error("Form validation failed", e);
    }
  };

  // 6. 辅助展示活跃任务的频率文案
  const renderJobSchedule = (job: any) => {
    if (job.schedule?.type === "once") {
      return `单次: ${dayjs(job.schedule.run_at).format("YYYY-MM-DD HH:mm")}`;
    }
    const cron = job.schedule?.cron || "";
    // 精美的中文解释
    if (cron.startsWith("*/")) {
      const mins = cron.match(/^\*\/(\d+)/)?.[1];
      return `每隔 ${mins} 分钟`;
    }
    if (cron.startsWith("0 */")) {
      const hrs = cron.match(/^0\s+\*\/(\d+)/)?.[1];
      return `每隔 ${hrs} 小时`;
    }
    if (cron.startsWith("0 0 */")) {
      const dys = cron.match(/^0\s+0\s+\*\/(\d+)/)?.[1];
      return `每隔 ${dys} 天`;
    }
    
    const parts = parseCron(cron);
    if (parts.type === "daily") {
      return `每天 ${String(parts.hour).padStart(2, "0")}:${String(parts.minute).padStart(2, "0")}`;
    }
    if (parts.type === "weekly") {
      const weekdayNames: Record<string, string> = {
        mon: "周一", tue: "周二", wed: "周三", thu: "周四", fri: "周五", sat: "周六", sun: "周日"
      };
      const days = (parts.daysOfWeek || []).map(d => weekdayNames[d] || d).join("、");
      return `每周 (${days}) ${String(parts.hour).padStart(2, "0")}:${String(parts.minute).padStart(2, "0")}`;
    }
    return `自定义 (Cron): ${cron}`;
  };

  // 过滤模版展示
  const filteredTemplates = activeCategory === "all"
    ? AUTOMATION_TEMPLATES
    : AUTOMATION_TEMPLATES.filter(t => t.category === activeCategory);

  // 7. 在提示词框的“技能”里加入快速标签插入功能
  const insertSkillTag = (tagName: string) => {
    const currentPrompt = form.getFieldValue("prompt") || "";
    form.setFieldsValue({
      prompt: currentPrompt + (currentPrompt ? "\n" : "") + `【使用内置技能：${tagName}】`
    });
  };

  return (
    <div className={styles.automationsPage}>
      {/* 头部标题与新建按钮 */}
      <div className={styles.headerSection}>
        <div className={styles.headerLeft}>
          <div className={styles.pageTitle}>
            <Zap size={22} color="#2563eb" fill="#2563eb" />
            自动化
          </div>
          <div className={styles.pageSubtitle}>
            管理自动化任务并查看近期运行记录。设定自动化任务模板，让 AI 在指定时间自动执行重复性工作，解放你的时间。
          </div>
        </div>
        <button className={styles.addButton} onClick={handleCreateNew}>
          <Plus size={15} />
          添加自动化任务
        </button>
      </div>

      {/* 分类过滤切换 Tab */}
      <div className={styles.sectionTitle}>从模版入手</div>
      <div className={styles.categoryTabs}>
        {CATEGORIES.map(cat => (
          <button
            key={cat.key}
            className={`${styles.categoryTab} ${activeCategory === cat.key ? styles.categoryTabActive : ""}`}
            onClick={() => setActiveCategory(cat.key)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      {/* 模版卡片网格区域 */}
      <div className={styles.cardsGrid}>
        {filteredTemplates.map(tpl => (
          <div
            key={tpl.id}
            className={styles.templateCard}
            onClick={() => handleOpenTemplate(tpl)}
          >
            {tpl.badge && (
              <span style={{
                position: "absolute",
                top: 14,
                right: 14,
                fontSize: 10,
                fontWeight: 600,
                color: "#ef4444",
                background: "rgba(239, 68, 68, 0.08)",
                padding: "2px 6px",
                borderRadius: 4
              }}>
                {tpl.badge}
              </span>
            )}
            <div>
              <div className={styles.cardHeader}>
                <div className={styles.iconWrapper} style={{ backgroundColor: tpl.bgColor, color: tpl.color }}>
                  {tpl.icon}
                </div>
                <div className={styles.cardMeta}>
                  <div className={tpl.badge ? styles.cardTitle + " pr-10" : styles.cardTitle}>{tpl.name}</div>
                  <div className={styles.cardFreq}>
                    <Clock size={11} />
                    {tpl.frequency}
                  </div>
                </div>
              </div>
              <div className={styles.cardDesc}>{tpl.desc}</div>
            </div>
            <div className={styles.deployBtn}>
              <Play size={11} fill="currentColor" />
              一键部署
            </div>
          </div>
        ))}
      </div>

      {/* 已部署活跃任务管理面板区 */}
      <div className={styles.activeSection}>
        <div className={styles.activeHeader}>
          <div className={styles.pageTitle} style={{ fontSize: 16 }}>
            <Layers size={16} color="#4b5563" />
            我的活跃自动化 ({jobs.length})
          </div>
        </div>

        {jobsLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "40px 0" }}>
            <Spin tip="载入自动化任务列表中..." />
          </div>
        ) : jobs.length === 0 ? (
          <div style={{
            background: "#ffffff",
            border: "1px dashed #d1d5db",
            borderRadius: 12,
            padding: "48px 24px",
            textAlign: "center",
            color: "#6b7280"
          }}>
            <Zap size={32} style={{ margin: "0 auto 12px", opacity: 0.4, color: "#6b7280" }} />
            <div style={{ fontSize: 13, fontWeight: 500 }}>暂未部署任何活跃自动化任务</div>
            <div style={{ fontSize: 12, opacity: 0.8, marginTop: 4 }}>点击上方预设模版或点击“添加自动化任务”快速部署您的第一个定时任务吧！</div>
          </div>
        ) : (
          <div className={styles.activeGrid}>
            {jobs.map((job: any) => {
              // 提取 Prompt 给卡片展示
              let pText = "";
              if (job.task_type === "agent" && job.request?.input) {
                try {
                  const arr = JSON.parse(job.request.input);
                  pText = arr[0]?.content?.[0]?.text || "";
                } catch(e) {
                  pText = String(job.request.input);
                }
              } else {
                pText = job.text || "";
              }

              const jobMeta = job.meta || {};

              return (
                <div key={job.id} className={styles.jobCard}>
                  <div>
                    <div className={styles.jobHeader}>
                      <div className={styles.jobTitleSection}>
                        <div className={styles.jobTitle}>
                          {job.name}
                        </div>
                        <div className={styles.jobTime}>
                          时区: {job.schedule?.timezone || "UTC"}
                        </div>
                      </div>
                      <Switch
                        size="small"
                        checked={job.enabled}
                        onChange={() => toggleEnabled(job)}
                      />
                    </div>
                    
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                      <div className={styles.jobSchedule}>
                        <Clock size={11} />
                        {renderJobSchedule(job)}
                      </div>
                      {jobMeta.workspace && (
                        <div style={{ fontSize: 11, padding: "2px 8px", background: "rgba(37, 99, 235, 0.05)", borderRadius: 10, color: "#2563eb" }}>
                          {getWorkspaceName(jobMeta.workspace)}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className={styles.jobBody}>
                    <strong>Prompt:</strong> {pText || "（空白）"}
                  </div>

                  <div className={styles.jobFooter}>
                    <span style={{ fontSize: 11, color: "#9ca3af" }}>
                      模型: {jobMeta.model || "Auto智能路由"}
                    </span>
                    <div className={styles.jobActions}>
                      <Tooltip title="立即执行一次">
                        <button
                          className={`${styles.actionButton} ${styles.runButton}`}
                          onClick={() => executeNow(job.id)}
                        >
                          <Play size={14} fill="currentColor" />
                        </button>
                      </Tooltip>
                      <Tooltip title="修改设置">
                        <button
                          className={styles.actionButton}
                          onClick={() => handleEditJob(job)}
                        >
                          <Edit size={14} />
                        </button>
                      </Tooltip>
                      <Popconfirm
                        title="确定删除该自动化任务吗？"
                        description="删除后将无法恢复，定时调度亦将终止。"
                        onConfirm={() => deleteJob(job.id)}
                        okText="确定删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                      >
                        <button className={`${styles.actionButton} ${styles.deleteButton}`}>
                          <Trash2 size={14} />
                        </button>
                      </Popconfirm>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 添加/编辑弹窗 Modal (高保真克隆 WorkBuddy 图 2) */}
      <Modal
        title={editingJob ? "修改自动化任务" : "添加自动化任务"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
        width={560}
        destroyOnClose
        className={styles.modalWrapper}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleFormSubmit}
          initialValues={{
            workspace: "default",
            model: "Auto (推荐智能路由)",
            cronSub: "daily",
            time: dayjs("09:00", "HH:mm"),
            weekDay: "mon",
            cronCustom: "0 9 * * *",
            intervalVal: 1,
            intervalUnit: "hours"
          }}
        >
          {/* 名称 (Name) */}
          <Form.Item
            name="name"
            label={<span className={styles.formLabel}>名称</span>}
            rules={[{ required: true, message: "请输入任务名称" }]}
          >
            <Input className={styles.formInput} placeholder="请输入任务名称，例如：每日 AI 新闻推送" />
          </Form.Item>

          {/* 工作空间 (Workspace) */}
          <Form.Item
            name="workspace"
            label={
              <span className={styles.formLabel}>
                工作空间 <span style={{ fontSize: 11, color: "#9ca3af", fontWeight: 400 }}>(可选)</span>
              </span>
            }
          >
            <Select
              className={styles.formInput}
              dropdownStyle={{ borderRadius: 6 }}
              suffixIcon={<Layers size={14} style={{ color: "#9ca3af" }} />}
            >
              {workspaces.map(w => (
                <Option key={w.id} value={w.id}>{w.name}</Option>
              ))}
            </Select>
          </Form.Item>

          {/* 提示词大框 (包含提示词文本域、Auto 模型下拉与技能标签) */}
          <Form.Item
            name="prompt"
            label={<span className={styles.formLabel}>提示词</span>}
            rules={[{ required: true, message: "请输入提示词指令" }]}
          >
            <div className={styles.promptContainer}>
              <textarea
                className={styles.promptTextarea}
                placeholder="关注当天 AI 领域的重要动态，侧重 AI coding 与具身智能方向。筛选 3-5 条有价值的信息，简要说明事件内容及值得关注的原因。"
                rows={4}
                value={form.getFieldValue("prompt")}
                onChange={(e) => form.setFieldsValue({ prompt: e.target.value })}
              />
              <div className={styles.promptFooterBar}>
                <div className={styles.promptActionsLeft}>
                  {/* 模型选择下拉 */}
                  <Form.Item name="model" noStyle>
                    <CustomModelSelector providers={providers} />
                  </Form.Item>
                  
                  {/* 技能微型气泡 */}
                  <CustomSkillPopover computedPoolSkills={computedPoolSkills} onSelectSkill={insertSkillTag} />
                </div>
              </div>
            </div>
          </Form.Item>

          {/* 执行频率 (横排 Tab 切换：周期、按间隔、单次) */}
          <div className={styles.formLabel}>执行频率</div>
          <div className={styles.freqTabGroup}>
            <button
              type="button"
              className={`${styles.freqTab} ${freqTab === "cron" ? styles.freqTabActive : ""}`}
              onClick={() => setFreqTab("cron")}
            >
              周期
            </button>
            <button
              type="button"
              className={`${styles.freqTab} ${freqTab === "interval" ? styles.freqTabActive : ""}`}
              onClick={() => setFreqTab("interval")}
            >
              按间隔
            </button>
            <button
              type="button"
              className={`${styles.freqTab} ${freqTab === "once" ? styles.freqTabActive : ""}`}
              onClick={() => setFreqTab("once")}
            >
              单次
            </button>
          </div>

          {/* 三种执行频率子表单切换 */}
          {freqTab === "cron" && (
            <div className={styles.freqOptionsRow}>
              <Form.Item name="cronSub" noStyle>
                <Select
                  className={styles.freqSelect}
                  onChange={(val) => setCronSubMode(val)}
                  dropdownStyle={{ borderRadius: 6 }}
                >
                  <Option value="daily">每天</Option>
                  <Option value="weekly">每周</Option>
                  <Option value="custom">自定义</Option>
                </Select>
              </Form.Item>

              {cronSubMode === "weekly" && (
                <Form.Item name="weekDay" noStyle>
                  <Select className={styles.freqSelect} style={{ width: 90 }} dropdownStyle={{ borderRadius: 6 }}>
                    <Option value="mon">周一</Option>
                    <Option value="tue">周二</Option>
                    <Option value="wed">周三</Option>
                    <Option value="thu">周四</Option>
                    <Option value="fri">周五</Option>
                    <Option value="sat">周六</Option>
                    <Option value="sun">周日</Option>
                  </Select>
                </Form.Item>
              )}

              {cronSubMode !== "custom" ? (
                <Form.Item name="time" noStyle>
                  <TimePicker
                    className={styles.timePicker}
                    format="HH:mm"
                    allowClear={false}
                    showNow={false}
                    suffixIcon={<Clock size={12} style={{ color: "#9ca3af" }} />}
                  />
                </Form.Item>
              ) : (
                <Form.Item name="cronCustom" noStyle rules={[{ required: true, message: "请输入 Cron 表达式" }]}>
                  <Input
                    className={styles.formInput}
                    style={{ flex: 1, height: 32 }}
                    placeholder="例如: 0 9 * * 1-5"
                  />
                </Form.Item>
              )}
            </div>
          )}

          {freqTab === "interval" && (
            <div className={styles.freqOptionsRow}>
              <span style={{ fontSize: 13, color: "#6b7280" }}>每隔</span>
              <Form.Item name="intervalVal" noStyle rules={[{ required: true }]}>
                <InputNumber className={styles.formInput} style={{ width: 70 }} min={1} />
              </Form.Item>
              <Form.Item name="intervalUnit" noStyle>
                <Select className={styles.freqSelect} dropdownStyle={{ borderRadius: 6 }}>
                  <Option value="minutes">分钟</Option>
                  <Option value="hours">小时</Option>
                  <Option value="days">天</Option>
                </Select>
              </Form.Item>
              <span style={{ fontSize: 13, color: "#6b7280" }}>执行一次</span>
            </div>
          )}

          {freqTab === "once" && (
            <div className={styles.freqOptionsRow}>
              <Form.Item name="onceRunAt" noStyle>
                <DatePicker
                  className={styles.formInput}
                  style={{ width: "100%" }}
                  showTime
                  format="YYYY-MM-DD HH:mm:ss"
                  placeholder="选择单次执行日期时间"
                />
              </Form.Item>
            </div>
          )}

          {/* 生效日期区间 (Effective Date Range) */}
          <div style={{ marginTop: 16 }}>
            <span className={styles.formLabel}>
              生效日期区间 <span style={{ fontSize: 11, color: "#9ca3af", fontWeight: 400 }}>(可选，留空表示始终生效)</span>
            </span>
            <div style={{ marginTop: 6 }}>
              <DatePicker.RangePicker
                className={styles.formInput}
                style={{ width: "100%" }}
                format="YYYY-MM-DD"
                placeholder={["生效开始日期", "生效结束日期"]}
              />
            </div>
          </div>

          {/* 隐藏的模版ID传参项 */}
          <Form.Item name="templateId" noStyle>
            <Input type="hidden" />
          </Form.Item>

          {/* 底部按钮 (取消、添加) */}
          <div className={styles.modalFooter}>
            <button
              type="button"
              className={`${styles.addButton} ${styles.cancelBtn}`}
              onClick={() => setModalOpen(false)}
            >
              取消
            </button>
            <button
              type="submit"
              className={`${styles.addButton} ${styles.submitBtn}`}
            >
              {editingJob ? "保存修改" : "添加"}
            </button>
          </div>
        </Form>
      </Modal>
    </div>
  );
}
