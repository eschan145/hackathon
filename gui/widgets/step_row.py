"""Reusable widget: a single row representing one Step's live status.

Used by TaskScreen's plan/step list. Status icon is a plain unicode glyph
(no external icon assets needed for the hackathon demo).
"""

from __future__ import annotations

from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout

STATUS_ICONS: dict[str, str] = {
    "pending": "○",  # hollow circle
    "ready": "○",
    "running": "◐",  # half circle (spinner-ish)
    "verified": "✅",  # check mark
    "failed": "❌",  # cross mark
    "skipped": "➖",  # minus
}

STATUS_COLORS: dict[str, tuple[float, float, float, float]] = {
    "pending": (0.6, 0.6, 0.6, 1),
    "ready": (0.6, 0.6, 0.6, 1),
    "running": (0.95, 0.75, 0.15, 1),
    "verified": (0.25, 0.8, 0.4, 1),
    "failed": (0.9, 0.3, 0.3, 1),
    "skipped": (0.5, 0.5, 0.5, 1),
}


class StepRow(BoxLayout):
    """Displays a step's description + a status icon that updates live.

    Instantiated dynamically by TaskScreen for each Step in the current
    TaskGraph; `step_id` lets TaskScreen find-and-update the right row
    when a STEP_STARTED/STEP_VERIFIED/STEP_FAILED event arrives.
    """

    step_id = StringProperty("")
    description = StringProperty("")
    status = StringProperty("pending")
    status_icon = StringProperty(STATUS_ICONS["pending"])

    def on_status(self, instance: "StepRow", value: str) -> None:
        self.status_icon = STATUS_ICONS.get(value, "?")
