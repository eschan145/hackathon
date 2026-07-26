"""Scoped filesystem operations, restricted to an allow-listed set of roots.

Per ARCHITECTURE.md section 6 ("a scoped FileOps module restricted to an
allow-listed set of directories ... with path-traversal checks before any
write/delete") and section 12 (least privilege, allow-listed per
config/security_policy.yaml).

Every operation:
  1. Resolves the requested path (Path.resolve()) to eliminate `..`/symlink
     traversal tricks.
  2. Confirms the resolved path is contained within one of the configured
     allowed_roots (also resolved).
  3. Confirms the resolved path doesn't match a deny_pattern (executables,
     system dirs, credential dirs).
  4. Logs the action via execution.audit_log.log_action before returning.

Raises `FileOpsPermissionError` on any violation rather than silently
no-op'ing, so callers (ActionExecutor, NativeInputBackend) can surface the
failure as a failed ActionResult.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
from pathlib import Path
from typing import Optional

import yaml

from execution.audit_log import log_action

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "security_policy.yaml"


class FileOpsPermissionError(PermissionError):
    """Raised when a requested path is outside the allow-list or hits a deny pattern."""


def _expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


class FileOps:
    """Filesystem gateway confined to allow-listed roots.

    Roots and deny patterns are loaded from config/security_policy.yaml
    (`filesystem.allowed_roots`, `filesystem.deny_patterns`) unless
    overridden explicitly (useful for tests).
    """

    def __init__(
        self,
        allowed_roots: Optional[list[str]] = None,
        deny_patterns: Optional[list[str]] = None,
        policy_path: Path | str = DEFAULT_POLICY_PATH,
    ) -> None:
        if allowed_roots is None or deny_patterns is None:
            policy = self._load_policy(policy_path)
            allowed_roots = allowed_roots if allowed_roots is not None else policy.get("allowed_roots", [])
            deny_patterns = deny_patterns if deny_patterns is not None else policy.get("deny_patterns", [])

        self.allowed_roots = [_expand(r).resolve() for r in allowed_roots]
        self.deny_patterns = list(deny_patterns)
        for root in self.allowed_roots:
            root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _load_policy(policy_path: Path | str) -> dict:
        path = Path(policy_path)
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("filesystem", {})

    # -- guard rails ---------------------------------------------------

    def _check(self, path: str | Path) -> Path:
        resolved = Path(path).resolve()

        if not any(self._is_within(resolved, root) for root in self.allowed_roots):
            raise FileOpsPermissionError(
                f"Path {resolved} is outside allow-listed roots: {self.allowed_roots}"
            )

        resolved_str = str(resolved)
        for pattern in self.deny_patterns:
            if fnmatch.fnmatch(resolved_str, pattern) or fnmatch.fnmatch(resolved_str.replace("\\", "/"), pattern):
                raise FileOpsPermissionError(f"Path {resolved} matches deny pattern {pattern!r}")

        return resolved

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    # -- operations ------------------------------------------------------

    def read(self, path: str | Path) -> bytes:
        resolved = self._check(path)
        data = resolved.read_bytes()
        log_action("file_read", {"path": str(resolved), "bytes": len(data)})
        return data

    def write(self, path: str | Path, content: bytes | str, *, append: bool = False) -> Path:
        resolved = self._check(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if append else "wb"
        payload = content.encode("utf-8") if isinstance(content, str) else content
        with resolved.open(mode) as f:
            f.write(payload)
        log_action("file_write", {"path": str(resolved), "bytes": len(payload), "append": append})
        return resolved

    def delete(self, path: str | Path) -> None:
        resolved = self._check(path)
        if resolved.is_dir():
            shutil.rmtree(resolved)
        elif resolved.exists():
            resolved.unlink()
        log_action("file_delete", {"path": str(resolved)})

    def list(self, path: str | Path) -> list[str]:
        resolved = self._check(path)
        entries = [str(p) for p in resolved.iterdir()] if resolved.is_dir() else []
        log_action("file_list", {"path": str(resolved), "count": len(entries)})
        return entries
