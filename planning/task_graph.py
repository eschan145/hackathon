"""DAG utilities over `core.models.TaskGraph` / `Step`.

Built on `networkx` for topological/cycle operations. Keeps the graph
representation ephemeral (built from a TaskGraph on demand) rather than
threading a networkx object through the rest of the system, since
core.models.TaskGraph/Step are the shared contract other subsystems import.
"""

from __future__ import annotations

import networkx as nx

from core.models import Step, TaskGraph


class CyclicGraphError(ValueError):
    """Raised when a TaskGraph's step dependencies contain a cycle."""


def to_networkx(graph: TaskGraph) -> nx.DiGraph:
    """Build a `networkx.DiGraph` from a TaskGraph.

    Nodes are step ids; each node stores the `Step` object under the
    "step" attribute. Edges point from dependency -> dependent
    (i.e. `dep -> step` for each `step.id` depending on `dep`).
    """
    g = nx.DiGraph()
    for step in graph.steps:
        g.add_node(step.id, step=step)
    for step in graph.steps:
        for dep_id in step.depends_on:
            if dep_id not in g:
                # Dangling dependency reference — add a stub node so the
                # graph stays well-formed; callers can detect/flag this
                # via missing "step" attribute if needed.
                g.add_node(dep_id)
            g.add_edge(dep_id, step.id)
    return g


def has_cycle(graph: TaskGraph) -> bool:
    """Return True if the step dependencies contain a cycle."""
    g = to_networkx(graph)
    return not nx.is_directed_acyclic_graph(g)


def find_cycle(graph: TaskGraph) -> list[str] | None:
    """Return one cycle (list of step ids) if present, else None."""
    g = to_networkx(graph)
    try:
        cycle_edges = nx.find_cycle(g)
        return [u for u, v in cycle_edges]
    except nx.NetworkXNoCycle:
        return None


def validate_dag(graph: TaskGraph) -> None:
    """Raise `CyclicGraphError` if the graph has a dependency cycle."""
    cycle = find_cycle(graph)
    if cycle is not None:
        raise CyclicGraphError(f"TaskGraph {graph.task_id!r} has a dependency cycle: {cycle}")


def get_ready_steps(graph: TaskGraph, completed_ids: set[str]) -> list[Step]:
    """Return steps whose dependencies are all in `completed_ids` and that
    have not themselves completed or failed yet.

    A step is "ready" when every id in its `depends_on` is present in
    `completed_ids` and the step's own status is still "pending" or
    "ready" (i.e. not already running/verified/failed/skipped).
    """
    ready: list[Step] = []
    for step in graph.steps:
        if step.status not in ("pending", "ready"):
            continue
        if all(dep_id in completed_ids for dep_id in step.depends_on):
            ready.append(step)
    return ready


def group_parallelizable(steps: list[Step]) -> list[list[Step]]:
    """Partition a set of *ready* steps into groups that can run concurrently.

    Heuristic (intentionally simple — no true resource/data-conflict
    analysis): two steps are considered safe to run in parallel only if
    they do NOT share the same `tool_hint` (a rough proxy for "touches the
    same app/backend"). Steps with an empty tool_hint are treated as
    always-conflicting with each other (unknown target => be conservative)
    but not with steps that do have a tool_hint. Any step with
    `exclusive=True` is always placed alone in its own group, since it
    must never run concurrently with anything else.

    Returns a list of groups (lists of Steps); steps within a group may be
    dispatched concurrently, groups themselves are just a partition (not
    an execution order — the caller already knows these steps are all
    "ready" simultaneously).
    """
    groups: list[list[Step]] = []
    used_tool_hints: set[str] = set()
    empty_hint_group_started = False
    remaining = list(steps)

    # Exclusive steps each get their own group up front.
    exclusive = [s for s in remaining if s.exclusive]
    remaining = [s for s in remaining if not s.exclusive]
    for s in exclusive:
        groups.append([s])

    current_group: list[Step] = []
    for step in remaining:
        hint = step.tool_hint or ""
        conflicts = (hint == "" and empty_hint_group_started) or (hint != "" and hint in used_tool_hints)
        if conflicts:
            groups.append(current_group)
            current_group = []
            used_tool_hints = set()
            empty_hint_group_started = False

        current_group.append(step)
        if hint == "":
            empty_hint_group_started = True
        else:
            used_tool_hints.add(hint)

    if current_group:
        groups.append(current_group)

    return groups


def mark_completed(graph: TaskGraph, step_id: str, status: str = "verified") -> None:
    """Convenience helper: set a step's status in-place (mutates `graph`)."""
    step = graph.step_by_id(step_id)
    if step is not None:
        step.status = status  # type: ignore[assignment]
