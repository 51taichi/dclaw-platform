import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Compass, X, CheckCircle2 } from "lucide-react";
import globalStyles from "../shared/ecoPage.module.less";
import styles from "./Explore.module.less";

const TEMPLATES = [
  {
    id: "annual-report",
    name: "交互式年度数据报告",
    desc: "一句话生成交互式数据报告（前端框架），自动提取高频词、生成图表。",
    color: "#2563EB",
    category: "office",
    badge: "new",
    tags: ["HTML", "数据可视化", "报告"],
    tools: [
      { name: "前端开发", icon: "💻", type: "专家" },
      { name: "数据分析师", icon: "📊", type: "技能" }
    ],
    prompt: "请帮我生成一个交互式年度数据报告单页 HTML。要求暗色主题，背景使用科技感的蓝绿色渐变，页面结构包含：\n1. Hero 封面区域，大标题 2025 Annual Report，使用 CSS 弹跳动画\n2. 关键数据概览，4 个数字卡片展示\n要求所有 CSS 内联，布局美观。",
    agentId: "fullstack-dev"
  },
  {
    id: "whiteboard",
    name: "实时协作白板原型",
    desc: "描述需求，自动生成支持拖拉拽、实时同步的白板工具基础原型代码。",
    color: "#10b981",
    category: "dev",
    badge: "new",
    tags: ["HTML", "协作", "前端"],
    tools: [
      { name: "全栈开发团队", icon: "👨‍💻", type: "专家" }
    ],
    prompt: "我需要一个在线协作白板的原型 HTML，支持基本的鼠标画笔作画，以及简单的拖拽文本框功能，界面类似 Miro，左侧是工具栏，右侧是大画布。",
    agentId: "fullstack-dev"
  },
  {
    id: "api-docs",
    name: "开发者 API 文档门户",
    desc: "提供接口格式，自动生成优雅的 API 文档静态页面，包含代码多语言切换。",
    color: "#8b5cf6",
    category: "dev",
    badge: "new",
    tags: ["HTML", "文档"],
    tools: [
      { name: "技术写作团队", icon: "📝", type: "专家" }
    ],
    prompt: "基于这份 JSON 数据，生成一个类似 Stripe 风格的 API 文档门户网页。左侧是导航，中间是参数说明，右侧是深色的代码示例区域（包含 curl 和 Node.js 请求示例）。",
    agentId: "fullstack-dev"
  },
  {
    id: "ai-daily",
    name: "今日 AI 日报一键生成",
    desc: "聚合当日 AI 资讯，排版并输出适合公众号或邮件订阅的 HTML 模板。",
    color: "#f59e0b",
    category: "content",
    badge: "new",
    tags: ["HTML", "资讯"],
    tools: [
      { name: "内容创作团队", icon: "✍️", type: "专家" },
      { name: "网页浏览器", icon: "🌐", type: "技能" }
    ],
    prompt: "请搜索今天关于 AI 模型发布、行业动态的最新新闻，帮我汇总并排版成一份精美的《今日 AI 晨报》HTML 格式，适合直接粘贴到公众号发送。",
    agentId: "content-team"
  },
  {
    id: "design-system",
    name: "AI 产品设计系统文档",
    desc: "生成一套现代化的设计系统规范文档，包含色板、排版及组件用法。",
    color: "#ec4899",
    category: "content",
    tags: ["HTML", "设计", "规范"],
    tools: [
      { name: "产品设计团队", icon: "🎨", type: "专家" }
    ],
    prompt: "为我的 AI 办公软件起草一份基础的设计系统（Design System）规范网页。要求包含：主色调深色、排版规范、按钮的三种状态（Primary, Secondary, Outline）展示。",
    agentId: "design-team"
  },
];

const CATEGORIES = [
  { key: "all", label: "全部" },
  { key: "office", label: "办公协同" },
  { key: "content", label: "内容创作" },
  { key: "dev", label: "开发工具" },
];

export default function ExplorePage() {
  const navigate = useNavigate();
  const [activeCategory, setActiveCategory] = useState("all");
  const [selectedTemplate, setSelectedTemplate] = useState<typeof TEMPLATES[0] | null>(null);

  const filtered = activeCategory === "all" ? TEMPLATES : TEMPLATES.filter((t) => t.category === activeCategory);

  return (
    <div className={globalStyles.ecoPage}>
      <div className={globalStyles.pageHeader}>
        <div className={globalStyles.pageTitle}>
          <span className={globalStyles.pageTitleIcon}><Compass size={18} /></span>
          探索
        </div>
      </div>

      <div className={globalStyles.categoryTabs} style={{ marginBottom: 24 }}>
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            className={`${globalStyles.categoryTab} ${activeCategory === cat.key ? globalStyles.categoryTabActive : ""}`}
            onClick={() => setActiveCategory(cat.key)}
          >
            {cat.label}
          </button>
        ))}
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: "24px"
      }}>
        {filtered.map((tpl) => (
          <div key={tpl.id} className={styles.exploreCard} onClick={() => setSelectedTemplate(tpl)}>
            <div className={styles.cardCover}>
              <div className={styles.cardCoverGradient} style={{ background: `linear-gradient(135deg, ${tpl.color}cc, ${tpl.color})` }}>
                <div className={styles.cardTitleBig}>{tpl.name}</div>
                <div className={styles.cardTitleSmall}>NovaCraft AI Templates</div>
              </div>
            </div>
            <div className={styles.cardBody}>
              <div className={styles.cardTitle}>{tpl.name}</div>
              <div className={styles.cardDesc}>{tpl.desc}</div>
              <div className={styles.cardBadges}>
                {tpl.badge === "new" && <span className={`${styles.cardBadge} ${styles.cardBadgeNew}`}>NEW</span>}
                {tpl.tags.slice(0,2).map(tag => (
                  <span key={tag} className={styles.cardBadge}>{tag}</span>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Detail Modal */}
      {selectedTemplate && (
        <div className={styles.modalOverlay} onClick={() => setSelectedTemplate(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <button className={styles.modalClose} onClick={() => setSelectedTemplate(null)}>
              <X size={18} />
            </button>
            
            <div className={styles.modalLeft}>
              <div className={styles.modalCoverGradient} style={{ background: `linear-gradient(135deg, ${selectedTemplate.color}dd, ${selectedTemplate.color})` }}>
                <div style={{ fontSize: 36, fontWeight: 800, marginBottom: 12 }}>{selectedTemplate.name}</div>
                <div style={{ opacity: 0.8, maxWidth: "80%" }}>{selectedTemplate.desc}</div>
              </div>
            </div>

            <div className={styles.modalRight}>
              <div className={styles.modalTitle}>{selectedTemplate.name}</div>
              <div className={styles.modalTags}>
                {selectedTemplate.tags.map(tag => (
                  <span key={tag} className={styles.modalTag}>{tag}</span>
                ))}
              </div>

              <button
                className={styles.modalAction}
                onClick={() => {
                  navigate("/workbench", {
                    state: {
                      initialPrompt: selectedTemplate.prompt,
                      selectedAgent: selectedTemplate.agentId
                    }
                  });
                }}
              >
                制作我的版本
              </button>

              <div className={styles.modalSectionTitle}>使用的工具集</div>
              <div className={styles.toolList}>
                {selectedTemplate.tools.map((tool, idx) => (
                  <div key={idx} className={styles.toolItem}>
                    <div className={styles.toolIcon}>{tool.icon}</div>
                    <div className={styles.toolName}>{tool.name}</div>
                    <div className={styles.toolStatus}>
                      <CheckCircle2 size={14} style={{ marginRight: 4, verticalAlign: -2 }} />
                      预设
                    </div>
                  </div>
                ))}
              </div>

              <div className={styles.modalSectionTitle}>详细介绍</div>
              <div className={styles.modalDesc}>
                {selectedTemplate.desc}<br/><br/>
                此模板专为提高效率而设计。点击上方按钮后，将会自动跳转至新建任务页，并将完整的提示词和所需的 AI 专家/技能配置加载到输入框中。您可以根据自己的具体需求修改提示词，然后点击发送开始执行。
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
