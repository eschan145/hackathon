"""Asyncio-based pub/sub event bus.

The Orchestrator publishes Events at every FSM transition; the GUI,
Memory subsystem, and audit logger subscribe. Handlers run as independent
asyncio tasks so a slow/misbehaving subscriber (e.g. a GUI redraw) never
blocks the orchestrator's own progress.

Kivy's GUI runs on the main thread while the orchestrator runs on a
background thread with its own asyncio loop (ARCHITECTURE.md section 10).
`publish_threadsafe` lets the GUI thread hand an Event to that loop safely.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable

from core.events import Event, EventType

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventBus:
    """Simple in-process asyncio pub/sub bus.

    Not thread-safe by itself for `publish` (must be called from the loop
    thread) — use `publish_threadsafe` from other threads.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop
        self._subscribers: dict[EventType, list[Handler]] = defaultdict(list)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record which running loop this bus is attached to.

        Required before publish_threadsafe can be used from another thread.
        """
        self._loop = loop

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Register an async handler for a given event type."""
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Handler) -> None:
        try:
            self._subscribers[event_type].remove(handler)
        except ValueError:
            pass

    def publish(self, event: Event) -> None:
        """Publish an event, dispatching each subscriber as a fire-and-forget task.

        Must be called from within the event loop thread (i.e. from async
        orchestrator code). Handler exceptions are logged, not raised, so
        one bad subscriber can't break the orchestrator.
        """
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            task = asyncio.ensure_future(self._run_handler(handler, event))
            # Keep a reference alive isn't strictly required since
            # ensure_future schedules on the running loop, but we avoid
            # "Task was destroyed but it is pending" warnings by letting
            # the loop own it; no further action needed here.
            _ = task

    async def _run_handler(self, handler: Handler, event: Event) -> None:
        try:
            await handler(event)
        except Exception:  # noqa: BLE001 - subscriber isolation by design
            logger.exception("EventBus handler %r raised for event %s", handler, event.type)

    def publish_threadsafe(self, event: Event) -> None:
        """Thread-safe publish for callers outside the bus's event loop (e.g. GUI thread).

        Requires bind_loop() to have been called with the orchestrator's
        running loop first.
        """
        if self._loop is None:
            raise RuntimeError("EventBus.bind_loop() must be called before publish_threadsafe()")
        asyncio.run_coroutine_threadsafe(self._publish_async(event), self._loop)

    async def _publish_async(self, event: Event) -> None:
        self.publish(event)
