"""Pydantic data models shared across the orchestrator and all subsystems.

These are the concrete shapes that flow across the Planner / Executor /
Verifier / Memory interfaces defined in core/interfaces.py. Keep these
stable — other agents build planning/, execution/, verification/, memory/
against this exact schema.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]

StepStatus = Literal[
    "pending",
    "ready",
    "running",
    "verified",
    "failed",
    "skipped",
]

TaskState = Literal[
    "RECEIVED",
    "PLANNING",
    "EXECUTING",
    "VERIFYING",
    "REPLANNING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "AWAITING_APPROVAL",
]


class Step(BaseModel):
    """A single node in a TaskGraph DAG.

    `depends_on` lists other Step.id values that must reach status
    "verified" before this step is dispatched. `tool_hint` is a free-form
    hint to the Executor about which backend/tool is likely appropriate
    (e.g. "native_input", "openclaw", "mcp:gmail") — the Executor is free
    to resolve it differently.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str
    tool_hint: str = ""
    depends_on: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = "low"
    success_criteria: str = ""
    status: StepStatus = "pending"
    exclusive: bool = False  # if True, never run concurrently with other steps
    retry_count: int = 0
    # Structured action data for the vision-agent pipeline: a plain dict
    # form of planning.action_dsl.Action (via dataclasses.asdict), read back
    # by execution/interpreter.py. Kept as a generic dict (not a typed
    # planning.* import) so core/ never depends on planning/ or execution/.
    action: Optional[dict[str, Any]] = None


class TaskGraph(BaseModel):
    """A DAG of Steps produced by the Planner for a given objective."""

    task_id: str
    objective: str
    steps: list[Step] = Field(default_factory=list)

    def step_by_id(self, step_id: str) -> Optional[Step]:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None


class ActionResult(BaseModel):
    """Result of the Executor performing a single Step's action.

    Returned by Executor.execute() and consumed by Verifier.verify().
    """

    screenshot_ref: Optional[str] = None
    a11y_snapshot: Optional[dict[str, Any]] = None
    raw_output: Optional[str] = None
    success: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    """Top-level record for one objective run through the Orchestrator."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    objective: str
    source: str = "gui"
    state: TaskState = "RECEIVED"
    created_at: float = Field(default_factory=time.time)
    graph: Optional[TaskGraph] = None
    history: list[dict[str, Any]] = Field(default_factory=list)

    def record(self, kind: str, **data: Any) -> None:
        """Append a lightweight history entry (for audit log / debugging)."""
        self.history.append({"kind": kind, "ts": time.time(), **data})
