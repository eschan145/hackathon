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
from core.models import (
    ActionResult,
    ObjectiveContract,
    ProcedureCandidate,
    Step,
    Task,
    TaskGraph,
)

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
        max_actions: int = 60,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.verifier = verifier
        self.memory = memory
        self.event_bus = event_bus or EventBus()
        self.max_retries = max_retries
        self.max_replans = max_replans
        # Safety cap on the total number of Steps the agentic
        # Planner.next_actions loop (see run_task) is allowed to append
        # over the lifetime of a task, so a planner that never converges
        # can't spin forever burning model calls.
        self.max_actions = max_actions
        self._actions_run = 0
        self._sem = asyncio.Semaphore(max_concurrency)
        self._breaker = CircuitBreaker()
        # step_id -> Future[bool] for HIGH risk steps awaiting a human
        # approve/deny decision (see resolve_approval()). This is the
        # resume hook that was previously a TODO: instead of _run_step
        # returning "await_approval" and run_task giving up, the step's
        # coroutine now blocks on this future until an API/GUI caller
        # resolves it, then continues (or fails->replans) accordingly.
        self._pending_approvals: dict[str, "asyncio.Future[bool]"] = {}

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

    async def run_task(
        self,
        objective: str,
        source: str = "gui",
        objective_contract: Optional[ObjectiveContract] = None,
    ) -> Task:
        """Run one objective end-to-end and return the final Task record.

        Wraps the actual run in a CancelledError handler so that a caller
        cancelling the backing asyncio.Task (backend/main.py's
        POST /api/tasks/{id}/cancel does exactly this) leaves behind a
        correctly-terminal CANCELLED record instead of the task staying
        stuck forever at whatever transient state (VERIFYING, REPLANNING,
        ...) it happened to be in when the cancellation landed - previously
        nothing ever persisted a state change on cancellation, so a
        cancelled task looked identical to a hung one to anyone querying it
        afterward.
        """
        task = Task(
            objective=objective,
            source=source,
            state="RECEIVED",
            objective_contract=objective_contract,
        )
        if objective_contract is not None:
            task.record(
                "objective_contract_created",
                contract_id=objective_contract.id,
                source_id=objective_contract.source_id,
                permissions=objective_contract.permissions,
                prohibited_actions=objective_contract.prohibited_actions,
                verification_requirements=objective_contract.verification_requirements,
            )
        self._emit(EventType.OBJECTIVE_RECEIVED, task, objective=objective, source=source)
        await self.memory.save_task(task)

        try:
            return await self._run_task_body(task, objective)
        except asyncio.CancelledError:
            await self._transition(task, "CANCELLED", reason="cancelled_by_caller")
            self._emit(EventType.TASK_CANCELLED, task)
            await self.memory.save_task(task)
            raise

    async def _run_task_body(self, task: Task, objective: str) -> Task:
        await self._transition(task, "PLANNING")

        try:
            # Prefer a cached workflow over invoking the planner from scratch
            # (ARCHITECTURE.md section 8 — workflow cache).
            # An email contract is a new, parameterized run. Never silently
            # replay a merely-similar workflow before the user has promoted
            # one into an explicit procedure.
            cached = (
                None
                if task.objective_contract is not None
                else await self.memory.get_similar_workflow(objective)
            )
            if cached is not None:
                graph = cached.model_copy(update={"task_id": task.id})
                # Reset any leftover step statuses from the cached graph so it
                # re-executes cleanly for this new task.
                for s in graph.steps:
                    s.status = "pending"
                    s.retry_count = 0
            else:
                graph = await self.planner.create_plan(task)
        except Exception as exc:  # noqa: BLE001
            # Without this, a planner/memory error (e.g. no local LLM
            # endpoint reachable) leaves the task stuck at PLANNING forever
            # with no signal to the caller/UI — surface it as a real failure
            # instead.
            await self._transition(task, "FAILED", reason=f"planning_error: {exc}")
            self._emit(EventType.TASK_FAILED, task, reason=f"planning_error: {exc}")
            await self.memory.save_task(task)
            return task

        task.graph = graph
        self._emit(EventType.PLAN_GENERATED, task, step_count=len(graph.steps))
        await self._transition(task, "EXECUTING")

        replans_used = 0
        awaiting_approval = False

        # NOTE: this used to be `while self._has_pending_work(graph) and not
        # awaiting_approval:`, with a bare `break` whenever `_ready_steps`
        # came back empty. That collapsed two different situations into
        # one exit: a real dependency deadlock among pre-existing steps,
        # and "nothing left to do" (which used to only mean "the DAG
        # finished"). The condition now lives inside the loop body so we
        # can tell those apart and, in the second case, give the agentic
        # Planner.next_actions a chance to contribute more work before
        # falling through to completion — including when `graph.steps`
        # starts out empty (an agentic Planner may not pre-compute a DAG
        # at all), which the old `_has_pending_work`-gated while condition
        # would never even have entered the loop for.
        while not awaiting_approval:
            ready = self._ready_steps(graph)
            if not ready:
                if self._has_pending_work(graph):
                    # Nothing ready but pending/running steps remain ->
                    # a genuine dependency deadlock among pre-existing
                    # steps. Preserve the old behavior: bail out to the
                    # completion/failure checks below.
                    break

                # Nothing ready and nothing pending/running either -> the
                # pre-computed DAG (if any) is fully resolved but the
                # objective hasn't been declared complete. This is the
                # agentic planner's turn to contribute more work based on
                # freshly-observed state (ARCHITECTURE.md's ReAct-style
                # loop) instead of a single up-front plan.
                if self._actions_run >= self.max_actions:
                    await self._transition(task, "FAILED", reason="max_actions_exhausted")
                    self._emit(EventType.TASK_FAILED, task, reason="max_actions_exhausted")
                    return task

                # This is a real, separately-billed model call (plus a fresh
                # screen capture/OCR pass) with no bracketing event before
                # it existed previously - the UI had nothing to show between
                # the prior step's STEP_VERIFIED and this one's STEP_STARTED,
                # so the whole multi-second planning round-trip visually sat
                # under the last step's "Checking the result" bubble instead
                # of its own.
                self._emit(EventType.PLANNING_NEXT_STEP, task)
                new_steps = await self.planner.next_actions(task)
                if not new_steps:
                    # An empty list alone can't distinguish "objective
                    # genuinely complete" (done()) from "agent gave up"
                    # (fail()) or a stalled turn — planning/vision_agent_planner.py
                    # documents that it always records a task.history entry
                    # first (kind in {"agent_done","agent_fail","agent_stall"},
                    # with a "success" bool) precisely so this can be routed
                    # correctly instead of reporting an abandoned objective
                    # as completed. Checked defensively (plain dict .get())
                    # so core/ doesn't need to import planning/.
                    last = task.history[-1] if task.history else {}
                    if last.get("kind") in ("agent_fail", "agent_stall") and last.get("success") is False:
                        reason = last.get("reason") or f"planner_stopped:{last.get('kind')}"
                        await self._transition(task, "FAILED", reason=reason)
                        self._emit(EventType.TASK_FAILED, task, reason=reason)
                        return task
                    # Otherwise the planner says the objective is complete
                    # -> fall through to the existing completion checks.
                    break

                graph.steps.extend(new_steps)
                self._actions_run += len(new_steps)
                continue

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

        if any(s.status in ("pending", "ready", "running") for s in graph.steps):
            # We only reach here by breaking out of the main loop, which
            # happens either because the planner legitimately signaled
            # completion (next_actions()/create_plan() left no non-terminal
            # steps behind) or because _ready_steps() came back empty while
            # pending/running steps remained -- a genuine dependency
            # deadlock (e.g. a Step depending on an id that no longer
            # exists in the graph, which a buggy Planner.replan() could
            # produce). Steps stuck in a non-terminal status here means the
            # latter: don't report success for work that never actually ran.
            await self._transition(task, "FAILED", reason="dependency_deadlock")
            self._emit(EventType.TASK_FAILED, task, reason="dependency_deadlock")
            return task

        if (
            task.objective_contract is not None
            and task.objective_contract.source_kind == "email"
        ):
            try:
                from verification.claim_evidence import verify_contract_report

                evidence_ok, evidence_details = verify_contract_report(
                    task.objective_contract
                )
            except Exception as exc:  # noqa: BLE001
                evidence_ok = False
                evidence_details = {"reason": f"evidence verification error: {exc}"}
            task.record(
                "claim_evidence_verification",
                success=evidence_ok,
                details=evidence_details,
            )
            if not evidence_ok:
                reason = str(
                    evidence_details.get("reason")
                    or "one or more report claims were not source-verified"
                )
                await self._transition(task, "FAILED", reason=reason)
                self._emit(
                    EventType.TASK_FAILED,
                    task,
                    reason=reason,
                    evidence=evidence_details,
                )
                return task

        summary = self._synthesize_summary(task, graph)
        task.record("summary", text=summary)
        if task.objective_contract is not None:
            task.procedure_candidate = ProcedureCandidate(
                name=_procedure_name(task),
                description=(
                    "Reuse the authorized-input, report, evidence, and draft-only "
                    "approval path from this successful run."
                ),
                source_task_id=task.id,
            )
            task.record(
                "procedure_offered",
                procedure_id=task.procedure_candidate.id,
                name=task.procedure_candidate.name,
            )
        await self._transition(task, "COMPLETED", summary=summary)
        self._emit(EventType.TASK_COMPLETED, task, summary=summary)
        if task.procedure_candidate is not None:
            self._emit(
                EventType.PROCEDURE_OFFERED,
                task,
                procedure=task.procedure_candidate.model_dump(),
            )
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
                # says otherwise. Surface the event, transition to
                # AWAITING_APPROVAL, and block this step's coroutine on a
                # Future that resolve_approval() resolves once the
                # GUI/API caller supplies the user's decision.
                self._emit(EventType.APPROVAL_REQUIRED, task, step_id=step.id)
                await self._transition(task, "AWAITING_APPROVAL", step_id=step.id)
                fut: "asyncio.Future[bool]" = self._pending_approvals.setdefault(
                    step.id, asyncio.get_event_loop().create_future()
                )
                approved = await fut
                self._pending_approvals.pop(step.id, None)
                await self._transition(task, "EXECUTING", step_id=step.id)
                if not approved:
                    step.status = "failed"
                    self._emit(
                        EventType.STEP_FAILED,
                        task,
                        step_id=step.id,
                        details={"reason": "user_denied_approval"},
                    )
                    return "replan"
                # else: approved -> fall through and execute normally below.

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
                    self._emit(
                        EventType.STEP_VERIFIED,
                        task,
                        step_id=step.id,
                        details=details,
                        screenshot_ref=action_result.screenshot_ref,
                    )
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
                    screenshot_ref=action_result.screenshot_ref,
                )

                if step.retry_count >= self.max_retries or self._breaker.is_tripped(step):
                    step.status = "failed"
                    return "replan"
                # else: loop and retry. Short flat backoff, not exponential -
                # these are blind mechanical re-attempts of the same action
                # (DeterministicVerifier makes no model call either way), so
                # the only thing worth waiting for is a moment of transient
                # UI lag, not a real backend rate limit.
                await asyncio.sleep(0.75)

    async def resolve_approval(self, task_id: str, step_id: str, approved: bool) -> bool:
        """Resume a step blocked at AWAITING_APPROVAL with the user's decision.

        Called by the API/GUI layer in response to a human approve/deny
        action on a HIGH risk step (ARCHITECTURE.md sections 7 and 10).
        Returns True if a pending approval for step_id was found and
        resolved, False if there was nothing waiting (already resolved,
        unknown step, or task_id mismatch is not checked here since
        step ids are unique per graph).
        """
        fut = self._pending_approvals.get(step_id)
        if fut is None or fut.done():
            return False
        fut.set_result(approved)
        return True

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
        to produce a natural-language completion summary"). For now,
        a deterministic string synthesis is sufficient and
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


def _procedure_name(task: Task) -> str:
    subject = task.objective_contract.objective if task.objective_contract else task.objective
    clean = subject.strip().splitlines()[0]
    return f"{clean[:64]} procedure"
