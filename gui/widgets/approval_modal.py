"""Blocking approval modal shown for high-risk steps (ARCHITECTURE.md sections 6-7, 10, 12).

Shown when an APPROVAL_REQUIRED event arrives for a step with
risk_level == "high" (payments, sending mail, deleting files, etc). The
orchestrator's run_task loop stops advancing (state AWAITING_APPROVAL)
until the user taps Approve/Deny here; the callbacks are responsible for
telling the orchestrator/executor how to proceed (wired by TaskScreen).
"""

from __future__ import annotations

from typing import Callable, Optional

from kivy.uix.popup import Popup


class ApprovalModal(Popup):
    """A modal Popup blocking further auto-progress on a high-risk step.

    `on_approve` / `on_deny` are callables invoked with the step_id when
    the user taps the corresponding button. TaskScreen wires these to
    submit the decision back to the orchestrator (e.g. via a coroutine
    scheduled on the background asyncio loop).
    """

    def __init__(
        self,
        step_id: str,
        description: str,
        on_approve: Optional[Callable[[str], None]] = None,
        on_deny: Optional[Callable[[str], None]] = None,
        **kwargs,
    ) -> None:
        self.step_id = step_id
        self.step_description = description
        self._on_approve = on_approve
        self._on_deny = on_deny
        super().__init__(**kwargs)

    def approve(self) -> None:
        if self._on_approve:
            self._on_approve(self.step_id)
        self.dismiss()

    def deny(self) -> None:
        if self._on_deny:
            self._on_deny(self.step_id)
        self.dismiss()
