"""ControlBackend interface + implementations, per ARCHITECTURE.md section 6.

Three backends implement the same `ControlBackend` Protocol:

  - NativeInputBackend: pyautogui/pynput + pywinauto + pyperclip + FileOps.
    Used for primitive/low-risk, already-resolved actions (literal (x, y)
    click coordinates, literal key/text injection, window focus, clipboard,
    file ops). Lowest latency, most reliable, no grounding required.
  - OpenClawBackend: adapter stub around the (not-yet-installed) `openclaw`
    package, which is expected to expose a screenshot+instruction ->
    grounded-action loop for semantic/ambiguous UI targets ("click Buy Now").
  - NemoClawBackend: same adapter shape, alternative NVIDIA-ecosystem
    agentic backend ("NemoClaw"), also stubbed.

`BackendRouter` reads config/backends.yaml and picks which backend handles
a given action kind, per ARCHITECTURE.md section 14 (new backends register
in config/backends.yaml, no orchestrator changes needed).

Anything targeting an external SaaS (Gmail, Todoist, Notion, ...) is *not*
handled here — it's delegated to integrations/ (built by another agent).
This module only exposes the extension point (see `IntegrationBackend`
stub below) so ActionExecutor has somewhere consistent to route to.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

import yaml

from execution.audit_log import log_action
from execution.file_ops import FileOps

DEFAULT_BACKENDS_CONFIG = Path(__file__).resolve().parent.parent / "config" / "backends.yaml"


@runtime_checkable
class ControlBackend(Protocol):
    """Common surface every computer-control backend must implement.

    Note: `click` takes an already-resolved (x, y) coordinate for
    NativeInputBackend, but semantic backends (OpenClaw/NemoClaw) resolve a
    natural-language `target_description` themselves — see
    `click_description` on those classes. ActionExecutor decides which
    entry point to call based on whether Vision/planner already produced
    coordinates or only a description.
    """

    def click(self, x: int, y: int) -> bool: ...

    def type_text(self, text: str) -> bool: ...

    def launch_app(self, app_name: str) -> bool: ...

    def press_keys(self, keys: list[str]) -> bool: ...

    def scroll(self, direction: str, amount: int) -> bool: ...


# ---------------------------------------------------------------------------
# Native backend
# ---------------------------------------------------------------------------


class NativeInputBackend:
    """Literal input injection via pyautogui/pynput, pywinauto, pyperclip.

    All optional third-party deps are imported lazily inside methods so this
    module still imports cleanly in environments where they aren't
    installed (e.g. CI, or a machine without a display) — callers get a
    clear ImportError only if they actually invoke the affected method.
    """

    def __init__(self, file_ops: Optional[FileOps] = None) -> None:
        self.file_ops = file_ops or FileOps()

    # -- mouse / keyboard -------------------------------------------------

    def click(self, x: int, y: int, button: str = "left") -> bool:
        import pyautogui

        pyautogui.click(x=x, y=y, button=button)
        log_action("click", {"backend": "native", "x": x, "y": y, "button": button})
        return True

    def type_text(self, text: str) -> bool:
        import pyautogui

        pyautogui.typewrite(text, interval=0.01)
        log_action("type_text", {"backend": "native", "length": len(text)})
        return True

    def press_keys(self, keys: list[str]) -> bool:
        import pyautogui

        if len(keys) == 1:
            pyautogui.press(keys[0])
        else:
            pyautogui.hotkey(*keys)
        log_action("press_keys", {"backend": "native", "keys": keys})
        return True

    def scroll(self, direction: str, amount: int) -> bool:
        import pyautogui

        delta = amount if direction in ("up", "left") else -amount
        if direction in ("up", "down"):
            pyautogui.scroll(delta)
        else:
            pyautogui.hscroll(delta)
        log_action("scroll", {"backend": "native", "direction": direction, "amount": amount})
        return True

    # -- window management (pywinauto / UIAutomation) ---------------------

    def launch_app(self, app_name: str) -> bool:
        from pywinauto import Application

        Application(backend="uia").start(app_name)
        log_action("launch_app", {"backend": "native", "app_name": app_name})
        return True

    def focus_window(self, title_substring: str) -> bool:
        from pywinauto import Desktop

        windows = Desktop(backend="uia").windows(title_re=f".*{title_substring}.*")
        if not windows:
            log_action("focus_window", {"backend": "native", "title_substring": title_substring, "found": False})
            return False
        windows[0].set_focus()
        log_action("focus_window", {"backend": "native", "title_substring": title_substring, "found": True})
        return True

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


# ---------------------------------------------------------------------------
# Agentic / grounding backends (OpenClaw, NemoClaw) — adapter stubs
# ---------------------------------------------------------------------------


class _AgenticBackendBase:
    """Shared adapter shape for screenshot+instruction -> grounded-action backends.

    The real integration (whichever SDK is installed) should:
      1. Take the current screenshot (from vision.capture.capture_screen) and
         an accessibility snapshot if available.
      2. Send them along with `target_description` (e.g. "the Buy Now
         button", "the John contact row") to the agent/model.
      3. Get back a grounded Action (coordinates + action type + confidence).
      4. Execute the low-level action itself (these SDKs typically drive
         input directly) OR return coordinates for us to feed to
         NativeInputBackend.click — adapter below assumes the SDK executes
         directly and just reports what it did, which is the more common
         shape for "computer use" agents.

    Subclasses only need to implement `_call_agent`.
    """

    name = "agentic-base"

    def __init__(self, confidence_threshold: float = 0.6, **options: Any) -> None:
        self.confidence_threshold = confidence_threshold
        self.options = options

    def _call_agent(self, screenshot: Any, instruction: str) -> dict[str, Any]:
        raise NotImplementedError

    # ControlBackend-shaped surface, but semantic: `click` here means
    # "resolve + click a described target" rather than literal coordinates.
    def click_description(self, target_description: str) -> bool:
        screenshot = self._capture_screenshot()
        result = self._call_agent(screenshot, f"click {target_description}")
        ok = bool(result.get("success")) and result.get("confidence", 0) >= self.confidence_threshold
        log_action("click", {"backend": self.name, "target_description": target_description, "result": result})
        return ok

    def type_text_description(self, target_description: str, text: str) -> bool:
        screenshot = self._capture_screenshot()
        result = self._call_agent(screenshot, f"type '{text}' into {target_description}")
        ok = bool(result.get("success")) and result.get("confidence", 0) >= self.confidence_threshold
        log_action("type_text", {"backend": self.name, "target_description": target_description, "result": result})
        return ok

    # Fall back to the literal ControlBackend surface where it makes sense
    # (an agentic backend can still take a literal (x, y) if the caller
    # already knows it — no reason to force a re-grounding round trip).
    def click(self, x: int, y: int) -> bool:
        result = self._call_agent(self._capture_screenshot(), f"click at ({x}, {y})")
        return bool(result.get("success"))

    def type_text(self, text: str) -> bool:
        result = self._call_agent(self._capture_screenshot(), f"type '{text}'")
        return bool(result.get("success"))

    def launch_app(self, app_name: str) -> bool:
        result = self._call_agent(self._capture_screenshot(), f"launch app {app_name}")
        return bool(result.get("success"))

    def press_keys(self, keys: list[str]) -> bool:
        result = self._call_agent(self._capture_screenshot(), f"press keys {'+'.join(keys)}")
        return bool(result.get("success"))

    def scroll(self, direction: str, amount: int) -> bool:
        result = self._call_agent(self._capture_screenshot(), f"scroll {direction} by {amount}")
        return bool(result.get("success"))

    @staticmethod
    def _capture_screenshot() -> Any:
        try:
            from vision.capture import capture_screen

            return capture_screen()
        except ImportError:
            # vision/ may not be built yet in parallel-development hackathon
            # mode — agentic backends degrade to "no screenshot" rather than
            # crashing the whole pipeline.
            return None


class OpenClawBackend(_AgenticBackendBase):
    """Adapter for the `openclaw` agentic computer-control package.

    # TODO: pip install openclaw; replace stub call below with the real SDK.
    Expected real shape (per project README, subject to change once the
    package is actually vendored):

        import openclaw
        agent = openclaw.Agent(model=..., api_base=...)  # local-only endpoint
        action = agent.step(screenshot=screenshot, instruction=instruction)
        # action: openclaw.Action(kind=..., x=..., y=..., confidence=..., raw=...)

    This adapter's job is only to translate our `target_description` +
    screenshot into that call and normalize the response into the plain
    dict shape `{"success": bool, "confidence": float, "raw": Any}` that
    `_AgenticBackendBase` consumes, so swapping SDKs later doesn't touch
    ActionExecutor or BackendRouter.
    """

    name = "openclaw"

    def _call_agent(self, screenshot: Any, instruction: str) -> dict[str, Any]:
        try:
            import openclaw  # type: ignore
        except ImportError:
            # Stub path: no real grounding available. Report a low-confidence
            # non-success so BackendRouter/ActionExecutor can fail over to
            # the configured fallback backend instead of silently lying.
            return {
                "success": False,
                "confidence": 0.0,
                "raw": None,
                "error": "openclaw package not installed (stub backend)",
            }

        # TODO: pip install openclaw; replace stub call below with the real SDK.
        agent = openclaw.Agent(screenshot=screenshot, instruction=instruction)  # type: ignore[attr-defined]
        action = agent.run()
        return {
            "success": getattr(action, "success", False),
            "confidence": getattr(action, "confidence", 0.0),
            "raw": action,
        }


class NemoClawBackend(_AgenticBackendBase):
    """Adapter for the NVIDIA-ecosystem "NemoClaw" agentic backend.

    # TODO: pip install nemoclaw (or the actual NVIDIA NIM-hosted SDK name
    # once known); replace stub call below with the real SDK/gRPC call.
    Expected real shape mirrors OpenClawBackend but is expected to talk to
    a local NIM-hosted VLM endpoint rather than a hosted API (keeps us
    within the "no cloud inference" constraint from ARCHITECTURE.md
    section 1):

        import nemoclaw
        client = nemoclaw.Client(endpoint="http://localhost:9000")
        action = client.ground(screenshot=screenshot, instruction=instruction)
    """

    name = "nemoclaw"

    def _call_agent(self, screenshot: Any, instruction: str) -> dict[str, Any]:
        try:
            import nemoclaw  # type: ignore
        except ImportError:
            return {
                "success": False,
                "confidence": 0.0,
                "raw": None,
                "error": "nemoclaw package not installed (stub backend)",
            }

        # TODO: pip install nemoclaw; replace stub call below with the real SDK.
        client = nemoclaw.Client(endpoint=self.options.get("endpoint", "http://localhost:9000"))  # type: ignore[attr-defined]
        action = client.ground(screenshot=screenshot, instruction=instruction)
        return {
            "success": getattr(action, "success", False),
            "confidence": getattr(action, "confidence", 0.0),
            "raw": action,
        }


# ---------------------------------------------------------------------------
# Integration extension point (SaaS actions) — built out by integrations/
# ---------------------------------------------------------------------------


class IntegrationBackend:
    """Extension point stub for actions targeting an external SaaS.

    Per ARCHITECTURE.md sections 6 and 15, anything hitting Gmail/Todoist/
    Notion/Drive/GitHub/Calendar goes through an MCP client in integrations/,
    not through native input injection or screen-grounding. This class is a
    thin placeholder so BackendRouter has a consistent object to return;
    the real dispatch logic (mapping a Step.tool_hint like "mcp:gmail" to a
    concrete MCP tool call) lives in integrations/ and should replace this
    import once that package exists.
    """

    name = "integration"

    def __init__(self) -> None:
        try:
            from integrations.mcp_client import MCPClientManager  # type: ignore

            self._manager: Optional[Any] = MCPClientManager()
        except ImportError:
            # integrations/ not built yet — keep this a soft dependency.
            self._manager = None

    async def call(self, service: str, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._manager is None:
            log_action(
                "integration_call_unavailable",
                {"service": service, "tool": tool, "params": params},
            )
            return {"success": False, "error": "integrations/ not available (stub)"}
        result = await self._manager.call_tool(service, tool, params)  # type: ignore[attr-defined]
        log_action("integration_call", {"service": service, "tool": tool, "params": params})
        return result


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class BackendRouter:
    """Selects which ControlBackend handles a given action, per config/backends.yaml.

    Routing rules (see config/backends.yaml `routing`) map an action
    "kind" (as inferred by ActionExecutor, e.g. "click", "type_text",
    "saas") to one of:
      - "native"      -> NativeInputBackend
      - "semantic"    -> the configured primary agentic backend
                         (openclaw/nemoclaw), falling back to the other on
                         failure
      - "integration" -> IntegrationBackend (delegates to integrations/)
    """

    def __init__(self, config_path: Path | str = DEFAULT_BACKENDS_CONFIG) -> None:
        self.config = self._load_config(config_path)
        self._native = NativeInputBackend()
        self._agentic: dict[str, _AgenticBackendBase] = {}
        self._integration: Optional[IntegrationBackend] = None

        backends_cfg = self.config.get("backends", {})
        for name, cls in (("openclaw", OpenClawBackend), ("nemoclaw", NemoClawBackend)):
            options = backends_cfg.get(name, {}).get("options", {})
            self._agentic[name] = cls(**options)

        semantic_cfg = self.config.get("semantic_backend", {})
        self.primary_semantic = semantic_cfg.get("primary", "openclaw")
        self.fallback_semantic = semantic_cfg.get("fallback", "nemoclaw")

        self.routing: list[dict[str, Any]] = self.config.get("routing", [])

    @staticmethod
    def _load_config(config_path: Path | str) -> dict[str, Any]:
        path = Path(config_path)
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def route(self, action_kind: str) -> ControlBackend | IntegrationBackend:
        """Return the backend instance that should handle `action_kind`."""
        for rule in self.routing:
            if action_kind in rule.get("match_kind", []):
                target = rule["backend"]
                if target == "native":
                    return self._native
                if target == "semantic":
                    return self.get_semantic_backend()
                if target == "integration":
                    return self.get_integration_backend()
        # default: native is the safest fallback for unknown kinds
        return self._native

    def get_semantic_backend(self, prefer_fallback: bool = False) -> _AgenticBackendBase:
        name = self.fallback_semantic if prefer_fallback else self.primary_semantic
        return self._agentic.get(name, self._agentic[self.primary_semantic])

    def get_integration_backend(self) -> IntegrationBackend:
        if self._integration is None:
            self._integration = IntegrationBackend()
        return self._integration

    @property
    def native(self) -> NativeInputBackend:
        return self._native
