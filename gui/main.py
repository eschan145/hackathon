"""Entrypoint: wires up the Orchestrator (real subsystems if importable,
no-op stubs otherwise) and launches the Kivy GUI.

This lets the GUI run standalone during development even though
planning/, execution/, verification/, and memory/ are being built
concurrently by other agents/contributors — every subsystem import is
wrapped in try/except and falls back to a minimal stub implementing the
same Protocol from core/interfaces.py (Planner, Executor, Verifier,
Memory), so `python -m gui.main` (or `python gui/main.py`) always starts.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Optional

# Allow running as `python gui/main.py` (script, not module) by ensuring
# the project root is on sys.path so `core`, `planning`, etc. resolve.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.event_bus import EventBus
from core.models import ActionResult, Step, Task, TaskGraph
from core.orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stub subsystem implementations (used only when the real ones can't be
# imported yet). Each satisfies the corresponding Protocol in
# core/interfaces.py just well enough to demo the GUI end-to-end with a
# trivial single-step "plan".
# ---------------------------------------------------------------------------


class _StubPlanner:
    """Produces a single-step trivial plan instead of calling a real LLM."""

    async def create_plan(self, task: Task) -> TaskGraph:
        step = Step(
            description=f"[stub] Pretend to accomplish: {task.objective}",
            tool_hint="stub",
            risk_level="low",
            success_criteria="always true (stub)",
        )
        return TaskGraph(task_id=task.id, objective=task.objective, steps=[step])

    async def replan(self, task: Task, failure_context: dict[str, Any]) -> TaskGraph:
        step = Step(
            description=f"[stub] Retry after failure: {task.objective}",
            tool_hint="stub",
            risk_level="low",
            success_criteria="always true (stub)",
        )
        return TaskGraph(task_id=task.id, objective=task.objective, steps=[step])


class _StubExecutor:
    """Does nothing but report success, so the GUI has events to react to."""

    async def execute(self, step: Step, task: Task) -> ActionResult:
        return ActionResult(success=True, raw_output="[stub executor] no-op", details={"stub": True})


class _StubVerifier:
    """Always verifies successfully."""

    async def verify(self, step: Step, action_result: ActionResult) -> tuple[bool, dict[str, Any]]:
        return True, {"stub": True, "note": "no real verification performed"}


class _StubMemory:
    """In-process, non-persistent stand-in for MemoryStore."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    async def save_task(self, task: Task) -> None:
        self._tasks[task.id] = task

    async def get_similar_workflow(self, objective: str) -> Optional[TaskGraph]:
        return None

    def list_recent_tasks(self, limit: int = 25) -> list[Task]:
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)[:limit]


# ---------------------------------------------------------------------------
# Best-effort real-subsystem wiring
# ---------------------------------------------------------------------------


def _local_llm_reachable() -> bool:
    """Quick synchronous reachability check against config/models.yaml's planning endpoint."""
    try:
        import httpx
        import yaml

        config_path = _PROJECT_ROOT / "config" / "models.yaml"
        base_url = "http://localhost:8000/v1"
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            base_url = cfg.get("planning", {}).get("base_url", base_url)
        httpx.get(base_url.rsplit("/v1", 1)[0] or base_url, timeout=1.5)
        return True
    except Exception:  # noqa: BLE001
        return False


def _build_planner() -> Any:
    try:
        from planning.planner import LLMPlanner

        if _local_llm_reachable():
            return LLMPlanner()
        raise RuntimeError("no local planning-model endpoint reachable (config/models.yaml)")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Local LLM planner not usable yet (%s); falling back to OpenClawPlanner "
            "(delegates the whole objective to OpenClaw's own agent instead of decomposing it)",
            exc,
        )
        try:
            from planning.openclaw_planner import OpenClawPlanner

            return OpenClawPlanner()
        except Exception as exc2:  # noqa: BLE001
            logger.warning("OpenClawPlanner not available either (%s); using no-op stub planner", exc2)
            return _StubPlanner()


def _build_executor() -> Any:
    try:
        from execution.executor import ActionExecutor

        return ActionExecutor()
    except Exception as exc:  # noqa: BLE001
        logger.warning("execution/ not available yet (%s); using stub executor", exc)
        return _StubExecutor()


def _local_vlm_reachable() -> bool:
    """Quick synchronous reachability check against config/models.yaml's vision endpoint."""
    try:
        import httpx
        import yaml

        config_path = _PROJECT_ROOT / "config" / "models.yaml"
        base_url = "http://localhost:8001/v1"
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            base_url = cfg.get("vision", {}).get("base_url", base_url)
        httpx.get(base_url.rsplit("/v1", 1)[0] or base_url, timeout=1.5)
        return True
    except Exception:  # noqa: BLE001
        return False


def _build_verifier() -> Any:
    try:
        from verification.verifier import ActionVerifier

        if _local_vlm_reachable():
            return ActionVerifier()
        raise RuntimeError("no local vision-model endpoint reachable (config/models.yaml)")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Local VLM verifier not usable yet (%s); falling back to OpenClawVerifier "
            "(asks OpenClaw's own agent to judge success instead of defaulting to failure)",
            exc,
        )
        try:
            from verification.openclaw_verifier import OpenClawVerifier

            return OpenClawVerifier()
        except Exception as exc2:  # noqa: BLE001
            logger.warning("OpenClawVerifier not available either (%s); using no-op stub verifier", exc2)
            return _StubVerifier()


def _build_memory() -> Any:
    try:
        from memory.store import MemoryStore

        return MemoryStore()
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory/ not available yet (%s); using in-memory stub", exc)
        return _StubMemory()


def build_orchestrator() -> Orchestrator:
    """Construct an Orchestrator with the best available subsystem implementations.

    Each of planner/executor/verifier/memory is imported lazily and falls
    back to a no-op stub on ImportError/other exceptions, so this function
    (and therefore the whole GUI) works standalone even before the other
    subsystems land.
    """
    planner = _build_planner()
    executor = _build_executor()
    verifier = _build_verifier()
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


def main() -> None:
    from gui.app import AssistantApp

    orchestrator, memory = build_orchestrator()
    app = AssistantApp(orchestrator=orchestrator, memory=memory)
    app.run()


if __name__ == "__main__":
    main()
