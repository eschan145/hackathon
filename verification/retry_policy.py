"""Retry policy: exponential backoff with jitter, plus action-variation
hooks so retries don't just blindly repeat the same failed action.

Per ARCHITECTURE.md section 7 step 5: "Retry strategy: exponential backoff
up to N attempts; each retry may vary the action (re-locate element,
scroll, alternate selector) rather than blindly repeating."
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from core.models import Step

# Small library of generic action-variation hints, cycled through on
# successive retries. These get appended to Step.description so the
# Executor's next attempt is nudged toward a different strategy rather
# than literally repeating pixel-identical input. Real per-app variation
# (e.g. "alternate selector") would need Executor-side hooks; this is the
# planner/verifier-facing half of that loop.
_VARIATION_HINTS = [
    "try scrolling the target into view first",
    "try an alternate label or synonym for the target element",
    "try waiting briefly for the UI to finish loading before retrying",
    "try re-locating the element via a full-window screenshot instead of cached coordinates",
    "try an alternate interaction (e.g. keyboard shortcut instead of click)",
]


@dataclass
class RetryPolicy:
    """Exponential backoff with jitter for step retries.

    `base_delay_seconds` and `max_delay_seconds` bound the exponential
    curve; jitter is uniform +/- `jitter_fraction` of the computed delay,
    to avoid retry storms if many steps fail at once.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_fraction: float = 0.2
    _rng: random.Random = field(default_factory=random.Random, repr=False)

    def should_retry(self, attempt: int) -> bool:
        """`attempt` is 1-indexed (the attempt number that just failed)."""
        return attempt < self.max_attempts

    def delay_for_attempt(self, attempt: int) -> float:
        """Seconds to wait before the next attempt (1-indexed attempt that
        just failed -> delay before attempt+1).
        """
        raw = min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)
        jitter = raw * self.jitter_fraction
        return max(0.0, raw + self._rng.uniform(-jitter, jitter))

    def next_action_variation(self, step: Step, attempt: int) -> Step:
        """Returns a copy of `step` with its description nudged toward a
        different approach for the next attempt, rather than repeating
        the exact same action. `attempt` is the attempt number about to be
        made (2, 3, ...) so hints cycle deterministically per retry index.
        """
        hint = _VARIATION_HINTS[(attempt - 2) % len(_VARIATION_HINTS)]
        varied = step.model_copy(deep=True)
        varied.description = f"{step.description} (retry {attempt}: {hint})"
        varied.retry_count = attempt - 1
        varied.status = "pending"
        return varied
