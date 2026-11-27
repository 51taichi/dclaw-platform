<div align="center">

# DClaw

**企业级智能体管理中台与多智能体工作站 (Enterprise Multi-Agent Workstation & Management Console)**

</div>

## 📖 项目简介 (Introduction)

DClaw 是一套功能强大的企业级 AI 智能体管理中台与个人工作站系统。它不仅提供了与底层大语言模型（LLM）对话的核心能力，更通过完善的后台管理、权限控制、插件生态以及多智能体协同机制，将 AI 能力深度转化为企业级的生产力工具。

与传统的开源客户端不同，DClaw 专为复杂的业务场景与企业级管理需求打造。

## ✨ 核心业务特性 (Core Business Features)

### 🏢 完善的后台管理 (Enterprise Administration)
- **用户与角色管理 (User Management)**：支持精确的角色划分（如 `admin` 管理员与 `user` 普通用户），实现安全、合规的用户权限隔离与账户分配。
- **对话审计日志 (Audit Chats)**：企业级的对话审计能力，支持留存、检索和分析系统内的交互历史。
- **Token 消耗统计 (Token Usage)**：精确追踪不同模型、不同用户的 Token 消耗情况，为成本核算提供数据支撑。
- **智能体数据面板 (Agent Stats)**：实时监控各个智能体的运行状态、调用频次和性能指标。

### 🤖 多智能体生态 (Multi-Agent Ecosystem)
- **自定义智能体 (Custom Agents)**：支持配置具有不同人设、不同底层模型、不同技能组合的独立智能体。
- **技能池与插件管理 (Skill Pool & Plugin Manager)**：支持动态安装、配置第三方插件与技能，赋予智能体联网搜索、读写文件、数据查询等业务能力。
- **MCP 协议支持**：深度集成 Model Context Protocol，支持灵活接入各类外部数据源和开发工具。

### 🛠 自动化与工作流 (Automation & Workflow)
- **工作台与任务流 (Workbench & Tasks)**：支持可视化的任务下发与状态追踪。
- **定时任务 (Cron Jobs)**：允许智能体在特定时间或周期内，主动执行后台业务逻辑（如生成简报、自动化巡检等）。
- **语音与多模态扩展 (Voice Transcription)**：内置语音转录等高级处理模块，适应更多交互场景。

## 🚀 快速启动 (Getting Started)

### 环境依赖 (Prerequisites)
- Node.js 18+ & npm
- Python 3.11+

### 本地启动 (Local Development)

1. **启动前端工作台 (Console)**
   ```bash
   cd console
   npm install
   npm run dev
   ```

2. **启动后端服务 (Backend)**
   ```bash
   # 在项目根目录下安装依赖
   pip install -e .
   # 初始化配置
   qwenpaw init --defaults
   # 启动服务
   qwenpaw app
   ```

3. **访问系统**
   默认情况下，系统将运行在 `http://127.0.0.1:5173/`（开发模式）或 `http://127.0.0.1:8088/`（生产模式）。

## 🛡️ 安全与隐私 (Security & Privacy)
- DClaw 采用严格的本地化数据存储，所有的对话记录、工作空间文件和敏感配置项均保留在企业内部。
- 后台采用基于角色的访问控制（RBAC），未经授权的用户无法访问审计、统计和系统设置。
  - **开启登录鉴权**：系统默认处于无权限开发模式。在生产环境中，请在启动时注入环境变量以强制开启登录拦截与用户管理：
    ```bash
    QWENPAW_AUTH_ENABLED=true qwenpaw app
    ```

---

> **DClaw** - Works for your business, grows with your team.
