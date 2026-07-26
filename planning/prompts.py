"""System/user prompt templates for the planning LLM.

Both templates ask the model to emit JSON matching the `TaskGraph`/`Step`
schema in `core.models` (see planning/llm_client.py for how that JSON is
validated/parsed). Keeping the templates in one module makes it easy to
iterate on prompt wording without touching planner logic.
"""

from __future__ import annotations

import json
from typing import Any

# Shared schema description injected into both prompts so the model always
# sees the exact field names/types it must produce.
_STEP_SCHEMA = """
Each Step object must have exactly these fields:
- "id": short unique string identifier, e.g. "s1", "s2" (must be unique within the graph)
- "description": a clear, concrete, single-action instruction (what to do, on which app/target)
- "tool_hint": free-form hint for the executor about which tool/app/backend is likely needed,
    e.g. "native_input", "openclaw", "mcp:gmail", "mcp:calendar", "browser"
- "depends_on": list of other step "id" strings that must complete before this step can run
    (empty list if this step can start immediately)
- "risk_level": one of "low", "medium", "high" — use "high" for irreversible actions such as
    sending emails/messages, making payments, deleting files, or submitting forms with
    real-world side effects; use "medium" for actions that change persistent state but are
    reversible; use "low" for read-only / navigational actions
- "success_criteria": a natural-language predicate describing observable evidence that this
    step succeeded, phrased so a vision/verification model can check it against a screenshot,
    e.g. "Sent folder contains an email to John with subject containing 'project update'"
- "status": always the literal string "pending" for newly created steps
"""

DECOMPOSITION_SYSTEM_PROMPT = f"""You are the planning module of a local autonomous desktop assistant.
Given a user's natural-language objective, decompose it into a directed acyclic graph (DAG) of
concrete, executable Steps that a computer-control agent can perform on the user's actual
desktop (clicking, typing, launching apps, calling integrations like Gmail/Todoist/Calendar/
Notion/Drive/GitHub via MCP tools, or manipulating local files).

Rules:
- Prefer the smallest number of steps that fully accomplishes the objective, but never merge two
  logically distinct actions (e.g. "open app" and "compose email" should usually be separate
  steps) since each step is independently verified before the next one starts.
- Encode true dependencies via "depends_on" so independent steps can run in parallel. Do not add
  a dependency unless one step's output/state is actually required by another.
- Assign risk_level conservatively: anything irreversible or externally visible (sending
  messages, payments, deletions, posting publicly) is "high".
- success_criteria must be checkable from a screenshot, OCR text, or an accessibility tree/API
  response — avoid vague criteria like "task looks correct".
- Output ONLY a single JSON object, no prose, no markdown fences, matching this schema exactly:

{{
  "task_id": "<echo the provided task id>",
  "objective": "<echo the provided objective>",
  "steps": [ {{ ...Step fields... }}, ... ]
}}
{_STEP_SCHEMA}
"""

REPLAN_SYSTEM_PROMPT = f"""You are the replanning module of a local autonomous desktop assistant.
A previously generated plan (TaskGraph) is currently being executed. One step failed after its
retries were exhausted. Given the original graph, the failed step, and failure context (error
message, verifier details, and a description of what the screen looked like), produce a PATCHED
TaskGraph.

Rules:
- Reuse the given "task_id" and "objective" verbatim.
- Keep all steps that already succeeded (status "verified") unchanged, including their "id".
- Replace ONLY the failed branch: the failed step itself and any steps that depended on it
  (directly or transitively) that have not yet run. You may introduce new steps, new step ids,
  and a different approach for that branch (e.g. an alternate app, alternate tool_hint, or
  additional recovery/verification steps) as long as it still satisfies the branch's original
  purpose within the overall objective.
- Do not remove or alter steps that are unrelated to the failed branch.
- Every step in the output must have "status" set to "pending" unless it was already "verified"
  in the input graph (copy those through as "verified").
- Output ONLY a single JSON object with the same schema as plan generation (task_id, objective,
  steps[]), no prose, no markdown fences.
{_STEP_SCHEMA}
"""


def build_decomposition_user_prompt(
    task_id: str,
    objective: str,
    memory_context: dict[str, Any] | None = None,
) -> str:
    """User-turn content for initial plan generation.

    `memory_context` is optional extra context pulled from the Memory
    subsystem (e.g. similar past workflows, known contacts/preferences) —
    kept as a free-form dict since Memory's exact shape isn't finalized yet.
    """
    parts = [
        f"task_id: {task_id}",
        f"objective: {objective}",
    ]
    if memory_context:
        parts.append(
            "relevant_memory_context (use if helpful, ignore if irrelevant):\n"
            + json.dumps(memory_context, indent=2, default=str)
        )
    parts.append("Produce the TaskGraph JSON now.")
    return "\n\n".join(parts)


def build_replan_user_prompt(
    task_id: str,
    objective: str,
    current_graph_json: dict[str, Any],
    failure_context: dict[str, Any],
) -> str:
    """User-turn content for replanning after a step failure."""
    parts = [
        f"task_id: {task_id}",
        f"objective: {objective}",
        "current_graph:\n" + json.dumps(current_graph_json, indent=2, default=str),
        "failure_context:\n" + json.dumps(failure_context, indent=2, default=str),
        "Produce the patched TaskGraph JSON now.",
    ]
    return "\n\n".join(parts)
