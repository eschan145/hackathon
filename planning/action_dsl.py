"""The compact action language OpenClaw's model emits each turn, and its parser.

Deliberately a tiny line-based grammar rather than JSON: one action per line
is cheap for the model to emit and cheap for us to parse, which matters
because every turn is a real, separately-billed `openclaw infer model run`
call (see planning/openclaw_client.py) — there is no session state on the
far side, so keeping both the prompt *and* the expected response compact is
a direct token/latency win, not just style.

Grammar (one call per line, args like a Python call):

    click(<element_id>)
    type(<element_id>, "text")
    key("ctrl+l")
    scroll("up"|"down"|"left"|"right", <amount>)
    launch("<app name>")
    focus(<window_id>)
    wait(<seconds>)
    done("<summary>")
    fail("<reason>")

`done`/`fail` are loop-control signals, not screen actions: they terminate
the agent loop (see planning/vision_agent_planner.py) rather than being
executed by execution/interpreter.py.

Any line starting with `#` is reasoning/commentary, not an action — the
model is asked to only emit these when the caller's prompt says reasoning
is enabled, so a disabled run naturally omits them (fewer output tokens).
Unparseable non-blank, non-comment lines are dropped rather than raising,
so one malformed line doesn't blow up an otherwise-useful chunk of actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SCREEN_ACTION_KINDS = ("click", "type", "key", "scroll", "launch", "focus", "wait")
CONTROL_ACTION_KINDS = ("done", "fail")
ACTION_KINDS = SCREEN_ACTION_KINDS + CONTROL_ACTION_KINDS

# Enforced defensively by callers (planner truncates, interpreter never sees
# more): keeps a single turn's blast radius small enough to re-observe and
# course-correct from, per the "chunks at a time" design.
MAX_ACTIONS_PER_TURN = 5

ACTION_DSL_SPEC = f"""Respond with plain text only (no markdown fences, no JSON). Emit at most {MAX_ACTIONS_PER_TURN} actions, one per line, using exactly this grammar:

click(<element_id>)              click the numbered element
type(<element_id>, "text")       click the numbered element, then type text into it
key("ctrl+l")                    press a key or chord (lowercase, + separated; use "enter", "=", "escape", "tab", "backspace" — not word names like "equals"/"return")
scroll("up"|"down"|"left"|"right", <amount>)
launch("<app name>")             launch an installed application by name
focus(<window_id>)               bring an already-open window to the front
wait(<seconds>)                  pause before observing again (e.g. after launching something slow)
done("<summary>")                the objective is fully complete; stop
fail("<reason>")                 the objective cannot be completed; stop

Only reference element ids and window ids that appear in the CURRENT screen state given to you this turn — ids are reassigned every turn and are not stable across turns.
Emit only the actions for this turn; you will see the resulting screen state and can continue next turn. Do not narrate future turns."""


@dataclass
class Action:
    """One parsed action-DSL call."""

    kind: str  # one of ACTION_KINDS
    element_id: Optional[int] = None
    window_id: Optional[str] = None
    text: Optional[str] = None
    keys: Optional[str] = None
    direction: Optional[str] = None
    amount: int = 3
    app_name: Optional[str] = None
    seconds: float = 1.0
    message: Optional[str] = None  # done()/fail() summary/reason
    raw: str = ""  # original source line, kept for logging/audit


def _split_args(inner: str) -> list[str]:
    """Split a call's parenthesized contents on top-level commas, honoring quotes."""
    args: list[str] = []
    cur = ""
    in_quotes = False
    quote_char = ""
    i = 0
    while i < len(inner):
        c = inner[i]
        if in_quotes:
            if c == "\\" and i + 1 < len(inner):
                cur += inner[i + 1]
                i += 2
                continue
            if c == quote_char:
                in_quotes = False
                i += 1
                continue
            cur += c
        else:
            if c in ("\"", "'"):
                in_quotes = True
                quote_char = c
                i += 1
                continue
            if c == ",":
                args.append(cur.strip())
                cur = ""
                i += 1
                continue
            cur += c
        i += 1
    tail = cur.strip()
    if tail or args:
        args.append(tail)
    return [a for a in args if a != ""]


def _unquote(arg: str) -> str:
    if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in ("\"", "'"):
        return arg[1:-1]
    return arg


def _parse_line(line: str) -> Optional[Action]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None

    open_paren = stripped.find("(")
    if open_paren == -1 or not stripped.endswith(")"):
        return None

    kind = stripped[:open_paren].strip().lower()
    if kind not in ACTION_KINDS:
        return None

    args = _split_args(stripped[open_paren + 1 : -1])

    try:
        if kind == "click":
            return Action(kind=kind, element_id=int(args[0]), raw=stripped)
        if kind == "type":
            return Action(kind=kind, element_id=int(args[0]), text=_unquote(args[1]), raw=stripped)
        if kind == "key":
            return Action(kind=kind, keys=_unquote(args[0]), raw=stripped)
        if kind == "scroll":
            return Action(
                kind=kind,
                direction=_unquote(args[0]).lower(),
                amount=int(args[1]) if len(args) > 1 else 3,
                raw=stripped,
            )
        if kind == "launch":
            return Action(kind=kind, app_name=_unquote(args[0]), raw=stripped)
        if kind == "focus":
            return Action(kind=kind, window_id=_unquote(args[0]), raw=stripped)
        if kind == "wait":
            return Action(kind=kind, seconds=float(args[0]) if args else 1.0, raw=stripped)
        if kind in ("done", "fail"):
            return Action(kind=kind, message=_unquote(args[0]) if args else "", raw=stripped)
    except (IndexError, ValueError):
        return None

    return None


def parse_actions(text: str) -> tuple[Optional[str], list[Action]]:
    """Parse a model turn's raw text into (reasoning, actions).

    `reasoning` is the concatenation of any `#`-prefixed lines (None if
    there were none). `actions` preserves source order; a line that isn't
    blank/comment/valid-grammar is silently skipped rather than raising, so
    one bad line doesn't discard an otherwise-useful chunk.
    """
    reasoning_lines: list[str] = []
    actions: list[Action] = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            reasoning_lines.append(stripped.lstrip("#").strip())
            continue
        action = _parse_line(stripped)
        if action is not None:
            actions.append(action)

    reasoning = " ".join(reasoning_lines) if reasoning_lines else None
    return reasoning, actions
