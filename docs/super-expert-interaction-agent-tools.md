# DClaw 基础交互能力 v1：Agent 调用文档

本文是签名超级专家 Agent 使用基础交互卡片的完整契约。它描述如何选择能力、构造请求、判断成功、处理错误和消费客户答案。DClaw 负责校验、持久化、渲染、提交与可信回传；Agent 负责业务问题、选项内容和后续编排。

## 1. 版本与兼容原则

- 能力组：`interaction`，当前版本 `1`。
- 组件：`single_select`、`multi_select`、`question_form`。它们是不同的 Agent 能力语义，即使客户端共享外层状态与样式也不得混用。
- 已发布 v1 字段、默认值和状态语义保持稳定。样式调整不改变 Agent 请求。
- 新组件或可选字段可以增量加入目录；不兼容语义必须发布新的组件类型或契约版本。
- 请求采用严格 Schema：未知字段被拒绝，DClaw 不猜测、不重命名、不静默修正。

安装清单必须完整声明：

```json
{
  "platform_contract_versions": {"interaction": "1"},
  "capabilities": [
    {"capability_id": "interaction.capabilities.list/1", "contract_version": "1"},
    {"capability_id": "interaction.card.create/1", "contract_version": "1"},
    {"capability_id": "interaction.card.cancel/1", "contract_version": "1"}
  ]
}
```

依赖闭包为：`cancel → create → catalog`。未获授权的工具不会暴露给 Agent。

## 2. 决策表

| 客户当前动作 | 使用方式 | 不应使用 |
|---|---|---|
| 从至少两个完整预设选项中选一项 | `single_select` | 自由事实补问、多项可同时成立 |
| 从至少两个完整预设选项中选多项 | `multi_select` | 只能选一个、答案无法预先列全 |
| 填写一个或多个无法可靠列全答案的文本问题 | `question_form` | 能形成完整选项、上传素材 |
| 上传图片、视频、文件等素材 | 对应素材能力 | 不用 `question_form` 伪装上传 |

Agent 必须先做“能否可靠列全”判断。问题原本以开放句式表达，不代表
它一定属于 `question_form`；目标、状态、阶段、能力等能形成完整分类时仍应
使用选择组件。选择与开放问题同轮出现时按业务依赖分别创建卡片，不把不同
字段类型塞进一个组件。

创建任何卡片前，先读取所选组件的详细目录。不要依赖训练时记忆的 Schema。

## 3. Agent 工具

### 3.1 `interaction_component_catalog`

读取平台当前目录。

```text
interaction_component_catalog(component_types=[])
```

- `component_types`：字符串数组。空数组返回精简决策索引；传 `single_select`、`multi_select`、`question_form` 或其组合，返回对应详细 Schema、默认值、正例和错误例。
- 非数组、空字符串、未知类型返回 `INVALID_CATALOG_REQUEST`。
- 精简索引用来选组件；创建前必须再读取确定组件的详细项。

示例：

```json
{"component_types":["single_select"]}
```

### 3.2 `interaction_card_create`

创建真实、可恢复的交互卡片。

```text
interaction_card_create(
  task_key,
  interaction_revision,
  component_type,
  card,
  input_policy="card_only",
  replaces_interaction_id="",
  expires_at=""
)
```

| 参数 | 必填 | 约束与语义 |
|---|---:|---|
| `task_key` | 是 | 1–160 字符；同一逻辑问题保持稳定 |
| `interaction_revision` | 是 | 正整数；问题、选项或选择语义实质变化时递增 |
| `component_type` | 是 | 精确为 `single_select`、`multi_select` 或 `question_form` |
| `card` | 是 | 必须符合所选类型实时 Schema |
| `input_policy` | 否 | 默认 `card_only`；也可显式用 `card_or_text`、`concurrent` |
| `replaces_interaction_id` | 否 | 显式替换当前活动阻塞卡；不得猜 ID |
| `expires_at` | 否 | RFC 3339、带时区、未来时间；空表示不自动过期 |

成功证据只有工具返回的真实 `interaction.interaction_id` 和 `PENDING` 状态。请求文本、模型自述、历史卡片或不确定错误都不能证明新卡片存在。

#### 3.2.1 回复内定位契约

DClaw 将卡片嵌入创建成功回执在本轮回复消息序列中的位置。Agent 可以正常输出业务说明，但必须把创建调用放在原本应出现问题或选项的位置：

1. 先输出需要保留的卡片前说明。
2. 在问题、问答项或选项列表应出现的位置调用 `interaction_card_create`。
3. 收到包含真实 `interaction.interaction_id` 的成功回执后，再输出需要保留的卡片后说明。

问题、问答项和选项只写入 `card` 参数，不应在普通正文中重复。成功后也不要用“卡片已发给你”等无新增信息的文字代替卡片。创建失败、回执无法解析或回执不含真实交互 ID 时不会生成精确位置锚点，Agent 必须按失败处理，不能宣称客户已看到卡片。

对于升级前已经存在、因历史消息缺少精确成功锚点而无法定位的卡片，客户端只提供兼容兜底：展示在视觉上最新的专家回复末尾。该兜底不是新调用的定位协议，新的 Agent 编排必须遵循上述顺序。

### 3.3 `interaction_card_status`

```text
interaction_card_status(interaction_id="")
```

- 传 ID：读取当前安装、当前会话中的指定卡片。
- 空 ID：读取当前活动的 `PENDING + card_only` 卡片。
- 跨安装、跨会话和不存在统一返回 `INTERACTION_NOT_FOUND`，避免泄漏身份。

### 3.4 `interaction_card_cancel`

```text
interaction_card_cancel(interaction_id, operation_key)
```

- 只取消仍为 `PENDING` 的卡片。
- `operation_key` 是本次逻辑取消动作的稳定键；网络重试时必须复用。
- 若要立刻用新问题替换当前阻塞卡，优先在新建请求中使用 `replaces_interaction_id`，保证替换原子完成。

## 4. 卡片字段

### 4.1 两类共有字段

| 字段 | 类型 | 默认 | 限制 |
|---|---|---|---|
| `title` | string | 无 | 必填，1–160 字符，去除首尾空白后不可为空 |
| `description` | string/null | `null` | 最长 2000；完整展示，不用于藏关键选择条件 |
| `options` | array | 无 | 必填，2–20 项；文本唯一，非空 ID 也必须唯一 |
| `supplement` | object | 关闭 | 见下节 |
| `layout` | enum | `auto` | `auto`、`list`、`grid`；只影响展示，不影响提交语义 |

### 4.2 `options[]`

| 字段 | 类型 | 默认 | 限制与用法 |
|---|---|---|---|
| `id` | string/null | `null` | 可选，1–160；有稳定业务候选时必须同时传 ID 与文本 |
| `text` | string | 无 | 必填，1–500；客户看到的完整选择语义 |
| `description` | string/null | `null` | 最长 1000；用于取舍条件，不应重复标题 |
| `recommended` | boolean | `false` | 仅显示“AI 推荐”，不会选中 |
| `default_selected` | boolean | `false` | 才表示初始已选；必须有真实业务依据 |

`recommended` 与 `default_selected` 是正交能力。推荐不能被客户端或 Agent 当成客户已选择。

### 4.3 `supplement`

| 字段 | 类型 | 默认 | 限制 |
|---|---|---|---|
| `enabled` | boolean | `false` | 关闭时不能提交非空补充文本 |
| `label` | string | `补充信息` | 1–80 |
| `placeholder` | string | `如有其他情况可以补充` | 1–200 |
| `required` | boolean | `false` | 只有 `enabled=true` 时允许为真 |
| `max_length` | integer | `2000` | 1–5000 |

补充信息不是固定必填项。只有缺少它就无法继续业务判断时才设为必填。

### 4.4 `single_select`

- 客户必须且只能提交一项。
- 最多一个 `default_selected=true`。
- 不接收 `min_selections`、`max_selections` 等多选字段。

```json
{
  "task_key": "primary-direction",
  "interaction_revision": 1,
  "component_type": "single_select",
  "input_policy": "card_only",
  "card": {
    "title": "请选择本轮优先方向",
    "description": "只选择一个最贴近当前目标的方向。",
    "options": [
      {"id": "growth", "text": "优先扩大有效触达", "recommended": true},
      {"id": "conversion", "text": "优先提高咨询转化", "default_selected": false},
      {"text": "目前都不贴近"}
    ],
    "supplement": {
      "enabled": true,
      "label": "补充信息（选填）",
      "placeholder": "可以说明不贴近的原因",
      "required": false,
      "max_length": 500
    },
    "layout": "auto"
  }
}
```

### 4.5 `multi_select`

- `min_selections` 默认 `1`，允许为 `0`。
- `max_selections` 默认选项总数，范围 1–20，不能超过选项数。
- `min_selections <= max_selections`。
- 默认选中项数量必须落在上下限内。

```json
{
  "task_key": "available-production-modes",
  "interaction_revision": 1,
  "component_type": "multi_select",
  "card": {
    "title": "请选择目前实际可用的制作方式",
    "options": [
      {"id": "on_camera", "text": "真人出镜并口播"},
      {"id": "voice_only", "text": "不出镜但可以配音"},
      {"id": "visual_text", "text": "图片、录屏或文字"},
      {"id": "team", "text": "有团队协助"}
    ],
    "min_selections": 1,
    "max_selections": 4,
    "supplement": {"enabled": true, "required": false},
    "layout": "grid"
  }
}
```

### 4.6 `question_form`

用于收集无法可靠枚举的一个或多个开放式文本答案。卡片只有 `title`、
`description` 和 `items`；不接收 `options`、`supplement`、`layout`、
`recommended`、`default_selected`、推荐答案或预填答案。

| 字段 | 类型 | 默认 | 限制与语义 |
|---|---|---|---|
| `title` | string | 无 | 必填，1–160，去除首尾空白后不可为空 |
| `description` | string/null | `null` | 最长 2000；说明整组填写口径 |
| `items` | array | 无 | 必填，1–20 项；客户端固定逐项独占一行 |

`items[]`：

| 字段 | 类型 | 默认 | 限制与语义 |
|---|---|---|---|
| `id` | string/null | `null` | 可选，1–160；同卡非空 ID 唯一；稳定业务字段建议提供 |
| `question` | string | 无 | 必填，1–500；同卡完整文本唯一 |
| `description` | string/null | `null` | 最长 1000；只解释填写口径，不另藏问题 |
| `placeholder` | string | `请输入回答` | 1–200；提示格式，不得暗示客户事实 |
| `required` | boolean | `true` | 缺少该答案仍能继续当前业务判断时才设为 `false` |
| `max_length` | integer | `2000` | 1–5000 |

```json
{
  "task_key": "collect-business-context",
  "interaction_revision": 1,
  "component_type": "question_form",
  "input_policy": "card_only",
  "card": {
    "title": "请补充以下信息",
    "description": "请按实际情况填写。",
    "items": [
      {
        "id": "service_scope",
        "question": "你目前主要提供哪些家电维修服务？",
        "description": "例如空调、冰箱、洗衣机等。",
        "placeholder": "请填写服务范围",
        "required": true,
        "max_length": 2000
      },
      {
        "question": "还有哪些需要补充的情况？",
        "placeholder": "选填",
        "required": false,
        "max_length": 1000
      }
    ]
  }
}
```

为什么没有 `input_type` 或 `layout`：DClaw 统一使用自动增高文本框，短答案保持
紧凑，长答案自动换行并在达到上限后内部滚动。展示差异属于客户端样式，不让
Agent 猜单行、多行、行数或网格。

## 5. 输入策略

| 值 | 客户端行为 | 使用条件 |
|---|---|---|
| `card_only` | 卡片真实创建后，文本、附件、拖放、语音、发送和消息型工具入口不可用 | 默认；答案必须来自卡片 |
| `card_or_text` | 卡片和普通输入二选一 | Agent 能可靠解释两种通道，且业务允许非结构化回答 |
| `concurrent` | 卡片与普通消息可并行 | 只有明确需要客户一边选择一边继续其他对话时显式使用 |

锁定只在持久化创建成功后生效。创建失败不能让客户端进入假锁定。一个会话最多有一张 `PENDING + card_only` 卡片；第二张必须显式替换或先取消。

## 6. 幂等、替换和状态

稳定身份由安装、会话、`task_key`、`interaction_revision` 确定。同一身份和同一请求重放返回原卡；同一幂等键或稳定身份承载不同内容返回 `IDEMPOTENCY_CONFLICT`。

状态机：

```text
PENDING ──submit──> SUBMITTED
   ├────cancel────> CANCELLED
   ├───replace────> REPLACED
   └────expire────> EXPIRED
```

只有 `PENDING` 可提交或取消。每次成功迁移使 `version` 加一。提交必须带客户端看到的当前版本；陈旧版本返回 `INTERACTION_VERSION_CONFLICT`。

替换示例：先读活动卡状态，随后新建卡传：

```json
{
  "task_key": "primary-direction",
  "interaction_revision": 2,
  "component_type": "single_select",
  "replaces_interaction_id": "interaction-old-real-id",
  "card": {"title": "请选择修订后的方向", "options": [{"text":"甲"},{"text":"乙"}]}
}
```

旧卡与新卡在同一持久化临界区内分别变为 `REPLACED` 与 `PENDING`，不存在静默覆盖窗口。

## 7. 客户提交与普通消息承接

客户端提交：

```http
POST /super-expert-platform/interactions/{interaction_id}/submit
Content-Type: application/json
```

```json
{
  "version": 1,
  "selected": [{"id": "growth"}],
  "supplement": "先验证一个月",
  "idempotency_key": "client-stable-submit-key"
}
```

文本型选项可传 `{"text":"完整且唯一的选项文本"}`。即使客户端同时提交了文本，服务端也只以持久化卡片解析最终文本；客户端不能篡改 Agent 收到的标签。

`question_form` 使用独立提交分支，不能携带 `selected` 或 `supplement`：

```json
{
  "version": 1,
  "answers": [
    {"id": "service_scope", "value": "主要维修空调和冰箱"},
    {"question": "还有哪些需要补充的情况？", "value": null}
  ],
  "idempotency_key": "client-stable-submit-key"
}
```

- 有 ID 的 item 用 `id` 引用；无 ID 的 item 用完整且唯一的 `question` 引用。
- 引用、值和标签都不能改变持久化卡片。DClaw 按原卡片顺序生成可信答案。
- 首尾空白被清理，回答内部换行保留；选填空答案标准化为 `null`。
- 每个持久化 item 在可信结果中恰好出现一次，客户端漏传的选填项仍返回 `null`。

可信问答结果：

```json
{
  "interaction_id": "interaction-...",
  "component_type": "question_form",
  "answers": [
    {
      "id": "service_scope",
      "question": "你目前主要提供哪些家电维修服务？",
      "value": "主要维修空调和冰箱"
    },
    {
      "id": null,
      "question": "还有哪些需要补充的情况？",
      "value": null
    }
  ],
  "submitted_at": "2026-09-17T08:00:00Z",
  "schema_version": 1
}
```

成功响应：

```json
{
  "interaction": {
    "interaction_id": "interaction-...",
    "status": "SUBMITTED",
    "version": 2,
    "answer": {
      "interaction_id": "interaction-...",
      "component_type": "single_select",
      "selected": [{"id":"growth","text":"优先扩大有效触达"}],
      "supplement": "先验证一个月",
      "submitted_at": "2026-09-17T08:00:00Z",
      "schema_version": 1
    }
  },
  "user_input": "优先扩大有效触达\n先验证一个月"
}
```

DClaw 提交接口只校验并持久化卡片答案，然后立即返回由持久化答案生成的 `user_input`；它不调用模型，也不等待 Agent 回复。客户端必须把 `user_input` 交给当前聊天原有的普通消息提交入口，等同于客户在输入框中输入这些内容并发送。后续使用原聊天、原超级专家、原已选模型、原计费和原流式回复链路，不新增卡片专用编排。

选择卡按原选项顺序输出可信选项文本，补充信息非空时追加一行；问答卡按 item 顺序输出所有非空 `value`，不加入问题复述或内部 JSON。结构化 `answer` 仍保存在 `interaction` 中供恢复与审计，但不作为另一条 Agent 输入协议。相同提交键重放只返回同一持久化答案和同一 `user_input`，不会重复状态迁移。

## 8. REST 恢复与实时事件

```http
GET /super-expert-platform/interactions?conversation_id={chat-or-session-id}
```

响应 `{"interactions":[...]}`。服务端校验当前用户对聊天的访问权、租户和安装；REST 是恢复权威。

实时事件类型固定为 `super_expert_interaction`：

```json
{
  "type": "super_expert_interaction",
  "scope": "session",
  "job_id": "interaction-...",
  "status": "PENDING",
  "payload": {
    "envelope": {
      "contract_version": "1",
      "event_id": "create-...",
      "installation_id": "installation-...",
      "conversation_id": "conversation-...",
      "interaction_id": "interaction-...",
      "event_type": "interaction.card.created",
      "interaction": {}
    }
  }
}
```

事件类型还包括 `interaction.card.cancelled`、`interaction.card.submitted`。该信封没有 `material_task_id`、`canvas_id`、`node_id` 等 AIGC 字段。客户端按 interaction ID 和 version 合并 REST/SSE；SSE 丢失时重新读取 REST。

## 9. 稳定错误

| 错误 | 含义 | Agent 动作 |
|---|---|---|
| `CAPABILITY_UNAVAILABLE` | 安装未获能力 | 不声称成功；检查已签名清单与授权 |
| `INVALID_CATALOG_REQUEST` | 目录过滤参数错误 | 修正类型列表 |
| `INVALID_INTERACTION_REQUEST` | 字段、类型、限制或未知字段错误 | 按 `field/issues` 和实时 Schema 修正 |
| `ACTIVE_BLOCKING_INTERACTION_EXISTS` | 已有活动阻塞卡 | 读取状态，显式替换或取消 |
| `INTERACTION_NOT_FOUND` | 不存在或不属于当前范围 | 不猜 ID；读取当前状态 |
| `INTERACTION_NOT_PENDING` | 已终态 | 停止重复提交/取消，读取状态 |
| `INTERACTION_VERSION_CONFLICT` | 提交版本陈旧 | 刷新 REST 后由客户基于当前卡重试 |
| `INVALID_SELECTION` | 选项不存在、重复或数量越界 | 刷新卡片，不信任客户端标签 |
| `SUPPLEMENT_REQUIRED` | 必填补充为空 | 保留选择并提示补充 |
| `REQUIRED_ANSWER_MISSING` | 问答卡必填 item 为空或未提交 | 保留已填内容并定位缺失项 |
| `ANSWER_TOO_LONG` | 某项答案超过该 item 的 `max_length` | 缩短对应答案后重试 |
| `INVALID_ANSWER_REFERENCE` | item 引用未知、重复、缺失或值类型错误 | 刷新卡片并按持久化 ID/问题重新提交 |
| `IDEMPOTENCY_CONFLICT` | 同一稳定身份承载不同内容 | 新逻辑动作使用新 revision/key |
| `PLATFORM_OPERATION_UNCONFIRMED` | 未能确认平台结果 | 读取状态后用原身份重试，不声称卡片存在 |

错误响应会提供 `retryable`，并在适用时提供 `field`、`issues`、`guidance`。不得把内部路径、密钥或异常文本展示给 Agent。

## 10. 责任边界

- 请求符合本文而 DClaw 的校验、持久化、状态、渲染、输入锁定、提交解析或续接不符合契约：DClaw 缺陷。
- DClaw 按契约执行，而 Agent 选错组件、把可枚举问题降级为问答、把开放问题伪装成不完整选项、提供错误业务选项、错误设置必填、错误使用推荐/默认、错误解释结构化答案或重复提问：Agent 编排缺陷。
- 纯样式调整不得要求 Agent 改调用逻辑。
- 新增能力通过目录和新的可选能力发布；已有 v1 语义不就地改变。
