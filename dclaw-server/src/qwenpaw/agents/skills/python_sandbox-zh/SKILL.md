---
name: python_sandbox
description: "当用户需要执行 Python 代码进行数据分析、文件生成、数学计算、图表绘制等任务时使用此 skill。提供安全的代码执行环境，支持自动安装 pip 依赖，自动保存 matplotlib 图表。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🐍"
    requires: {}
---

# Python 代码沙箱 (Python Sandbox)

本 skill 提供安全的 Python 代码执行环境，适用于数据分析、文件处理、数学计算、图表生成等场景。

## 基本用法

```json
{
  "code": "import pandas as pd\ndf = pd.read_csv('data.csv')\nprint(df.describe())",
  "install_packages": "pandas"
}
```

## 自动安装依赖

通过 `install_packages` 参数指定需要的 pip 包，多个包用逗号分隔：

```json
{
  "code": "...",
  "install_packages": "pandas,matplotlib,openpyxl,seaborn"
}
```

已安装的包会自动跳过，不会重复安装。

## 数据分析示例

```json
{
  "code": "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.read_csv('sales.csv')\ndf.groupby('category')['revenue'].sum().plot(kind='bar')\nplt.title('Revenue by Category')\nplt.tight_layout()",
  "install_packages": "pandas,matplotlib"
}
```

matplotlib 图表会自动保存为 PNG 文件并返回路径。

## 文件生成示例

```json
{
  "code": "from openpyxl import Workbook\nwb = Workbook()\nws = wb.active\nws.append(['Name', 'Score'])\nws.append(['Alice', 95])\nws.append(['Bob', 87])\nwb.save('report.xlsx')\nprint('[GENERATED_FILE] report.xlsx')",
  "install_packages": "openpyxl"
}
```

## 内置变量

- `WORKSPACE_DIR`: 当前工作空间目录路径，代码在此目录下执行

## 注意事项

- 代码在工作空间目录下执行，可以读写该目录中的文件
- 默认超时时间为 120 秒，可通过 `timeout` 参数调整
- 输出超过 8000 字符会被截断
- matplotlib 图表会自动设置非交互模式并保存
- 使用 `print('[GENERATED_FILE] path')` 标记生成的文件
