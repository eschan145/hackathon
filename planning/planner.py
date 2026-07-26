"""LLM-backed Planner implementation (satisfies core.interfaces.Planner).

`LLMPlanner.create_plan` decomposes a Task's objective into a `TaskGraph`
via the local reasoning LLM. `LLMPlanner.replan` asks the LLM to produce a
patched subgraph that replaces only the failed branch, reusing all steps
that already succeeded.
"""

from __future__ import annotations

from typing import Any, Optional

from core.models import Task, TaskGraph
from planning.llm_client import LocalLLMClient
from planning.prompts import (
    DECOMPOSITION_SYSTEM_PROMPT,
    REPLAN_SYSTEM_PROMPT,
    build_decomposition_user_prompt,
    build_replan_user_prompt,
)
from planning.task_graph import validate_dag


class LLMPlanner:
    """Planner that decomposes/replans objectives using a local LLM.

    Conforms to the `core.interfaces.Planner` Protocol structurally (no
    inheritance needed — Protocols are duck-typed).
    """

    def __init__(self, llm_client: Optional[LocalLLMClient] = None) -> None:
        self.llm_client = llm_client or LocalLLMClient()

    async def create_plan(self, task: Task) -> TaskGraph:
        """Decompose `task.objective` into a DAG of Steps via the LLM.

        Pulls prior task.history (if any, e.g. from a resumed/checkpointed
        task) into the prompt as loose memory context — the Memory
        subsystem's richer context (past workflows, contacts, preferences)
        is expected to be merged in by the Orchestrator before calling
        this, via a fuller `task.history`/future context field; we pass
        through whatever's already on the Task object.
        """
        memory_context: dict[str, Any] | None = None
        if task.history:
            memory_context = {"task_history": task.history}

        user_prompt = build_decomposition_user_prompt(
            task_id=task.id,
            objective=task.objective,
            memory_context=memory_context,
        )

        graph = await self.llm_client.complete_structured(
            system_prompt=DECOMPOSITION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=TaskGraph,
        )

        # Defensive fixups: make sure the model echoed the right ids, and
        # that the produced graph is actually a DAG before handing it back
        # to the Orchestrator.
        graph.task_id = task.id
        graph.objective = task.objective
        validate_dag(graph)
        return graph

    async def replan(self, task: Task, failure_context: dict[str, Any]) -> TaskGraph:
        """Produce a patched TaskGraph after a step's retries are exhausted.

        `failure_context` is expected to contain at least the failed step
        id and details (error message / verifier output / screen
        description) per the `core.interfaces.Planner.replan` contract.
        Steps already `status == "verified"` in `task.graph` are preserved
        verbatim by instruction to the LLM; we also enforce it defensively
        below in case the model drops or mutates them.
        """
        if task.graph is None:
            # No existing graph to patch (e.g. failure occurred before any
            # plan existed) — fall back to a fresh plan.
            return await self.create_plan(task)

        current_graph = task.graph
        user_prompt = build_replan_user_prompt(
            task_id=task.id,
            objective=task.objective,
            current_graph_json=current_graph.model_dump(),
            failure_context=failure_context,
        )

        patched = await self.llm_client.complete_structured(
            system_prompt=REPLAN_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=TaskGraph,
        )

        patched.task_id = task.id
        patched.objective = task.objective

        # Defensively re-splice: any step that was "verified" in the
        # original graph and is still present in the patched graph should
        # keep its verified status/fields, in case the LLM altered it.
        verified_by_id = {s.id: s for s in current_graph.steps if s.status == "verified"}
        for step in patched.steps:
            if step.id in verified_by_id:
                original = verified_by_id[step.id]
                step.description = original.description
                step.tool_hint = original.tool_hint
                step.depends_on = list(original.depends_on)
                step.risk_level = original.risk_level
                step.success_criteria = original.success_criteria
                step.status = "verified"

        # Make sure every previously-verified step is actually still
        # present (the LLM was told to keep them; if it dropped one,
        # re-add it so downstream dependents don't dangle).
        present_ids = {s.id for s in patched.steps}
        for step_id, original in verified_by_id.items():
            if step_id not in present_ids:
                patched.steps.append(original.model_copy())

        validate_dag(patched)
        return patched
