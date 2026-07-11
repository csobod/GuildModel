"""Multi-part worktable layout & nesting (BUILDPLAN M6.5 + M7.6).

Cut several components — frame front(s), temples, base-curve block(s) — in **one**
GRBL program on the bed. The bed *is* the fixture (config/fixtures/guild_cnc.yaml
already carries the six blank zones + hold-down screws); each component is
generated in its own design frame, translated onto its bed zone, and the whole
set is scheduled to **minimise tool changes across the bed** (group by tool while
respecting each part's internal op order, M6.1) before posting.

Everything here is geometry on `CamOp` paths plus a precedence-aware scheduler; the
existing `write_castle_program` posts the combined op list, and `cuttime` /
`lint_program` measure and gate it.

**M7.6** generalises the M6.5 fixture-name machinery onto the user-tagged
`Worktable` (M7.4): `nest_components_on_worktable` matches each built component to a
zone whose ROLE matches its kind (`frame_front` → a frame-front zone, …) and packs
several components of one kind across several same-role zones;
`worktable_clearance_violations` checks every placed cutting point against the bed's
**arbitrary keep-out polygons** (a screw circle is a special case), keeping the
base-curve drill-at-screw exemption. The M6.5 `build_bed_program` / fixture-dict path
stays for the legacy Guild-fixture flow and the M7.7 combined post.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

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


def rotate_ops_about(ops: list[CamOp], cx: float, cy: float,
                     deg: float) -> list[CamOp]:
    """New CamOps rotated by `deg` about the point (cx, cy) — rotation in place that
    keeps the ops' current position (used for interactive bed rotation, where a placed
    footprint spins about its own centre rather than the machine origin)."""
    th = math.radians(deg)
    c, s = math.cos(th), math.sin(th)
    # rotate-about-(cx,cy) = rotate-about-origin then translate by (c - R·c)
    rcx = c * cx - s * cy
    rcy = s * cx + c * cy
    return transform_ops(ops, cx - rcx, cy - rcy, deg)


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


def place_ops_at_polygon_zone(
    ops: list[CamOp], zone, rotation_deg: float = 0.0,
) -> tuple[list[CamOp], tuple[float, float]]:
    """Like `place_ops_at_zone` but onto a tagged `WorktableZone` polygon (M7.6):
    rotate about the origin then translate so the ops' bbox centre lands on the
    zone's bbox centre. Returns (placed_ops, (dx, dy) applied)."""
    rotated = transform_ops(ops, 0.0, 0.0, rotation_deg) if rotation_deg else ops
    bx, by = ops_bbox_center(rotated)
    cx, cy = zone.bbox_center()
    dx, dy = cx - bx, cy - by
    placed = transform_ops(ops, dx, dy, rotation_deg)
    return placed, (dx, dy)


# ------------------------------------------------------------------ scheduling

def schedule_bed_ops(
    components: list[list[CamOp]],
    cost: Callable[[CamOp], float] | None = None,
) -> list[CamOp]:
    """Order ops across components to minimise tool changes AND front-load the
    briefest tools (BUILDPLAN M6.5 + operator-time optimisation).

    Hard constraint: each component's ops keep their internal order (a part's
    drilling / relief must precede its profile release). Within that, we greedily
    stay on the current tool while any ready op needs it, and when forced to change
    pick the ready tool with the least TOTAL cutting work over the whole bed — so the
    distinct tools come out in ascending order of work and the single longest-running
    tool is LAST. On a desktop CNC with no automatic tool changer that minimises the
    operator's *monitored* time: every manual change happens in the brief opening
    phase, then the final tool runs the bulk of the job unattended. The change count
    stays the minimum (one per distinct tool) whenever the parts' tool orders agree.

    `cost` measures an op's work (default: its 3-D cutting length — a robust proxy for
    time, since a tool's total length dominates its cycle contribution). Op count is a
    secondary key, so ties (and the synthetic zero-length ops of unit tests) still order
    deterministically, with a name tie-break for full stability.
    """
    cost = cost if cost is not None else (lambda op: op.path_length_mm())
    pointers = [0] * len(components)
    tool_cost: dict[str | None, float] = {}
    tool_ops: dict[str | None, int] = {}
    for comp in components:
        for op in comp:
            tool_cost[op.tool_name] = tool_cost.get(op.tool_name, 0.0) + cost(op)
            tool_ops[op.tool_name] = tool_ops.get(op.tool_name, 0) + 1

    def rank(t: str | None) -> tuple:
        # ascending: least total work first → longest-running tool last
        return (tool_cost.get(t, 0.0), tool_ops.get(t, 0), str(t))

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
            current = min({op.tool_name for _, op in rdy}, key=rank)
            i, op = next((i, op) for i, op in rdy if op.tool_name == current)
        result.append(op)
        pointers[i] += 1
    return result


def count_distinct_tools(ops: list[CamOp]) -> int:
    return len({op.tool_name for op in ops if op.tool_name is not None})


def count_tool_changes(ops: list[CamOp]) -> int:
    """Number of tool changes the post will emit over `ops` in their given order."""
    changes = 0
    cur = None
    for op in ops:
        if op.tool_name is None:
            continue
        if cur is not None and op.tool_name != cur:
            changes += 1
        cur = op.tool_name
    return changes


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


def worktable_clearance_violations(
    ops: list[CamOp], worktable, skip_op_names: set | None = None,
) -> list[str]:
    """Check every placed (machine-coordinate) *cutting* point against the bed's
    **arbitrary keep-out polygons** (BUILDPLAN M7.6) — the polygon generalisation of
    `bed_clearance_violations`'s circular screws.

    Each KEEP_OUT zone contributes its polygon (a screw keeps its exact circle via
    `radius_mm`); a point is a violation when it falls within `tool_radius` of the
    keep-out (the tool would foul the hold-down). `skip_op_names` is exempt — the
    base-curve block's mounting holes are drilled *at* the screws on purpose, so the
    drill ops are excluded; contours / relief still must clear.
    """
    from shapely import contains_xy, prepare
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union

    skip = skip_op_names or set()
    base: list = []
    for z in worktable.keep_outs():
        if z.radius_mm is not None and z.radius_mm > 0:
            cx, cy = z.center()
            base.append(Point(cx, cy).buffer(float(z.radius_mm), quad_segs=24))
        elif len(z.polygon) >= 3:
            p = Polygon(z.polygon)
            if p.is_valid and not p.is_empty:
                base.append(p)
    if not base:
        return []

    guard_cache: dict[float, object] = {}

    def guard_for(op_r: float):
        key = round(op_r, 4)
        g = guard_cache.get(key)
        if g is None:
            g = unary_union([p.buffer(op_r) for p in base] if op_r > 0 else base)
            prepare(g)
            guard_cache[key] = g
        return g

    out: list[str] = []
    for op in ops:
        if op.name in skip:
            continue
        guard = guard_for(op.tool["radius_mm"] if op.tool else 0.0)
        hit_xy = None
        for path in op.paths:
            if not path:
                continue
            xs = np.fromiter((p[0] for p in path), dtype=float, count=len(path))
            ys = np.fromiter((p[1] for p in path), dtype=float, count=len(path))
            mask = contains_xy(guard, xs, ys)
            idx = np.flatnonzero(mask)
            if idx.size:
                hit_xy = (xs[idx[0]], ys[idx[0]])
                break
        if hit_xy is not None:
            out.append(f"{op.name}: enters a keep-out near "
                       f"machine ({hit_xy[0]:.1f}, {hit_xy[1]:.1f})")
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
    # Place by the DESIGN ORIGIN (the blank centre) instead of the ops' bbox centre.
    # A blank-end-snapped temple's ops live in its blank frame (blank centred on the
    # origin, butt on the short edge); mapping blank centre → zone centre keeps the
    # core end registered against the zone's end, exactly how the blank slides into
    # its slot on the worktable (2026-07-09 core-aligned nesting).
    place_by_origin: bool = False


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
    return BedProgram(scheduled, contour_names, drill_names, placements,
                      count_tool_changes(scheduled))


# ------------------------------------------------------------------ M7.6 role nesting

@dataclass
class BedPlacement:
    """One component placed on a tagged worktable zone (BUILDPLAN M7.6)."""
    kind: str                              # ComponentKind value
    label: str
    zone_id: str
    role: str                              # BedRole value (== kind for placements)
    dx: float                              # translation applied (machine coords)
    dy: float
    rotation_deg: float
    ops: list[CamOp]                       # placed ops (machine coords; names NOT prefixed)
    contour_names: set = field(default_factory=set)
    drill_names: set = field(default_factory=set)

    def nudge(self, ddx: float, ddy: float) -> None:
        """Shift the placement (and its placed ops) by (ddx, ddy) — interactive
        nudge on the bed; clearance is re-checked by the caller."""
        self.ops = transform_ops(self.ops, ddx, ddy, 0.0)
        self.dx += ddx
        self.dy += ddy

    def rotate(self, ddeg: float) -> None:
        """Rotate the placement in place about its own footprint centre by `ddeg`
        (interactive bed rotation — spin a temple so it loads into a slot, or flip the
        left temple 180° to face the right). The centre is preserved, so the part stays
        on its zone; ``rotation_deg`` accumulates and clearance is re-checked by the
        caller. The rotated ops post directly, so the worktable.nc matches the render."""
        cx, cy = ops_bbox_center(self.ops)
        self.ops = rotate_ops_about(self.ops, cx, cy, ddeg)
        self.rotation_deg = (self.rotation_deg + ddeg) % 360.0


@dataclass
class BedNest:
    """The result of nesting a project's components onto a worktable (M7.6)."""
    placements: list[BedPlacement]
    unplaced: list[BedPart]                # no free zone of the matching role
    work_area: tuple[float, float]

    def all_ops(self) -> list[CamOp]:
        return [op for pl in self.placements for op in pl.ops]

    def drill_op_names(self) -> set:
        names: set = set()
        for pl in self.placements:
            names |= pl.drill_names
        return names


# A temple_left is the mirror of a temple_right, so it nests hinge-reversed; a 180°
# default faces its end the same way as the right temple. A starting point only —
# the maker rotates any placement freely on the bed (BedPlacement.rotate).
_DEFAULT_NEST_ROTATION_DEG: dict[str, float] = {"temple_left": 180.0}


def default_nest_rotation(kind: str) -> float:
    """The sensible starting rotation (deg) for a component of `kind` on the bed."""
    return _DEFAULT_NEST_ROTATION_DEG.get(kind, 0.0)


def nest_components_on_worktable(parts: list[BedPart], worktable) -> BedNest:
    """Place each part on a zone whose ROLE matches its kind (BUILDPLAN M7.6).

    Parts of a kind fill the same-role zones in order (bottom-left zone first), so
    N copies of a kind nest across N same-role zones; a part with no free matching
    zone is returned unplaced. Each placed part's ops are in machine coordinates
    (bbox centre → zone bbox centre, like M6.5), names left UN-prefixed (the M7.7
    combined post prefixes them; clearance + render read base names).
    """
    from ..project.schema import BedRole

    pools: dict[BedRole, list] = {}
    for z in worktable.placement_zones():
        pools.setdefault(BedRole(z.role), []).append(z)
    for zs in pools.values():
        zs.sort(key=lambda z: (round(z.bbox()[1], 3), round(z.bbox()[0], 3), z.id))

    placements: list[BedPlacement] = []
    unplaced: list[BedPart] = []
    used: dict[BedRole, int] = {}
    for part in parts:
        try:
            role = BedRole(part.kind)
        except ValueError:
            unplaced.append(part)
            continue
        zones = pools.get(role, [])
        i = used.get(role, 0)
        if i >= len(zones):
            unplaced.append(part)
            continue
        used[role] = i + 1
        zone = zones[i]
        if part.place_by_origin:
            # Blank frame → zone: design origin (the blank centre) lands on the zone
            # centre, so a snapped part keeps its registration against the zone end.
            dx, dy = zone.bbox_center()
            placed = transform_ops(part.ops, dx, dy, part.rotation_deg)
        else:
            placed, (dx, dy) = place_ops_at_polygon_zone(part.ops, zone, part.rotation_deg)
        placements.append(BedPlacement(
            kind=part.kind, label=part.label, zone_id=zone.id, role=role.value,
            dx=round(dx, 3), dy=round(dy, 3), rotation_deg=part.rotation_deg,
            ops=placed, contour_names=set(part.contour_names),
            drill_names=set(part.drill_names)))

    return BedNest(placements, unplaced,
                   (worktable.work_area_width_mm, worktable.work_area_height_mm))


# ------------------------------------------------------------------ M7.7 combined post

@dataclass
class NestProgram:
    """One combined GRBL program for a whole nested bed (BUILDPLAN M7.7).

    The worktable analogue of `BedProgram`: the scheduled, machine-coordinate op
    list (op names prefixed per placement) plus the through-cut / drill name sets
    `write_castle_program` needs, the placements it came from, and the tool-change
    count. Unlike `BedProgram` it carries the M7.6 `BedPlacement`s directly (their
    role-typed kind is richer than the M6.5 `ComponentPlacement` literal)."""
    ops: list[CamOp]                       # scheduled, machine coords, names prefixed
    contour_op_names: set
    drill_op_names: set
    placements: list                       # BedPlacement (machine coords)
    n_tool_changes: int


def build_nest_program(nest: BedNest) -> NestProgram:
    """Combine a role-matched `BedNest` (M7.6) into ONE scheduled bed program (M7.7).

    The nest's placements are already in machine coordinates; here we prefix each
    placement's op names with its label (so two parts' "Perimeter" ops don't
    collide), collect the through-cut / drill name sets from the prefixed names,
    and run the precedence-aware tool-change minimiser (`schedule_bed_ops`) over the
    whole bed. The result posts through `write_castle_program` exactly like the M6.5
    fixture bed — only the placement source (a user-tagged `Worktable`, possibly
    nudged) differs. Op copies are renamed, so the nest's own ops (the bed render)
    are left untouched.
    """
    placed_components: list[list[CamOp]] = []
    contour_names: set = set()
    drill_names: set = set()

    for pl in nest.placements:
        comp = transform_ops(pl.ops, 0.0, 0.0, 0.0)   # independent copies to rename
        for op in comp:
            base = op.name
            op.name = f"{pl.label} · {base}"
            if base in pl.contour_names:
                contour_names.add(op.name)
            if base in pl.drill_names:
                drill_names.add(op.name)
        placed_components.append(comp)

    scheduled = schedule_bed_ops(placed_components)
    return NestProgram(scheduled, contour_names, drill_names,
                       list(nest.placements), count_tool_changes(scheduled))
