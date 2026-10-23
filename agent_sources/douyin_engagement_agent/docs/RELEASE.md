# 发布规格

## 发布身份

- Agent：`douyin-engagement-agent`
- 版本：1.0.0
- 包类型：`super_expert`
- 标准：`dclaw.super-agent-development` 1.12
- DevKit 要求：1.1.0
- Git commit：密封时填写已推送到 `origin/main` 的源提交
- 签名者：密封时填写平台已入驻的 `signer_id`

## 组件与能力

本发布只有密封超级专家，不含业务服务和本地能力包。能力清单为：

1. `workspace.turn.orchestrate/1`
2. `agent.execute`
3. `session.context`
4. `runtime.trace`
5. `runtime.complete`
6. `runtime.fail`

本地助手模式为 `none`。最终 `capability_digest`、`content_digest`、ZIP SHA-256、
公钥指纹、release ID 和 installation ID 必须由官方 DevKit与目标平台产生后填写，
禁止手工推断。

## 自动验证记录

验证日期：2026-10-23（Asia/Shanghai）。

```text
.venv/bin/python -m pytest agent_sources/douyin_engagement_agent/tests -q
31 passed in 0.09s

.venv/bin/python -m compileall -q agent_sources/douyin_engagement_agent/agent
passed

uvx ruff check agent_sources/douyin_engagement_agent/agent \
  agent_sources/douyin_engagement_agent/tests
All checks passed!

git diff --check
passed
```

Ruff 通过 `uvx` 隔离运行。项目虚拟环境未安装 Flake8。官方 DevKit 校验和独立
验签因目标入口 404 尚未执行。

## 密封前置条件

1. 目标 DClaw 发布 `/api/super-agent-support/developer-kit` 与 `v1.zip`。
2. 核对元数据中的 DevKit 版本和 ZIP SHA-256。
3. 平台已登记一个允许签发 `super_expert` 的稳定 `signer_id`。
4. 对应 Ed25519 私钥只在受控发布环境中可用，不进入仓库或聊天。
5. `origin/main` 已包含待发布源码，且本项目没有未提交发布修改。

## 官方 DevKit 构建与验证

以下命令必须在不含 DClaw 服务端源码的干净目录执行，路径由发布人员替换：

```bash
python dclaw_agent_devkit.py contracts
python dclaw_agent_devkit.py digest \
  --manifest /clean/douyin_engagement_agent/manifest.template.json \
  --write
python dclaw_agent_devkit.py validate \
  --source /clean/douyin_engagement_agent/agent \
  --manifest /clean/douyin_engagement_agent/manifest.template.json
python dclaw_agent_devkit.py build \
  --source /clean/douyin_engagement_agent/agent \
  --manifest /clean/douyin_engagement_agent/manifest.template.json \
  --private-key /secure/release-private-key.b64 \
  --output /secure/release/douyin-engagement-agent-1.0.0.zip
python dclaw_agent_devkit.py verify \
  --package /secure/release/douyin-engagement-agent-1.0.0.zip \
  --public-key /secure/release-public-key.b64
```

验签后列出 ZIP 文件，确认只有 manifest、signature 和 `agent/` 发布文件，且不含
`.env`、密钥、Cookie、日志、缓存、测试账号、客户内容、`workspace/` 或 `tests/`。

## 管理员上传说明

1. 登录目标 DClaw 管理后台，进入“设置 -> 密封 Agent”。
2. 上传独立验签通过的 `douyin-engagement-agent-1.0.0.zip`。
3. 核对 `agent_id`、版本、签名者、`content_digest`、`capability_digest` 与本记录一致。
4. 打开授权预览，确认只有上列六项基础能力且没有 `local.*`；有任何额外能力则取消。
5. 整体接受安装授权并记录 installation ID。
6. 激活 1.0.0，确认运行时验证成功且状态为 `active`。
7. 使用测试客户从客户端执行健康检查、评论树、归因、私信回复和线索判断冒烟。
8. 连续执行三个不同真实任务，其中至少一个覆盖无归因或可恢复失败；记录脱敏输入、
   产物/输出校验、trace ID 和操作者。

上传成功、授权成功、激活成功和真实验收成功必须分别记录，任何一步都不能代替下一步。

## 回滚

若主流程失败、错误率异常、证据串会话、trace 无法定位或新版本不能读取受支持状态，
立即重新激活上一发布版。首个密封版本无可回滚包时停用该发布，并恢复现有普通 Agent
与 Bot Server 配置。密封 ZIP、上一版本和验签公钥必须保留。

## 当前状态

| 状态 | 结果 | 证据/阻塞 |
|---|---|---|
| `source-complete` | yes | 独立目录测试、编译、静态检查和发布内容扫描通过 |
| `sealed` | blocked | 目标官方 DevKit 入口 404；未提供已入驻签名者私钥 |
| `uploaded` | not started | 依赖签名 ZIP |
| `granted` | not started | 依赖上传 |
| `active` | not started | 依赖整体授权 |
| `e2e-verified` | not started | 依赖激活与三个真实任务 |

## 已知限制

- 源材料未给出所有时间间隔/分散度字段的机器合同，详见 `SOURCE_BEHAVIOR_SPEC.md`。
- 归因改为超级专家内部模型判断，不再使用 Jev；真实阈值校准必须在受控账号验收。
- 当前目标环境尚未发布标准要求的官方 DevKit 入口。
