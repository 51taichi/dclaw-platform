---
name: skill_creator
description: "Skill Creator: Professional skill architect that designs, writes, and generates valid SKILL.md packages conforming to DClaw 2026 standards, with strict validation, resilient failures, and self-contained tests."
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "🔮"
    requires: {}
config:
  is_default: true
  market_category: dev
  icon: tool
  display_name: "Skill Creator"
---
# Skill Creator

This skill is designed to capture users' functional conceptualizations, follow the DClaw 2026 specification, and automatically design, write, and generate highly available `SKILL.md` files that can be instantly hot-imported as local running skill instances.

## Core Responsibilities

When a user requests to "create a skill for...", "teach you how to do...", or "build a tool for...", activate this skill. You must generate the output in a strict structural format so the frontend streaming regular expression scanner can parse the metadata and display the magic import card flawlessly.

## Skill Output Specifications

Every skill you generate **must strictly adhere to the 2026 Skill Golden Standards**, and must start and encompass the following YAML frontmatter block (enclosed in `---` lines) to ensure the regular expression parser triggers successfully:

Before writing the file, follow this output-location rule exactly: write one file at the relative path `SKILL.md` in the current task workspace so it appears in the artifact panel. Do not use an absolute path, and do not write generated skills to the workspace root, `skills/`, `sessions_data/`, or another session directory. The task should only create the artifact; installing it into "My Skills" must be done through the import button in the artifact panel.

Do not use `execute_shell_command` for skill artifact file management. Never run `rm`, `mv`, `cp`, `touch`, `cat >`, shell redirection, or backup/cleanup commands against `SKILL.md`. If the artifact needs to be updated, call `write_file` again with `file_path` exactly equal to the relative path `SKILL.md`.

```markdown
---
name: [lower_case_identifier_with_underscores, e.g. code_reviewer, pdf_parser]
description: "[Highly condensed description of what this skill does, under 100 characters]"
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "[A single expressive emoji, e.g., 🔍, 📝, 📊]"
    requires: {}
---
# Skill Name

[Detailed definition and purpose of the skill.]

## 2026 Skill Engineering Self-Defense Checklist

- [ ] **Input Type Guard (Schema)**: Strict input validation using Zod/Pydantic schemas.
- [ ] **Resilient Failure (Fail-Safe)**: Built-in Exponential Backoff retries and Timeout controls.
- [ ] **Unified Standard Output**: Consistent JSON structure: `{"code", "message", "data", "debug_info"}`.
- [ ] **Sandbox & No Side-Effects**: Path traversal block and proper resource closing inside finally blocks.
- [ ] **Self-Contained Mock Tests**: Embedded mock assertions for millisecond-level local auto-verification.

## Standard Workflow

[Step-by-step instructions on how the agent should execute this skill.]

## Core Commands & High-Availability Scripts

The scripts or commands you output must implement the above guidelines natively (e.g., Python script with schema verification and testing):

\```python
import time
from typing import Dict, Any
from pydantic import BaseModel, ValidationError

# 1. Strict Input Schema
class ToolInputSchema(BaseModel):
    # Define fields
    pass

# 2. Resilient Execution & Structured Output
def execute_skill(params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        validated = ToolInputSchema(**params)
    except ValidationError as e:
        return {"code": 400, "message": "Validation failed", "data": {}, "debug_info": str(e)}

    # Retries and core logic
    backoff = 0.5
    for attempt in range(1, 4):
        try:
            # Business logic
            return {"code": 200, "message": "Success", "data": {}}
        except Exception as e:
            if attempt == 3:
                return {"code": 500, "message": "Execution crashed", "data": {}, "debug_info": str(e)}
            time.sleep(backoff)
            backoff *= 2

# 3. Self-Contained Mock Test Suite
def test_execute_skill():
    # Assertions for both normal and abnormal bounds
    pass
\```

## Security & Guardrails

- Never execute destructive or harmful scripts on the user's local operating system.
- Guide the agent on how to handle failures gracefully.
- Match response language to user query context.
```

> [!IMPORTANT]
> **Physical Artifact Rule**: You MUST call the file-writing tool and save the complete generated skill to the relative path `SKILL.md` in the current task workspace. The first line of that file MUST be `---`, and the YAML Frontmatter MUST include both `name:` and `description:`. Do not merely describe or summarize the skill in the chat response; without a `SKILL.md` artifact, the skill creation task is incomplete.
>
> **Write Verification Rule**: Before sending the final user-facing response, verify that you received a tool result similar to `Wrote ... SKILL.md`. If the write did not succeed, do not claim completion; call the file-writing tool again and fix the artifact first.
>
> **Path Boundary Rule**: Write the generated skill only with the relative path `SKILL.md` in the current task workspace. Never use `/Users/...` or any other absolute path, and never write generated skill artifacts into the workspace root, `skills/`, `.qwenpaw/`, `sessions_data/`, or another system/internal directory. Installing it into “My Skills” is handled by the user through the artifact panel import action.
>
> **Tool Boundary Rule**: Do not call `execute_shell_command` to manage skill files. Do not use `rm`, `mv`, `cp`, `touch`, `cat >`, or shell redirection for `SKILL.md`; only use `write_file` with `file_path` set to `SKILL.md`.

## User Guidance

Upon completing the skill output, friendly instruct the user:
"*🔮 I've designed the skill and saved it as `SKILL.md` in this task's artifacts. Open `SKILL.md` in the right artifact panel and click the import action to add and enable it in My Skills. After that, select it from the chat skill picker whenever you want to use it.*"
