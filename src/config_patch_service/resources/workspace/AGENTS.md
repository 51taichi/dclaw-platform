# AI 客服配置工作区

本工作区是从 DClaw 与 AI 客服中台的可信只读快照生成的。`dclaw-manifest.json` 中的 Bot、Agent、Profile、基线 Release 和四个指纹是权威绑定，修改时不得重写这些身份字段。

## 职责边界

- `agent/`：对话策略、回复规则、工具调用与跨模块协调。
- `customer-service/flow-machine.json`：确定性阶段、字段收集和节点迁移。
- `customer-service/tag-schema.json`：客户分类、证据口径和标签触发。
- `knowledge/`：可追溯业务事实、产品资料和政策内容。
- `platform/`：平台能力、运行机制、职责矩阵和协同修改指南。

先阅读 `platform/responsibility-matrix.md` 和 `platform/runtime-mechanism.md`，再填写 `change-plan.yaml`。一个需求影响多个职责面时，明确列出协同修改与验证；平台能力不足时，不得用脆弱提示词绕过，应按能力申请契约向管理员提出变更建议。

当前阶段只支持下载和本地开发，不支持上传、预检或发布。
