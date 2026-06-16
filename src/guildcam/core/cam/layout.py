"""Multi-part worktable layout & nesting (BUILDPLAN M6.5).

Cut several components — frame front(s), temples, base-curve block(s) — in **one**
GRBL program on the bed. The bed *is* the fixture (config/fixtures/guild_cnc.yaml
already carries the six blank zones + hold-down screws); each component is
generated in its own design frame, translated onto its bed zone, and the whole
set is scheduled to **minimise tool changes across the bed** (group by tool while
respecting each part's internal op order, M6.1) before posting.

Everything here is geometry on `CamOp` paths plus a precedence-aware scheduler; the
existing `write_castle_program` posts the combined op list, and `cuttime` /
`lint_program` measure and gate it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .castle_ops import CamOp

Point3 = tuple[float, float, float]


# ------------------------------------------------------------------ geometry

def ops_bbox_center(ops: list[CamOp]) -> tuple[float, float]:
    """XY centre of the combined bounding box of every op path (design frame)."""
    xs: list[float] = []
    ys: list[float] = []
    for op in ops:
        for path in op.paths:
            for x, y, _ in path:
                xs.append(x)
                ys.append(y)
    if not xs:
        return (0.0, 0.0)
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def transform_ops(ops: list[CamOp], dx: float, dy: float,
                  rotation_deg: float = 0.0) -> list[CamOp]:
    """New CamOps with each path rotated about the origin then translated by
    (dx, dy). Z, tool and name are preserved."""
    th = math.radians(rotation_deg)
    c, s = math.cos(th), math.sin(th)
    out: list[CamOp] = []
    for op in ops:
        new = CamOp(op.name, tool=op.tool)
        for path in op.paths:
            new.paths.append([(c * x - s * y + dx, s * x + c * y + dy, z)
                              for x, y, z in path])
        out.append(new)
    return out


def zone_center(fixture: dict, zone_name: str) -> tuple[float, float]:
    """Machine-coordinate centre of a fixture blank zone."""
    z = fixture["blank_zones"][zone_name]
    return (z["x_mm"] + z["width_mm"] / 2.0, z["y_mm"] + z["height_mm"] / 2.0)


def place_ops_at_zone(
    ops: list[CamOp], fixture: dict, zone_name: str, rotation_deg: float = 0.0,
) -> tuple[list[CamOp], tuple[float, float]]:
    """Rotate (about origin) then translate `ops` so their bounding-box centre
    lands on the zone centre. Returns (placed_ops, (dx, dy) applied)."""
    rotated = transform_ops(ops, 0.0, 0.0, rotation_deg) if rotation_deg else ops
    bx, by = ops_bbox_center(rotated)
    cx, cy = zone_center(fixture, zone_name)
    dx, dy = cx - bx, cy - by
    placed = transform_ops(ops, dx, dy, rotation_deg)
    return placed, (dx, dy)


# ------------------------------------------------------------------ scheduling

def schedule_bed_ops(components: list[list[CamOp]]) -> list[CamOp]:
    """Order ops across components to minimise tool changes (BUILDPLAN M6.5).

    Hard constraint: each component's ops keep their internal order (a part's
    drilling / relief must precede its profile release). Within that, we greedily
    stay on the current tool while any ready op needs it, and when forced to
    change pick the ready tool with the *fewest remaining ops* — front-loading the
    special tools (drill / engrave / pocket) and batching the bulk last. The
    number of changes is then the minimum (one per distinct tool) whenever the
    parts' tool orders don't conflict.
    """
    pointers = [0] * len(components)
    remaining: dict[str | None, int] = {}
    for comp in components:
        for op in comp:
            remaining[op.tool_name] = remaining.get(op.tool_name, 0) + 1

    def ready() -> list[tuple[int, CamOp]]:
        return [(i, components[i][pointers[i]])
                for i in range(len(components)) if pointers[i] < len(components[i])]

    result: list[CamOp] = []
    current: str | None = None
    while any(pointers[i] < len(components[i]) for i in range(len(components))):
        rdy = ready()
        same = [(i, op) for i, op in rdy if op.tool_name == current]
        if same:
            i, op = same[0]
        else:
            tools = {op.tool_name for _, op in rdy}
            current = min(tools, key=lambda t: remaining.get(t, 0))
            i, op = next((i, op) for i, op in rdy if op.tool_name == current)
        result.append(op)
        remaining[op.tool_name] -= 1
        pointers[i] += 1
    return result


def count_distinct_tools(ops: list[CamOp]) -> int:
    return len({op.tool_name for op in ops if op.tool_name is not None})


# ------------------------------------------------------------------ clearance

def bed_clearance_violations(
    ops: list[CamOp], fixture: dict, skip_op_names: set | None = None,
) -> list[str]:
    """Check every placed (machine-coordinate) *cutting* toolpath point against
    the bed's hold-down screw keep-outs — the whole layout at once.

    `skip_op_names` are exempt — the base-curve block's mounting holes are drilled
    *at* the fixture's screw positions on purpose (the screws are its mounting
    bolts), so drilling ops are excluded; the contours / relief still must clear.
    """
    skip = skip_op_names or set()
    screws = np.array([[s["x"], s["y"]] for s in fixture["hold_down_screws"]])
    screw_r = fixture["hold_down_screw_radius_mm"]
    out: list[str] = []
    for op in ops:
        if op.name in skip:
            continue
        op_r = op.tool["radius_mm"] if op.tool else 0.0
        keep_r = screw_r + op_r
        for path in op.paths:
            pts = np.asarray([(p[0], p[1]) for p in path], dtype=float)
            if pts.size == 0:
                continue
            d2 = ((pts[:, None, :] - screws[None, :, :]) ** 2).sum(axis=2)
            hit = np.flatnonzero((d2 < keep_r ** 2).any(axis=1))
            if hit.size:
                x, y = pts[hit[0]]
                out.append(f"{op.name}: enters a screw keep-out near "
                           f"machine ({x:.1f}, {y:.1f})")
                break
    return out


# ------------------------------------------------------------------ assembly

@dataclass
class BedPart:
    """A component to place on the bed: its ops (design frame) + classification."""
    kind: str
    label: str
    zone: str
    ops: list[CamOp]
    contour_names: set = field(default_factory=set)
    drill_names: set = field(default_factory=set)
    rotation_deg: float = 0.0


@dataclass
class BedProgram:
    ops: list[CamOp]                       # scheduled, in machine coordinates
    contour_op_names: set
    drill_op_names: set
    placements: list                       # ComponentPlacement, with applied dx/dy
    n_tool_changes: int


def build_bed_program(parts: list[BedPart], fixture: dict) -> BedProgram:
    """Place each part on its zone, prefix its op names with the part label,
    collect the through-cut / drill name sets, schedule the whole bed by tool, and
    return the combined op list ready for `write_castle_program`."""
    from ..project.schema import ComponentPlacement

    placed_components: list[list[CamOp]] = []
    contour_names: set = set()
    drill_names: set = set()
    placements: list = []

    for part in parts:
        placed, (dx, dy) = place_ops_at_zone(part.ops, fixture, part.zone, part.rotation_deg)
        for op in placed:
            base = op.name
            op.name = f"{part.label} · {base}"
            if base in part.contour_names:
                contour_names.add(op.name)
            if base in part.drill_names:
                drill_names.add(op.name)
        placed_components.append(placed)
        placements.append(ComponentPlacement(
            kind=part.kind, label=part.label, fixture_zone=part.zone,
            x_mm=round(dx, 3), y_mm=round(dy, 3), rotation_deg=part.rotation_deg))

    scheduled = schedule_bed_ops(placed_components)
    # tool changes the post will emit over the scheduled order
    changes = 0
    cur = None
    for op in scheduled:
        if op.tool_name is not None and cur is not None and op.tool_name != cur:
            changes += 1
        if op.tool_name is not None:
            cur = op.tool_name
    return BedProgram(scheduled, contour_names, drill_names, placements, changes)
