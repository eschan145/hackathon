# core/

Central FSM, event bus, and shared data models. This is the hub other
subsystems plug into — it should rarely change once the interfaces below
are agreed on.

## Files

- `events.py` — `EventType` enum + `Event` dataclass published on every FSM transition.
- `models.py` — Pydantic `Step`, `TaskGraph`, `ActionResult`, `Task` — the exact schema that crosses subsystem boundaries.
- `event_bus.py` — asyncio pub/sub `EventBus`. Use `subscribe(event_type, async_handler)`; use `publish_threadsafe` when calling from the Kivy GUI thread into the orchestrator's loop.
- `interfaces.py` — `Planner`, `Executor`, `Verifier`, `Memory` Protocols. **This is the contract other modules build against.**
- `orchestrator.py` — `Orchestrator.run_task(objective, source)` drives one `Task` through `RECEIVED -> PLANNING -> EXECUTING <-> VERIFYING -> (REPLANNING) -> COMPLETED | FAILED | AWAITING_APPROVAL`.

## Wiring

`Orchestrator(planner, executor, verifier, memory, event_bus=...)` takes four
duck-typed objects. It never imports `planning/`, `execution/`,
`verification/`, or `memory/` directly — only the Protocols in
`interfaces.py`. Implement these exact async method signatures:

```python
class Planner(Protocol):
    async def create_plan(self, task: Task) -> TaskGraph: ...
    async def replan(self, task: Task, failure_context: dict) -> TaskGraph: ...

class Executor(Protocol):
    async def execute(self, step: Step, task: Task) -> ActionResult: ...

class Verifier(Protocol):
    async def verify(self, step: Step, action_result: ActionResult) -> tuple[bool, dict]: ...

class Memory(Protocol):
    async def save_task(self, task: Task) -> None: ...
    async def get_similar_workflow(self, objective: str) -> TaskGraph | None: ...
```

Any class with matching method signatures satisfies these (no inheritance
required — they're `typing.Protocol`, checked structurally).

## Behavior other modules should know about

- **Dependency graph**: the orchestrator only dispatches a `Step` once every
  id in `Step.depends_on` has reached status `"verified"` in the current
  `TaskGraph`. Steps with no unmet deps and `exclusive=False` run
  concurrently via `asyncio.gather`; `exclusive=True` steps run alone.
- **Retries**: on verify failure, the orchestrator retries the *same* step
  (calling `Executor.execute` again) up to `max_retries` times with
  exponential backoff, then marks it `"failed"` and calls
  `Planner.replan(task, failure_context)`.
- **Circuit breaker**: if a `(step.id, step.tool_hint)` pair fails
  repeatedly within a rolling time window, retries stop early and the
  branch is failed immediately (avoids infinite retry loops on a broken
  backend) — see `CircuitBreaker` in `orchestrator.py`.
- **High risk steps**: any `Step.risk_level == "high"` currently always
  triggers `EventType.APPROVAL_REQUIRED` and pauses that branch — the GUI
  is expected to subscribe to that event and resume/cancel the task (resume
  path is a TODO left for the gui/ + memory/ integration).
- **Persistence**: `Memory.save_task` is called after every state
  transition, so `memory/` should make this fast and idempotent — it's the
  crash-recovery checkpoint described in ARCHITECTURE.md section 11.
- **Workflow cache**: before planning, the orchestrator calls
  `Memory.get_similar_workflow(objective)`; if it returns a `TaskGraph`, the
  orchestrator reuses it directly (resetting step statuses) instead of
  calling `Planner.create_plan`.
- **Events**: subscribe via `orchestrator.event_bus.subscribe(EventType.X, handler)`
  where `handler` is `async def handler(event: Event) -> None`. From a
  non-asyncio thread (e.g. Kivy's main thread), call
  `event_bus.publish_threadsafe(event)` instead of `publish`, after the bus
  has been bound to the orchestrator's running loop via `bind_loop()`.
- **Completion summary**: `Orchestrator._synthesize_summary` is a plain
  string synthesis today (no LLM call) — there's an explicit comment marking
  it as the place to plug in a local summarizer LLM later.
