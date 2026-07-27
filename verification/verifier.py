"""DeterministicVerifier: implements the `core.interfaces.Verifier` protocol.

Verification used to mean asking a VLM/another model call whether a
post-action screenshot satisfied a step's success_criteria. That's gone:
the new ReAct-style planner (see planning/) already looks at the resulting
screenshot on its *next* turn and self-corrects if the action didn't
accomplish what it intended, so re-litigating "did this actually work,
semantically?" here would just be a second, redundant, separately-billed
model call for a question the planner is about to answer anyway.

What's left for the Verifier to check cheaply and without any model call
is whether the Executor's own action succeeded at the mechanical level:
did the element it was told to click/type into actually exist, did the
OS-level call raise, etc. The interpreter (execution/interpreter.py)
already knows this definitively when it builds the ActionResult, so
DeterministicVerifier just trusts that signal instead of re-deriving it.
"""

from __future__ import annotations

from typing import Any

from core.models import ActionResult, Step


class DeterministicVerifier:
    """Concrete Verifier implementation with zero extra model calls."""

    async def verify(self, step: Step, action_result: ActionResult) -> tuple[bool, dict[str, Any]]:
        """Trusts the interpreter's own success signal — no model call.

        The interpreter (execution/interpreter.py, another workstream)
        already knows definitively whether e.g. the element id it was
        asked to click existed and the OS-level action didn't raise; there
        is nothing more reliable to check without spending another model
        call, and semantic correctness ("did clicking that actually
        accomplish the objective?") is deliberately left to the *next*
        planning turn, which sees the resulting screen state itself.
        """
        if action_result.success:
            return True, {"check": "interpreter_reported_success", "details": action_result.details}
        return False, {
            "check": "interpreter_reported_failure",
            "raw_output": action_result.raw_output,
            "details": action_result.details,
        }
