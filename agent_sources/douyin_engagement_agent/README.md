# 抖音互动超级专家

本目录是从普通 DClaw Agent 迁移得到的密封超级专家项目。发布目标是 `agent/` 与
`manifest.template.json`；`workspace/` 只保留为源行为证据，不进入密封包。

超级专家接受七种严格操作：健康检查、评论剧本生成、剧本修复、依赖丢失恢复、
私信任务归因、私信回复和线索规则判断。它只产出经过确定性校验的 JSON，不直接
操作抖音，不管理 Bot、配额或调度，也不宣称消息已经送达。

全部业务判断均在密封超级专家内完成。发布版不依赖 Jev 平台插件、业务 MCP、
本地能力包或 DClaw 本地助手，也不声明任何 `local.*` 能力。

## Local validation

```bash
python -m pytest tests -q
```

密封、签名和独立验签必须使用目标 DClaw 下载的官方 Super Agent DevKit。禁止手工
打 ZIP，也禁止从 DClaw 服务端仓库复制 DevKit 脚本。具体命令与管理员流程见
`docs/RELEASE.md`。

## Operator handoff

管理员只上传官方 DevKit 生成且验签通过的 `super_expert` ZIP，并整体核对六项基础能力。
无需安装本地助手或 Jev 插件。上传、授权、激活和真实任务验收是独立状态，不能用
源码测试替代。
