---
name: computer_use
description: "当用户需要控制桌面进行自动化操作时使用此 skill。包括：截取屏幕截图查看当前状态、在指定坐标点击/双击/右键、输入文本、按键和快捷键组合、滚动页面、拖拽元素等。适用于操控任意桌面应用程序。"
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🖥️"
    requires:
      pip: "pyautogui mss pyperclip"
---

# 桌面自动化操控 (Computer Use)

本 skill 提供完整的桌面自动化能力，让 AI 可以像人类一样操控电脑上的任何应用程序。

## 核心工作流程

**截屏 → 分析 → 操作 → 截屏 → 验证**

1. 首先使用 `screenshot` 获取当前屏幕状态
2. 分析截图中的 UI 元素位置
3. 执行鼠标/键盘操作
4. 再次截屏验证操作结果
5. 根据结果决定下一步操作

## 可用操作

### 截屏

```json
{"action": "screenshot"}
```

截取当前整个屏幕，保存为 PNG 文件并返回路径。这是所有操作的起点。

### 鼠标点击

```json
{"action": "click", "x": 500, "y": 300}
```

在指定坐标执行鼠标左键单击。

```json
{"action": "double_click", "x": 500, "y": 300}
```

双击操作，常用于打开文件或选中文字。

```json
{"action": "right_click", "x": 500, "y": 300}
```

右键点击，用于打开上下文菜单。

### 文本输入

```json
{"action": "type", "text": "你好世界", "x": 500, "y": 300}
```

先点击指定位置，然后输入文本。支持中文输入（通过剪贴板粘贴）。

如果不指定坐标，则在当前光标位置输入：

```json
{"action": "type", "text": "Hello World"}
```

### 按键操作

```json
{"action": "press", "key": "enter"}
```

按下单个按键。常用按键：enter, tab, escape, backspace, delete, space, up, down, left, right, f1-f12

### 快捷键组合

```json
{"action": "hotkey", "hotkey": "ctrl+c"}
```

按下组合键。macOS 上 ctrl 会自动映射为 command。

常用快捷键：
- `ctrl+c` / `ctrl+v` — 复制/粘贴
- `ctrl+a` — 全选
- `ctrl+s` — 保存
- `ctrl+z` — 撤销
- `alt+tab` — 切换窗口
- `ctrl+shift+s` — 另存为

### 滚动

```json
{"action": "scroll_up", "scroll_amount": 5}
```

```json
{"action": "scroll_down", "x": 500, "y": 300, "scroll_amount": 3}
```

在指定位置或当前位置滚动页面。

### 辅助操作

获取屏幕尺寸：

```json
{"action": "get_screen_size"}
```

获取当前鼠标位置：

```json
{"action": "get_mouse_position"}
```

## 安全提醒

- 关键操作前（如删除文件、发送邮件），**必须先截屏确认**当前状态
- 操作后必须**再次截屏验证**结果是否符合预期
- 如果操作可能造成不可逆后果，应先向用户确认
- `pyautogui.FAILSAFE` 已启用：将鼠标移到屏幕左上角可以紧急中断

## 依赖

需要安装以下 Python 包：

```bash
pip install pyautogui mss pyperclip
```

macOS 还需要在"系统设置 → 隐私与安全性 → 辅助功能"中授权终端/Python 应用。
