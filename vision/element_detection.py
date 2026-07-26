"""Element/target resolution for execution grounding and verification.

Per ARCHITECTURE.md section 9: "Element detection: accessibility API first
(UIAutomation/AT-SPI), VLM-based grounding ('Set-of-Marks' style prompting
with detected candidate boxes) as fallback for non-instrumented UIs."
"""

from __future__ import annotations

import io
from typing import Any, Optional

from PIL import Image, ImageDraw

from vision.vlm_client import LocalVLMClient, default_vlm_client

try:
    from pywinauto import Desktop  # type: ignore
except ImportError:  # pragma: no cover - Windows-only, optional
    Desktop = None  # TODO: `pip install pywinauto` for real UIAutomation
    # tree walking. AT-SPI (Linux) is not implemented at all here — this is
    # a Windows-first hackathon stub per the deny-list of "cross-platform
    # accessibility tree" work not being feasible in the time available.


def _find_via_accessibility_tree(description: str) -> Optional[dict[str, Any]]:
    """Best-effort UIAutomation lookup by matching visible control names/
    text against `description`. Returns None (not "no match found") if the
    accessibility backend isn't available at all, distinguishing
    "couldn't try" from "tried and found nothing" isn't done here for
    simplicity — both currently return None and fall through to VLM.

    TODO: this only implements a shallow, Windows/UIAutomation-specific
    walk of the topmost window's children; a real implementation would
    need per-platform backends (AT-SPI on Linux, NSAccessibility on macOS)
    and fuzzy/semantic matching rather than exact substring matching.
    """
    if Desktop is None:
        return None

    try:
        window = Desktop(backend="uia").top_window()
        needle = description.strip().lower()
        for ctrl in window.descendants():
            try:
                name = (ctrl.window_text() or "").strip().lower()
            except Exception:
                continue
            if name and (needle in name or name in needle):
                rect = ctrl.rectangle()
                return {
                    "source": "accessibility_tree",
                    "bbox": (rect.left, rect.top, rect.right, rect.bottom),
                    "name": ctrl.window_text(),
                    "control_type": getattr(ctrl.element_info, "control_type", None),
                    "confidence": 1.0,
                }
    except Exception:
        return None

    return None


def _draw_candidate_marks(image: Image.Image, candidates: list[dict[str, Any]]) -> Image.Image:
    """Annotate `image` with numbered boxes for Set-of-Marks-style VLM
    grounding: each candidate gets a rectangle + index label the VLM can
    refer to by number in its answer.
    """
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    for i, cand in enumerate(candidates):
        bbox = cand["bbox"]
        draw.rectangle(bbox, outline=(255, 0, 0), width=2)
        draw.text((bbox[0], max(bbox[1] - 12, 0)), str(i), fill=(255, 0, 0))
    return annotated


async def find_element(
    image: Image.Image,
    description: str,
    *,
    candidates: Optional[list[dict[str, Any]]] = None,
    vlm_client: Optional[LocalVLMClient] = None,
) -> Optional[dict[str, Any]]:
    """Resolve `description` (e.g. "the Submit button") to a bounding box.

    Order of operations (ARCHITECTURE.md section 9):
      1. Accessibility-tree lookup (fast, deterministic) — stubbed/TODO
         for cross-platform, implemented for Windows/UIAutomation only.
      2. VLM Set-of-Marks grounding fallback: if `candidates` (a list of
         {"bbox": (l, t, r, b), ...} dicts, e.g. from an OCR pass or a
         generic region-proposal step) are supplied, annotate the image
         with numbered boxes and ask the VLM to pick one; otherwise ask
         the VLM to describe the location directly.

    Returns None if no element could be resolved by either path.
    """
    hit = _find_via_accessibility_tree(description)
    if hit is not None:
        return hit

    client = vlm_client or default_vlm_client

    if candidates:
        annotated = _draw_candidate_marks(image, candidates)
        question = (
            f"The image is annotated with numbered candidate regions. "
            f"Which numbered region best matches: {description!r}? "
            f'Set "answer" to the integer index as a string (e.g. "2"), '
            f'or "none" if none match.'
        )
        result = await client.ask(annotated, question)
        answer = str(result.get("answer", "")).strip()
        if answer.isdigit() and int(answer) < len(candidates):
            chosen = candidates[int(answer)]
            return {
                "source": "vlm_som",
                "bbox": chosen["bbox"],
                "confidence": result.get("confidence", 0.0),
                "reasoning": result.get("reasoning", ""),
            }
        return None

    # No candidate boxes supplied: ask the VLM to locate the element
    # directly. Less reliable than Set-of-Marks but useful when a caller
    # hasn't produced candidate regions (e.g. OCR found nothing).
    question = (
        f"Locate this UI element in the screenshot: {description!r}. "
        f'Set "answer" to true if you can identify a specific location, '
        f'false otherwise, and describe the location in "reasoning".'
    )
    result = await client.ask(image, question)
    if not result.get("answer"):
        return None
    return {
        "source": "vlm_freeform",
        "bbox": None,  # freeform path doesn't produce pixel coordinates
        "confidence": result.get("confidence", 0.0),
        "reasoning": result.get("reasoning", ""),
    }
