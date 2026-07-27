# Introduction

This page explains what QwenPaw is, what it can do, and how to get started
step by step with the documentation.

---

## What is QwenPaw?

QwenPaw / DClaw is an **enterprise AI workspace and multi-agent execution platform** that runs in your own environment.

![console fig](https://img.alicdn.com/imgextra/i2/O1CN01EP1ra01iOAcBvF0TC_!!6000000004402-2-tps-3822-2070.png)

- **Task Workbench** — Create tasks, attach context, select agents, Skills, or expert teams, and track execution status and results.
- **Multi-agent collaboration** — Create independent agents with their own configuration, memory, and Skills, then combine them with expert teams for complex work.
- **AIGC Studio** — Use canvas nodes to organize scripts, images, video, audio, and reference assets into a creative production flow.
- **Enterprise knowledge** — Connect local files, enterprise documents, and Feishu/Lark cloud docs with keyword and semantic retrieval.
- **Models, plugins, and MCP** — Connect model providers, Skills, plugins, and MCP tools to real business systems.
- **Governance and security** — Manage users, roles, chat audits, token usage, tool guards, file access controls, object storage, and backups.
- **Multi-endpoint access** — Use the console, desktop app, mini app, DingTalk, Feishu, Discord, Telegram, and other channels where each workflow lives.

QwenPaw is built by the [AgentScope team](https://github.com/agentscope-ai) on
[AgentScope](https://github.com/agentscope-ai/agentscope),
[AgentScope Runtime](https://github.com/agentscope-ai/agentscope-runtime), and
[ReMe](https://github.com/agentscope-ai/ReMe).

---

## How do you use QwenPaw?

There are five main ways to use QwenPaw:

1. **Create tasks in Workbench**
   Describe the goal, upload attachments, choose agents, Skills, or expert teams, and get a traceable execution flow.

2. **Produce content in AIGC Studio**
   Use canvas nodes for scripts, images, video, audio, and reference assets, with generation driven by model capabilities.

3. **Search and reuse enterprise knowledge**
   Upload enterprise files, connect cloud docs, and use keyword plus semantic retrieval for answers, summaries, and context.

4. **Let agents execute together**
   Use Skills, plugins, MCP, and expert teams to connect tools, business systems, and automation workflows.

5. **Operate across endpoints with governance**
   Use the console, desktop app, mini app, or business channels, while admins manage models, users, audits, usage, and backups.

---

## Key concepts in the documentation

- **Console** — QwenPaw's built-in web management interface. Chat, configure
  channels, manage skills, set up models, and more. See [Console](./console).
- **Channel** — Where you talk to QwenPaw (DingTalk, Feishu, QQ, Discord,
  iMessage, etc.). Configure step by step in [Channels](./channels).
- **Heartbeat** — Ask QwenPaw your prepared questions at fixed intervals, and
  optionally send the answers to your last active channel. See
  [Heartbeat](./heartbeat).
- **Scheduled tasks** — Multiple tasks, each with independent time configuration
  (send X daily at 9am, ask QwenPaw Y every 2 hours, etc.), managed through the
  Console or [CLI](./cli).
- **Skill pool and workspace skills** — The skill pool is a shared skill
  repository. Workspace skills are local copies that an agent actually uses
  when running. See [Skills](./skills).
- **MCP and tools** — MCP (Model Context Protocol) is a standard protocol for
  connecting external tool servers to extend capabilities. Tools are QwenPaw's
  built-in core abilities (reading/writing files, executing commands, browser,
  etc.). See [MCP and Tools](./mcp).
- **Agent/Workspace** — Starting from v0.1.0, QwenPaw supports multi-agent,
  allowing multiple independent AI agents to run. Each agent has its own
  workspace, configuration, memory, skills, and conversation history. Agents
  can communicate and collaborate through collaboration skills to complete
  complex tasks. See [Multi-Agent](./multi-agent).
- **Security mechanisms** — QwenPaw provides multi-layer security, including
  tool protection (intercept dangerous command parameters), file protection
  (restrict sensitive path access), and skill scanner (check skill package
  security). See [Security](./security).

Each concept is explained in detail in its corresponding chapter.

---

## Suggested reading and setup order

1. **[Quick start](./quickstart)** — Get the service running in three commands.
2. **[Console](./console)** — After the service starts, open the Console in
   your browser (`http://127.0.0.1:8088/`). **This is the central hub for
   configuring and using QwenPaw.** Start by chatting and configuring models in
   the Console to understand how QwenPaw works.
3. **[Models](./models)** — Configure API keys for cloud LLM providers or
   download local models. This is a **required prerequisite** for using QwenPaw.
4. **Configure and use as needed**:
   - [Channels](./channels) — Connect DingTalk / Feishu / WeChat / Discord / Telegram to chat with QwenPaw in those apps;
   - [Skills](./skills) — Understand and extend QwenPaw's capabilities;
   - [MCP and Tools](./mcp) — Connect external MCP tool servers;
   - [Magic Commands](./commands) — Use special commands to quickly control conversation state (like `/new` for new conversation, `/clear` to clear history, `/stop` to stop tasks, `/restart` to restart service, etc.) without waiting for AI to understand;
   - [Security](./security) — Configure tool protection, file protection, skill security scanning, and other security mechanisms;
   - [Heartbeat](./heartbeat) — Set up scheduled check-ins or digests (optional);
   - [Scheduled tasks](./console#scheduled-tasks) or [CLI](./cli) — Scheduled tasks, `qwenpaw doctor` diagnostics, `qwenpaw doctor fix`, and more;
   - [Multi-Agent](./multi-agent) — Multi-agent configuration, management, and collaboration (v0.1.0+ feature);
   - [Config & working directory](./config) — Working directory and config file details.
