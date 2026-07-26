"""ControlBackend interface + native implementation.

`NativeInputBackend` is the sole `ControlBackend` implementation in this
module: pyautogui/pynput + pyperclip + FileOps, driving literal, already-
resolved actions (pixel-coordinate clicks, literal key/text injection,
window focus via vision.windows, app launch via vision.apps, clipboard,
file ops). This is the only control layer used by the vision-agent
pipeline (execution/interpreter.py) — there is no semantic/agentic
grounding backend or router in this build; the planner/vision subsystem
resolves element and window ids itself, so ActionExecutor only ever needs
literal execution.

Anything targeting an external SaaS (Gmail, Todoist, Notion, ...) is not
handled here — it's delegated to integrations/ (owned by another agent).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from execution.audit_log import log_action
from execution.file_ops import FileOps


# pyautogui's actual key-name vocabulary (pyautogui.KEYBOARD_KEYS) is a
# specific, somewhat arbitrary set (e.g. "=" for equals, "enter" not
# "return" for... actually both exist, but "equal"/"plus"/"equals" do NOT)
# — a model emitting key("equal") or key("plus") is a completely
# reasonable guess that pyautogui doesn't understand. Map the common
# natural-language names an LLM is likely to use onto the real ones,
# rather than let them silently no-op.
_KEY_ALIASES: dict[str, str] = {
    "equal": "=",
    "equals": "=",
    "plus": "+",
    "minus": "-",
    "dash": "-",
    "period": ".",
    "dot": ".",
    "comma": ",",
    "slash": "/",
    "backslash": "\\",
    "return": "enter",
    "esc": "escape",
    "spacebar": "space",
    "del": "delete",
    "control": "ctrl",
}


def _normalize_key_name(key: str) -> str:
    lowered = key.strip().lower()
    return _KEY_ALIASES.get(lowered, lowered)


def _import_pyautogui() -> Any:
    """Import pyautogui, working around `mouseinfo`'s hard `sys.exit()`.

    pyautogui unconditionally imports `mouseinfo` (only actually needed
    for its interactive `mouseInfo()` GUI debug tool, which this codebase
    never calls) — and on Linux without tkinter, `mouseinfo` does
    `sys.exit("NOTE: you must install tkinter...")` at import time. That's
    not a raised Exception, so no `except Exception` anywhere in this
    codebase (interpreter/executor/orchestrator) can catch it — it kills
    the whole process outright. Stub the module out first so pyautogui's
    `import mouseinfo` line is a no-op instead of a crash.
    """
    if "mouseinfo" not in sys.modules:
        try:
            import mouseinfo  # noqa: F401
        except SystemExit:
            sys.modules["mouseinfo"] = types.ModuleType("mouseinfo")

    import pyautogui

    return pyautogui


@runtime_checkable
class ControlBackend(Protocol):
    """Common surface every computer-control backend must implement."""

    def click(self, x: int, y: int) -> bool: ...

    def type_text(self, text: str) -> bool: ...

    def launch_app(self, app_name: str) -> bool: ...

    def press_keys(self, keys: list[str]) -> bool: ...

    def scroll(self, direction: str, amount: int) -> bool: ...


# ---------------------------------------------------------------------------
# Native backend
# ---------------------------------------------------------------------------


class NativeInputBackend:
    """Literal input injection via pyautogui/pynput, pyperclip, vision.windows/apps.

    All optional third-party deps are imported lazily inside methods so this
    module still imports cleanly in environments where they aren't
    installed (e.g. CI, or a machine without a display) — callers get a
    clear ImportError only if they actually invoke the affected method.
    """

    def __init__(self, file_ops: Optional[FileOps] = None) -> None:
        self.file_ops = file_ops or FileOps()

    # -- mouse / keyboard -------------------------------------------------

    def click(self, x: int, y: int, button: str = "left") -> bool:
        pyautogui = _import_pyautogui()

        pyautogui.click(x=x, y=y, button=button)
        log_action("click", {"backend": "native", "x": x, "y": y, "button": button})
        return True

    def type_text(self, text: str) -> bool:
        pyautogui = _import_pyautogui()

        pyautogui.typewrite(text, interval=0.01)
        log_action("type_text", {"backend": "native", "length": len(text)})
        return True

    def press_keys(self, keys: list[str]) -> bool:
        pyautogui = _import_pyautogui()

        normalized = [_normalize_key_name(k) for k in keys]
        unrecognized = [
            orig for orig, norm in zip(keys, normalized) if norm not in pyautogui.KEYBOARD_KEYS
        ]
        if unrecognized:
            # pyautogui.press()/hotkey() silently no-op on a key name they
            # don't recognize (observed live: press("equal") does nothing,
            # no exception, no effect -- the correct name is "=") rather
            # than raising, so without this check a bad key name from the
            # model would be reported as a successful ActionResult despite
            # never actually happening. Fail loudly instead so the planner
            # sees it next turn and can retry with a real key name.
            log_action(
                "press_keys",
                {"backend": "native", "keys": keys, "success": False, "unrecognized": unrecognized},
            )
            return False

        if len(normalized) == 1:
            pyautogui.press(normalized[0])
        else:
            pyautogui.hotkey(*normalized)
        log_action("press_keys", {"backend": "native", "keys": keys, "success": True})
        return True

    def scroll(self, direction: str, amount: int) -> bool:
        pyautogui = _import_pyautogui()

        delta = amount if direction in ("up", "left") else -amount
        if direction in ("up", "down"):
            pyautogui.scroll(delta)
        else:
            pyautogui.hscroll(delta)
        log_action("scroll", {"backend": "native", "direction": direction, "amount": amount})
        return True

    # -- window management / app launch (vision.windows / vision.apps) ----

    def launch_app(self, app_name: str) -> bool:
        from vision.apps import launch_app as _launch_app

        ok = _launch_app(app_name)
        log_action("launch_app", {"backend": "native", "app_name": app_name})
        return ok

    def focus_window(self, title_substring: str) -> bool:
        """Best-effort focus by title substring.

        `vision.windows.focus_window` expects a real window id (e.g.
        "0x02c00003"), not a free-text title — historically this method is
        called with a title substring, so we first resolve it to an id via
        `vision.windows.list_open_windows()` and only then call
        `focus_window(id)`. Degrades to returning False (never raises) if
        nothing matches.
        """
        from vision.windows import focus_window as _focus_window
        from vision.windows import list_open_windows

        try:
            windows = list_open_windows()
        except Exception:
            windows = []

        needle = title_substring.lower()
        match = next(
            (w for w in windows if needle in (getattr(w, "title", "") or "").lower()),
            None,
        )
        if match is None:
            log_action(
                "focus_window",
                {"backend": "native", "title_substring": title_substring, "found": False},
            )
            return False

        ok = _focus_window(match.id)
        log_action(
            "focus_window",
            {"backend": "native", "title_substring": title_substring, "found": True, "window_id": match.id},
        )
        return ok

    # -- clipboard (audit-logged, per ARCHITECTURE.md section 6/12) -------

    def clipboard_write(self, text: str) -> bool:
        import pyperclip

        pyperclip.copy(text)
        log_action("clipboard_write", {"backend": "native", "length": len(text)})
        return True

    def clipboard_read(self) -> str:
        import pyperclip

        value = pyperclip.paste()
        log_action("clipboard_read", {"backend": "native", "length": len(value)})
        return value

    # -- filesystem (delegates to scoped FileOps) --------------------------

    def file_read(self, path: str) -> bytes:
        return self.file_ops.read(path)

    def file_write(self, path: str, content: bytes | str, append: bool = False) -> Path:
        return self.file_ops.write(path, content, append=append)

    def file_delete(self, path: str) -> None:
        self.file_ops.delete(path)

    def file_list(self, path: str) -> list[str]:
        return self.file_ops.list(path)
