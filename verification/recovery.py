"""Recovery policy: classifies exhausted-retry failures and decides what
the orchestrator should do next.

Per ARCHITECTURE.md section 7 step 6 / section 11:
"on exhausted retries — classify failure (transient/UI-changed/blocked/
needs-auth) and either (a) trigger replanning with failure context, (b)
escalate to GUI approval modal for irreversible/ambiguous actions, or
(c) mark step failed and continue if non-blocking."

This module is pure decision logic — no I/O, no side effects — so it's
trivially unit-testable and the Orchestrator stays in control of actually
acting on the decision (calling Planner.replan, publishing
APPROVAL_REQUIRED, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from core.models import ActionResult, Step


class FailureClass(str, Enum):
    TRANSIENT = "transient"  # e.g. network blip, slow load, momentary UI lag
    UI_CHANGED = "ui_changed"  # target element moved/renamed/disappeared
    BLOCKED = "blocked"  # e.g. modal dialog, permission prompt, rate limit
    NEEDS_AUTH = "needs_auth"  # login wall, expired session, 2FA prompt
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    RETRY = "retry"
    REPLAN = "replan"
    ESCALATE_TO_USER = "escalate_to_user"
    SKIP_NON_BLOCKING = "skip_non_blocking"


@dataclass
class RecoveryDecision:
    action: RecoveryAction
    failure_class: FailureClass
    reason: str
    details: dict[str, Any]


# Cheap keyword heuristics over verifier details / raw_output. A real
# implementation would likely also consult the VLM ("why did this fail?"),
# but keyword classification keeps this fast and deterministic for the
# common cases, matching the "quick yes/no VLM calls" perf guidance in
# section 13 (reserve VLM calls for cases these heuristics can't resolve).
_AUTH_PATTERNS = re.compile(r"\b(log ?in|sign ?in|session expired|please authenticate|2fa|verification code)\b", re.I)
_BLOCKED_PATTERNS = re.compile(r"\b(permission denied|access denied|rate limit|too many requests|modal|dialog|captcha)\b", re.I)
_UI_CHANGED_PATTERNS = re.compile(r"\b(element not found|no such element|not visible|layout changed|element moved)\b", re.I)
_TRANSIENT_PATTERNS = re.compile(r"\b(timeout|timed out|network error|temporarily unavailable|loading|try again)\b", re.I)


def classify_failure(verification_details: dict[str, Any], raw_output: Optional[str]) -> FailureClass:
    """Classifies a failure from the combined text of verifier `details`
    and the Executor's `raw_output`.
    """
    haystack = " ".join(
        [
            raw_output or "",
            str(verification_details.get("checks", "")),
            str(verification_details),
        ]
    )

    if _AUTH_PATTERNS.search(haystack):
        return FailureClass.NEEDS_AUTH
    if _BLOCKED_PATTERNS.search(haystack):
        return FailureClass.BLOCKED
    if _UI_CHANGED_PATTERNS.search(haystack):
        return FailureClass.UI_CHANGED
    if _TRANSIENT_PATTERNS.search(haystack):
        return FailureClass.TRANSIENT
    return FailureClass.UNKNOWN


class RecoveryPolicy:
    """Pure decision logic: given a step, its ActionResult, and verifier
    details, decide the next `RecoveryAction` after retries are exhausted
    (or immediately, for classes that should never be blindly retried).
    """

    def decide(
        self,
        step: Step,
        action_result: ActionResult,
        verification_details: dict[str, Any],
        *,
        retries_exhausted: bool,
    ) -> RecoveryDecision:
        failure_class = classify_failure(verification_details, action_result.raw_output)

        # High-risk / irreversible steps always escalate to the user once
        # they've failed verification, regardless of failure class or
        # retry budget — matches section 12's human-in-the-loop-for-
        # irreversible-actions requirement.
        if step.risk_level == "high":
            return RecoveryDecision(
                action=RecoveryAction.ESCALATE_TO_USER,
                failure_class=failure_class,
                reason="Step is high-risk; failures always escalate rather than auto-retry/replan.",
                details=verification_details,
            )

        if failure_class == FailureClass.NEEDS_AUTH:
            return RecoveryDecision(
                action=RecoveryAction.ESCALATE_TO_USER,
                failure_class=failure_class,
                reason="Needs user authentication/2FA which the assistant cannot complete autonomously.",
                details=verification_details,
            )

        if not retries_exhausted and failure_class in (FailureClass.TRANSIENT, FailureClass.UI_CHANGED):
            return RecoveryDecision(
                action=RecoveryAction.RETRY,
                failure_class=failure_class,
                reason="Transient/UI-changed failures are worth retrying with a varied action before replanning.",
                details=verification_details,
            )

        if failure_class == FailureClass.BLOCKED:
            return RecoveryDecision(
                action=RecoveryAction.ESCALATE_TO_USER,
                failure_class=failure_class,
                reason="A blocking dialog/permission/rate-limit needs human judgment to resolve.",
                details=verification_details,
            )

        if retries_exhausted:
            if not step.depends_on and step.risk_level == "low":
                # Leaf-ish, low-risk steps that aren't blocking other work
                # can be skipped rather than failing the whole task.
                # NOTE: "non-blocking" here is approximated as "nothing in
                # the current graph depends on this step" — the
                # orchestrator, which has the full TaskGraph, should
                # double-check downstream dependents before honoring this.
                return RecoveryDecision(
                    action=RecoveryAction.SKIP_NON_BLOCKING,
                    failure_class=failure_class,
                    reason="Retries exhausted on a low-risk step with no known dependents; safe to skip.",
                    details=verification_details,
                )
            return RecoveryDecision(
                action=RecoveryAction.REPLAN,
                failure_class=failure_class,
                reason="Retries exhausted; asking the planner to find an alternate approach.",
                details=verification_details,
            )

        # Default: keep retrying within budget for unknown-classified
        # failures rather than escalating prematurely.
        return RecoveryDecision(
            action=RecoveryAction.RETRY,
            failure_class=failure_class,
            reason="Unclassified failure with retry budget remaining; retry before escalating.",
            details=verification_details,
        )
