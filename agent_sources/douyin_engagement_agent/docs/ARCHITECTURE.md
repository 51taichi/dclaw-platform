# 架构规格

## 交付形态

仅交付密封超级专家。无业务服务、无本地能力包、无本地助手要求。

```text
DClaw 可信请求
  -> runtime.py 确定性外壳
  -> agent.execute 生成业务候选
  -> contracts.py 严格校验
  -> runtime.complete 或 runtime.fail
```

## 能力放置

| 能力 | 所有者与位置 | 理由 |
|---|---|---|
| 协议解析、操作路由、输出校验 | 开发方，超级专家 | 抖音业务专属规则 |
| 评论树与私信文案生成 | 开发方，超级专家模型提示 | 业务语义判断 |
| 候选任务归因与阈值门禁 | 开发方，超级专家 | 任务语义、阈值和完成判据均属业务规则 |
| 会话上下文、模型执行、追踪和终结 | DClaw 公共 Host | 所有超级专家共用的稳定合同 |
| Bot 调度、额度、执行与审计 | 移植包既有外部调用方 | 不属于专家输出能力 |

旧普通 Agent 依赖的 `jev-private-routing` 插件不进入目标架构。归因候选由模型判断，
候选 ID、概率阈值和最小置信差由确定性外壳复核，因此平台无需理解抖音任务。

## 数据、凭证与成本

- 输入只来自本轮可信 DClaw 请求；用户业务 JSON 始终视为不可信数据。
- 无长期凭证、Cookie、第三方 Token 或客户文件。
- 无开发方业务服务和第三方 API 费用；成本只有 DClaw 提供的模型调用。
- trace 只记录操作、尝试次数和稳定错误码，不记录客户原文。
- 不使用进程内对象作为持久事实；每轮无外部副作用。

## 能力清单

发布版只声明：

- `workspace.turn.orchestrate/1`
- `agent.execute`
- `session.context`
- `runtime.trace`
- `runtime.complete`
- `runtime.fail`

不声明 `interaction`、`aigc`、`local_execution` 或任何 `local.*` 能力。本地助手模式为
`none`。能力依赖方向只为 DClaw Host 到密封专家，不导入 DClaw 服务端或插件代码。

## 兼容矩阵

| 组件 | 要求 |
|---|---|
| 开发标准 | 1.12 |
| Super Agent DevKit | 1.1.0 |
| DClaw | 至少 1.1.10，且含标准 1.12 对应合同 |
| runtime / runtime_host | 1 / 1 |
| Windows 客户端 | 无特殊要求 |
| Runner | 不需要 |

目标环境是否实际满足这些要求，必须由官方 DevKit 元数据和管理员上传结果确认。
