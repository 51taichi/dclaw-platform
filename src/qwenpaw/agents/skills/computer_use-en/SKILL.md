---
name: computer_use
description: "Use this skill when the user needs desktop automation. Includes: taking screenshots to see the current state, clicking/double-clicking/right-clicking at coordinates, typing text, pressing keys and key combinations, scrolling, and dragging elements. Works with any desktop application."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "🖥️"
    requires:
      pip: "pyautogui mss pyperclip"
---

# Desktop Automation (Computer Use)

This skill provides full desktop automation, allowing the AI to control any application on the user's computer just like a human would.

## Core Workflow

**Screenshot → Analyze → Act → Screenshot → Verify**

1. Take a `screenshot` to see the current screen state
2. Analyze UI element positions in the screenshot
3. Perform mouse/keyboard actions
4. Take another screenshot to verify the result
5. Decide next action based on the result

## Available Actions

### Screenshot

```json
{"action": "screenshot"}
```

### Mouse Click

```json
{"action": "click", "x": 500, "y": 300}
{"action": "double_click", "x": 500, "y": 300}
{"action": "right_click", "x": 500, "y": 300}
```

### Type Text

```json
{"action": "type", "text": "Hello World", "x": 500, "y": 300}
```

### Press Key / Hotkey

```json
{"action": "press", "key": "enter"}
{"action": "hotkey", "hotkey": "ctrl+c"}
```

### Scroll

```json
{"action": "scroll_up", "scroll_amount": 5}
{"action": "scroll_down", "x": 500, "y": 300}
```

### Utilities

```json
{"action": "get_screen_size"}
{"action": "get_mouse_position"}
```

## Safety

- Always screenshot before critical operations (delete, send, etc.)
- Always screenshot after to verify the result
- Ask for user confirmation before irreversible actions
- FAILSAFE is enabled: move mouse to top-left corner to abort

## Dependencies

```bash
pip install pyautogui mss pyperclip
```
