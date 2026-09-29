"""Operation order within one component's program: the briefest tool first,
where the cut allows it (2026-09-27).

The worktable scheduler (`layout.schedule_bed_ops`) has ordered a *bed* this way
since M6.5: stay on the current tool while anything ready needs it, and when a
change is unavoidable pick the ready tool with the least total work over the
whole program, so the distinct tools come out in ascending order of work and
the longest-running tool is last. On a desktop machine with no tool changer
that is what minimizes the operator's attended time: the brief tools are
changed through at the start, and the long one runs the bulk of the job alone.

A single component's program never got the same treatment — each generator
emitted its ops in a fixed order. On a temple whose hinge pockets and profile
share a 2 mm end mill and whose engraving takes the engraving bit, that put the
end mill first, then a change to the bit, then a change back: two changes and
the long tool split around the short one. The maker's ask: the engraving bit
runs first, the operator pre-loads it, starts the program, and swaps once.

`order_by_tool_work` does that under **precedence tiers** the generator states:
every op in tier *k* precedes every op in tier *k+1* (pocket and engrave while
the blank is rigid; then inside through-cuts; then the profile that releases the
part). Within a tier the bed's greedy applies. An op the tiers do not name is a
barrier — it keeps its place, and nothing crosses it — so a generator that grows
an op the tiers have not heard of gets the historical order around it rather
than a guess.

Work is measured by 3D cutting length, as on the bed: a tool's total length
dominates its time, and the feeds are not stamped until the post. A caller
that has them may pass `cost`.
"""
from __future__ import annotations

from typing import Callable, Iterable

from .castle_ops import CamOp

_NO_TOOL = object()


def order_by_tool_work(
    ops: list[CamOp],
    tiers: Iterable[Iterable[str]],
    cost: Callable[[CamOp], float] | None = None,
) -> list[CamOp]:
    """`ops` reordered so the tool with the least total work runs first wherever
    `tiers` allow, with tool changes kept to the minimum the order permits.

    Stable: ops of one tool within one tier keep their generator order, and a
    program that uses a single tool comes back exactly as it went in. The op
    objects are the same objects; only the list order changes.
    """
    cost = cost if cost is not None else (lambda op: op.path_length_mm())
    tier_of: dict[str, int] = {}
    for k, names in enumerate(tiers):
        for name in names:
            tier_of.setdefault(name, k)

    tool_cost: dict[str | None, float] = {}
    tool_ops: dict[str | None, int] = {}
    for op in ops:
        tool_cost[op.tool_name] = tool_cost.get(op.tool_name, 0.0) + cost(op)
        tool_ops[op.tool_name] = tool_ops.get(op.tool_name, 0) + 1

    def rank(tool: str | None) -> tuple:
        # ascending: least total work first → the longest-running tool last
        return (tool_cost.get(tool, 0.0), tool_ops.get(tool, 0), str(tool))

    out: list[CamOp] = []
    # Nothing is loaded before the first op: a sentinel, not None, so an op
    # that carries no tool (tool_name None) is ranked like any other rather
    # than mistaken for "the tool already in the spindle".
    current: object = _NO_TOOL

    def emit_segment(segment: list[CamOp]) -> None:
        nonlocal current
        # tiers in order; within a tier the bed's greedy
        levels = sorted({tier_of[op.name] for op in segment})
        for level in levels:
            pending = [op for op in segment if tier_of[op.name] == level]
            while pending:
                same = [op for op in pending if op.tool_name == current]
                if same:
                    op = same[0]
                else:
                    current = min({op.tool_name for op in pending}, key=rank)
                    op = next(op for op in pending if op.tool_name == current)
                out.append(op)
                pending.remove(op)

    segment: list[CamOp] = []
    for op in ops:
        if op.name in tier_of:
            segment.append(op)
            continue
        # a barrier: flush what precedes it, keep it in place, start afresh
        emit_segment(segment)
        segment = []
        out.append(op)
        current = op.tool_name
    emit_segment(segment)
    return out
