import React from "react";
import {
  Users,
  Code,
  Palette,
  TrendingUp,
  FileText,
  BarChart3,
  Briefcase,
  Lightbulb,
} from "lucide-react";

export interface ExpertUIConfig {
  id: string;
  name: string;
  desc: string;
  icon: React.ReactNode;
  color: string;
  members: string[];
  tags: string[];
  category: string;
  badge?: "hot" | "new";
}

export const EXPERT_USAGE_COUNTS: Record<string, number> = {
  fullstack_dev: 12850,
  content_creation: 9320,
  product_design: 7640,
  data_analysis: 6180,
  finance_research: 5420,
  consultant: 4250,
  opc_company: 8910,
  legal: 3180,
  marketing_agent: 15420,
  luyu_dclaw_agent: 0,
  luyu_dclaw_dzb_agent: 0,
  ai_video_team: 0,
  software_dev_team: 0,
  deep_research_team: 0,
};

export const EXPERT_UI_CONFIGS: ExpertUIConfig[] = [
  {
    id: "fullstack_dev",
    name: "全栈开发专家",
    desc: "综合架构、前端、后端、测试视角的专业开发专家，可完成从需求分析到部署上线的完整开发流程。",
    icon: <Code size={22} />,
    color: "#2563EB",
    members: ["架构师", "前端专家", "后端专家", "测试工程师"],
    tags: ["软件开发", "全栈"],
    category: "dev",
    badge: "hot",
  },
  {
    id: "content_creation",
    name: "内容创作专家",
    desc: "专业的文案策划、SEO 优化、社交媒体运营专家，助力品牌传播与内容营销。",
    icon: <FileText size={22} />,
    color: "#8b5cf6",
    members: ["文案策划", "SEO 专家", "新媒体运营"],
    tags: ["内容营销", "品牌"],
    category: "content",
    badge: "hot",
  },
  {
    id: "product_design",
    name: "产品设计专家",
    desc: "用户研究、交互设计、视觉设计全流程覆盖，打造极致用户体验。",
    icon: <Palette size={22} />,
    color: "#ec4899",
    members: ["产品经理", "UX 设计师", "UI 设计师"],
    tags: ["产品设计", "UX"],
    category: "business",
    badge: "new",
  },
  {
    id: "data_analysis",
    name: "数据分析专家",
    desc: "数据采集、清洗、建模、可视化一站式服务，用数据驱动业务决策。",
    icon: <BarChart3 size={22} />,
    color: "#10b981",
    members: ["数据分析师", "BI 工程师", "数据科学家"],
    tags: ["数据分析", "BI"],
    category: "data",
  },
  {
    id: "finance_research",
    name: "金融投研专家",
    desc: "市场分析、行业研究、财务建模、投资策略，为您的投资决策提供专业支持。",
    icon: <TrendingUp size={22} />,
    color: "#f59e0b",
    members: ["行业研究员", "量化分析师", "风控专家"],
    tags: ["金融", "投研"],
    category: "finance",
  },
  {
    id: "consultant",
    name: "企业咨询顾问",
    desc: "战略规划、流程优化、组织变革，帮助企业实现数字化转型与效率提升。",
    icon: <Briefcase size={22} />,
    color: "#6366f1",
    members: ["战略顾问", "流程专家", "变革管理师"],
    tags: ["企业咨询", "管理"],
    category: "business",
  },
  {
    id: "opc_company",
    name: "OPC 一人公司",
    desc: "融合多领域能力的超级个体解决方案，让一个人拥有一支团队的能力。",
    icon: <Lightbulb size={22} />,
    color: "#ef4444",
    members: ["全能助手", "运营专家", "技术顾问"],
    tags: ["一人公司", "全能"],
    category: "business",
    badge: "hot",
  },
  {
    id: "legal",
    name: "法务合规专家",
    desc: "合同审查、法律咨询、合规管理、知识产权保护，为企业保驾护航。",
    icon: <Users size={22} />,
    color: "#0ea5e9",
    members: ["法律顾问", "合规专家", "知产顾问"],
    tags: ["法务", "合规"],
    category: "business",
    badge: "new",
  },
  {
    id: "marketing_agent",
    name: "营销智能体",
    desc: "专注于品牌传播、用户增长、SEO 优化与新媒体裂变策略的数字营销专家。",
    icon: <TrendingUp size={22} />,
    color: "#f97316",
    members: ["营销总监", "增长黑客", "SEO 专家"],
    tags: ["数字营销", "增长", "SEO"],
    category: "business",
    badge: "hot",
  },
];

export const CATEGORIES = [
  { key: "all", label: "全部" },
  { key: "dev", label: "技术开发" },
  { key: "content", label: "内容创作" },
  { key: "business", label: "商业运营" },
  { key: "data", label: "数据分析" },
  { key: "finance", label: "金融投研" },
  { key: "research", label: "深度研究" },
];

export const TEAM_COLORS = [
  "#2563EB",
  "#8B5CF6",
  "#10B981",
  "#F59E0B",
  "#EC4899",
  "#0EA5E9",
];
