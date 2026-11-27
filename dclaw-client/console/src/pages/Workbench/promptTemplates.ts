export const WORKBENCH_PROMPT_KEYS = [
  "dev",
  "website",
  "agent",
  "skillDev",
  "cicd",
  "docs",
  "doc",
  "finance",
  "data",
  "research",
  "product",
  "slides",
  "design",
  "email",
] as const;

export type WorkbenchPromptKey = (typeof WORKBENCH_PROMPT_KEYS)[number];

type Translate = (key: string, fallback: string) => string;

const PROMPT_FALLBACKS: Record<WorkbenchPromptKey, string> = {
  dev: "请帮我开发一个功能：\n目标：\n当前问题：\n技术栈：\n期望你输出实现方案、关键代码和验证步骤。",
  website:
    "请帮我做一个网页：\n主题：\n目标用户：\n需要的页面/模块：\n视觉风格：\n请直接给出可运行的实现。",
  agent:
    "请帮我设计一个智能体应用：\n使用场景：\n用户会输入什么：\n智能体需要完成什么：\n请给出工作流、工具能力和落地方案。",
  skillDev:
    "请帮我创建一个新技能：\n技能名称：\n适用场景：\n输入信息：\n输出产物：\n请生成可导入的 SKILL.md。",
  cicd: "请帮我优化 CI/CD 流程：\n项目类型：\n当前流程：\n遇到的问题：\n期望目标：\n请给出配置建议和排查步骤。",
  docs: "请帮我编写技术文档：\n项目/功能：\n读者对象：\n需要覆盖的内容：\n请输出结构清晰、可直接发布的文档。",
  doc: "请帮我处理一份文档：\n文档内容/附件：\n处理目标：\n输出格式：\n请提炼重点、整理结构，并给出可交付版本。",
  finance:
    "请帮我做金融分析：\n标的/行业：\n分析周期：\n关注指标：\n风险偏好：\n请输出结论、依据、风险点和后续观察清单。",
  data: "请帮我做数据分析与可视化：\n数据来源：\n想回答的问题：\n关键字段：\n请清洗数据、分析趋势，并建议适合的图表。",
  research:
    "请帮我做深度研究：\n研究主题：\n使用场景：\n需要比较的对象：\n请输出摘要、关键发现、证据来源和行动建议。",
  product:
    "请帮我做产品管理任务：\n产品/功能：\n目标用户：\n当前痛点：\n请输出需求拆解、优先级、验收标准和下一步计划。",
  slides:
    "请帮我制作一份幻灯片大纲：\n主题：\n听众：\n时长：\n希望传达的结论：\n请输出页级结构、每页标题和内容要点。",
  design:
    "请帮我做设计方案：\n产品/页面：\n目标用户：\n品牌气质：\n需要的界面/组件：\n请输出布局、视觉风格和交互建议。",
  email:
    "请帮我编辑一封邮件：\n收件人：\n沟通目的：\n语气：\n必须包含的信息：\n请输出一个清晰、礼貌、可直接发送的版本。",
};

export function buildWorkbenchPrompt(key: string, t: Translate): string {
  if (!WORKBENCH_PROMPT_KEYS.includes(key as WorkbenchPromptKey)) {
    return t(
      "workbench.promptDefault",
      "请帮我完成一个任务：\n目标：\n背景：\n期望产物：",
    );
  }

  return t(
    `workbench.prompts.${key}`,
    PROMPT_FALLBACKS[key as WorkbenchPromptKey],
  );
}
