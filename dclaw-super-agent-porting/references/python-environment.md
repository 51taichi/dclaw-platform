# 诊断脚本的 Python 环境

本 Skill 的 v3–v6 关联 ID 查询、搜索和离线摘要使用完整 Draft 2020-12 Schema 与日期格式校验，需要 `jsonschema[format]>=4.20,<5`。官方 DevKit 的 bootstrap 环境可能只安装其自身依赖；不能据此推定它也包含本 Skill 的诊断依赖。系统 Python 缺包或指向错误解释器是本地环境问题，无须申请新的平台合同。

在当前 Agent 项目内、待密封 Agent 输入目录之外选一个持久工具目录。已有合规隔离环境时可复用；否则建立虚拟环境并安装依赖。以下变量由 Codex 按当前开发者的实际路径填写，不使用 Skill 维护者的目录。

Windows PowerShell：

```powershell
$toolDir = '<当前 Agent 项目的工具目录>'
$skillDir = '<本 Skill 的实际安装目录>'
New-Item -ItemType Directory -Force -Path $toolDir | Out-Null
python -m venv (Join-Path $toolDir '.venv')
$python = Join-Path $toolDir '.venv\Scripts\python.exe'
& $python -m pip install 'jsonschema[format]>=4.20,<5'
& $python (Join-Path $skillDir 'scripts\check_diagnostics_env.py')
```

macOS/Linux：

```sh
tool_dir='<current Agent project tool directory>'
skill_dir='<installed Skill directory>'
mkdir -p "$tool_dir"
python3 -m venv "$tool_dir/.venv"
python="$tool_dir/.venv/bin/python"
"$python" -m pip install 'jsonschema[format]>=4.20,<5'
"$python" "$skill_dir/scripts/check_diagnostics_env.py"
```

自检成功后，后续运行本 Skill 的 `runtime_diagnostics_with_login.py`、`summarize_runtime_diagnostics.py` 及相关测试都用**同一个 `$python` / `$tool_dir/.venv/bin/python`**，显式传入已核验正式 DevKit 的路径；不要再用裸 `python`、系统 Python 或只含 DevKit 自身依赖的另一环境。在线查询仍须在可交互终端运行，并按原规则保存回执。测试使用正式 DevKit Schema 时，先把 `DCLAW_DEVKIT_ROOT` 设为其 `devkit` 目录，再以同一解释器运行 `-m unittest discover -s <Skill>/tests`。

如果自检显示缺包、版本不符或日期格式校验不可用，只修复当前隔离环境并重跑自检；依赖安装受网络或本机策略阻断时，使用开发方批准的软件源或离线包。只有解释器和依赖已通过自检、正式材料也已核对，而目标实例的接口或 Schema 仍有证据显示缺失或不一致时，才按平台合同问题处理。
