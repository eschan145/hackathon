"""ActionVerifier: implements the `core.interfaces.Verifier` protocol.

Per ARCHITECTURE.md section 7, checks run in this priority order (fastest/
most-deterministic first, falling back to slower/fuzzier checks):

  1. Accessibility-tree / DOM predicate check against `step.success_criteria`
     when `action_result.a11y_snapshot` is available and the criteria looks
     structurally checkable (e.g. mentions an element/text that can be
     looked up in the snapshot rather than requiring visual judgment).
  2. OCR cross-check for text-critical criteria (order totals, confirmation
     numbers, etc.) — extracts text from the post-action screenshot and
     regex/substring-matches it against content mentioned in
     success_criteria.
  3. VLM judge fallback — asks the local VLM "Does this screenshot satisfy:
     {success_criteria}?" and uses its confidence.

Whichever check first produces a confident result short-circuits the rest;
if none are confident, the step is considered failed with all attempted
checks recorded in `details` for the Planner's replan failure_context.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from core.models import ActionResult, Step
from vision.ocr import OCREngine, default_ocr_engine
from vision.vlm_client import LocalVLMClient, default_vlm_client
from vision.capture import default_frame_store

# Below this confidence, a check is treated as "inconclusive" rather than
# a definitive pass/fail, so verification falls through to the next check
# instead of trusting a low-confidence signal.
CONFIDENCE_THRESHOLD = 0.6

# Words that suggest success_criteria references literal/extractable text
# (a confirmation code, an exact label) rather than a purely visual/
# subjective judgment — used to decide whether the OCR check is worth
# attempting at all.
_TEXT_HINT_PATTERN = re.compile(
    r"\btext\b|\bsays\b|\bcontains\b|\bnumber\b|\bconfirmation\b|\btitle\b|\bmatches\b|\bregex\b",
    re.IGNORECASE,
)


def _extract_quoted_expectations(success_criteria: str) -> list[str]:
    """Pulls out any quoted substrings from success_criteria to use as the
    literal text OCR should look for, e.g. success_criteria = 'text shows
    "Order Confirmed"' -> ["Order Confirmed"].
    """
    return re.findall(r'"([^"]+)"|\'([^\']+)\'', success_criteria)


def _flatten_quotes(pairs: list[tuple[str, str]]) -> list[str]:
    return [a or b for a, b in pairs if (a or b)]


def _looks_structurally_checkable(success_criteria: str) -> bool:
    """Heuristic: does success_criteria reference something we could
    plausibly find as a named element/property in an a11y snapshot (vs.
    something inherently visual, like "the button looks highlighted")?
    """
    lowered = success_criteria.lower()
    structural_hints = ("element", "visible", "button", "field", "window", "process", "exited", "focused")
    return any(hint in lowered for hint in structural_hints)


def _check_a11y_predicate(step: Step, snapshot: dict[str, Any]) -> Optional[tuple[bool, dict[str, Any]]]:
    """Very small declarative-predicate evaluator over an a11y snapshot.

    TODO: the actual shape of `a11y_snapshot` is owned by execution/ and
    not finalized yet; this assumes a shallow shape like
    {"elements": [{"name": str, "visible": bool, "control_type": str}, ...]}
    plus optionally {"process_exit_code": int}. Adjust matching logic once
    execution/'s ActionResult population is settled.
    """
    lowered = step.success_criteria.lower()

    if "exited" in lowered or "exit code" in lowered:
        exit_code = snapshot.get("process_exit_code")
        if exit_code is not None:
            expects_zero = "0" in lowered or "success" in lowered
            passed = (exit_code == 0) if expects_zero else (exit_code != 0)
            return passed, {"check": "a11y_predicate", "kind": "process_exit", "exit_code": exit_code}

    elements = snapshot.get("elements") or []
    quoted = _flatten_quotes(_extract_quoted_expectations(step.success_criteria))
    needles = quoted or [step.success_criteria]

    for needle in needles:
        needle_l = needle.strip().lower()
        if not needle_l:
            continue
        for el in elements:
            name = str(el.get("name", "")).strip().lower()
            if needle_l in name or name in needle_l:
                visible = el.get("visible", True)
                return bool(visible), {
                    "check": "a11y_predicate",
                    "kind": "element_match",
                    "matched_element": el.get("name"),
                    "visible": visible,
                }

    return None  # inconclusive: nothing in the snapshot matched either way


class ActionVerifier:
    """Concrete Verifier implementation combining a11y + OCR + VLM checks."""

    def __init__(
        self,
        ocr_engine: Optional[OCREngine] = None,
        vlm_client: Optional[LocalVLMClient] = None,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
    ) -> None:
        self.ocr_engine = ocr_engine or default_ocr_engine
        self.vlm_client = vlm_client or default_vlm_client
        self.confidence_threshold = confidence_threshold

    async def verify(self, step: Step, action_result: ActionResult) -> tuple[bool, dict[str, Any]]:
        attempted: list[dict[str, Any]] = []

        # 1. Accessibility-tree predicate check.
        if action_result.a11y_snapshot and _looks_structurally_checkable(step.success_criteria):
            result = _check_a11y_predicate(step, action_result.a11y_snapshot)
            if result is not None:
                passed, info = result
                attempted.append(info)
                return passed, {"checks": attempted, "decisive_check": "a11y_predicate"}
            attempted.append({"check": "a11y_predicate", "kind": "inconclusive"})

        image = None
        if action_result.screenshot_ref:
            try:
                image = default_frame_store.get(action_result.screenshot_ref)
            except FileNotFoundError:
                image = None

        # 2. OCR cross-check for text-critical criteria.
        if image is not None and _TEXT_HINT_PATTERN.search(step.success_criteria):
            expectations = _flatten_quotes(_extract_quoted_expectations(step.success_criteria))
            extracted_text = self.ocr_engine.extract_text(image)
            if expectations:
                matched = [exp for exp in expectations if exp.lower() in extracted_text.lower()]
                info = {
                    "check": "ocr_cross_check",
                    "expected": expectations,
                    "matched": matched,
                    "extracted_text_preview": extracted_text[:300],
                }
                attempted.append(info)
                if matched:
                    return True, {"checks": attempted, "decisive_check": "ocr_cross_check"}
                if extracted_text:
                    # OCR ran and found text, but none of it matched — a
                    # meaningful negative signal, but we still let the VLM
                    # have a look before declaring failure since OCR can
                    # miss stylized/partial text.
                    pass
            else:
                attempted.append(
                    {"check": "ocr_cross_check", "kind": "skipped_no_literal_expectation"}
                )

        # 3. VLM judge fallback.
        if image is not None:
            question = f"Does this screenshot satisfy the following condition: {step.success_criteria!r}?"
            vlm_result = await self.vlm_client.ask(image, question)
            confidence = float(vlm_result.get("confidence", 0.0))
            answer = vlm_result.get("answer")
            passed = bool(answer) and confidence >= self.confidence_threshold
            attempted.append(
                {
                    "check": "vlm_judge",
                    "answer": answer,
                    "confidence": confidence,
                    "reasoning": vlm_result.get("reasoning", ""),
                }
            )
            return passed, {"checks": attempted, "decisive_check": "vlm_judge"}

        # No screenshot available at all and a11y didn't resolve it either.
        attempted.append({"check": "none", "kind": "no_evidence_available"})
        return False, {"checks": attempted, "decisive_check": None}
