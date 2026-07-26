"""Protocol interfaces the Orchestrator depends on.

Other subsystems (planning/, execution/, verification/, memory/) implement
these Protocols. The Orchestrator only ever calls through these contracts,
so any conforming implementation can be swapped in without touching
core/orchestrator.py (see ARCHITECTURE.md section 14, Scalability /
Extensibility).

Protocols are used (rather than ABCs) so implementations don't need to
inherit from anything here — plain duck-typed classes satisfy the type
checker as long as method signatures match.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from core.models import ActionResult, Step, Task, TaskGraph


@runtime_checkable
class Planner(Protocol):
    """Produces and revises TaskGraphs for an objective.

    Implemented by planning/. May call a local reasoning LLM and pull
    Memory context (past workflows, preferences) before returning.
    """

    async def create_plan(self, task: Task) -> TaskGraph:
        """Decompose task.objective into a DAG of Steps.

        `task` is provided (not just the objective string) so the planner
        can use task.id, task.source, and any prior task.history.
        """
        ...

    async def replan(self, task: Task, failure_context: dict[str, Any]) -> TaskGraph:
        """Produce a patched TaskGraph after a step's retries are exhausted.

        `failure_context` should include at minimum: the failed step id,
        the last ActionResult, and the verifier's failure details, so the
        planner can reason about *why* it failed rather than blindly
        redoing the whole task.
        """
        ...


@runtime_checkable
class Executor(Protocol):
    """Performs a single Step's action against the real desktop/OS/SaaS.

    Implemented by execution/. Resolves Step.description /
    Step.tool_hint to a concrete ControlBackend action (native input,
    OpenClaw/NemoClaw grounding, or an MCP tool call) and returns evidence
    for Verification.
    """

    async def execute(self, step: Step, task: Task) -> ActionResult:
        ...


@runtime_checkable
class Verifier(Protocol):
    """Checks whether a Step's ActionResult satisfies its success_criteria.

    Implemented by verification/. Returns (success, details) where
    `details` is a free-form dict suitable for storing on the Task history
    and for feeding into Planner.replan's failure_context on failure.
    """

    async def verify(self, step: Step, action_result: ActionResult) -> tuple[bool, dict[str, Any]]:
        ...


@runtime_checkable
class Memory(Protocol):
    """Unified MemoryStore facade (SQLite + vector store), per ARCHITECTURE.md section 8.

    Implemented by memory/. The Orchestrator persists state after every
    transition via save_task, and checks get_similar_workflow before
    invoking the Planner so previously-successful workflows can be reused.
    """

    async def save_task(self, task: Task) -> None:
        ...

    async def get_similar_workflow(self, objective: str) -> Optional[TaskGraph]:
        ...
