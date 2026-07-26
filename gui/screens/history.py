"""HistoryScreen: past tasks list + replay stub.

ARCHITECTURE.md section 10 ("HistoryScreen (past tasks, replay/reuse)")
and section 12 (audit log "viewable in the GUI History screen"). Pulls
from `memory.store.MemoryStore.list_recent_tasks` when available; memory/
is being built concurrently, so the import is optional and this screen
falls back to an empty/placeholder list rather than crashing.
"""

from __future__ import annotations

import logging
from typing import Any

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen

try:
    from memory.store import MemoryStore  # noqa: F401
    _MEMORY_AVAILABLE = True
except Exception:  # pragma: no cover - memory/ may not exist yet
    MemoryStore = None  # type: ignore[assignment,misc]
    _MEMORY_AVAILABLE = False

logger = logging.getLogger(__name__)


class HistoryScreen(Screen):
    """Lists past tasks pulled from MemoryStore, with a Replay stub button."""

    def on_pre_enter(self, *args) -> None:
        self.refresh()

    def refresh(self) -> None:
        container = self.ids.get("history_list")
        if container is None:
            return
        container.clear_widgets()

        tasks = self._load_recent_tasks()
        if not tasks:
            container.add_widget(
                Label(
                    text=(
                        "No task history available yet."
                        if _MEMORY_AVAILABLE
                        else "Memory subsystem not yet available (memory/ is under construction)."
                    ),
                    size_hint_y=None,
                    height=40,
                )
            )
            return

        for task in tasks:
            container.add_widget(self._build_row(task))

    def _load_recent_tasks(self) -> list[Any]:
        if not _MEMORY_AVAILABLE:
            return []
        app = App.get_running_app()
        memory = getattr(app, "memory", None)
        if memory is None or not hasattr(memory, "list_recent_tasks"):
            return []
        try:
            result = memory.list_recent_tasks(limit=25)
            # list_recent_tasks may be async; best-effort sync call only.
            return result if isinstance(result, list) else []
        except Exception:
            logger.exception("Failed to load recent tasks from MemoryStore")
            return []

    def _build_row(self, task: Any) -> BoxLayout:
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=44, spacing=8)
        objective = getattr(task, "objective", str(task))
        state = getattr(task, "state", "?")
        row.add_widget(Label(text=f"{objective}  [{state}]", halign="left"))
        replay_btn = Button(text="Replay", size_hint_x=None, width=100)
        replay_btn.bind(on_release=lambda *_: self._replay(task))
        row.add_widget(replay_btn)
        return row

    def _replay(self, task: Any) -> None:
        """Stub: replay is a future feature (workflow-cache reuse, section 8)."""
        objective = getattr(task, "objective", "")
        logger.info("Replay requested for task: %s (stub, not yet implemented)", objective)
        home = self.manager.get_screen("home")
        objective_input = home.ids.get("objective_input")
        if objective_input is not None:
            objective_input.text = objective
        self.manager.current = "home"
