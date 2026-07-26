"""Append-only JSONL audit logger.

Per ARCHITECTURE.md section 12 (Security): every input-injection and
file/clipboard/network action must be recorded in an immutable append-only
log, viewable later in the GUI History screen. This module is deliberately
tiny — a single function that appends one JSON line per call, plus a
convenience singleton so other execution/ modules don't have to wire up
their own file handles.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = Path(
    os.environ.get("HACKATHON_AUDIT_LOG", str(Path(__file__).resolve().parent.parent / "data" / "audit_log.jsonl"))
)

_lock = threading.Lock()


def log_action(action_type: str, details: dict[str, Any], *, log_path: Path | str = DEFAULT_LOG_PATH) -> dict[str, Any]:
    """Append a single audit record and return it.

    Parameters
    ----------
    action_type: short machine-readable category, e.g. "click", "type_text",
        "file_write", "clipboard_read", "launch_app".
    details: free-form JSON-serializable dict — should include enough
        context (task_id, step_id, target, backend) to reconstruct what
        happened without needing to correlate with other logs.
    log_path: override for testing; defaults to data/audit_log.jsonl.

    This is append-only by construction: we never open in "w" mode, only
    "a", and callers have no delete/update entry point in this module.
    """
    record = {
        "id": uuid.uuid4().hex[:12],
        "ts": time.time(),
        "action_type": action_type,
        "details": details,
    }
    path = Path(log_path)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    return record


class AuditLogger:
    """Thin object wrapper so callbacks can be passed around as `logger.log`."""

    def __init__(self, log_path: Path | str = DEFAULT_LOG_PATH) -> None:
        self.log_path = Path(log_path)

    def log(self, action_type: str, details: dict[str, Any]) -> dict[str, Any]:
        return log_action(action_type, details, log_path=self.log_path)


default_logger = AuditLogger()
