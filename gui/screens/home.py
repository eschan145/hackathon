"""HomeScreen: objective input + quick-source pickers + Run button.

ARCHITECTURE.md section 10: "HomeScreen (objective input + quick source
pickers)". Quick-source buttons are demo stubs that just prefill an
example objective string for the corresponding integration (Todoist,
Gmail, Calendar, Files) rather than actually querying those services.
"""

from __future__ import annotations

from kivy.app import App
from kivy.uix.screenmanager import Screen

QUICK_SOURCE_EXAMPLES: dict[str, str] = {
    "todoist": "Complete my top 3 overdue Todoist tasks",
    "gmail": "Reply to unread emails from my manager with a short status update",
    "calendar": "Find a free 30-minute slot tomorrow and schedule a call with Alex",
    "files": "Organize my Downloads folder into dated subfolders",
}


class HomeScreen(Screen):
    """Landing screen: type/pick an objective, then Run."""

    def set_quick_source(self, source: str) -> None:
        """Prefill the objective input with an example for `source`."""
        example = QUICK_SOURCE_EXAMPLES.get(source, "")
        objective_input = self.ids.get("objective_input")
        if objective_input is not None:
            objective_input.text = example

    def run_objective(self) -> None:
        """Submit the current objective text to the orchestrator and switch screens."""
        objective_input = self.ids.get("objective_input")
        text = (objective_input.text if objective_input is not None else "").strip()
        if not text:
            return

        app = App.get_running_app()
        task_screen = self.manager.get_screen("task")
        task_screen.start_new_task(text)
        self.manager.current = "task"

        if objective_input is not None:
            objective_input.text = ""
