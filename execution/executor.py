"""ActionExecutor: the Executor implementation for the Execution subsystem.

Per core/interfaces.py::Executor, `execute(step, task) -> ActionResult` is
the entire contract the Orchestrator relies on. This class:

  1. Infers an action "kind" from `step.tool_hint`/`step.description`
     (click, type_text, press_keys, scroll, launch_app, file_ops,
     clipboard, saas/integration).
  2. Asks BackendRouter for the right backend given that kind (+ risk
     level influences whether we prefer native literal coordinates over a
     semantic grounding call, per ARCHITECTURE.md section 6).
  3. Performs the action.
  4. Captures a post-action screenshot via vision.capture.capture_screen
     (soft-imported; vision/ may not exist yet in parallel hackathon dev).
  5. Returns an ActionResult with screenshot_ref/a11y_snapshot/raw_output/
     success/details for the Verification subsystem to consume.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Optional

from core.models import ActionResult, Step, Task
from execution.audit_log import log_action
from execution.control_backend import BackendRouter, IntegrationBackend, _AgenticBackendBase

SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "screenshots"

# Coordinate hint pattern, e.g. tool_hint="native:click(320,480)" or a step
# description containing "at (320, 480)". Planner isn't expected to hand-
# compute pixels per ARCHITECTURE.md section 6, but if it (or a prior
# vision-grounding pass) already did, we honor it rather than re-grounding.
_COORD_RE = re.compile(r"\(?\s*(\d+)\s*,\s*(\d+)\s*\)?")

# tool_hint prefixes that map directly onto an action kind, e.g.
# "native:type_text", "openclaw:click", "mcp:gmail".
_KNOWN_KINDS = {
    "click",
    "type_text",
    "press_keys",
    "scroll",
    "launch_app",
    "file_ops",
    "clipboard",
    "saas",
    "integration",
    "semantic_ui",
}


class ActionExecutor:
    """Resolves a Step to a concrete backend action and returns an ActionResult."""

    def __init__(self, router: Optional[BackendRouter] = None) -> None:
        self.router = router or BackendRouter()

    async def execute(self, step: Step, task: Task) -> ActionResult:
        kind = self._infer_action_kind(step)
        backend = self.router.route(kind)

        details: dict[str, Any] = {"step_id": step.id, "kind": kind, "risk_level": step.risk_level}
        raw_output: Optional[str] = None
        success = False

        try:
            if isinstance(backend, IntegrationBackend):
                result = await backend.call(
                    service=self._extract_service(step),
                    tool=step.tool_hint,
                    params={"description": step.description},
                )
                success = bool(result.get("success"))
                raw_output = str(result)
                details["integration_result"] = result

            elif isinstance(backend, _AgenticBackendBase):
                if kind == "click":
                    success = backend.click_description(step.description)
                else:
                    # Ambiguous/general action (kind == "semantic_ui", e.g. a
                    # whole-objective stopgap step) — hand it over verbatim
                    # rather than forcing a "click ..." wrapper that doesn't
                    # make sense for non-click instructions.
                    success = backend.act(step.description)
                raw_output = f"{backend.name} grounded action for: {step.description}"
                details["backend"] = backend.name

            else:
                # NativeInputBackend: literal action, resolve coordinates if
                # the step/tool_hint already carries them (e.g. from a prior
                # vision pass), otherwise this is a non-click primitive.
                success, raw_output = self._run_native(backend, kind, step)
                details["backend"] = "native"

        except Exception as exc:  # noqa: BLE001 - surface as failed ActionResult, not a crash
            success = False
            raw_output = f"exception: {exc!r}"
            details["error"] = str(exc)

        log_action(
            "step_execute",
            {"task_id": task.id, "step_id": step.id, "kind": kind, "success": success},
        )

        screenshot_ref = self._capture_screenshot(task.id, step.id)
        a11y_snapshot = self._capture_a11y_snapshot()

        return ActionResult(
            screenshot_ref=screenshot_ref,
            a11y_snapshot=a11y_snapshot,
            raw_output=raw_output,
            success=success,
            details=details,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _infer_action_kind(step: Step) -> str:
        hint = step.tool_hint.lower().strip()

        # tool_hint like "native:type_text" or "openclaw:click" or "mcp:gmail"
        if ":" in hint:
            prefix, _, rest = hint.partition(":")
            if prefix in ("mcp",):
                return "saas"
            if rest in _KNOWN_KINDS:
                return rest

        for kind in _KNOWN_KINDS:
            if kind in hint:
                return kind

        desc = step.description.lower()
        if any(w in desc for w in ("send email", "gmail", "todoist", "notion", "calendar", "github", "drive")):
            return "saas"
        if any(w in desc for w in ("click", "select", "buy", "press the")):
            return "click"
        if any(w in desc for w in ("type", "enter text", "fill in")):
            return "type_text"
        if any(w in desc for w in ("scroll",)):
            return "scroll"
        if any(w in desc for w in ("launch", "open app", "start app")):
            return "launch_app"
        if any(w in desc for w in ("copy", "paste", "clipboard")):
            return "clipboard"
        if any(w in desc for w in ("file", "save", "delete", "read", "write")):
            return "file_ops"
        # default: ambiguous UI action, prefer semantic grounding
        return "semantic_ui"

    @staticmethod
    def _extract_service(step: Step) -> str:
        hint = step.tool_hint
        if hint.startswith("mcp:"):
            return hint.split(":", 1)[1]
        return "unknown"

    def _run_native(self, backend: Any, kind: str, step: Step) -> tuple[bool, str]:
        if kind == "click":
            match = _COORD_RE.search(step.description) or _COORD_RE.search(step.tool_hint)
            if not match:
                return False, "native click requires resolved (x, y); none found in step"
            x, y = int(match.group(1)), int(match.group(2))
            ok = backend.click(x, y)
            return ok, f"native click at ({x}, {y})"

        if kind == "type_text":
            text = step.description
            ok = backend.type_text(text)
            return ok, f"native type_text len={len(text)}"

        if kind == "press_keys":
            keys = [k.strip() for k in re.split(r"[+, ]", step.tool_hint or step.description) if k.strip()]
            ok = backend.press_keys(keys)
            return ok, f"native press_keys {keys}"

        if kind == "scroll":
            direction = "down"
            for d in ("up", "down", "left", "right"):
                if d in step.description.lower():
                    direction = d
                    break
            ok = backend.scroll(direction, 3)
            return ok, f"native scroll {direction}"

        if kind == "launch_app":
            app_name = step.tool_hint.split(":", 1)[-1] if ":" in step.tool_hint else step.description
            ok = backend.launch_app(app_name)
            return ok, f"native launch_app {app_name}"

        if kind == "clipboard":
            if "read" in step.description.lower() or "paste" in step.description.lower():
                value = backend.clipboard_read()
                return True, f"clipboard_read: {value[:80]!r}"
            ok = backend.clipboard_write(step.description)
            return ok, "clipboard_write"

        if kind == "file_ops":
            # Steps needing real file paths should carry them in tool_hint,
            # e.g. "file_ops:write:/path/to/file". Kept minimal for demo.
            return False, "file_ops requires explicit path in tool_hint (not resolved here)"

        return False, f"unhandled native action kind: {kind}"

    @staticmethod
    def _capture_screenshot(task_id: str, step_id: str) -> Optional[str]:
        try:
            from vision.capture import capture_screen
        except ImportError:
            return None

        try:
            image = capture_screen()
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            ref = SCREENSHOT_DIR / f"{task_id}_{step_id}_{int(time.time() * 1000)}.png"
            if hasattr(image, "save"):
                image.save(ref)
            return str(ref)
        except Exception:
            return None

    @staticmethod
    def _capture_a11y_snapshot() -> Optional[dict[str, Any]]:
        try:
            from vision.capture import capture_a11y_snapshot  # type: ignore
        except ImportError:
            return None
        try:
            return capture_a11y_snapshot()
        except Exception:
            return None
