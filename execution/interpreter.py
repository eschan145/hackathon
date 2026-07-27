"""ActionInterpreter: executes one parsed action-DSL Action against a ScreenState.

This is the layer between planning/action_dsl.py's parsed `Action` and the
literal OS-level input injection in execution/control_backend.py. It knows
how to resolve `Action.element_id`/`Action.window_id` against the specific
`ScreenState` the planner reasoned about (ids are only valid for the
ScreenState they came from — see vision/screen_state.py's docstring), then
delegates to `NativeInputBackend` for the actual click/type/key/scroll/
launch/focus.

Does NOT capture a new screenshot itself — execution/executor.py owns
screenshot/a11y capture for the returned ActionResult; this class only
performs the OS-level action and reports success/failure + a short
raw_output string.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from core.models import ActionResult
from execution.control_backend import NativeInputBackend

if TYPE_CHECKING:
    from planning.action_dsl import Action
    from vision.screen_state import ScreenState


class ActionInterpreter:
    """Resolves + executes one parsed Action against the ScreenState it was decided from."""

    def __init__(self, native: Optional[NativeInputBackend] = None) -> None:
        self.native = native or NativeInputBackend()

    async def execute(self, action: "Action", screen_state: Optional["ScreenState"]) -> ActionResult:
        try:
            if action.kind == "click":
                return self._do_click(action, screen_state)
            if action.kind == "type":
                return self._do_type(action, screen_state)
            if action.kind == "key":
                return self._do_key(action)
            if action.kind == "scroll":
                return self._do_scroll(action)
            if action.kind == "launch":
                return self._do_launch(action)
            if action.kind == "focus":
                return self._do_focus(action, screen_state)
            if action.kind == "wait":
                return await self._do_wait(action)
            if action.kind in ("done", "fail"):
                return self._do_control(action)

            return ActionResult(
                success=False,
                raw_output=f"unknown action kind: {action.kind!r}",
                details={"kind": action.kind},
            )
        except Exception as exc:  # noqa: BLE001 - surface as failed ActionResult, not a crash
            return ActionResult(
                success=False,
                raw_output=f"exception: {exc!r}",
                details={"kind": action.kind, "error": str(exc)},
            )

    # -- per-kind handlers ---------------------------------------------------

    def _do_click(self, action: "Action", screen_state: Optional["ScreenState"]) -> ActionResult:
        if screen_state is None:
            return ActionResult(
                success=False,
                raw_output="no screen state available to resolve element ids against",
                details={"kind": "click", "element_id": action.element_id},
            )
        el = screen_state.element_by_id(action.element_id)
        if el is None:
            return ActionResult(
                success=False,
                raw_output=f"element {action.element_id} not found in current screen state",
                details={"kind": "click", "element_id": action.element_id},
            )
        x, y = _center(el.bbox)
        ok = self.native.click(x, y)
        return ActionResult(
            success=ok,
            raw_output=f"click element {action.element_id} at ({x}, {y})",
            details={"kind": "click", "element_id": action.element_id, "x": x, "y": y},
        )

    def _do_type(self, action: "Action", screen_state: Optional["ScreenState"]) -> ActionResult:
        if screen_state is None:
            return ActionResult(
                success=False,
                raw_output="no screen state available to resolve element ids against",
                details={"kind": "type", "element_id": action.element_id},
            )
        el = screen_state.element_by_id(action.element_id)
        if el is None:
            return ActionResult(
                success=False,
                raw_output=f"element {action.element_id} not found in current screen state",
                details={"kind": "type", "element_id": action.element_id},
            )
        x, y = _center(el.bbox)
        clicked = self.native.click(x, y)
        typed = self.native.type_text(action.text or "")
        ok = clicked and typed
        return ActionResult(
            success=ok,
            raw_output=f"type into element {action.element_id} at ({x}, {y}): {action.text!r}",
            details={"kind": "type", "element_id": action.element_id, "x": x, "y": y},
        )

    def _do_key(self, action: "Action") -> ActionResult:
        raw = (action.keys or "").strip()
        # "+" is both the chord separator ("ctrl+l") AND a real key in its
        # own right (Calculator's plus button, numpad plus, ...) --
        # "+".split("+") gives ["", ""], which filters down to an empty
        # chord and would wrongly report "no keys parsed" for the single
        # most likely literal key a calculator-driving turn ever presses.
        if raw == "+":
            keys = ["+"]
        else:
            keys = [k.strip() for k in raw.split("+") if k.strip()]
        if not keys:
            return ActionResult(
                success=False,
                raw_output=f"no keys parsed from {action.keys!r}",
                details={"kind": "key"},
            )
        ok = self.native.press_keys(keys)
        return ActionResult(
            success=ok,
            raw_output=f"press_keys {keys}",
            details={"kind": "key", "keys": keys},
        )

    def _do_scroll(self, action: "Action") -> ActionResult:
        ok = self.native.scroll(action.direction or "down", action.amount)
        return ActionResult(
            success=ok,
            raw_output=f"scroll {action.direction} by {action.amount}",
            details={"kind": "scroll", "direction": action.direction, "amount": action.amount},
        )

    def _do_launch(self, action: "Action") -> ActionResult:
        ok = self.native.launch_app(action.app_name or "")
        return ActionResult(
            success=ok,
            raw_output=f"launch {action.app_name!r}",
            details={"kind": "launch", "app_name": action.app_name},
        )

    def _do_focus(self, action: "Action", screen_state: Optional["ScreenState"]) -> ActionResult:
        win = screen_state.window_by_id(action.window_id) if screen_state is not None else None
        details: dict = {"kind": "focus", "window_id": action.window_id, "found_in_screen_state": win is not None}
        if win is None:
            details["note"] = "window id not present in current screen state; attempting best-effort focus anyway"

        from vision.windows import focus_window as _focus_window

        ok = _focus_window(action.window_id)
        return ActionResult(
            success=ok,
            raw_output=f"focus window {action.window_id}",
            details=details,
        )

    async def _do_wait(self, action: "Action") -> ActionResult:
        await asyncio.sleep(action.seconds)
        return ActionResult(
            success=True,
            raw_output=f"waited {action.seconds}s",
            details={"kind": "wait", "seconds": action.seconds},
        )

    def _do_control(self, action: "Action") -> ActionResult:
        # done()/fail() are loop-control signals, not screen actions — report
        # faithfully and let the caller (executor.py / orchestrator loop)
        # decide what it means for the Step/Task outcome.
        return ActionResult(
            success=True,
            raw_output=action.message,
            details={"kind": action.kind, "message": action.message},
        )


def _center(bbox: tuple[int, int, int, int]) -> tuple[int, int]:
    left, top, right, bottom = bbox
    return (left + right) // 2, (top + bottom) // 2
