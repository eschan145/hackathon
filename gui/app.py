"""Kivy App entrypoint wiring: GUI thread <-> orchestrator asyncio thread.

ARCHITECTURE.md section 10:
  "GUI runs on the main thread; orchestrator runs in an asyncio loop on a
  background thread, communicating via a thread-safe queue (Clock.schedule_once
  to marshal events back to Kivy's main loop) — keeps the UI responsive
  during long-running autonomous execution."

`AssistantApp` owns:
  - the background thread running its own asyncio event loop
    (`asyncio.new_event_loop()` + `loop.run_forever()`)
  - a `GuiEventBridge` subscribed to every EventType on the orchestrator's
    EventBus, which marshals each Event to the Kivy main thread via
    `Clock.schedule_once` and forwards it to the active TaskScreen.

The orchestrator instance itself (with planner/executor/verifier/memory
already wired, real or stub) is constructed by gui/main.py and passed in,
so this module has no opinion about which implementations are live.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder

from core.event_bus import EventBus
from core.events import Event, EventType
from core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

KV_PATH = Path(__file__).resolve().parent / "assistant.kv"

ALL_EVENT_TYPES = list(EventType)


class GuiEventBridge:
    """Subscribes to every EventType and marshals events onto the Kivy thread.

    Each orchestrator-thread `publish` fires this bridge's async handler
    (on the orchestrator's own loop). The handler schedules the actual UI
    update via `Clock.schedule_once`, which Kivy guarantees runs on the
    main/GUI thread on the next frame.
    """

    def __init__(self, event_bus: EventBus, on_event) -> None:
        self._on_event = on_event
        for event_type in ALL_EVENT_TYPES:
            event_bus.subscribe(event_type, self._handle)

    async def _handle(self, event: Event) -> None:
        Clock.schedule_once(lambda dt: self._on_event(event), 0)


class AssistantApp(App):
    """Main Kivy application: screens, background orchestrator loop, event bridge."""

    def __init__(self, orchestrator: Orchestrator, memory: Optional[Any] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.orchestrator = orchestrator
        self.memory = memory
        self.event_bus: EventBus = orchestrator.event_bus

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._current_task_future: Optional[Future] = None
        self._current_task: Any = None
        self._paused: bool = False
        self._latest_screenshot_path: Optional[str] = None

        self._bridge = GuiEventBridge(self.event_bus, self._on_event)

    # -- Kivy lifecycle ---------------------------------------------------

    def build(self):
        self.title = "Autonomous Desktop Assistant"
        return Builder.load_file(str(KV_PATH))

    def on_start(self) -> None:
        self._start_background_loop()

    def on_stop(self) -> None:
        self._stop_background_loop()

    # -- background asyncio loop -------------------------------------------

    def _start_background_loop(self) -> None:
        ready = threading.Event()

        def _run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self.event_bus.bind_loop(loop)
            ready.set()
            try:
                loop.run_forever()
            finally:
                loop.close()

        self._loop_thread = threading.Thread(target=_run_loop, name="orchestrator-loop", daemon=True)
        self._loop_thread.start()
        ready.wait(timeout=5)

    def _stop_background_loop(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=2)

    # -- API used by screens ------------------------------------------------

    def submit_objective(self, objective: str) -> None:
        """Submit an objective to the orchestrator from the GUI thread."""
        if self._loop is None:
            logger.error("Background event loop not running; cannot submit objective")
            return

        async def _run() -> Any:
            return await self.orchestrator.run_task(objective, source="gui")

        self._current_task = None
        self._current_task_future = asyncio.run_coroutine_threadsafe(_run(), self._loop)

        def _on_done(fut: Future) -> None:
            try:
                self._current_task = fut.result()
            except Exception:
                logger.exception("run_task failed for objective: %s", objective)

        self._current_task_future.add_done_callback(_on_done)

    def get_current_task(self) -> Any:
        """Best-effort accessor for the in-flight/most-recent Task record.

        Only populated once run_task's future resolves (the Orchestrator
        doesn't currently expose the live, in-progress Task object) —
        screens should treat this as "may be None or stale" and rely
        primarily on the incremental Event payloads instead.
        """
        return self._current_task

    def get_latest_screenshot_path(self) -> Optional[str]:
        """Path to the most recent screenshot for the TaskScreen preview.

        TODO(vision integration): once vision/ exposes a ring buffer of
        frames (ARCHITECTURE.md section 9), wire this up to read the
        latest frame path instead of returning whatever was last recorded
        from an ActionResult.screenshot_ref in an event payload.
        """
        return self._latest_screenshot_path

    def resolve_approval(self, step_id: str, approved: bool) -> None:
        """User's Approve/Deny decision for a high-risk step.

        TODO(orchestrator integration): the current Orchestrator.run_task
        stops at AWAITING_APPROVAL and returns rather than exposing a
        resume-with-decision hook. Once that hook exists, call it here via
        run_coroutine_threadsafe. For now this just logs the decision so
        the demo doesn't crash when a HIGH risk step is encountered.
        """
        logger.info("Approval decision for step %s: %s", step_id, "approved" if approved else "denied")

    def set_paused(self, paused: bool) -> None:
        """Pause/resume toggle.

        TODO(orchestrator integration): Orchestrator has no pause hook yet;
        this just tracks GUI-side state for the demo.
        """
        self._paused = paused

    def cancel_current_task(self) -> None:
        if self._current_task_future is not None and not self._current_task_future.done():
            self._current_task_future.cancel()

    # -- event bridge callback (runs on Kivy main thread) --------------------

    def _on_event(self, event: Event) -> None:
        payload = event.payload or {}
        screenshot_ref = payload.get("screenshot_ref") or (payload.get("details") or {}).get("screenshot_ref")
        if screenshot_ref:
            self._latest_screenshot_path = screenshot_ref

        task_screen = self.root.get_screen("task") if self.root else None
        if task_screen is not None:
            try:
                task_screen.handle_event(event)
            except Exception:
                logger.exception("TaskScreen failed to handle event %s", event.type)
