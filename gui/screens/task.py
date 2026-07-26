"""TaskScreen: live plan/step tracker, screen preview, pause/approve/cancel.

ARCHITECTURE.md section 10: "TaskScreen (live plan tree, step status
icons, screen preview thumbnail, pause/approve/cancel controls)".

This screen owns no orchestrator/event-bus logic directly; `AssistantApp`
(gui/app.py) submits objectives and marshals EventBus events to
`handle_event`, which is always invoked already on the Kivy main thread
(via Clock.schedule_once in GuiEventBridge).
"""

from __future__ import annotations

import logging
from typing import Optional

from kivy.app import App
from kivy.uix.screenmanager import Screen

from gui.widgets.approval_modal import ApprovalModal
from gui.widgets.step_row import StepRow

try:
    from core.events import Event, EventType
except Exception:  # pragma: no cover - core/ may not be importable yet
    Event = object  # type: ignore[assignment,misc]

    class EventType:  # type: ignore[no-redef]
        OBJECTIVE_RECEIVED = "objective_received"
        PLAN_GENERATED = "plan_generated"
        STEP_STARTED = "step_started"
        STEP_VERIFIED = "step_verified"
        STEP_FAILED = "step_failed"
        REPLANNED = "replanned"
        TASK_COMPLETED = "task_completed"
        TASK_FAILED = "task_failed"
        APPROVAL_REQUIRED = "approval_required"


logger = logging.getLogger(__name__)


class TaskScreen(Screen):
    """Displays the live step list + screen preview for the active task."""

    def on_pre_enter(self, *args) -> None:
        self._ensure_state()

    def _ensure_state(self) -> None:
        if not hasattr(self, "step_rows"):
            self.step_rows: dict[str, StepRow] = {}
            self.current_task_id: Optional[str] = None
            self.current_objective: str = ""
            self.paused: bool = False
            self._approval_modal: Optional[ApprovalModal] = None

    # -- lifecycle -----------------------------------------------------

    def start_new_task(self, objective: str) -> None:
        """Called by HomeScreen when the user hits Run."""
        self._ensure_state()
        self.current_objective = objective
        self.current_task_id = None
        self.paused = False
        self._clear_steps()
        self._set_status_text(f"Submitting: {objective}")

        app = App.get_running_app()
        app.submit_objective(objective)

    def _clear_steps(self) -> None:
        self.step_rows = {}
        container = self.ids.get("step_list")
        if container is not None:
            container.clear_widgets()
        preview = self.ids.get("preview_image")
        if preview is not None:
            preview.source = ""

    def _set_status_text(self, text: str) -> None:
        status_label = self.ids.get("status_label")
        if status_label is not None:
            status_label.text = text

    # -- event handling (always called on Kivy main thread) -------------

    def handle_event(self, event: "Event") -> None:
        self._ensure_state()
        etype = event.type
        payload = event.payload or {}
        self.current_task_id = event.task_id

        if etype == EventType.OBJECTIVE_RECEIVED:
            self._set_status_text(f"Planning: {payload.get('objective', self.current_objective)}")

        elif etype == EventType.PLAN_GENERATED:
            self._set_status_text(f"Plan ready: {payload.get('step_count', '?')} steps")
            self._rebuild_steps_from_task()

        elif etype == EventType.STEP_STARTED:
            self._upsert_step(payload.get("step_id", ""), payload.get("description", ""), "running")
            self._update_preview()

        elif etype == EventType.STEP_VERIFIED:
            self._upsert_step(payload.get("step_id", ""), None, "verified")
            self._update_preview()

        elif etype == EventType.STEP_FAILED:
            self._upsert_step(payload.get("step_id", ""), None, "failed")
            self._update_preview()

        elif etype == EventType.REPLANNED:
            self._set_status_text("Replanning after failure...")
            self._rebuild_steps_from_task()

        elif etype == EventType.APPROVAL_REQUIRED:
            self._show_approval_modal(payload.get("step_id", ""))

        elif etype == EventType.TASK_COMPLETED:
            self._set_status_text(payload.get("summary", "Task completed."))

        elif etype == EventType.TASK_FAILED:
            self._set_status_text(f"Task failed: {payload.get('reason', 'unknown')}")

    def _rebuild_steps_from_task(self) -> None:
        """Best-effort: pull the full step list from Memory/orchestrator state.

        The event payloads carry step_id/description incrementally, but if
        the app exposes the live Task/TaskGraph (via App.get_running_app())
        we can (re)build the full row list up front for a nicer initial
        view. Falls back to doing nothing if that's unavailable.
        """
        app = App.get_running_app()
        task = getattr(app, "get_current_task", lambda: None)()
        if task is None or task.graph is None:
            return
        container = self.ids.get("step_list")
        if container is None:
            return
        for step in task.graph.steps:
            self._upsert_step(step.id, step.description, step.status)

    def _upsert_step(self, step_id: str, description: Optional[str], status: str) -> None:
        if not step_id:
            return
        container = self.ids.get("step_list")
        row = self.step_rows.get(step_id)
        if row is None:
            row = StepRow(step_id=step_id, description=description or step_id)
            self.step_rows[step_id] = row
            if container is not None:
                container.add_widget(row)
        elif description:
            row.description = description
        row.status = status

    def _update_preview(self) -> None:
        """Refresh the screen-preview thumbnail from the latest screenshot ref.

        Verification/Execution write screenshots to disk and reference the
        path in ActionResult.screenshot_ref; the exact plumbing of "latest
        screenshot path" into the GUI is a TODO once vision/ lands. For now
        this just looks for a conventional path if present.
        """
        app = App.get_running_app()
        latest = getattr(app, "get_latest_screenshot_path", lambda: None)()
        preview = self.ids.get("preview_image")
        if preview is not None and latest:
            preview.source = latest
            preview.reload()

    # -- approval modal --------------------------------------------------

    def _show_approval_modal(self, step_id: str) -> None:
        description = ""
        row = self.step_rows.get(step_id)
        if row is not None:
            description = row.description
        modal = ApprovalModal(
            step_id=step_id,
            description=description,
            on_approve=self._approve_step,
            on_deny=self._deny_step,
        )
        self._approval_modal = modal
        modal.open()

    def _approve_step(self, step_id: str) -> None:
        app = App.get_running_app()
        logger.info("Step %s approved by user", step_id)
        app.resolve_approval(step_id, approved=True)
        self._upsert_step(step_id, None, "running")

    def _deny_step(self, step_id: str) -> None:
        app = App.get_running_app()
        logger.info("Step %s denied by user", step_id)
        app.resolve_approval(step_id, approved=False)
        self._upsert_step(step_id, None, "failed")

    # -- controls ----------------------------------------------------------

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        app = App.get_running_app()
        app.set_paused(self.paused)
        self._set_status_text("Paused" if self.paused else "Resumed")

    def cancel_task(self) -> None:
        app = App.get_running_app()
        app.cancel_current_task()
        self._set_status_text("Cancelled")
        self.manager.current = "home"
