const fs = require('fs');
const path = require('path');
const os = require('os');

const PRESET_SKILLS = [
  {
    name: "网页浏览器",
    description: "智能网页浏览、信息提取和内容摘要，支持 JavaScript 渲染和截图。",
    tags: ["网页", "爬虫", "搜索"],
    icon: "web",
    category: "recommended",
    downloads: 15200,
    author: "DClaw Official",
    backendSkillName: "browser_cdp",
    isBuiltin: true,
  },
  {
    name: "代码执行器",
    description: "安全的 Python/JavaScript 代码沙箱执行环境，支持动态安装依赖包。",
    tags: ["代码", "Python", "沙箱"],
    icon: "code",
    category: "recommended",
    downloads: 12800,
    author: "DClaw Official",
    backendSkillName: "python_sandbox",
    isBuiltin: true,
  },
  {
    name: "数据分析师",
    description: "CSV/Excel/JSON 数据分析与可视化，自动生成图表和统计报告。",
    tags: ["数据", "可视化", "Excel"],
    icon: "chart",
    category: "recommended",
    downloads: 9600,
    author: "DClaw Official",
    backendSkillName: "xlsx",
    isBuiltin: true,
  },
  {
    name: "AI 绘图助手",
    description: "基于 DALL-E / Stable Diffusion 的图像生成和编辑能力。",
    tags: ["图像", "AI", "设计"],
    icon: "image",
    category: "recommended",
    downloads: 8400,
    author: "Community",
    backendSkillName: "ai_paint_assistant",
    isBuiltin: false,
  },
  {
    name: "邮件管理器",
    description: "智能邮件撰写、回复建议、邮件分类和优先级管理。",
    tags: ["邮件", "办公", "效率"],
    icon: "email",
    category: "opc",
    downloads: 6200,
    author: "Community",
    backendSkillName: "himalaya",
    isBuiltin: true,
  },
  {
    name: "文档转换器",
    description: "支持 PDF、Word、Markdown、HTML 之间的智能格式转换和排版优化。",
    tags: ["文档", "转换", "PDF"],
    icon: "default",
    category: "opc",
    downloads: 5800,
    author: "Community",
    backendSkillName: "file_reader",
    isBuiltin: true,
  },
  {
    name: "API 调试器",
    description: "HTTP/REST API 测试工具，支持请求构造、响应解析和自动化测试。",
    tags: ["API", "测试", "HTTP"],
    icon: "tool",
    category: "dev",
    downloads: 4500,
    author: "Community",
    backendSkillName: "api_debugger",
    isBuiltin: false,
  },
  {
    name: "数据库助手",
    description: "自然语言转 SQL 查询，支持 MySQL/PostgreSQL/SQLite 数据库操作。",
    tags: ["数据库", "SQL", "查询"],
    icon: "data",
    category: "dev",
    downloads: 7100,
    author: "DClaw Official",
    backendSkillName: "database_assistant",
    isBuiltin: false,
  },
  {
    name: "智能翻译官",
    description: "多语言实时翻译，支持文档批量翻译、术语一致性维护和本地化。",
    tags: ["翻译", "多语言", "本地化"],
    icon: "bot",
    category: "life",
    downloads: 11200,
    author: "Community",
    backendSkillName: "chat_with_agent",
    isBuiltin: true,
  },
];

const manifestPath = path.join(os.homedir(), '.qwenpaw', 'skill_pool', 'skill.json');

if (!fs.existsSync(manifestPath)) {
  console.error('File not found:', manifestPath);
  process.exit(1);
}

const data = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));

PRESET_SKILLS.forEach(preset => {
  const skillKey = preset.backendSkillName;
  if (!data.skills[skillKey]) {
    data.skills[skillKey] = {
      name: skillKey,
      description: preset.description,
      version_text: "1.0",
      commit_text: "",
      source: preset.isBuiltin ? "builtin" : "customized",
      protected: false,
      requirements: { require_bins: [], require_envs: [] },
      updated_at: new Date().toISOString()
    };
  }

  const skill = data.skills[skillKey];
  skill.visibility = "public";
  
  skill.config = skill.config || {};
  skill.config.display_name = preset.name;
  skill.config.market_category = preset.category;
  skill.config.icon = preset.icon;
  skill.config.downloads = preset.downloads;
  skill.config.author = preset.author;
  skill.config.tags = preset.tags;
});

if (data.skills['skill_creator']) {
  data.skills['skill_creator'].visibility = "public";
  data.skills['skill_creator'].config = data.skills['skill_creator'].config || {};
  data.skills['skill_creator'].config.display_name = "技能生成器";
  data.skills['skill_creator'].config.market_category = "dev";
  data.skills['skill_creator'].config.icon = "tool";
}

fs.writeFileSync(manifestPath, JSON.stringify(data, null, 2), 'utf8');
console.log('Successfully injected preset skills metadata into pool manifest!');
