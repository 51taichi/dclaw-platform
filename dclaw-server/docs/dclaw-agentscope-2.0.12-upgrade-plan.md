# DClaw AgentScope 2.0.12 升级实施方案

> 状态：实施基线  
> 日期：2026-11-25  
> 升级工作区：`/Users/moxi/Desktop/codex space/dclaw-agentscope2-lab/dclaw-server`  
> 生产源码快照：`/Users/moxi/Desktop/codex space/dclaw-platform`（升级完成前只读）

## 1. 目标与边界

本次升级按以下固定顺序执行：

1. 删除已废弃的超级专家专用 Harness，使所有 Agent 只经过同一执行底座。
2. 以官方 AgentScope 2.0.12 源码为依据完成 API 和架构评估。
3. 将 DClaw 核心执行链完整迁移至 AgentScope 2.0.12。
4. 在本地完成单元、契约、集成和关键场景测试。

不在本次源码升级中执行的操作：

- 不修改 `/Users/moxi/Desktop/codex space/dclaw-platform`。
- 不构建或更新 Docker 镜像。
- 不部署、停止或重启生产服务。
- 不连接或推送原 Git 仓库。
- 不把 DClaw 的多租户、计费、插件、渠道和数据库替换为 AgentScope 官方 App。

## 2. 已完成的统一 Harness 清理

提交 `2985ddd` 已删除废弃的 `sealed_harness/1`、`sealed_entrypoint/1` 及其 adapter、协议、worker 和无效测试，共减少约 2381 行代码。当前保留并统一使用的路径是：

```text
DClaw API / IM channel
  -> DClaw AgentRunner
  -> QwenPawAgent
  -> AgentScope core loop
  -> DClaw tools / plugins / workspace
```

历史 Manifest 中的 `runtime_adapter` 字段继续只读保留，用于旧发布包的解析和审计，不再参与执行。超级专家仍由普通 Runner 执行，安全边界、签名校验、工作区隔离和 `workspace.turn.orchestrate/1` 插件合同继续有效。

清理后的定向回归为 `229 passed`。

## 3. 官方升级基线

本次只以官方发布物为升级依据：

| 项目 | 固定值 |
| --- | --- |
| PyPI 版本 | `agentscope==2.0.12` |
| Git 标签 | `v2.0.12` |
| Git 提交 | `28ab5ef6b1d8969c6ed8a3975c2063478a5c4986` |
| Python 要求 | `>=3.11` |
| PyPI sdist SHA-256 | `8320bcb97f6e4ab5f5b19bae2850729f9accfb422f217e23a4d9bd65f335b0eb` |
| 本地官方源码 | `../upstream/agentscope-2.0.12` |
| 独立验证环境 | `../upstream/agentscope2-venv`（Python 3.11.15） |

`agentscope-runtime` 不存在于 2.0.12，必须从项目依赖和生产源码中完全移除。

## 4. 现状影响面

静态检索结果：

- 生产源码中共有 192 个 AgentScope 或 Runtime import，分布于 119 个文件。
- 其中 74 处直接依赖 `agentscope_runtime`。
- 旧 Runner、协议类型、异常类型、核心 Agent、记忆、Toolkit、Formatter、模型包装器和渠道渲染均受影响。
- 不能通过单纯修改依赖版本完成升级。

### 4.1 关键破坏性变化

| AgentScope 1 / Runtime 1 | AgentScope 2.0.12 | DClaw 迁移决策 |
| --- | --- | --- |
| `ReActAgent` | `agentscope.agent.Agent` | `QwenPawAgent` 改为继承 `Agent` |
| `InMemoryMemory` | `AgentState` | 历史消息迁入 `AgentState.messages`，DClaw 摘要元数据放入自有状态字段 |
| 私有 `_MemoryMark` | 不存在 | 删除私有 API 依赖，提示和摘要改用公开 Block/状态 |
| `Msg(content=str)` | `Msg(content=list[ContentBlock])` | 统一通过 DClaw 消息构造器生成 `TextBlock` 等内容块 |
| `Toolkit.register_tool_function()` | `await Toolkit.add_tool()` / 构造参数 | 引入集中式异步工具注册器，启动阶段完成注册 |
| `set_msg_queue_enabled()` | `Agent.reply_stream()` | 用原生事件流投影为 DClaw 的增量消息和终态 |
| `ChatModelBase(config_name, model_name, ...)` | `ChatModelBase(credential, model, parameters, ...)` | 所有 Provider 和包装器迁移到新构造及调用合同 |
| 同步 Formatter 假设 | `async FormatterBase.format()` | 调用链全部改为 await，不在事件循环内同步桥接 |
| Runtime `Runner` | 不存在 | DClaw `AgentRunner` 成为独立类，保留现有业务入口 |
| Runtime `AgentApp` | AgentScope 新 App | 保留 DClaw FastAPI 生命周期，只移除 Runtime 基类 |
| Runtime schemas | 不存在 | 建立 `qwenpaw.runtime` 自有稳定协议 |
| Runtime exceptions | 不存在 | 建立 `qwenpaw.runtime.exceptions`，保持错误码和 HTTP 语义 |

## 5. 目标架构

```text
FastAPI / OpenAPI / 14+ IM channels
              |
              v
qwenpaw.runtime contracts + error taxonomy
              |
              v
DClaw AgentRunner + TaskTracker + Session
              |
              v
AgentScope 2 Agent.reply_stream()
    |             |               |
    v             v               v
AgentState     Toolkit         Middleware
    |             |               |
    +------ DClaw adapters --------+
              |
              v
plugins / sealed workspace / billing / AIGC / persistence
```

只有 Agent 的推理和工具循环由 AgentScope 2 执行。DClaw 自有合同隔离上层业务与框架版本，避免渠道和数据库再次直接依赖第三方 Runtime 类型。

## 6. 分阶段实施与提交门禁

### 阶段 A：内部 Runtime 合同

新增 `qwenpaw.runtime`：

- 迁移 `AgentRequest`、`AgentResponse`、`Message`、内容类型、消息类型和运行状态。
- 迁移业务实际使用的异常层级、错误码和 HTTP 状态映射。
- 用兼容序列化测试锁定现有 API/渠道 JSON 形状。
- 将所有 `agentscope_runtime` import 改为内部合同。
- 将 `AgentRunner` 和 DClaw App 与 Runtime 基类解耦。

门禁：

- 生产源码中 `agentscope_runtime` 命中数为 0。
- 所有渠道 schema 和 OpenAPI 契约测试通过。
- Runtime 依赖从 `pyproject.toml` 和 lockfile 删除。

### 阶段 B：依赖、消息与工具系统

- Python 下限提升到 3.11。
- 固定 `agentscope==2.0.12`。
- 建立消息内容块转换器，覆盖文本、图片、音频、视频、文件和工具事件。
- 把 Toolkit 注册迁移到 `add_tool()`，保留名称冲突策略和插件热加载语义。
- 避免业务代码直接构造不合法的 `Msg(content=str)`。

门禁：

- 依赖可在全新 Python 3.11 环境解析和安装。
- 所有消息、工具注册、插件和 MCP 单元测试通过。
- 不出现事件循环内 `run_until_complete` 等同步兼容桥。

### 阶段 C：模型、Formatter 与计量

- 迁移 OpenAI、OpenRouter、Anthropic、Gemini、Ollama Provider。
- 重写 Retry、Routing、TokenRecording、Billing、OpenAPI failover/response-format 包装器。
- 统一 ChatResponse、ChatUsage 和流式 Usage 的归一化。
- 保持模型配置 ID、Base URL、API key 引用、参数覆盖和 fallback 顺序不变。

门禁：

- 每个 Provider 至少有构造、非流式、流式、异常转换测试。
- Token Usage 不漏记、不重复；计费终态继续 fail-closed。
- 模型配置迁移不修改用户现有配置内容。

### 阶段 D：核心 Agent、状态和流式执行

- `QwenPawAgent` 迁移至 `Agent`。
- `ToolGuardMixin` 改为 AgentScope 2 Middleware 或公开 hook，禁止覆盖私有实现。
- `AgentContext` 迁移至 `AgentState` 适配器，保留摘要、压缩、持久化和历史会话读取。
- Runner 消费 `reply_stream()` 的 `TextBlock*`、`ThinkingBlock*`、`ToolCall*`、`ToolResult*`、`ReplyEndEvent`。
- 用事件投影器保持渠道当前的累积 Message 形状，随后渠道无需感知框架事件。
- 取消时关闭异步生成器和模型任务，保证 TaskTracker 正确终态。

门禁：

- 流式输出不吞字、不重复、恰好一个终态。
- 成功、失败、取消、超时都写入可查询的任务终态。
- 历史 Session 能读取、继续并重新保存。

### 阶段 E：DClaw 企业能力回接

- 保持密封 Agent 签名、工作区边界和工具白名单。
- 保持 `workspace.turn.orchestrate/1` 插件合同。
- 回归 OpenAPI 隔离尝试、AIGC Studio、交互工具、任务恢复和计费。
- 逐渠道验证 console、飞书、钉钉、企微、微信、QQ、OneBot、Telegram、Discord、Matrix、Mattermost、MQTT、iMessage、小艺、SIP/Voice。

门禁：

- 普通 Agent 与超级专家都只经过同一 `AgentRunner -> QwenPawAgent -> AgentScope Agent` 路径。
- 仓库中不重新出现 `sealed_harness` 或 `sealed_entrypoint` 执行器。
- 关键渠道的 start/update/finish 顺序及错误终态契约不变。

### 阶段 F：本地全量验证

1. 静态 import 和依赖审计。
2. 单元测试与契约测试。
3. PostgreSQL/Redis 本地集成测试。
4. AgentScope 2 假模型流式和工具循环测试。
5. 真实配置的本地只读 smoke test；任何外部付费模型调用必须显式受控。
6. 超级专家签名包、工作区隔离和编排插件回归。
7. 取消、超时、模型失败、工具失败、后置条件失败和恢复失败注入测试。

源码测试全部通过后，Docker 镜像构建和部署仍需用户另行明确批准。

## 7. Bot 诊断与可观测性硬门禁

涉及 Bot task、flow、node 的路径必须持久化结构化事件，不能只写本地日志：

- start 和 terminal（success/failure/cancellation/skip）事件。
- 共享的 `command_id/run_id`、`task_id`、`flow_id`、`node_id`。
- attempt、timestamp、elapsed time。
- 失败节点、内部失败阶段和稳定错误码。
- 每次 transition 的 expected condition、fresh observed condition、View 标识/数量、action result、重试或 fallback 原因、剩余预算和恢复结果。

必须分别注入并测试 precondition、action、postcondition、timeout 和 recovery 失败，不能将其折叠成 generic error。日志不得包含凭据、私聊正文或生成回复正文。

## 8. 升级前测试基线

Harness 清理后的全量基线：

```text
4852 passed, 38 skipped, 16 failed
```

以下 16 项已在升级前失败，后续评估以“不新增失败”为最低门禁，并在最终验收前逐项判断是否属于本次范围：

```text
tests/unit/agents/test_setup_utils_md_files.py::test_copy_workspace_md_files_does_not_install_bootstrap_by_default
tests/unit/app/integration_delivery/test_sealed_update.py::test_sealed_update_preserves_declarations_and_can_restore[super_expert]
tests/unit/app/test_console_chat_headers.py::test_continue_message_resumes_paused_team_without_new_run
tests/unit/app/test_console_static_cache.py::test_console_spa_index_disables_browser_cache
tests/unit/app/test_super_expert_porting_playbook.py::test_current_delivery_section_uses_current_toolchain_versions
tests/unit/plugins/test_super_agent_developer_pack.py::test_developer_pack_archive_is_complete_and_reproducible
tests/unit/plugins/test_super_agent_developer_pack.py::test_upgrade_updates_devkit_version_and_immediately_validates
tests/unit/plugins/test_super_agent_devkit.py::test_devkit_has_no_server_source_import_and_runs_standalone
tests/unit/plugins/test_super_agent_devkit.py::test_devkit_bundles_and_verifies_locked_encryption_dependencies
tests/unit/plugins/test_super_agent_release_tools.py::test_standalone_plugin_release_contains_canonical_standard
tests/unit/plugins/test_super_agent_release_tools.py::test_plugin_archive_embeds_current_standard_and_is_reproducible
tests/unit/plugins/test_super_agent_support.py::test_platform_ffmpeg_builtin_prepares_exact_component_version
tests/unit/plugins/test_super_agent_support.py::test_developer_kit_is_downloadable_without_server_source
tests/unit/plugins/test_super_agent_support.py::test_developer_pack_is_downloadable_and_self_describing
tests/unit/plugins/test_super_agent_support.py::test_aigc_asset_localization_is_device_only_and_idempotent
tests/unit/plugins/test_super_agent_support.py::test_aigc_asset_dispatch_failure_is_terminal_and_replayable
```

## 9. 风险控制与回滚

每个阶段使用独立本地提交。失败时只回退当前阶段，不跨阶段混合修改。关键回滚点：

| 回滚点 | 内容 |
| --- | --- |
| R0 | 生产源码快照，始终只读 |
| R1 | `2985ddd`，废弃 Harness 已删除但仍为 AgentScope 1 |
| R2 | 内部 Runtime 合同完成，尚未切换 Agent 核心 |
| R3 | AgentScope 2 核心可运行，企业能力尚在回归 |
| R4 | 全量本地测试通过，可进入镜像评估 |

主要风险及控制：

- 历史会话：读旧写新，保留 schema version 和 fixture。
- 流式渠道：统一事件投影，不在每个渠道重复解释 AgentScope 事件。
- 计费：Usage 归一化和终态幂等测试，失败关闭。
- 插件：保持 DClaw 合同，不让插件依赖 AgentScope 私有类。
- 配置：迁移只改变解析器，不批量重写用户配置。
- 上游变化：固定 2.0.12 和源码哈希，完成升级前不追随新版本。

## 10. 完成定义

只有同时满足以下条件，源码升级才算完成：

- `agentscope-runtime` 已从依赖和生产代码完全消失。
- 所有 Agent 使用同一套 AgentScope 2.0.12 执行路径。
- 不依赖 AgentScope 私有下划线 API。
- DClaw 的 API、数据库、计费、插件、渠道和工作区合同保持兼容。
- 新增的 Bot 失败注入测试能定位到 task、flow、node、stage、reason 和 recovery outcome。
- 全量测试没有新增失败，升级相关测试全部通过。
- 工作树只包含本任务变更，并形成可审计的本地提交。
- 未构建镜像、未部署、未修改生产环境。
