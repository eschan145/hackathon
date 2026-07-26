"""Tiny shared cache handing the exact ScreenState a planner reasoned about
to execution/executor.py, keyed by task id.

Why this exists: `planning.action_dsl.Action.element_id`/`window_id` are
only valid against the specific `ScreenState` capture the planner saw when
it decided the action (ids are reassigned every capture — see
vision/screen_state.py's docstring). execution/executor.py cannot simply
capture a *fresh* ScreenState right before executing — ids may have shifted
since the planner reasoned about the old one — so the exact same
ScreenState instance must be threaded through.

COORDINATION NOTE: this module is new and not part of the planning
workstream's original spec. `planning/vision_agent_planner.py` (owned by
another workstream) needs to call `set_screen_state(task.id, state)`
immediately after each `vision.screen_state.capture_screen_state()` call,
so that `execution/executor.py` can retrieve the matching state via
`get_screen_state(task.id)` before handing the parsed Action to
`ActionInterpreter.execute()`. Flagging loudly since the planning side
needs to wire this in for grounding to actually work end-to-end.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from vision.screen_state import ScreenState

_last_screen_state: dict[str, "ScreenState"] = {}


def set_screen_state(task_id: str, state: "ScreenState") -> None:
    """Stash the ScreenState the planner just used to decide an action, keyed by task id."""
    _last_screen_state[task_id] = state


def get_screen_state(task_id: str) -> Optional["ScreenState"]:
    """Retrieve the most recently stashed ScreenState for this task id, if any."""
    return _last_screen_state.get(task_id)
