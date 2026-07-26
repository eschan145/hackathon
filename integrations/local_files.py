"""Native (non-MCP) local filesystem integration.

Per ARCHITECTURE.md section 15: "Local documents/files — Native, not MCP —
Local filesystem access needs no network protocol/auth negotiation — direct
`FileOps` calls are faster and simpler; MCP adds unneeded indirection for
same-machine file I/O."

This module provides:
- `LocalObjectiveScanner`: scans allow-listed directories for objective-like
  content (unchecked `- [ ]` todo items in plain-text/markdown files) and
  returns them as candidate objective strings, tagged with their source
  file — feeding the "obtaining objectives from external sources" flow
  described in section 3/5.
- `LocalDocumentReader`: restricted text file reader, gated by the same
  allow-list pattern used by execution/file_ops.py (reads
  config/security_policy.yaml's `filesystem.allowed_roots` when present,
  else falls back to a safe local ./data/sandbox directory).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

_UNCHECKED_TODO_RE = re.compile(r"^\s*-\s*\[\s\]\s+(.*\S)\s*$")

_DEFAULT_SANDBOX = Path("data/sandbox")

_DENY_PATTERNS_DEFAULT = [
    "*.exe",
    "*.dll",
    "*/System32/*",
    "*/.ssh/*",
    "*/.aws/*",
]


def _load_allowed_roots(security_policy_path: str | Path) -> list[Path]:
    path = Path(security_policy_path)
    if path.exists() and yaml is not None:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            roots = raw.get("filesystem", {}).get("allowed_roots")
            if roots:
                return [
                    Path(os.path.expanduser(os.path.expandvars(r))).resolve()
                    for r in roots
                ]
        except Exception:
            pass
    # Fallback: a safe local sandbox dir, created on demand.
    _DEFAULT_SANDBOX.mkdir(parents=True, exist_ok=True)
    return [_DEFAULT_SANDBOX.resolve()]


def _is_allowed(path: Path, allowed_roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


@dataclass
class CandidateObjective:
    text: str
    source: str  # e.g. "local_file:C:/Users/.../todo.md"

    def to_dict(self) -> dict:
        return {"text": self.text, "source": self.source}


class LocalDocumentReader:
    """Restricted plain-text file reader, scoped to allow-listed roots."""

    def __init__(
        self, security_policy_path: str | Path = "config/security_policy.yaml"
    ) -> None:
        self.allowed_roots = _load_allowed_roots(security_policy_path)

    def read_text(self, path: str | Path) -> str:
        p = Path(os.path.expanduser(os.path.expandvars(str(path))))
        if not _is_allowed(p, self.allowed_roots):
            raise PermissionError(
                f"Refusing to read '{p}': not under an allow-listed root "
                f"({[str(r) for r in self.allowed_roots]})"
            )
        if not p.exists():
            raise FileNotFoundError(str(p))
        return p.read_text(encoding="utf-8", errors="replace")


class LocalObjectiveScanner:
    """Scans allow-listed directories/files for objective-like content.

    Hackathon-scope heuristic: any plain-text/markdown file containing
    unchecked GitHub-flavored-markdown todo items (`- [ ] do the thing`) is
    treated as a source of candidate objectives. Real deployments would
    likely extend this to parse a Todoist export file, a "Notes" folder of
    .txt files, etc. — the allow-list + parsing pattern here generalizes.
    """

    def __init__(
        self,
        scan_paths: Optional[list[str | Path]] = None,
        security_policy_path: str | Path = "config/security_policy.yaml",
    ) -> None:
        self.reader = LocalDocumentReader(security_policy_path)
        if scan_paths is not None:
            self.scan_paths = [Path(os.path.expanduser(str(p))) for p in scan_paths]
        else:
            # Reasonable hackathon defaults: allowed roots + any *.md/*.txt
            # directly inside them. Real usage should pass explicit paths
            # (e.g. a "Notes" folder or a specific todo.md).
            self.scan_paths = list(self.reader.allowed_roots)

    def _iter_candidate_files(self) -> list[Path]:
        files: list[Path] = []
        for base in self.scan_paths:
            if base.is_file():
                files.append(base)
                continue
            if base.is_dir():
                for pattern in ("*.md", "*.txt"):
                    files.extend(base.glob(pattern))
        return files

    def scan(self) -> list[CandidateObjective]:
        """Scan all configured paths and return candidate objectives."""
        candidates: list[CandidateObjective] = []
        for f in self._iter_candidate_files():
            try:
                text = self.reader.read_text(f)
            except (PermissionError, FileNotFoundError, OSError):
                continue
            for line in text.splitlines():
                match = _UNCHECKED_TODO_RE.match(line)
                if match:
                    candidates.append(
                        CandidateObjective(
                            text=match.group(1), source=f"local_file:{f}"
                        )
                    )
        return candidates
