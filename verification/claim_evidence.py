"""Deterministic claim-to-source verification for email reports."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.models import ObjectiveContract


def verify_contract_report(contract: ObjectiveContract) -> tuple[bool, dict[str, Any]]:
    if not contract.deliverable_paths:
        return False, {"reason": "contract has no report path"}
    report_path = Path(contract.deliverable_paths[0])
    if not report_path.is_file():
        return False, {"reason": f"report not found: {report_path}"}
    report = report_path.read_text(encoding="utf-8", errors="replace")
    marker = re.search(r"^##\s+Evidence map\s*$", report, flags=re.IGNORECASE | re.MULTILINE)
    if marker is None:
        return False, {"reason": "report is missing an Evidence map"}

    evidence_section = report[marker.end() :]
    entries = _parse_entries(evidence_section)
    if not entries:
        return False, {"reason": "Evidence map contains no claim entries"}

    allowed_sources = {
        str(Path(item.local_path).resolve()): item
        for item in contract.inputs
        if item.local_path
    }
    failures: list[dict[str, str]] = []
    for entry in entries:
        source_path = str(Path(entry["source"]).expanduser().resolve())
        if source_path not in allowed_sources:
            failures.append({"claim": entry["claim"], "reason": "source is not a contract input"})
            continue
        source_text = _extract_text(Path(source_path))
        if _normalize(entry["evidence"]) not in _normalize(source_text):
            failures.append(
                {"claim": entry["claim"], "reason": "cited evidence is absent from source"}
            )

    details: dict[str, Any] = {
        "claim_count": len(entries),
        "verified_claim_count": len(entries) - len(failures),
        "failures": failures,
        "report_path": str(report_path),
    }
    return not failures, details


def _parse_entries(text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"^\s*(?:-\s*)?Claim:\s*(?P<claim>.+?)\s*$"
        r"\s*^\s*Evidence:\s*[\"“]?(?P<evidence>.+?)[\"”]?\s*$"
        r"\s*^\s*Source:\s*(?P<source>.+?)\s*$",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return [
        {key: value.strip() for key, value in match.groupdict().items()}
        for match in pattern.finditer(text)
    ]


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        except ImportError as exc:
            raise RuntimeError("pypdf is required to verify PDF evidence") from exc
    return path.read_text(encoding="utf-8", errors="replace")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
