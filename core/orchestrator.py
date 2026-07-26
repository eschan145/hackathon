"""Central task-lifecycle FSM.

Implements the flow from ARCHITECTURE.md sections 3-4 and 11:

    RECEIVED -> PLANNING -> EXECUTING <-> VERIFYING -> (REPLANNING) ->
    COMPLETED | FAILED | AWAITING_APPROVAL

The Orchestrator only depends on the Protocol interfaces in
core/interfaces.py (Planner, Executor, Verifier, Memory) — it never
imports planning/execution/verification/memory directly. Any module that
implements those Protocols can be wired in via the constructor.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Deque, Optional

from core.event_bus import EventBus
from core.events import Event, EventType
from core.interfaces import Executor, Memory, Planner, Verifier
from core.models import ActionResult, Step, Task, TaskGraph

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Trips when the same (step_id, tool_hint) fails repeatedly in a rolling window.

    Prevents the retry/replan loop from spinning forever on a backend that
    is persistently broken (ARCHITECTURE.md section 11).
    """

    def __init__(self, max_failures: int = 4, window_seconds: float = 120.0) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[str, Deque[float]] = defaultdict(deque)

    def _key(self, step: Step) -> str:
        return f"{step.id}:{step.tool_hint}"

    def record_failure(self, step: Step) -> None:
        now = time.time()
        q = self._failures[self._key(step)]
        q.append(now)
        while q and now - q[0] > self.window_seconds:
            q.popleft()

    def is_tripped(self, step: Step) -> bool:
        now = time.time()
        q = self._failures[self._key(step)]
        while q and now - q[0] > self.window_seconds:
            q.popleft()
        return len(q) >= self.max_failures

    def reset(self, step: Step) -> None:
        self._failures.pop(self._key(step), None)


class Orchestrator:
    """Drives one Task through the lifecycle FSM using injected subsystems."""

    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        verifier: Verifier,
        memory: Memory,
        event_bus: Optional[EventBus] = None,
        max_retries: int = 3,
        max_replans: int = 2,
        max_concurrency: int = 4,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.verifier = verifier
        self.memory = memory
        self.event_bus = event_bus or EventBus()
        self.max_retries = max_retries
        self.max_replans = max_replans
        self._sem = asyncio.Semaphore(max_concurrency)
        self._breaker = CircuitBreaker()

    # -- helpers ---------------------------------------------------------

    def _emit(self, event_type: EventType, task: Task, **payload) -> None:
        self.event_bus.publish(Event(type=event_type, task_id=task.id, payload=payload))

    async def _transition(self, task: Task, state: str, **payload) -> None:
        task.state = state  # type: ignore[assignment]
        task.record("state_transition", state=state, **payload)
        await self.memory.save_task(task)

    def _ready_steps(self, graph: TaskGraph) -> list[Step]:
        """Steps whose dependencies are all verified and that haven't run yet."""
        verified_ids = {s.id for s in graph.steps if s.status == "verified"}
        ready = []
        for step in graph.steps:
            if step.status not in ("pending", "ready"):
                continue
            if all(dep in verified_ids for dep in step.depends_on):
                ready.append(step)
        return ready

    def _has_pending_work(self, graph: TaskGraph) -> bool:
        return any(s.status not in ("verified", "failed", "skipped") for s in graph.steps)

    # -- main entry point --------------------------------------------------

    async def run_task(self, objective: str, source: str = "gui") -> Task:
        """Run one objective end-to-end and return the final Task record."""
        task = Task(objective=objective, source=source, state="RECEIVED")
        self._emit(EventType.OBJECTIVE_RECEIVED, task, objective=objective, source=source)
        await self.memory.save_task(task)

        await self._transition(task, "PLANNING")

        # Prefer a cached workflow over invoking the planner from scratch
        # (ARCHITECTURE.md section 8 — workflow cache).
        cached = await self.memory.get_similar_workflow(objective)
        if cached is not None:
            graph = cached.model_copy(update={"task_id": task.id})
            # Reset any leftover step statuses from the cached graph so it
            # re-executes cleanly for this new task.
            for s in graph.steps:
                s.status = "pending"
                s.retry_count = 0
        else:
            graph = await self.planner.create_plan(task)

        task.graph = graph
        self._emit(EventType.PLAN_GENERATED, task, step_count=len(graph.steps))
        await self._transition(task, "EXECUTING")

        replans_used = 0
        awaiting_approval = False

        while self._has_pending_work(graph) and not awaiting_approval:
            ready = self._ready_steps(graph)
            if not ready:
                # Nothing ready but work remains -> either a dependency
                # deadlock (treat as failure) or steps are mid-flight.
                break

            # Partition into concurrently-runnable vs exclusive steps.
            # Exclusive steps run alone to avoid contending for the same
            # app/window (ARCHITECTURE.md section 5, per-branch isolation).
            exclusive = [s for s in ready if s.exclusive]
            parallel = [s for s in ready if not s.exclusive]

            for s in exclusive:
                s.status = "ready"
            for s in parallel:
                s.status = "ready"

            if exclusive:
                # Run exclusive steps one at a time before/instead of the
                # parallel batch to keep things simple and deterministic.
                for s in exclusive:
                    result = await self._run_step(s, task, graph)
                    if result == "await_approval":
                        awaiting_approval = True
                        break
                if awaiting_approval:
                    break
                continue

            results = await asyncio.gather(*(self._run_step(s, task, graph) for s in parallel))
            if any(r == "await_approval" for r in results):
                awaiting_approval = True
                break

            if any(r == "replan" for r in results):
                if replans_used >= self.max_replans:
                    await self._transition(task, "FAILED", reason="max_replans_exhausted")
                    self._emit(EventType.TASK_FAILED, task, reason="max_replans_exhausted")
                    return task
                replans_used += 1
                failed_step = next(s for s in graph.steps if s.status == "failed")
                await self._replan(task, graph, failed_step)

        if awaiting_approval:
            await self._transition(task, "AWAITING_APPROVAL")
            return task

        if any(s.status == "failed" for s in graph.steps):
            await self._transition(task, "FAILED")
            self._emit(EventType.TASK_FAILED, task, reason="unresolved_failed_steps")
            return task

        summary = self._synthesize_summary(task, graph)
        task.record("summary", text=summary)
        await self._transition(task, "COMPLETED", summary=summary)
        self._emit(EventType.TASK_COMPLETED, task, summary=summary)
        await self.memory.save_task(task)
        return task

    # -- step execution ----------------------------------------------------

    async def _run_step(self, step: Step, task: Task, graph: TaskGraph) -> str:
        """Execute+verify one step with retries. Returns 'ok' | 'replan' | 'await_approval'."""
        async with self._sem:
            step.status = "running"
            self._emit(EventType.STEP_STARTED, task, step_id=step.id, description=step.description)

            if step.risk_level == "high":
                # High-risk actions require human approval before dispatch
                # unless a pre-authorization mechanism (not modeled here)
                # says otherwise. Real approval-handling GUI hook is a TODO
                # for the gui/ subsystem; we surface the event and stop.
                self._emit(EventType.APPROVAL_REQUIRED, task, step_id=step.id)
                return "await_approval"

            while True:
                if self._breaker.is_tripped(step):
                    step.status = "failed"
                    await self._transition(task, "EXECUTING", step_id=step.id, note="circuit_breaker_tripped")
                    return "replan"

                action_result: ActionResult = await self.executor.execute(step, task)
                await self._transition(task, "VERIFYING", step_id=step.id)
                success, details = await self.verifier.verify(step, action_result)

                if success:
                    step.status = "verified"
                    self._emit(EventType.STEP_VERIFIED, task, step_id=step.id, details=details)
                    await self._transition(task, "EXECUTING", step_id=step.id)
                    return "ok"

                step.retry_count += 1
                self._breaker.record_failure(step)
                self._emit(
                    EventType.STEP_FAILED,
                    task,
                    step_id=step.id,
                    details=details,
                    retry_count=step.retry_count,
                )

                if step.retry_count >= self.max_retries or self._breaker.is_tripped(step):
                    step.status = "failed"
                    return "replan"
                # else: loop and retry (exponential backoff)
                await asyncio.sleep(min(2 ** step.retry_count, 30))

    async def _replan(self, task: Task, graph: TaskGraph, failed_step: Step) -> None:
        await self._transition(task, "REPLANNING", step_id=failed_step.id)
        failure_context = {
            "step_id": failed_step.id,
            "description": failed_step.description,
            "retry_count": failed_step.retry_count,
            "history": [h for h in task.history if h.get("step_id") == failed_step.id],
        }
        new_graph = await self.planner.replan(task, failure_context)
        task.graph = new_graph
        self._emit(EventType.REPLANNED, task, step_id=failed_step.id, new_step_count=len(new_graph.steps))
        # Mutate graph in place so the running loop's reference stays valid.
        graph.steps = new_graph.steps
        await self._transition(task, "EXECUTING")

    # -- completion summary --------------------------------------------------

    def _synthesize_summary(self, task: Task, graph: TaskGraph) -> str:
        """Produce a simple natural-language completion summary.

        Extension point: swap this for a call to a local summarizer LLM
        (per ARCHITECTURE.md section 3, step 8 — "asks the summarizer LLM
        to produce a natural-language completion summary"). For the
        hackathon demo, a deterministic string synthesis is sufficient and
        avoids an extra inference round trip on the completion path.

        e.g. replace the body below with:
            return await self.summarizer.summarize(task, graph)
        where `summarizer` implements a `Summarizer` Protocol analogous to
        the others in core/interfaces.py.
        """
        verified = [s for s in graph.steps if s.status == "verified"]
        return (
            f"Completed '{task.objective}': {len(verified)}/{len(graph.steps)} "
            f"steps succeeded."
        )
