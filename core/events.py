"""Typed events for the orchestrator's pub/sub event bus.

See docs/ARCHITECTURE.md sections 1-4 and 11: every FSM transition in the
Orchestrator is emitted as an Event so the GUI, Memory subsystem, and any
other subscriber can react without being coupled to the orchestrator
internals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """All event kinds published on the EventBus.

    Named to mirror the task lifecycle FSM in ARCHITECTURE.md section 4:
    RECEIVED -> PLANNING -> EXECUTING <-> VERIFYING -> (REPLANNING) ->
    COMPLETED | FAILED | AWAITING_APPROVAL
    """

    OBJECTIVE_RECEIVED = "objective_received"
    PLAN_GENERATED = "plan_generated"
    PLANNING_NEXT_STEP = "planning_next_step"
    STEP_STARTED = "step_started"
    STEP_VERIFIED = "step_verified"
    STEP_FAILED = "step_failed"
    REPLANNED = "replanned"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    APPROVAL_REQUIRED = "approval_required"


@dataclass
class Event:
    """A single event flowing through the EventBus.

    Attributes:
        type: The kind of event (see EventType).
        task_id: The Task this event pertains to.
        payload: Free-form event-specific data (e.g. {"step_id": ..,
            "action_result": ..}). Keep JSON-serializable so it can be
            persisted/logged/sent to the GUI without extra work.
        timestamp: Unix epoch seconds when the event was created.
    """

    type: EventType
    task_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
