"""OCR wrapper used by Verification (text cross-check) and Execution
(grounding on canvas/Electron UIs without an accessibility tree).

Backed by the lightweight `tesseract-ocr` apt package via `pytesseract`
(no torch dependency, unlike the easyocr path this used to have). The
import is lazy/optional since the box may not have pytesseract/tesseract
installed yet — in that case `extract_text_boxes` just returns `[]` so
callers degrade gracefully (verifier falls through to the VLM judge).
"""

from __future__ import annotations

import shutil
from typing import Any

from PIL import Image

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover - optional dep
    pytesseract = None  # TODO: `pip install pytesseract` + `apt install
    # tesseract-ocr` (the actual OCR binary pytesseract shells out to).


class OCREngine:
    """Lazily checks whether the pytesseract backend is usable.

    `extract_text` returns a single concatenated string (cheap for
    substring/regex checks in verification). `extract_text_boxes` returns
    per-detection boxes+confidence for grounding use cases (element
    detection, set-of-marks candidate labeling).
    """

    def __init__(self, languages: list[str] | None = None) -> None:
        self.languages = languages or ["en"]
        self._available: bool | None = None

    def _ensure_backend(self) -> bool:
        if self._available is None:
            # pytesseract still needs the actual `tesseract` binary on PATH.
            self._available = pytesseract is not None and shutil.which("tesseract") is not None
        return self._available

    def extract_text(self, image: Image.Image) -> str:
        boxes = self.extract_text_boxes(image)
        return " ".join(b["text"] for b in boxes)

    def extract_text_boxes(self, image: Image.Image) -> list[dict[str, Any]]:
        """Returns a list of {"text": str, "bbox": (l, t, r, b), "confidence": float}."""
        if not self._ensure_backend():
            # No OCR backend installed: return empty so callers can
            # gracefully skip the OCR check rather than crash.
            return []
        return self._extract_via_pytesseract(image)

    def _extract_via_pytesseract(self, image: Image.Image) -> list[dict[str, Any]]:
        try:
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        except Exception:
            # tesseract binary failed at runtime (bad install, unsupported
            # image mode, etc.) — degrade to no OCR results rather than crash.
            return []
        boxes = []
        for i, text in enumerate(data["text"]):
            if not text.strip():
                continue
            l, t, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            conf_raw = data["conf"][i]
            try:
                conf = max(float(conf_raw), 0.0) / 100.0
            except (TypeError, ValueError):
                conf = 0.0
            boxes.append(
                {
                    "text": text,
                    "bbox": (l, t, l + w, t + h),
                    "confidence": conf,
                }
            )
        return boxes


default_ocr_engine = OCREngine()
