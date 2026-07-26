"""OCR wrapper used by Verification (text cross-check) and Execution
(grounding on canvas/Electron UIs without an accessibility tree).

Per ARCHITECTURE.md section 9/6: EasyOCR or PaddleOCR locally, or a
NIM-hosted VLM with OCR capability. We default to `easyocr` here with
`pytesseract` documented as a lighter-weight alternative (see the
`_extract_via_pytesseract` fallback path). Both imports are lazy/optional
since the hackathon box may not have either installed yet.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

try:
    import easyocr  # type: ignore
except ImportError:  # pragma: no cover - optional heavy dep
    easyocr = None  # TODO: `pip install easyocr` (pulls in torch). This is
    # the primary OCR path referenced in ARCHITECTURE.md section 9.

try:
    import pytesseract  # type: ignore
except ImportError:  # pragma: no cover - optional, lighter alternative
    pytesseract = None  # TODO: `pip install pytesseract` + install the
    # Tesseract binary separately. Used only if easyocr is unavailable.


class OCREngine:
    """Lazily initializes whichever OCR backend is available.

    `extract_text` returns a single concatenated string (cheap for
    substring/regex checks in verification). `extract_text_boxes` returns
    per-detection boxes+confidence for grounding use cases (element
    detection, set-of-marks candidate labeling).
    """

    def __init__(self, languages: list[str] | None = None) -> None:
        self.languages = languages or ["en"]
        self._reader: Any = None
        self._backend: str | None = None

    def _ensure_backend(self) -> None:
        if self._backend is not None:
            return
        if easyocr is not None:
            self._reader = easyocr.Reader(self.languages, gpu=True)
            self._backend = "easyocr"
        elif pytesseract is not None:
            self._backend = "pytesseract"
        else:
            self._backend = "none"

    def extract_text(self, image: Image.Image) -> str:
        boxes = self.extract_text_boxes(image)
        return " ".join(b["text"] for b in boxes)

    def extract_text_boxes(self, image: Image.Image) -> list[dict[str, Any]]:
        """Returns a list of {"text": str, "bbox": (l, t, r, b), "confidence": float}."""
        self._ensure_backend()

        if self._backend == "easyocr":
            import numpy as np  # local import: only needed on this path

            results = self._reader.readtext(np.array(image))
            boxes = []
            for points, text, conf in results:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                boxes.append(
                    {
                        "text": text,
                        "bbox": (min(xs), min(ys), max(xs), max(ys)),
                        "confidence": float(conf),
                    }
                )
            return boxes

        if self._backend == "pytesseract":
            return self._extract_via_pytesseract(image)

        # No OCR backend installed: return empty so callers can gracefully
        # skip the OCR check rather than crash (verifier falls through to
        # VLM judge in that case).
        return []

    def _extract_via_pytesseract(self, image: Image.Image) -> list[dict[str, Any]]:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
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
