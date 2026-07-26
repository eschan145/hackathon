"""Stopgap Verifier that asks OpenClaw's own agent to judge success.

verification.verifier.ActionVerifier needs a local VLM endpoint reachable
per config/models.yaml (`vision.base_url`) for its screenshot-judge fallback.
Until one is being served, every step whose success can't be confirmed via
the (currently placeholder-shaped) accessibility snapshot or a literal OCR
text match defaults to "unverified" -- so even an action that actually
succeeded (e.g. Notepad really did open) loops through retries/replans
until max_replans_exhausted, and the task reports FAILED despite having
worked.

OpenClaw's own agent already has a working model + exec tool (see
execution.control_backend.OpenClawBackend) and can answer factual
yes/no questions about current system state (verified earlier: correctly
read the active window title without being asked to act). This verifier
asks it, non-destructively, whether the step's success_criteria currently
holds, instead of defaulting to failure.

Swap back to (or combine with) verification.verifier.ActionVerifier once a
local vision-model endpoint is actually being served per config/models.yaml.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

from core.models import ActionResult, Step

_YES_RE = re.compile(r"\byes\b", re.IGNORECASE)
_NO_RE = re.compile(r"\bno\b", re.IGNORECASE)


class OpenClawVerifier:
    """Asks the local OpenClaw agent to judge whether a step's criteria hold."""

    def __init__(
        self,
        agent_id: str = "main",
        cli_path: str = "openclaw",
        timeout_seconds: int = 90,
    ) -> None:
        self.agent_id = agent_id
        self.cli_path = cli_path
        self.timeout_seconds = timeout_seconds

    async def verify(self, step: Step, action_result: ActionResult) -> tuple[bool, dict[str, Any]]:
        if not action_result.success:
            # The action itself already reported failure (e.g. the backend
            # call errored) -- no need to ask the agent to check anything.
            return False, {"reason": "action_result.success was False", "backend": "openclaw"}

        message = (
            "Do not take any new action or open/close anything. Just check the current "
            f"state of this computer and answer: is the following currently true: "
            f"{step.success_criteria!r}. Reply with YES or NO as the first word, then a "
            "brief one-sentence reason."
        )

        resolved_cli = shutil.which(self.cli_path) or self.cli_path
        try:
            proc = subprocess.run(
                [resolved_cli, "agent", "--agent", self.agent_id, "--message", message, "--json"],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=(os.name == "nt"),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return False, {"reason": f"openclaw call failed: {exc}", "backend": "openclaw"}

        if proc.returncode != 0:
            return False, {"reason": proc.stderr.strip() or "openclaw exited non-zero", "backend": "openclaw"}

        reply = _extract_reply(proc.stdout) or proc.stdout
        passed = bool(_YES_RE.search(reply)) and not bool(_NO_RE.match(reply.strip()))
        return passed, {"reply": reply, "backend": "openclaw"}


def _extract_reply(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None

    def _search(node: Any) -> str | None:
        if isinstance(node, dict):
            for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
                if key in node:
                    return node[key]
            for value in node.values():
                found = _search(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = _search(item)
                if found is not None:
                    return found
        return None

    return _search(payload)
