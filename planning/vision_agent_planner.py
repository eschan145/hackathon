"""VisionAgentPlanner: the vision -> prompt -> OpenClaw -> parse agent loop.

Implements the Planner protocol (core/interfaces.py) by, every turn:
  1. capturing a fresh ScreenState (vision/screen_state.py) — algorithmic,
     no model call;
  2. building a compact prompt (objective + action-DSL grammar + condensed
     history + current screen state);
  3. asking OpenClawModelClient for a single stateless completion;
  4. parsing the response with planning.action_dsl.parse_actions and
     turning each Action into a Step the Executor can run.

Every turn is a real, separately-billed `openclaw infer model run` call
with no session state on the far side (see planning/openclaw_client.py),
so the condensed-history step above is a real token/latency lever, not
just style: we summarize the last handful of *already-executed* Steps
(from task.graph.steps, which is the one cross-workstream contract we can
rely on) rather than replaying a full verbose transcript.

done()/fail() handling — READ THIS if you're reconciling with
core/orchestrator.py:
    The Planner protocol's `next_actions` can only communicate "stop" one
    way: return `[]`. There is no way to tell the Orchestrator *why* it
    stopped (objective satisfied vs. objective abandoned) through the
    return value alone. Per the task spec for this workstream, both
    done() and fail() (and, here, an unparseable/empty model turn after
    one retry) all cause `next_actions` to return `[]`. To make the
    distinction recoverable, this planner always records a clearly
    differentiated history entry first:
        - done()  -> task.record("agent_done", summary=..., success=True)
        - fail()  -> task.record("agent_fail", reason=..., success=False)
        - stall   -> task.record("agent_stall", success=False)
    ...so a future patch to core/orchestrator.py (or to Task.state
    transition logic) can inspect `task.history[-1]` and route to
    COMPLETED vs FAILED accordingly. As specified today, the orchestrator
    falls through to COMPLETED for *all* of these — meaning an abandoned
    ("fail") objective currently reports as completed. Flagged for
    reconciliation with whoever owns core/orchestrator.py.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Optional

from core.models import Step, Task, TaskGraph
from execution.screen_state_cache import set_screen_state
from planning.action_dsl import (
    ACTION_DSL_SPEC,
    Action,
    CONTROL_ACTION_KINDS,
    MAX_ACTIONS_PER_TURN,
    parse_actions,
)
from planning.openclaw_client import OpenClawModelClient
from vision.capture import default_frame_store
from vision.screen_state import ScreenState, capture_screen_state

# Turns count against the "consecutive failures" screenshot escalation
# threshold when this many trailing steps in task.graph.steps have status
# "failed" — a screen_state.screenshot_ref alone (OCR text + bboxes) is
# cheap and usually enough to decide the next action, so a raw image is
# only worth the extra multimodal call once text-only turns are clearly
# stuck.
_SCREENSHOT_ESCALATION_THRESHOLD = 2

# Keyword heuristic for bumping a launch()/key() Step to risk_level="high"
# when the *objective* text suggests something consequential/irreversible.
# Deliberately simple - not meant to be exhaustive.
_HIGH_RISK_OBJECTIVE_KEYWORDS = (
    "delete",
    "format",
    "uninstall",
    "purchase",
    "buy",
    "pay",
    "send",
)

# Actions worth a one-line rendering for Step.description; falls back to
# Action.raw for anything unexpected (defensive, shouldn't normally hit).
def _describe_action(a: Action) -> str:
    if a.kind == "click":
        return f"click element {a.element_id}"
    if a.kind == "type":
        return f'type "{a.text}" into element {a.element_id}'
    if a.kind == "key":
        return f'press key "{a.keys}"'
    if a.kind == "scroll":
        return f"scroll {a.direction} by {a.amount}"
    if a.kind == "launch":
        return f'launch "{a.app_name}"'
    if a.kind == "focus":
        return f"focus window {a.window_id}"
    if a.kind == "wait":
        return f"wait {a.seconds}s"
    if a.kind == "done":
        return f"done: {a.message}"
    if a.kind == "fail":
        return f"fail: {a.message}"
    return a.raw or a.kind


def _risk_level(action: Action, objective: str) -> str:
    if action.kind in ("launch", "key"):
        objective_lower = objective.lower()
        if any(kw in objective_lower for kw in _HIGH_RISK_OBJECTIVE_KEYWORDS):
            return "high"
    return "low"


class VisionAgentPlanner:
    """Planner implementation driving the vision-grounded OpenClaw agent loop."""

    def __init__(self, client: Optional[OpenClawModelClient] = None) -> None:
        self._client = client or OpenClawModelClient()

    # ------------------------------------------------------------------
    # Planner protocol
    # ------------------------------------------------------------------

    async def create_plan(self, task: Task) -> TaskGraph:
        # First turn only: send the (cached, so cheap) installed-apps list
        # so the model knows what it can launch() by name.
        _reasoning, actions, _screen = await self._run_turn(
            task, include_installed_apps=True, failure_note=None
        )
        steps = self._actions_to_steps(task, actions, previous_step_id=None)
        return TaskGraph(task_id=task.id, objective=task.objective, steps=steps)

    async def next_actions(self, task: Task) -> list[Step]:
        reasoning, actions, _screen = await self._run_turn(
            task, include_installed_apps=False, failure_note=None
        )
        screen_actions, control = _split_actions(actions)
        previous_step_id = _last_step_id(task)
        steps = self._actions_to_steps(task, screen_actions, previous_step_id)

        if control is not None:
            _record_control(task, control, reasoning)
            # If real screen actions preceded the control signal this same
            # turn, run those first; the loop will naturally re-observe and
            # the model will likely re-emit done()/fail() next turn once
            # those actions are visible on screen. Only when the control
            # signal was the *entire* turn's output do we end the loop now.
            return steps

        if not steps:
            # Nothing parsed at all, even after _run_turn's one corrective
            # retry - can't safely keep the loop spinning on a model that
            # isn't emitting valid actions, so end the loop. See the
            # module docstring: this collapses into the same "[] means
            # done" ambiguity as fail() today.
            task.record("agent_stall", raw_reasoning=reasoning)
            return []

        return steps

    async def replan(self, task: Task, failure_context: dict[str, Any]) -> TaskGraph:
        failure_note = (
            "A previous action failed and needs to be corrected. "
            f"Failure context: {failure_context}"
        )
        reasoning, actions, _screen = await self._run_turn(
            task, include_installed_apps=False, failure_note=failure_note
        )
        screen_actions, control = _split_actions(actions)
        # Unlike next_actions() (which appends onto the existing
        # task.graph.steps, so chaining off the previous step's id via
        # _last_step_id is correct there), core/orchestrator.py's
        # _replan() *replaces* graph.steps wholesale with whatever this
        # method returns. Chaining depends_on off the old (about-to-be-
        # discarded) failed step's id would leave the new steps depending
        # on an id that no longer exists anywhere in the graph -- a
        # permanent, unsatisfiable dependency that deadlocks the task
        # forever. The replanned steps are the new start of the graph, so
        # the first one must have no dependency.
        steps = self._actions_to_steps(task, screen_actions, previous_step_id=None)

        if control is not None:
            _record_control(task, control, reasoning)
        elif not steps:
            task.record("agent_stall", raw_reasoning=reasoning)

        return TaskGraph(task_id=task.id, objective=task.objective, steps=steps)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _run_turn(
        self,
        task: Task,
        *,
        include_installed_apps: bool,
        failure_note: Optional[str],
    ) -> tuple[Optional[str], list[Action], ScreenState]:
        """Capture screen state, prompt the model once, parse the result.

        Retries once (with a corrective nudge appended to the same prompt)
        if the first response contains no parseable action-DSL lines at
        all - mirrors the single-retry-on-bad-response pattern the old
        (now-deleted) planning/llm_client.py used for malformed JSON.
        """
        screen = capture_screen_state(include_installed_apps=include_installed_apps)
        # Every turn's fresh capture overwrites the previous one for this
        # task_id - execution/executor.py resolves a Step's element/window
        # ids against whatever ScreenState is cached here, and those ids
        # are only valid relative to the exact capture they were assigned
        # from (see vision/screen_state.py's docstring), so this must run
        # every turn, not just the first.
        set_screen_state(task.id, screen)
        image_path = self._screenshot_if_escalated(task, screen)
        prompt = self._build_prompt(task, screen, failure_note=failure_note)

        text = await self._client.complete(prompt, image_path=image_path)
        reasoning, actions = parse_actions(text)

        if not actions:
            nudge_prompt = (
                f"{prompt}\n\n"
                "Your previous response contained no parseable action-DSL lines. "
                "Emit at least one line using the exact grammar above (use "
                "done()/fail() if that's genuinely the right call)."
            )
            text = await self._client.complete(nudge_prompt, image_path=image_path)
            reasoning, actions = parse_actions(text)

        return reasoning, actions, screen

    def _build_prompt(
        self, task: Task, screen: ScreenState, *, failure_note: Optional[str]
    ) -> str:
        lines: list[str] = [f"OBJECTIVE: {task.objective}", ""]

        if failure_note:
            lines.append(failure_note)
            lines.append("")

        history_summary = _condensed_history(task)
        if history_summary:
            lines.append("RECENT ACTION HISTORY (most recent last):")
            lines.append(history_summary)
            lines.append("")

        lines.append(ACTION_DSL_SPEC)
        if self._client.reasoning_visible:
            lines.append(
                "You may prefix brief one-line reasoning with '#' before your "
                "action lines; keep it short."
            )
        else:
            lines.append("Do not include any reasoning/commentary lines - actions only.")
        lines.append("")

        lines.append("CURRENT SCREEN STATE:")
        lines.append(screen.to_prompt_text())

        return "\n".join(lines)

    def _screenshot_if_escalated(self, task: Task, screen: ScreenState) -> Optional[Path]:
        """Resolve the current screenshot's on-disk path, but only once
        turns have clearly stalled (2+ consecutive failed steps) - normal
        turns are text-only, since OCR text + bboxes is usually enough and
        a multimodal call is a heavier/slower `openclaw infer model run`.
        """
        if screen.screenshot_ref is None:
            return None
        if _consecutive_failure_count(task) < _SCREENSHOT_ESCALATION_THRESHOLD:
            return None
        # FrameStore.save() names files "<ref_id>.png" under its directory
        # (see FrameStore._path_for in vision/capture.py); re-derive rather
        # than reach into that private method.
        return default_frame_store.directory / f"{screen.screenshot_ref}.png"

    def _actions_to_steps(
        self, task: Task, actions: list[Action], previous_step_id: Optional[str]
    ) -> list[Step]:
        truncated = actions[:MAX_ACTIONS_PER_TURN]
        steps: list[Step] = []
        prev_id = previous_step_id
        for action in truncated:
            step = Step(
                description=_describe_action(action),
                tool_hint="vision_action",
                depends_on=[prev_id] if prev_id else [],
                risk_level=_risk_level(action, task.objective),
                success_criteria=f"action {action.kind} executed without error",
                action=dataclasses.asdict(action),
            )
            steps.append(step)
            prev_id = step.id
        return steps


# ----------------------------------------------------------------------
# Module-level helpers (no instance state needed)
# ----------------------------------------------------------------------


def _last_step_id(task: Task) -> Optional[str]:
    if task.graph is None or not task.graph.steps:
        return None
    return task.graph.steps[-1].id


def _consecutive_failure_count(task: Task) -> int:
    """Count trailing steps with status == "failed" in task.graph.steps.

    Used (rather than an instance-level counter keyed by task.id) so the
    escalation decision is stateless and survives planner re-instantiation
    - it's derived purely from the one cross-workstream contract we can
    rely on (Step.status), not from anything private to this class.
    """
    if task.graph is None:
        return 0
    count = 0
    for step in reversed(task.graph.steps):
        if step.status == "failed":
            count += 1
        else:
            break
    return count


def _condensed_history(task: Task) -> str:
    """Last ~5 already-executed steps, one line each: "- <description> -> <status>".

    Deliberately built from task.graph.steps (a Step's `status` field is a
    stable cross-workstream contract) rather than task.history's free-form
    dicts, whose exact shape depends on what execution/verification choose
    to record - this keeps the summary robust to those workstreams' choices.
    """
    if task.graph is None or not task.graph.steps:
        return ""
    executed = [s for s in task.graph.steps if s.status in ("verified", "failed", "skipped")]
    recent = executed[-5:]
    if not recent:
        return ""
    return "\n".join(f"- {s.description} -> {s.status}" for s in recent)


def _split_actions(actions: list[Action]) -> tuple[list[Action], Optional[Action]]:
    """Split a turn's actions into (screen_actions, control_action).

    done()/fail() are loop-control signals meaning "stop" - anything the
    model emitted after one (however unlikely, given the DSL spec asks it
    not to narrate future turns) is discarded along with it.
    """
    screen_actions: list[Action] = []
    for action in actions:
        if action.kind in CONTROL_ACTION_KINDS:
            return screen_actions, action
        screen_actions.append(action)
    return screen_actions, None


def _record_control(task: Task, control: Action, reasoning: Optional[str]) -> None:
    if control.kind == "done":
        task.record("agent_done", summary=control.message, reasoning=reasoning, success=True)
    else:  # "fail"
        task.record("agent_fail", reason=control.message, reasoning=reasoning, success=False)
