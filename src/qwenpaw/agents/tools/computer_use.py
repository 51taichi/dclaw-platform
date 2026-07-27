# -*- coding: utf-8 -*-
"""Computer Use tool: keyboard and mouse control for desktop automation.

Provides screenshot capture, mouse clicks, keyboard input, scrolling,
and window management capabilities. Designed to work with vision LLMs
(e.g., Qwen-VL, GPT-4o) for screen-to-action automation loops.
"""

import json
import os
import platform
import time
from typing import Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR


def _tool_error(msg: str) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(
                    {"ok": False, "error": msg},
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
        ],
    )


def _tool_ok(data: dict) -> ToolResponse:
    result = {"ok": True, **data}
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2),
            ),
        ],
    )


def _ensure_pyautogui():
    """Lazy import pyautogui and return it, or raise with install hint."""
    try:
        import pyautogui

        pyautogui.FAILSAFE = True  # Move mouse to corner to abort
        pyautogui.PAUSE = 0.1
        return pyautogui
    except ImportError:
        raise ImportError(
            "computer_use requires 'pyautogui'. "
            "Install with: pip install pyautogui"
        )


def _ensure_mss():
    """Lazy import mss and return it, or raise with install hint."""
    try:
        import mss

        return mss
    except ImportError:
        raise ImportError(
            "computer_use requires 'mss' for screenshots. "
            "Install with: pip install mss"
        )


def _get_screenshot_path() -> str:
    """Generate a unique screenshot path in the workspace directory."""
    base_dir = get_current_workspace_dir() or WORKING_DIR
    return str(base_dir / f"computer_use_screenshot_{int(time.time())}.png")


async def computer_use(
    action: str,
    x: Optional[int] = None,
    y: Optional[int] = None,
    text: Optional[str] = None,
    key: Optional[str] = None,
    hotkey: Optional[str] = None,
    clicks: int = 1,
    button: str = "left",
    scroll_amount: int = 3,
    duration: float = 0.2,
    screenshot_path: str = "",
    interval: float = 0.05,
) -> ToolResponse:
    """Control the desktop: take screenshots, click, type, scroll, and press keys.

    This tool provides full desktop automation capability. Use it to interact
    with any application on the user's desktop by taking screenshots to see
    the current state, then performing mouse/keyboard actions.

    **Workflow**: screenshot → analyze → act → screenshot → verify

    Args:
        action (`str`):
            The action to perform. One of:
            - "screenshot": Capture the current screen state
            - "click": Click at coordinates (x, y)
            - "double_click": Double-click at coordinates (x, y)
            - "right_click": Right-click at coordinates (x, y)
            - "move": Move mouse to coordinates (x, y)
            - "type": Type text at the current cursor position
            - "press": Press a single key (e.g., "enter", "tab", "escape")
            - "hotkey": Press a key combination (e.g., "ctrl+c", "cmd+v")
            - "scroll_up": Scroll up at current position or (x, y)
            - "scroll_down": Scroll down at current position or (x, y)
            - "drag": Drag from current position to (x, y)
            - "get_screen_size": Get the screen dimensions
            - "get_mouse_position": Get current mouse coordinates
        x (`int`, optional):
            X coordinate for mouse actions.
        y (`int`, optional):
            Y coordinate for mouse actions.
        text (`str`, optional):
            Text to type (for "type" action).
        key (`str`, optional):
            Key name to press (for "press" action).
            Examples: "enter", "tab", "escape", "backspace", "delete",
            "up", "down", "left", "right", "space", "f1"-"f12"
        hotkey (`str`, optional):
            Key combination string (for "hotkey" action).
            Use "+" to separate keys. Examples: "ctrl+c", "cmd+v",
            "alt+tab", "ctrl+shift+s"
        clicks (`int`, defaults to 1):
            Number of clicks for click actions.
        button (`str`, defaults to "left"):
            Mouse button: "left", "right", or "middle".
        scroll_amount (`int`, defaults to 3):
            Number of scroll units for scroll actions.
        duration (`float`, defaults to 0.2):
            Duration in seconds for mouse movement animations.
        screenshot_path (`str`, optional):
            Custom path to save screenshot. Auto-generated if empty.
        interval (`float`, defaults to 0.05):
            Interval between keystrokes when typing.

    Returns:
        `ToolResponse`:
            JSON with "ok" status, action details, and optional
            "screenshot_path" for screenshot actions.
    """
    action = (action or "").strip().lower()

    if not action:
        return _tool_error("action is required")

    # ─── Screenshot ───────────────────────────────────────────────────
    if action == "screenshot":
        try:
            mss_module = _ensure_mss()
        except ImportError as e:
            return _tool_error(str(e))

        path = (screenshot_path or "").strip() or _get_screenshot_path()
        if not path.lower().endswith(".png"):
            path += ".png"

        try:
            with mss_module.MSS() as sct:
                sct.shot(mon=0, output=path)
            if not os.path.isfile(path):
                return _tool_error("Screenshot failed: file not created")
            return _tool_ok({
                "action": "screenshot",
                "path": os.path.abspath(path),
                "message": f"Screenshot saved to {path}",
            })
        except Exception as e:
            return _tool_error(f"Screenshot failed: {e!s}")

    # ─── Get Screen Size ──────────────────────────────────────────────
    if action == "get_screen_size":
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))
        size = pag.size()
        return _tool_ok({
            "action": "get_screen_size",
            "width": size.width,
            "height": size.height,
        })

    # ─── Get Mouse Position ───────────────────────────────────────────
    if action == "get_mouse_position":
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))
        pos = pag.position()
        return _tool_ok({
            "action": "get_mouse_position",
            "x": pos.x,
            "y": pos.y,
        })

    # ─── Click Actions ────────────────────────────────────────────────
    if action in ("click", "double_click", "right_click"):
        if x is None or y is None:
            return _tool_error(f"{action} requires x and y coordinates")
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))

        try:
            if action == "double_click":
                pag.doubleClick(x=x, y=y, duration=duration)
            elif action == "right_click":
                pag.rightClick(x=x, y=y, duration=duration)
            else:
                pag.click(
                    x=x,
                    y=y,
                    clicks=clicks,
                    button=button,
                    duration=duration,
                )
            return _tool_ok({
                "action": action,
                "x": x,
                "y": y,
                "message": f"Performed {action} at ({x}, {y})",
            })
        except Exception as e:
            return _tool_error(f"{action} failed: {e!s}")

    # ─── Mouse Move ───────────────────────────────────────────────────
    if action == "move":
        if x is None or y is None:
            return _tool_error("move requires x and y coordinates")
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))
        try:
            pag.moveTo(x=x, y=y, duration=duration)
            return _tool_ok({
                "action": "move",
                "x": x,
                "y": y,
                "message": f"Mouse moved to ({x}, {y})",
            })
        except Exception as e:
            return _tool_error(f"move failed: {e!s}")

    # ─── Drag ─────────────────────────────────────────────────────────
    if action == "drag":
        if x is None or y is None:
            return _tool_error("drag requires target x and y coordinates")
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))
        try:
            start_pos = pag.position()
            pag.moveTo(x=x, y=y, duration=duration, _pause=False)
            pag.mouseDown(button=button)
            time.sleep(0.05)
            pag.moveTo(x=x, y=y, duration=duration)
            pag.mouseUp(button=button)
            return _tool_ok({
                "action": "drag",
                "from_x": start_pos.x,
                "from_y": start_pos.y,
                "to_x": x,
                "to_y": y,
                "message": f"Dragged from ({start_pos.x}, {start_pos.y}) to ({x}, {y})",
            })
        except Exception as e:
            return _tool_error(f"drag failed: {e!s}")

    # ─── Type Text ────────────────────────────────────────────────────
    if action == "type":
        if not text:
            return _tool_error("type action requires text parameter")
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))

        try:
            # Click at position first if coordinates provided
            if x is not None and y is not None:
                pag.click(x=x, y=y, duration=0.1)
                time.sleep(0.1)

            # Use pyperclip for non-ASCII text (Chinese, etc.)
            if any(ord(c) > 127 for c in text):
                try:
                    import pyperclip

                    pyperclip.copy(text)
                    system = platform.system()
                    if system == "Darwin":
                        pag.hotkey("command", "v")
                    else:
                        pag.hotkey("ctrl", "v")
                except ImportError:
                    # Fallback: write each character
                    pag.write(text, interval=interval)
            else:
                pag.write(text, interval=interval)

            return _tool_ok({
                "action": "type",
                "text": text[:100] + ("..." if len(text) > 100 else ""),
                "message": f"Typed {len(text)} characters",
            })
        except Exception as e:
            return _tool_error(f"type failed: {e!s}")

    # ─── Press Key ────────────────────────────────────────────────────
    if action == "press":
        if not key:
            return _tool_error("press action requires key parameter")
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))
        try:
            pag.press(key)
            return _tool_ok({
                "action": "press",
                "key": key,
                "message": f"Pressed key: {key}",
            })
        except Exception as e:
            return _tool_error(f"press failed: {e!s}")

    # ─── Hotkey ───────────────────────────────────────────────────────
    if action == "hotkey":
        if not hotkey:
            return _tool_error("hotkey action requires hotkey parameter")
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))
        try:
            keys = [k.strip() for k in hotkey.split("+")]
            # Normalize common key names
            key_map = {
                "ctrl": "ctrl",
                "control": "ctrl",
                "cmd": "command",
                "win": "win",
                "alt": "alt",
                "shift": "shift",
                "meta": "command" if platform.system() == "Darwin" else "win",
            }
            normalized = [key_map.get(k.lower(), k.lower()) for k in keys]
            pag.hotkey(*normalized)
            return _tool_ok({
                "action": "hotkey",
                "hotkey": hotkey,
                "message": f"Pressed hotkey: {hotkey}",
            })
        except Exception as e:
            return _tool_error(f"hotkey failed: {e!s}")

    # ─── Scroll ───────────────────────────────────────────────────────
    if action in ("scroll_up", "scroll_down"):
        try:
            pag = _ensure_pyautogui()
        except ImportError as e:
            return _tool_error(str(e))
        try:
            amount = scroll_amount if action == "scroll_up" else -scroll_amount
            if x is not None and y is not None:
                pag.scroll(amount, x=x, y=y)
            else:
                pag.scroll(amount)
            return _tool_ok({
                "action": action,
                "amount": scroll_amount,
                "message": f"Scrolled {'up' if action == 'scroll_up' else 'down'} by {scroll_amount}",
            })
        except Exception as e:
            return _tool_error(f"scroll failed: {e!s}")

    return _tool_error(
        f"Unknown action: {action}. "
        f"Valid actions: screenshot, click, double_click, right_click, "
        f"move, drag, type, press, hotkey, scroll_up, scroll_down, "
        f"get_screen_size, get_mouse_position"
    )
