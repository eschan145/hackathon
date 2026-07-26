"""Stopgap Planner that delegates the whole objective to OpenClaw's own agent.

planning.planner.LLMPlanner needs a local planning-model endpoint reachable
per config/models.yaml (`planning.base_url`) — until one is actually being
served (e.g. once a local Qwen2.5-VL-72B-Instruct deployment is up), every
real objective fails at the PLANNING state with a connection error.

OpenClaw's own agent (see execution.control_backend.OpenClawBackend) already
has a working model configured through the local OpenClaw Gateway and a
paired node with a real exec tool — verified to actually perform actions
(launch Notepad, run shell commands) end-to-end. This planner produces a
single step that hands the objective to it directly instead of decomposing
via a local LLM, so simple objectives ("open Notepad", "what's the active
window") get real work done today rather than hanging at PLANNING forever.

Swap back to LLMPlanner (see gui/main.py and backend/main.py's
_build_planner()) once a local planning-model endpoint is actually being
served.
"""

from __future__ import annotations

from typing import Any

from core.models import Step, Task, TaskGraph


class OpenClawPlanner:
    """Single-step Planner: hands the whole objective to the OpenClaw backend."""

    async def create_plan(self, task: Task) -> TaskGraph:
        step = Step(
            description=task.objective,
            tool_hint="openclaw",
            risk_level="medium",
            success_criteria=f"the objective '{task.objective}' has been accomplished",
        )
        return TaskGraph(task_id=task.id, objective=task.objective, steps=[step])

    async def replan(self, task: Task, failure_context: dict[str, Any]) -> TaskGraph:
        step = Step(
            description=(
                f"Retry the objective '{task.objective}', taking into account this "
                f"prior failure: {failure_context}"
            ),
            tool_hint="openclaw",
            risk_level="medium",
            success_criteria=f"the objective '{task.objective}' has been accomplished",
        )
        return TaskGraph(task_id=task.id, objective=task.objective, steps=[step])
