---
name: python_sandbox
description: "Use this skill when the user needs to execute Python code for data analysis, file generation, math computation, chart plotting, etc. Provides a safe execution environment with automatic pip dependency installation and matplotlib chart saving."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🐍"
    requires: {}
---

# Python Code Sandbox

This skill provides a safe Python code execution environment for data analysis, file processing, computation, and chart generation.

## Basic Usage

```json
{
  "code": "import pandas as pd\ndf = pd.read_csv('data.csv')\nprint(df.describe())",
  "install_packages": "pandas"
}
```

## Auto-install Dependencies

Use `install_packages` to specify pip packages (comma-separated):

```json
{
  "code": "...",
  "install_packages": "pandas,matplotlib,openpyxl"
}
```

## Built-in Variables

- `WORKSPACE_DIR`: Current workspace directory path

## Notes

- Code runs in the workspace directory
- Default timeout: 120 seconds
- Output truncated at 8000 characters
- matplotlib charts auto-saved as PNG
- Mark generated files with `print('[GENERATED_FILE] path')`
