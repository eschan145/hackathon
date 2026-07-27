"""Constructs the real Orchestrator for the FastAPI backend.

Relocated from the now-deleted gui/main.py. Unlike that module, this one
doesn't do a "is a local LLM endpoint reachable" reachability dance before
choosing a planner/verifier implementation: the vision->OpenClaw-model->
interpreter pipeline is the only pipeline now, and `openclaw infer model
run` (via an authenticated `openclaw` CLI) is assumed to be present on this
hackathon demo box. If it isn't, we still construct a real
VisionAgentPlanner rather than silently swapping in a no-op stub -- letting
the real OpenClawModelClient surface the failure per-turn is far more
useful for debugging than a stub that always reports success.

Memory is the one subsystem that keeps a fallback: a fresh checkout may not
have its sqlite dir set up yet, so we fall back to an in-process stub
rather than blocking startup on that.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any, Optional

from core.event_bus import EventBus
from core.models import Task, TaskGraph
from core.orchestrator import Orchestrator
from execution.executor import ActionExecutor
from planning.vision_agent_planner import VisionAgentPlanner
from verification.verifier import DeterministicVerifier

logger = logging.getLogger(__name__)


class _StubMemory:
    """In-process, non-persistent stand-in for MemoryStore.

    Used only if memory/store.py's MemoryStore can't be constructed (e.g.
    its sqlite/Chroma directories aren't set up yet on a fresh checkout).
    """

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._conversations: dict[str, list[dict[str, Any]]] = {}

    async def save_task(self, task: Task) -> None:
        self._tasks[task.id] = task

    async def get_similar_workflow(self, objective: str) -> Optional[TaskGraph]:
        return None

    async def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    async def delete_task(self, task_id: str) -> bool:
        self._conversations.pop(task_id, None)
        return self._tasks.pop(task_id, None) is not None

    async def list_conversation_messages(self, task_id: str) -> list[dict[str, Any]]:
        return list(self._conversations.get(task_id, []))

    async def append_conversation_message(
        self, task_id: str, message_id: str, role: str, text: str, created_at: float
    ) -> dict[str, Any]:
        messages = self._conversations.setdefault(task_id, [])
        message = {
            "id": message_id,
            "task_id": task_id,
            "role": role,
            "text": text,
            "created_at": created_at,
        }
        if not any(existing["id"] == message_id for existing in messages):
            messages.append(message)
        return message

    def list_recent_tasks(self, limit: int = 25) -> list[Task]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)[:limit]


def _build_memory() -> Any:
    try:
        from memory.store import MemoryStore

        return MemoryStore()
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory/ not usable yet (%s); using in-memory stub", exc)
        return _StubMemory()


def build_orchestrator() -> tuple[Orchestrator, Any]:
    """Construct the Orchestrator with the real subsystems.

    Logs a clear, loud warning (not a silent stub swap) if the `openclaw`
    CLI isn't on PATH, since every real objective depends on it -- but still
    constructs a real VisionAgentPlanner regardless (it'll surface the
    error per-turn via its own OpenClawModelClient, which is more useful
    for debugging than falling back to a stub that always no-ops).
    """
    openclaw_path = shutil.which("openclaw")
    if openclaw_path is None:
        logger.warning("openclaw CLI not found on PATH; objectives will fail until it's installed")
    else:
        logger.info("openclaw CLI found at %s", openclaw_path)

    planner = VisionAgentPlanner()
    executor = ActionExecutor()
    verifier = DeterministicVerifier()
    memory = _build_memory()
    event_bus = EventBus()

    orchestrator = Orchestrator(
        planner=planner,
        executor=executor,
        verifier=verifier,
        memory=memory,
        event_bus=event_bus,
    )
    return orchestrator, memory
