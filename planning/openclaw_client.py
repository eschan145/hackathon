"""The only place in this codebase allowed to shell out to the `openclaw` CLI.

OpenClaw is used exclusively as a stateless completion runner here — never
as an autonomous agent. Every call is `openclaw infer model run`, a single
prompt-in/text-out request with no session/conversation state on the far
side: each call must carry its own full context in `--prompt`. Nothing in
this file ever invokes `openclaw agent`.

Config is read from config/models.yaml the same lightweight way
planning/llm_client.py (now deleted) used to for its own local-LLM
config: yaml.safe_load with hardcoded fallback defaults, best-effort, no
schema validation, no env var override layer.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Optional

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"

# This project runs exclusively against the local Qwen3-VL model served by
# Ollama (see run.sh's setup_local_models()) — no cloud model is ever an
# acceptable substitute (a core requirement: all computing must
# be done locally on the NVIDIA DGX Spark). Enforced in
# OpenClawModelClient.__init__ below rather than left as just a default,
# so a stray config edit can't silently start routing completions to a
# cloud provider through OpenClaw's own catalog.
LOCAL_MODEL_ID = "ollama/qwen3-vl:30b-a3b"

_DEFAULTS: dict[str, Any] = {
    "model": LOCAL_MODEL_ID,
    "thinking": "low",
    "timeout_seconds": 120,
    "reasoning_visible": True,
}


def _load_config(config_path: Path) -> dict[str, Any]:
    """Read config/models.yaml, falling back to hardcoded defaults.

    Deliberately simple: one file, no sections, no merging logic beyond
    "yaml value if present, else default". Any read/parse error is
    swallowed (best-effort, per the fallback pattern this mirrors)
    and defaults are used instead.
    """
    cfg: dict[str, Any] = dict(_DEFAULTS)
    try:
        if config_path.exists():
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                cfg.update({k: v for k, v in raw.items() if v is not None})
    except Exception:
        pass
    return cfg


class OpenClawModelClient:
    """Thin async wrapper around `openclaw infer model run --json`.

    This is the ONLY place in the whole codebase allowed to shell out to
    `openclaw`, and only ever via `infer model run` — never `agent`. That
    subcommand used to let OpenClaw's own agent act autonomously (shelling
    out with `agent --message "...use your exec tool to do X yourself..."`);
    that pattern is ripped out project-wide. From here on, we (this
    codebase) run the vision -> decide -> act loop ourselves, and only ask
    OpenClaw for a single raw model completion each turn.
    """

    def __init__(self, config_path: Path | str = _CONFIG_PATH) -> None:
        self.config_path = Path(config_path)
        cfg = _load_config(self.config_path)
        self.model: str = str(cfg["model"])
        if self.model != LOCAL_MODEL_ID:
            raise RuntimeError(
                f"Refusing to use model {self.model!r}: this project only ever runs "
                f"the local model {LOCAL_MODEL_ID!r} (config/models.yaml). Cloud models "
                f"are not supported — fix config/models.yaml instead of pointing it "
                f"elsewhere."
            )
        self.thinking: str = str(cfg["thinking"])
        self.timeout_seconds: float = float(cfg["timeout_seconds"])
        self.reasoning_visible: bool = bool(cfg["reasoning_visible"])
        # Resolve the `openclaw` binary the same cautious way the
        # now-deleted execution.control_backend.OpenClawBackend used to
        # (shutil.which, so a Windows .cmd shim on PATH resolves properly),
        # falling back to the literal string if PATH lookup fails.
        self._binary: str = shutil.which("openclaw") or "openclaw"

    async def complete(
        self,
        prompt: str,
        *,
        image_path: Optional[Path | str] = None,
        thinking: Optional[str] = None,
    ) -> str:
        """Run one stateless `openclaw infer model run` completion call.

        Returns the model's raw text response (`outputs[0]["text"]`).
        Raises RuntimeError (with a stderr excerpt) on non-zero exit,
        on timeout, or if stdout can't be parsed as the expected JSON
        shape — callers (the planner) decide how to handle failures (e.g.
        retry); this client never silently swallows errors.
        """
        args: list[str] = [
            self._binary,
            "infer",
            "model",
            "run",
            "--model",
            self.model,
            "--prompt",
            prompt,
        ]
        if image_path is not None:
            args.extend(["--file", str(image_path)])
        args.extend(["--thinking", thinking or self.thinking])
        args.append("--json")

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Could not find the `openclaw` binary (resolved as {self._binary!r}): {exc}"
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise RuntimeError(
                f"`openclaw infer model run` timed out after {self.timeout_seconds}s "
                f"(model={self.model!r})"
            ) from exc
        except asyncio.CancelledError:
            # The caller (core/orchestrator.py's run_task, cancelled via
            # backend/main.py's /cancel endpoint) gave up on this turn -
            # without this, only the internal timeout above ever killed the
            # subprocess, so a user-cancelled task left its `openclaw infer
            # model run` process running to completion in the background,
            # still burning GPU time on a result nothing will ever read.
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            raise RuntimeError(
                f"`openclaw infer model run` exited {proc.returncode} "
                f"(model={self.model!r}); stderr excerpt: {stderr_text[-2000:]!r}"
            )

        try:
            data = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Could not parse `openclaw infer model run` stdout as JSON: {exc}; "
                f"stdout excerpt: {stdout_text[:2000]!r}; stderr excerpt: {stderr_text[-2000:]!r}"
            ) from exc

        try:
            outputs = data["outputs"]
            text = outputs[0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Unexpected `openclaw infer model run` JSON shape (missing outputs[0].text): "
                f"{exc}; payload excerpt: {json.dumps(data)[:2000]!r}"
            ) from exc

        if not isinstance(text, str):
            raise RuntimeError(
                f"Unexpected `openclaw infer model run` output text type: {type(text)!r}"
            )

        return text


# ---------------------------------------------------------------------------
# Model status (cloud vs. local, availability) — for the UI's mode indicator
# ---------------------------------------------------------------------------

# Keyed by model string; (fetched_at, result). Read-only catalog lookup that
# doesn't change mid-session (the configured model is fixed until someone
# edits config/models.yaml and restarts the backend), so a short TTL just
# avoids a ~1s subprocess round trip on every frontend poll/page load rather
# than actually needing freshness.
_STATUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_STATUS_CACHE_TTL_SECONDS = 30.0


def _unknown_status(model: str, provider: str, error: str) -> dict[str, Any]:
    return {
        "model": model,
        "provider": provider,
        "display_name": model,
        "local": None,
        "available": None,
        "mode": "unknown",
        "error": error,
    }


async def get_model_status(config_path: Path | str = _CONFIG_PATH) -> dict[str, Any]:
    """Ask OpenClaw's own model catalog whether the configured model is
    cloud-hosted or local, and currently available.

    Uses `openclaw models list --json --provider <provider>` — a read-only
    catalog inspection, not an agent/exec call, and (unlike `openclaw
    models status --json`, which embeds live OAuth tokens) safe to expose
    to the frontend as-is. Degrades to mode="unknown" (never raises) on
    any failure — CLI missing, timeout, bad JSON, model not in the catalog
    — since this is purely informational for the UI, not on the critical
    path for actually running a task.
    """
    cfg = _load_config(Path(config_path))
    model = str(cfg["model"])
    provider = model.split("/", 1)[0] if "/" in model else model

    cached = _STATUS_CACHE.get(model)
    now = time.time()
    if cached is not None and now - cached[0] < _STATUS_CACHE_TTL_SECONDS:
        return cached[1]

    binary = shutil.which("openclaw") or "openclaw"
    result: dict[str, Any]
    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "models",
            "list",
            "--json",
            "--provider",
            provider,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode != 0:
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            result = _unknown_status(model, provider, stderr_text or f"exit {proc.returncode}")
        else:
            payload = json.loads(stdout_bytes.decode("utf-8", errors="replace"))
            entry = next(
                (m for m in payload.get("models", []) if m.get("key") == model), None
            )
            if entry is None:
                result = _unknown_status(
                    model, provider, f"model {model!r} not found in openclaw's catalog"
                )
            else:
                is_local = bool(entry.get("local", False))
                result = {
                    "model": model,
                    "provider": provider,
                    "display_name": entry.get("name") or model,
                    "local": is_local,
                    "available": bool(entry.get("available", False)),
                    "mode": "local" if is_local else "cloud",
                }
    except FileNotFoundError as exc:
        result = _unknown_status(model, provider, f"openclaw CLI not found: {exc}")
    except asyncio.TimeoutError:
        result = _unknown_status(model, provider, "openclaw models list timed out")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        result = _unknown_status(model, provider, f"unexpected openclaw output: {exc}")

    _STATUS_CACHE[model] = (now, result)
    return result
