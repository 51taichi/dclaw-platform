# 平台能力与工具缺口

## SA-TOOLING-001：目标环境缺少官方 DevKit 下载入口

- 申请方：抖音互动超级专家开发方
- Agent：`douyin-engagement-agent`
- 目标平台：`http://192.168.0.5:4312`
- 当前流程：按标准 1.12 第 21.1 节获取与目标合同匹配的 DevKit 1.1.0。
- 阻塞位置：`GET /api/super-agent-support/developer-kit` 返回 HTTP 404。
- 已尝试能力：标准规定的元数据入口；未读取、复制或导入 DClaw 服务端源码。
- 为什么业务侧无法安全实现：能力摘要、Schema 校验、规范化 manifest、内容摘要和
  Ed25519 签名必须与平台验收实现一致，开发方自制工具不能替代官方 DevKit。
- 通用语义：向所有超级 Agent 开发方提供同一版本化 DevKit 元数据与下载物。
- 建议处理：部署并启用 `dclaw.super-agent-support` 1.3.0，发布 DevKit 1.1.0 入口，
  返回版本与 ZIP SHA-256，并确认最低 DClaw 版本。
- 验收：元数据 200；ZIP 摘要匹配；`contracts`、`digest`、`validate`、`keygen`、
  `build`、`verify` 均可在不含服务端源码的干净目录运行。

该项是标准已覆盖但目标环境未发布的工具能力，不申请新增业务能力，也不直接修改
DClaw 平台。平台评审建议分类为 `covered`（需部署）或 `platform_bug`。
