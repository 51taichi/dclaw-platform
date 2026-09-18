# DClaw 基础交互能力清单设计

## 目标与范围

本次升级为 DClaw 增加独立于 AIGC 的基础交互能力模块，并让陆羽超级专家把所有真正需要客户从闭集选项中选择的提问迁移为真实卡片交互。首版只交付 `single_select` 与 `multi_select`，但目录、授权、持久化和事件边界必须允许后续以新增能力的方式扩展确认、评分、排序、表单和其他模块。

本轮只修改和验证本地代码：不更新生产服务器，不构建 Agent 发布包，不构建镜像，不部署，也不 push。DClaw Server 与 DClaw Client 在隔离 worktree 中开发；陆羽源码目录没有 Git 元数据，直接修改本地源文件。后续经用户确认后，Server 与 Client 各集中一次提交和 push，Agent 再进入打包与镜像部署流程。

## 不可变原则

1. DClaw 暴露能力、执行校验、持久化状态、渲染组件并回传结构化结果；业务含义和调用时机由超级专家决定。
2. 已发布能力版本不原地进行破坏性修改。不兼容变化必须新增 `component_type` 或主版本。
3. 样式、布局、hover、主题和无障碍优化不得改变 Agent 调用与回传契约。
4. 新增能力采用目录追加；新字段只能是可选字段，且旧调用不传时保持原行为。
5. 文档、JSON Schema、服务端校验与客户端类型来自同一能力定义或由契约测试锁定，不能分别手写后静默漂移。
6. 支持页面上的闭集选择必须创建真实卡片。目录或创建失败时 Agent 不得伪造卡片，也不得静默退回 A/B/C 或数字文本选择。

## 能力架构

在现有 `PLATFORM_CAPABILITY_CATALOG_V1` 中新增 `interaction` 分组和三项 v1 能力：

- `interaction.capabilities.list/1`：读取基础交互能力目录。
- `interaction.card.create/1`：创建或幂等恢复当前会话的交互卡片。
- `interaction.card.cancel/1`：由 Agent 显式取消仍待提交的卡片。

标准 Agent 循环按安装授权临时注册以下模型工具：

- `interaction_component_catalog(component_types=[])`
- `interaction_card_create(task_key, interaction_revision, component_type, card, input_policy="card_only", replaces_interaction_id="", expires_at="")`
- `interaction_card_status(interaction_id="")`
- `interaction_card_cancel(interaction_id, operation_key)`

目录工具采用两层返回：不传 `component_types` 时只给精简索引；传入一个或多个精确类型时返回对应能力的完整 JSON Schema、使用条件、禁用场景、默认值、约束、返回结构、正确示例和错误示例。这样 Agent 先做低歧义选择，再加载所需能力的详细协议，不把不断扩大的完整目录一次塞进模型上下文。

`interaction.card.create/1` 使用统一入口，但 `component_type` 是严格判别字段。服务端按目录中的对应 Schema 校验 `card`，未知字段和非法组合直接返回带字段路径的稳定错误，不做静默修正。

## 首版组件契约

### 通用创建字段

| 字段 | 规则 |
| --- | --- |
| `task_key` | 必填，1–160 字符；同一逻辑问题跨重试保持不变 |
| `interaction_revision` | 必填，正整数；问题或选项实质变化时递增 |
| `component_type` | 必填，首版仅 `single_select`、`multi_select` |
| `input_policy` | 可选；`card_only`、`card_or_text`、`concurrent`，默认 `card_only` |
| `card` | 必填；严格匹配对应组件 Schema |
| `replaces_interaction_id` | 可选；显式替换当前活动阻塞卡片 |
| `expires_at` | 可选；RFC 3339 UTC 时间，省略表示不自动过期 |

同一安装、会话、`task_key` 与 `interaction_revision` 确定稳定的 `interaction_id` 和幂等键。相同键和相同请求返回原卡片；相同键但不同请求返回 `IDEMPOTENCY_CONFLICT`。

### 选项

每个选项使用以下公共结构：

```json
{
  "id": "optional-stable-id",
  "text": "客户看到且提交时返回的完整文本",
  "description": "可选的补充说明",
  "recommended": true,
  "default_selected": false
}
```

- `id` 可选，存在时在同一卡片内唯一；`text` 必填且在同一卡片内唯一。
- 每项 `text` 为 1–500 字符；`description` 最多 1000 字符。
- 每张卡 2–20 个选项。
- 推荐与默认选中完全独立。推荐只改变提示标识，默认选中才改变初始选择。
- 文本型临时选项可以不带 ID；存在稳定候选、流程跳转或统计需求时 Agent 应提供 ID。

### `single_select`

`card` 字段：

- `title`：必填，1–160 字符。
- `description`：可选，最多 2000 字符。
- `options`：必填，公共选项数组。
- `supplement`：可选对象，见下文；默认关闭。
- `layout`：`auto`、`list`、`grid`，默认 `auto`。

最多一个选项可设 `default_selected=true`。提交时必须且只能选择一个选项。

### `multi_select`

除 `single_select` 公共字段外增加：

- `min_selections`：默认 1，范围 0–20。
- `max_selections`：默认选项总数，范围 1–20，且不小于 `min_selections`。

默认选中数量必须位于合法范围内。提交选择数量同样按该范围校验。

### 补充信息

```json
{
  "enabled": true,
  "label": "补充信息",
  "placeholder": "如有其他情况可以补充",
  "required": false,
  "max_length": 2000
}
```

补充信息默认关闭；开启后默认非必填。`required=true` 时空白文本不可提交。`max_length` 范围为 1–5000。关闭时提交载荷不得包含补充文本。

## 状态、阻塞与替换

交互卡片状态为 `PENDING`、`SUBMITTED`、`CANCELLED`、`REPLACED`、`EXPIRED`。只有 `PENDING` 可提交、取消或替换。

`card_only` 是默认策略。当前会话存在有效 `card_only` 卡片时：

- 普通文本、发送、附件、语音以及会产生新消息的快捷入口不可用；
- 输入区显示“请先完成上方选择”；
- 卡片真实创建成功前不得禁用输入区；
- 提交、取消、替换或过期后解除阻塞。

同一会话最多存在一张 `PENDING + card_only` 卡片。再次创建会返回 `ACTIVE_BLOCKING_INTERACTION_EXISTS`，除非请求显式提供并准确匹配 `replaces_interaction_id`。替换在同一临界区内把旧卡标记为 `REPLACED` 并创建新卡，不能静默覆盖。

`card_or_text` 允许卡片或普通消息二选一；`concurrent` 允许卡片保持待处理同时继续其他对话。首版陆羽选择题统一使用默认 `card_only`。

## 提交与普通消息承接

客户端通过受认证接口提交，而不是直接构造 Agent 消息：

```text
POST /super-expert-platform/interactions/{interaction_id}/submit
GET  /super-expert-platform/interactions?conversation_id=...
```

提交请求包含卡片 `version`、选中项引用、补充文本和客户端生成的幂等键。服务端重新读取持久化卡片并验证用户、租户、安装、会话、状态、版本、选项与数量限制。验证成功后原子写入以下结构化答案：

```json
{
  "interaction_id": "interaction-...",
  "component_type": "single_select",
  "selected": [
    {"id": "optional-stable-id", "text": "完整选项文本"}
  ],
  "supplement": null,
  "submitted_at": "2026-09-17T00:00:00Z",
  "schema_version": 1
}
```

服务端从持久化答案生成可信 `user_input` 并立即返回，不调用模型、不等待 Agent 回复。客户端把 `user_input` 交给当前聊天已有的普通消息提交入口，等同于客户在输入框中输入后发送；原会话、模型、计费、流式回复和 Agent 编排全部沿用既有链路。

提交失败不改变卡片状态。重复使用同一提交幂等键与相同答案返回原回执；不同答案返回冲突。多个不同请求争抢同一卡片时只有首个合法提交成功。

## 持久化与事件

基础交互使用独立的 `InteractionCardRepository`，不复用与画布和物料任务绑定的 `AigcTaskRepository` 或旧 `card.create`。持久化文档包含卡片、状态迁移和结构化答案，并沿用进程锁与文件锁保证原子写入。

服务端发布 `super_expert_interaction` 运行事件，载荷使用独立 `InteractionEventEnvelope`，不向现有 AIGC 事件信封塞入虚假的 `material_task_id`、`canvas_id` 或 `node_id`。REST 列表是恢复权威，SSE 只负责实时刷新。

## 客户端设计

聊天页增加 `SuperExpertInteractionCards` 与类型化投影。活动卡片位于消息区底部、输入区上方；提交后冻结选择并显示摘要。只显示当前会话、当前用户可访问的卡片。

视觉沿用 DClaw 现有设计语言：Ant Design 主题变量、`#315efb` 强调色、12px 圆角、轻阴影、150ms 状态过渡、Lucide 图标、浅色/深色/系统主题、`prefers-reduced-motion` 与 `focus-visible`。

布局规则：

- `auto` 根据容器宽度、选项数与文本长度选择网格或列表；窄屏固定单列。
- 选择语义文本不使用省略号；完整换行展示。说明文本也不隐藏影响判断的信息。
- 控件和推荐标记顶部对齐，卡片高度随内容增长。
- hover 仅在 `@media (hover: hover)` 下启用，且不能与选中状态混淆。
- 支持默认、hover、focus-visible、pressed、selected、disabled、submitting、submitted、error 和 expired 状态。
- 补充文本框自动增高，显示字符限制和必填错误。
- 桌面端首发；协议跨端一致，移动端/小程序可用同一数据降级为单列。

`WorkbenchInput.disabled` 接入活动 `card_only` 状态，并补全工具栏、附件、语音、发送和拖放禁用表现。卡片提交中防重复点击；失败恢复可编辑状态并展示可重试错误。

## 陆羽迁移

陆羽清单声明新增 `interaction` v1 能力，不复制平台完整 Schema 到 Skill。全局规则和入口规则增加：

1. 当问题存在两个及以上预设选项、客户需要选择或校准时，先调用目录获取精确组件契约，再创建真实卡片。
2. 单选使用 `single_select`，允许多个选择使用 `multi_select`；不得通过一个模糊 `choice` 参数让模型猜模式。
3. 推荐和默认选中分别表达；补充输入按问题需要启用且默认非必填。
4. 内部候选存在稳定标识时同时传 ID 和文本；临时文本选项允许只传文本。
5. 卡片创建成功后，客户可见回复不再重复列出 A/B/C、编号或要求手工输入。
6. 创建失败只准确说明本次卡片未创建成功并保留重试，不伪造、不静默降级。
7. 开放式事实补问、素材上传说明和自由表达仍使用普通对话，不为了形式强行卡片化。
8. 客户提交后复用结构化结果，不重复询问已提交选择。

现有明确闭集选择至少包括流量诊断候选校准、内容制作能力 A/B/C/D、多账号扩张授权以及其他节点实际生成的预设候选。迁移通过共享规则覆盖模型动态生成的选择题，同时更新这些显式规则，避免旧文字指令与新卡片协议冲突。更新 turn packet 后验证所有节点取得同一规则版本。

## 错误与责任边界

稳定错误至少包括：`CAPABILITY_UNAVAILABLE`、`INVALID_CATALOG_REQUEST`、`INVALID_INTERACTION_REQUEST`、`ACTIVE_BLOCKING_INTERACTION_EXISTS`、`INTERACTION_NOT_FOUND`、`INTERACTION_NOT_PENDING`、`INTERACTION_VERSION_CONFLICT`、`INVALID_SELECTION`、`SUPPLEMENT_REQUIRED`、`IDEMPOTENCY_CONFLICT` 与 `PLATFORM_OPERATION_UNCONFIRMED`。每个错误返回 `retryable`、字段路径和修正指引；不泄漏路径、凭据或内部异常。

若请求符合已发布文档而 DClaw 校验、持久化、渲染或回传不符合契约，属于 DClaw 缺陷。若 DClaw 按契约执行，而 Agent 选择了错误能力、构造了错误选项或错误解释结果，属于 Agent 编排问题。非破坏性的安全、性能、浏览器兼容和实现缺陷修复允许修改 DClaw，但不能要求 Agent 改调用逻辑。

## 验证标准

Server 自动化验证：

- 目录摘要与按类型详情、Schema 和示例一致；
- Manifest 能力闭包和工具授权正确；
- 创建、幂等、冲突、替换、取消、过期、跨会话隔离；
- 单选、多选、默认值、推荐、补充信息与长文本边界；
- 单会话单阻塞卡、并发提交只有一次成功；
- 提交产生可信结构化 Agent 输入和原会话续接；
- REST 恢复与 SSE 事件一致；
- 现有 AIGC 能力和 189 项相关基线不回归。

Client 自动化与视觉验证：

- 单选、多选、默认与推荐分离；
- `auto/list/grid`、长文本、窄屏、深色、hover、键盘与减少动效；
- `card_only` 完整禁用输入区所有消息入口并显示提示；
- 提交中、失败重试、提交冻结、过期与替换；
- REST 初始恢复与 SSE 更新合并去重；
- 类型检查、相关 Vitest 和生产构建通过。

陆羽验证：

- 工作区结构、能力声明和摘要正确；
- turn packet 重新生成且校验通过；
- 显式选择场景不再要求客户输入字母或编号；
- 开放式问题不误用卡片；
- 创建失败不伪造或降级；
- 本地全量 Agent 测试通过。

最终只报告本地代码、测试与可复现的本地 smoke 结果。发布包、镜像、生产更新和 push 均留待用户确认后的后续步骤。
