// ── URLs ──────────────────────────────────────────────────────────────────

export const PYPI_URL = "https://pypi.org/pypi/qwenpaw/json";

export const GITHUB_URL = "https://github.com/agentscope-ai/QwenPaw" as const;

// ── Timing ────────────────────────────────────────────────────────────────

export const ONE_HOUR_MS = 60 * 60 * 1000;

// ── Navigation ────────────────────────────────────────────────────────────

export const DEFAULT_OPEN_KEYS = [
  "control-group",
  "agent-group",
  "settings-group",
  "advanced-group",
];

export const KEY_TO_PATH: Record<string, string> = {
  workbench: "/workbench",
  "aigc-studio": "/aigc-studio",
  claw: "/claw",
  experts: "/experts",
  "skill-market": "/skill-market",
  explore: "/explore",
  connectors: "/connectors",
  library: "/tencent-doc",
  automations: "/automations",
  channels: "/admin/channels",
  sessions: "/admin/sessions",
  inbox: "/admin/inbox",
  "cron-jobs": "/admin/cron-jobs",
  heartbeat: "/admin/heartbeat",

  "skill-pool": "/admin/skill-pool",
  "expert-teams": "/admin/expert-teams",
  tools: "/admin/tools",
  mcp: "/admin/mcp",
  acp: "/admin/acp",
  workspace: "/admin/workspace",
  "tencent-doc": "/tencent-doc",
  agents: "/admin/agents",
  models: "/admin/models",
  "web-search": "/admin/web-search",
  environments: "/admin/environments",
  "object-storage": "/admin/object-storage",
  "enterprise-knowledge": "/admin/enterprise-knowledge",
  "mindspace-cloud": "/admin/mindspace-cloud",
  "agent-config": "/admin/agent-config",
  security: "/admin/security",
  "token-usage": "/admin/token-usage",
  "audit-chats": "/admin/audit-chats",
  "agent-stats": "/admin/agent-stats",
  users: "/admin/users",
  "voice-transcription": "/admin/voice-transcription",
  debug: "/admin/debug",
  backups: "/admin/backups",
  "plugin-manager": "/admin/plugin-manager",
  "open-api": "/admin/open-api",
};

export const KEY_TO_LABEL: Record<string, string> = {
  "aigc-studio": "nav.aigcStudio",
  channels: "nav.channels",
  sessions: "nav.sessions",
  inbox: "nav.inbox",
  "cron-jobs": "nav.cronJobs",
  heartbeat: "nav.heartbeat",
  skills: "nav.skills",
  "skill-pool": "nav.skillPool",
  "expert-teams": "nav.expertTeams",
  tools: "nav.tools",
  mcp: "nav.mcp",
  acp: "nav.acp",
  "agent-config": "nav.agentConfig",
  workspace: "nav.workspace",
  "tencent-doc": "nav.tencentDoc",
  models: "nav.models",
  "web-search": "nav.webSearch",
  environments: "nav.environments",
  "object-storage": "nav.objectStorage",
  "enterprise-knowledge": "nav.enterpriseKnowledge",
  "mindspace-cloud": "nav.mindspaceCloud",
  security: "nav.security",
  users: "nav.users",
  "token-usage": "nav.tokenUsage",
  agents: "nav.agents",
  debug: "nav.debug",
  backups: "nav.backups",
  "plugin-manager": "nav.pluginManager",
  "audit-chats": "nav.auditChats",
  "open-api": "nav.openApi",
};

// ── URL helpers ───────────────────────────────────────────────────────────

export const getWebsiteLang = (lang: string): string =>
  lang.startsWith("zh") ? "zh" : "en";

export const getDocsUrl = (lang: string): string =>
  `https://qwenpaw.agentscope.io/docs/intro?lang=${getWebsiteLang(lang)}`;

export const getFaqUrl = (lang: string): string =>
  `https://qwenpaw.agentscope.io/docs/faq?lang=${getWebsiteLang(lang)}`;

export const getReleaseNotesUrl = (lang: string): string =>
  `https://qwenpaw.agentscope.io/release-notes?lang=${getWebsiteLang(lang)}`;

// ── Version helpers ────────────────────────────────────────────────────────

// Filter out pre-release versions; post-releases are treated as stable.
// PEP 440 pre-release suffixes: aN / bN / rcN (or cN) / devN.
export const isStableVersion = (v: string): boolean =>
  !/(\d)(a|alpha|b|beta|rc|c|dev)\d*/i.test(v);

// Compare two PEP 440 version strings. Returns >0 if a>b, <0 if a<b, 0 if equal.
// .postN releases sort after their base version (e.g. 1.0.0.post1 > 1.0.0).
// Pre-release versions (aN, bN, rcN) sort before their base version.
export const compareVersions = (a: string, b: string): number => {
  const normalise = (v: string): number[] => {
    // Handle .postN suffix
    const postMatch = v.match(/\.post(\d+)$/i);
    const postNum = postMatch ? Number(postMatch[1]) : 0;
    const baseVersion = v.replace(/\.post\d+$/i, "");

    // Handle pre-release suffix (e.g., 1.0.1b1 -> base=1.0.1, preType=b, preNum=1)
    const preMatch = baseVersion.match(/^(.+?)(a|alpha|b|beta|rc|c)(\d*)$/i);
    let coreVersion = baseVersion;
    let preType = 0; // 0 = stable, -3 = alpha, -2 = beta, -1 = rc
    let preNum = 0;
    if (preMatch) {
      coreVersion = preMatch[1];
      const preLabel = preMatch[2].toLowerCase();
      preType =
        preLabel === "a" || preLabel === "alpha"
          ? -3
          : preLabel === "b" || preLabel === "beta"
          ? -2
          : -1; // rc or c
      preNum = preMatch[3] ? Number(preMatch[3]) : 0;
    }

    const parts = coreVersion.split(/[.\-]/).map((seg) => Number(seg) || 0);
    // Append: preType (0 for stable, negative for pre-release), preNum, postNum
    return [...parts, preType, preNum, postNum];
  };

  const aN = normalise(a);
  const bN = normalise(b);
  const len = Math.max(aN.length, bN.length);
  for (let i = 0; i < len; i++) {
    const diff = (aN[i] ?? 0) - (bN[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
};

// ── Update markdown ───────────────────────────────────────────────────────
// TODO
export const UPDATE_MD: Record<string, string> = {
  zh: `### DClaw如何更新

要更新 DClaw 到最新版本，可根据你的安装方式选择对应方法：

1. 如果你使用的是一键安装脚本，直接重新运行安装命令即可自动升级。

2. 如果你是通过 pip 安装，在终端中执行以下命令升级：

\`\`\`
dclaw update
\`\`\`

3. 如果你是从源码安装，进入项目目录并拉取最新代码后重新安装：

\`\`\`
cd DClaw
git pull origin main
cd console && npm ci && npm run build
cd .. && mkdir -p src/qwenpaw/console
cp -R console/dist/. src/qwenpaw/console/
pip install -e .
\`\`\`

4. 如果你使用的是 Docker，拉取最新镜像并重启容器：

\`\`\`
docker pull agentscope/dclaw:latest
docker run -p 127.0.0.1:8088:8088 -v dclaw-data:/app/working agentscope/dclaw:latest
\`\`\`

升级后重启服务 qwenpaw app。`,

  ru: `### Как обновить DClaw

Чтобы обновить DClaw, выберите способ в зависимости от типа установки:

1. Если вы устанавливали через однострочный скрипт, повторно запустите установщик для обновления.

2. Если устанавливали через pip, выполните:

\`\`\`
dclaw update
\`\`\`

3. Если устанавливали из исходников, получите последние изменения и переустановите:

\`\`\`
cd DClaw
git pull origin main
cd console && npm ci && npm run build
cd .. && mkdir -p src/qwenpaw/console
cp -R console/dist/. src/qwenpaw/console/
pip install -e .
\`\`\`

4. Если используете Docker, загрузите новый образ и перезапустите контейнер:

\`\`\`
docker pull agentscope/dclaw:latest
docker run -p 127.0.0.1:8088:8088 -v dclaw-data:/app/working agentscope/dclaw:latest
\`\`\`

After upgrading, restart the service with \`qwenpaw app\`.`,

  en: `### How to update DClaw

To update DClaw, use the method matching your installation type:

1. If installed via one-line script, re-run the installer to upgrade.

2. If installed via pip, run:

\`\`\`
dclaw update
\`\`\`

3. If installed from source, pull the latest code and reinstall:

\`\`\`
cd DClaw
git pull origin main
cd console && npm ci && npm run build
cd .. && mkdir -p src/qwenpaw/console
cp -R console/dist/. src/qwenpaw/console/
pip install -e .
\`\`\`

4. If using Docker, pull the latest image and restart the container:

\`\`\`
docker pull agentscope/dclaw:latest
docker run -p 127.0.0.1:8088:8088 -v dclaw-data:/app/working agentscope/dclaw:latest
\`\`\`

After upgrading, restart the service with \`qwenpaw app\`.`,
};
