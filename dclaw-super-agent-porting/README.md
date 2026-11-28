# DClaw 超级专家开发 Skill（EC 工作区）

本目录是当前 `dclaw-agentscope2-lab` monorepo 中的独立维护版。它以原 Skill 候选提交 `f4c62fac` 为基线；源码指导已更新到标准 2.73、Developer Pack 1.10.52 和 DevKit 1.9.37，目标 EC 的认证版本仍须单独核对。当前版本为 `v1.9.19`。本目录不使用旧 Skill 仓库或用户级安装副本作为更新源，也不包含其他专家的源码交接包。

## 工作入口

在这个工作区开发、修复或发布超级专家时，先读根目录与 `超级专家/` 下的 `AGENTS.md`、[主 Skill](SKILL.md)、[知识库](references/knowledge-base.md) 和平台当前标准。按专家项目的实际状态走 `new-development` 或 `optimization`；节点记录、源码、密封输入和发布回执留在该专家自己的目录。Skill 中的相对链接均相对于本目录。

EC 客户端入口是 `https://dclaw.rouhigh.com`。陆羽 1.1.34 的正式工具链和发布回执使用 `https://api.rouhigh.com`，与当前专家构建器的来源检查一致。正式标准、DevKit、能力目录和发布状态仍须从实际目标实例认证读取；本地源码版本不能代替部署回执。本仓库的 Skill 维护不向阿里云上传或部署。

## 维护与验证

Skill、平台和专家源码共用本仓库的 `main`。修改前检查共享工作树，提交时只暂存本任务文件或 hunk，遵守根目录 `AGENTS.md` 的 Git 串行规则。平台公开合同变化时，在同一任务更新 Skill 本体和受影响参考文件，递增版本并记录依据与旧专家兼容结论；交接说明不能代替 Skill 更新。卡点先在专家项目内记录，脱敏后由本工作区维护方审核，通用修订直接提交本仓库；不得向旧 Skill 仓库发 Issue、PR 或推送。

校验需要隔离 Python 环境中的 `pytest`、`PyYAML` 和 `jsonschema[format]>=4.20,<5`。在当前 Mac 上可运行：

```bash
uv venv /tmp/dclaw-skill-test-venv
uv pip install --python /tmp/dclaw-skill-test-venv/bin/python 'pytest>=8.3' 'PyYAML>=6' 'jsonschema[format]>=4.20,<5' 'requests>=2.31'
/tmp/dclaw-skill-test-venv/bin/python /Users/moxi/.codex/skills/.system/skill-creator/scripts/quick_validate.py dclaw-super-agent-porting
/tmp/dclaw-skill-test-venv/bin/python -m pytest -q dclaw-super-agent-porting/tests
```

上述路径是当前 Mac 的验证工具位置，其他开发环境按其 Skill Creator 安装位置调整。源码提交不授权构建镜像、上传专家包或部署；具体发布动作须遵守本仓库的部署规则及该专家的发布门槛。

问题与版本记录见[卡点回传](references/blocker-feedback.md)和[版本记录](references/release-notes.md)。
