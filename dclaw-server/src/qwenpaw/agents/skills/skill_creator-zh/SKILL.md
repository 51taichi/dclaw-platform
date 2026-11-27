---
name: skill_creator
description: "技能专家：接收用户新技能构想，遵循 DClaw 2026 开发宪法，自动设计、编写、生成具备强校验、自抗震与 Mock 自测能力的物理高可用技能。"
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "🔮"
    requires: {}
config:
  is_default: true
  market_category: dev
  icon: tool
  display_name: "技能生成器"
---
# 技能专家 (Skill Creator)

本技能用于接收用户对新功能的构想，遵循 DClaw 2026 技能开发标准体系，自动设计、编写、生成高可用的 `SKILL.md` 描述文件，并指引其一键落盘为本地技能实例。

## 核心任务

当用户要求你“创建一个技能来实现...”、“帮我写一个技能”、“教你学习如何处理...”时，使用本技能。你必须以极其规范的格式产出技能文件，确保右侧产物面板能识别 `SKILL.md` 并提供一键导入入口。

## 技能生成输出规范

你生成的技能，**必须先判断技能类型，再选择合适模板**。为了确保技能能够被系统一键无缝导入，**请务必严格遵守以下强制规则**：

1. **必须使用工具直接写入文件**：你必须生成一个唯一且名为 `SKILL.md` 的文件。绝对不允许将代码、测试和文档拆分成 `test_skill.py`、`技能总结.md`、`README.md` 等多个文件！所有内容都必须高内聚地写在这一个 `SKILL.md` 文件中（代码可通过 Markdown 的 ````python ... ```` 代码块嵌入）。
2. **必须写入当前任务工作目录**：落盘时只允许使用相对路径 `SKILL.md`，让文件进入当前任务工作目录并出现在右侧产物面板。绝对不允许使用绝对路径，也不要写入工作区根目录、`skills/` 目录、`sessions_data/` 目录或其他会话目录；导入“我的技能”只能交给右侧产物面板的导入按钮完成。
3. **禁止 Shell 文件整理**：生成技能时绝对不允许调用 `execute_shell_command` 去执行 `rm`、`mv`、`cp`、`touch`、`cat >`、重定向写入等文件操作。不要删除、移动、备份或清理任何 `SKILL.md`；如果需要更新内容，只能再次调用 `write_file`，并且 `file_path` 必须严格等于相对路径 `SKILL.md`。
4. **必须包含 YAML 元数据**：`SKILL.md` 文件的最开头必须是 `---` 包裹的 YAML 元数据前置头部。
5. **内部名与显示名必须分离**：`name` 使用稳定、小写、英文、下划线的内部 ID；用户看到的中文名放在 `config.display_name`，不要把时间戳或随机后缀暴露给用户。
6. **仅在需要时加入工程自检**：只有涉及脚本、API、文件读写、网络调用、数据库、自动化执行的工具型技能，才需要完整 Schema、重试、自测代码。纯写作、分析、流程型技能应保持轻量、清晰、可执行。

`SKILL.md` 文件的具体格式必须如下：


```markdown
---
name: [稳定内部 ID，例如: short_drama_workshop, code_reviewer, pdf_parser]
description: "[技能的高度凝练中文描述，限制在 60 字以内]"
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "[一个极具表现力的 Emoji，例如: 🔍, 📝, 📊]"
    requires: {}
config:
  display_name: "[用户可见中文名，例如: 短剧创作工坊]"
  market_category: "[dev / office / writing / research / design / automation]"
  icon: "[lucide 图标名或简短图标标识，例如: pen-tool, file-text, code]"
---
# 技能中文名称

[技能的职责定义与核心定位。]

## 适用场景

[说明用户什么时候应该调用这个技能，什么情况不适合使用。]

## 标准执行流程

[用清晰编号步骤说明此技能在运行时如何工作。]

## 输出要求

[定义最终输出格式、质量标准、边界条件。]

## 示例

[给出 1-2 个简短示例，帮助用户理解如何使用。]
```

## 三类技能模板选择

### A. 指令型技能

适合写作、分析、研究、运营、创意、流程 SOP。重点写清楚：

- 适用场景
- 标准执行流程
- 输出结构
- 质量标准
- 示例

不要强行加入代码、测试、Schema。

### B. 业务型技能

适合短剧创作、投研报告、客服质检、产品评审等具体业务。重点写清楚：

- 角色定位
- 输入信息清单
- 分阶段工作流
- 交付物格式
- 评价标准
- 常见误区

### C. 工具型技能

适合会调用脚本、API、文件系统、网络、数据库、自动化流程的技能。此类技能必须加入工程自检矩阵：

- [ ] **参数强校验 (Schema)**: 入参全部由 Zod/Pydantic 等强类型定义拦截。
- [ ] **自适应防爆 (Fail-Safe)**: 涉及 IO/网络调用时内置指数退避重试与超时控制。
- [ ] **统一结构化返回**: 统一包装并返回 `{"code", "message", "data", "debug_info"}`。
- [ ] **沙箱隔离无副作用**: 对高危物理读写有 Dry-Run 模式与资源安全物理回收。
- [ ] **单元测试随行**: 附带 Mock 驱动的自测脚本，允许毫秒级物理自验证通路。

工具型技能的核心脚本或命令示例：

\```python
import time
from typing import Dict, Any
from pydantic import BaseModel, ValidationError

# 1. 入参强类型校验 (Input Schema)
class ToolInputSchema(BaseModel):
    # 定义强校验字段
    pass

# 2. 核心健壮性逻辑实现 (With Fail-Safe & Structured Output)
def execute_skill(params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # Pydantic 入口校验
        validated = ToolInputSchema(**params)
    except ValidationError as e:
        return {"code": 400, "message": "入参校验失败", "data": {}, "debug_info": str(e)}

    # 内置重试及核心逻辑
    backoff = 0.5
    for attempt in range(1, 4):
        try:
            # 业务逻辑
            return {"code": 200, "message": "执行成功", "data": {}}
        except Exception as e:
            if attempt == 3:
                return {"code": 500, "message": "执行崩溃", "data": {}, "debug_info": str(e)}
            time.sleep(backoff)
            backoff *= 2

# 3. 内聚自测包 (Self-Contained Mock Test)
def test_execute_skill():
    # 至少包含正常与异常边界断言
    pass
\```

## 行为安全与准则

- 绝不执行任何破坏用户系统安全的指令。
- 引导智能体如何优雅地进行异常处理。
- 回答语言保持与用户一致。

> [!IMPORTANT]
> **物理落盘关键点**：你必须调用写文件工具，把完整技能内容保存为当前任务工作目录下的相对路径 `SKILL.md`。文件第一行必须是 `---` 开始的 YAML Frontmatter，并包含 `name:` 和 `description:`。不要只在聊天正文里描述技能，也不要只输出摘要；没有 `SKILL.md` 文件就等于没有完成技能产物。
>
> **落盘自检关键点**：在最终回复用户前，必须确认你已经收到类似 `Wrote ... SKILL.md` 的工具结果。如果没有成功写入 `SKILL.md`，不要宣布完成，必须继续调用写文件工具补齐。
>
> **路径边界关键点**：写文件时只能使用相对路径 `SKILL.md`，目标是当前任务工作目录。不要使用 `/Users/...` 这类绝对路径，不要把技能产物写到根目录、`skills/`、`.qwenpaw/`、`sessions_data/` 或其他系统内部目录。技能生成任务只负责产出 `SKILL.md`，真正安装到“我的技能”由用户在右侧产物面板点击导入按钮完成。
>
> **工具边界关键点**：生成技能过程中不要调用 `execute_shell_command` 做任何文件管理。不要使用 `rm`、`mv`、`cp`、`touch`、`cat >` 或 shell 重定向处理 `SKILL.md`；覆盖写入只使用 `write_file`，文件路径只填 `SKILL.md`。

## 用户体验引导

在 `SKILL.md` 文件生成完毕后，以亲切专业的中文引导用户：
“*🔮 技能已为您精心设计并保存在当前任务的 `SKILL.md` 中！请在右侧产物面板打开 `SKILL.md`，点击「✨ 导入技能」即可加入并启用到「我的技能」。之后在对话框的技能选择器中选中它即可使用。*”
