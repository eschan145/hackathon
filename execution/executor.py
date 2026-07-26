"""ActionExecutor: the Executor implementation for the Execution subsystem.

Per core/interfaces.py::Executor, `execute(step, task) -> ActionResult` is
the entire contract the Orchestrator relies on. This class:

  1. Reconstructs the parsed `planning.action_dsl.Action` from
     `step.action` (a plain dict, produced via `dataclasses.asdict`).
  2. Retrieves the exact `ScreenState` the planner used to decide this
     action (via execution/screen_state_cache.get_screen_state, keyed by
     task id) so element/window ids resolve against the same capture they
     were assigned in.
  3. Hands both to ActionInterpreter.execute() to perform the OS-level
     action.
  4. Captures a post-action screenshot via vision.capture.capture_screen
     (soft-imported; vision/ may not exist yet in parallel hackathon dev).
  5. Returns an ActionResult with screenshot_ref/a11y_snapshot/raw_output/
     success/details for the Verification subsystem to consume.
"""

from __future__ import annotations

from typing import Any, Optional

from core.models import ActionResult, Step, Task
from execution.audit_log import log_action
from execution.interpreter import ActionInterpreter
from execution.screen_state_cache import get_screen_state
from planning.action_dsl import Action


class ActionExecutor:
    """Resolves a Step's parsed action and returns an ActionResult."""

    def __init__(self, interpreter: Optional[ActionInterpreter] = None) -> None:
        self.interpreter = interpreter or ActionInterpreter()

    async def execute(self, step: Step, task: Task) -> ActionResult:
        details: dict[str, Any] = {"step_id": step.id, "risk_level": step.risk_level}

        if step.action is None:
            log_action(
                "step_execute",
                {"task_id": task.id, "step_id": step.id, "success": False, "error": "no parsed action"},
            )
            return ActionResult(
                screenshot_ref=None,
                a11y_snapshot=None,
                raw_output="step has no parsed action",
                success=False,
                details={**details, "error": "step has no parsed action"},
            )

        action = Action(**step.action)
        details["kind"] = action.kind

        screen_state = get_screen_state(task.id)
        if screen_state is None:
            details["screen_state_missing"] = True

        result = await self.interpreter.execute(action, screen_state)

        screenshot_ref = self._capture_screenshot()
        a11y_snapshot = self._capture_a11y_snapshot()

        merged_details = {**details, **result.details}

        log_action(
            "step_execute",
            {"task_id": task.id, "step_id": step.id, "kind": action.kind, "success": result.success},
        )

        return ActionResult(
            screenshot_ref=screenshot_ref,
            a11y_snapshot=a11y_snapshot,
            raw_output=result.raw_output,
            success=result.success,
            details=merged_details,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _capture_screenshot() -> Optional[str]:
        try:
            from vision.capture import capture_screen, default_frame_store
        except ImportError:
            return None

        try:
            image = capture_screen()
            # Bare ref_id via the shared FrameStore (same convention
            # vision/screen_state.py uses for pre-action captures), not a
            # standalone path — backend/main.py's _event_to_message()
            # rebuilds the /api/frames URL from a bare ref_id, and
            # StaticFiles serves default_frame_store.directory specifically.
            return default_frame_store.save(image)
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
