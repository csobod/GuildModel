"""Parts on the worktable without their programs (BUILDPLAN M20).

Until M20, placing a part on the bed meant generating its program first: the
nest was the ops, nudged and rotated in machine coordinates, and it lived in
memory only. This module separates the two. A part's **footprint** is its blank
and the outline it cuts, in the design frame its program is generated in — the
workspace knows both before any program exists — and a **placement** is the
affine ``p ↦ R(θ)·p + (dx, dy)`` that puts that frame on the bed
(`project.schema.WorktablePlacement`, saved with the project). Auto-placing
fills zones by role instantly; the live clearance check grows the footprint by
the largest tool and tests it against the keep-outs; the exact per-op check
runs at Generate, when the ops exist, and the saved placements are turned into
`BedPlacement`s with ops by `nest_from_placements`.

The design frame is the frame every generator works in: the blank centered on
the design origin, the front's drawing as placed on its blank
(`component_workspace.place_front_on_blank`), a temple snapped to its blank
end (`relief.flat.place_temple_on_blank`), a block's lens centered
(`block_ops.center_on_origin`). So the design origin is the blank's center
for every kind, and a part is placed by sending that origin to the zone's
center: the blank sits in its pocket on the fixture, and the cut lands on the
blank wherever the drawing put it. A snapped temple keeps the orientation its
snap gave it; an unsnapped left temple starts turned 180° to face the right
one (`layout.default_nest_rotation`), as before.

Staleness is a key, not an event. A part's program depends on its parameters,
its CAM context and its geometry (`part_program_key`); a placement's on the
zone, the offset and the bed's own settings (`placement_key`). Generate records
the pair on each placement; a pair that no longer matches is stale. Pure
shapely and hashing; no Qt.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from shapely.affinity import rotate as _rotate, translate as _translate
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from .layout import BedNest, BedPart, BedPlacement, default_nest_rotation, transform_ops

#: Snap a dragged footprint to its zone's center within this distance (§5.2.5).
SNAP_MM = 3.0


# ------------------------------------------------------------------ footprints

@dataclass
class Footprint:
    """A part's blank and the outline it cuts, in its design frame.

    ``cut`` is what is drawn; ``swept()`` is what the tool passes over, which
    the live clearance check grows by the tool radius. A front's relief sweeps
    its whole body, so the body less its lens openings (the fixture's screws
    stand in those openings); a temple's pockets and engraving sweep its body;
    a block is only profiled — its mounting holes are drilled at the screws on
    purpose and are exempt — so only its outline ring is swept.
    """
    component_id: str
    kind: str
    label: str
    blank: Polygon                       # the stock blank, centered on the origin
    cut: Polygon | MultiPolygon          # what the program cuts around
    tool_radius_mm: float = 0.0          # the largest tool the part's cut uses
    rotation_default_deg: float = 0.0    # the orientation a fresh placement starts with
    extras: list = field(default_factory=list)   # further blank pieces (the pad block)
    ring_only: bool = False              # the program sweeps the cut's edge, not its area

    def bounds(self) -> tuple[float, float, float, float]:
        return unary_union([self.blank, self.cut, *self.extras]).bounds

    def swept(self):
        return self.cut.boundary if self.ring_only else self.cut


def _blank(length_mm: float, width_mm: float) -> Polygon:
    return box(-length_mm / 2.0, -width_mm / 2.0, length_mm / 2.0, width_mm / 2.0)


def _radius(tools_cfg: dict, names) -> float:
    r = 0.0
    for n in names:
        t = tools_cfg.get(n) if isinstance(tools_cfg, dict) else None
        if t and t.get("radius_mm"):
            r = max(r, float(t["radius_mm"]))
    return r


def footprint_front(component_id: str, label: str, outline: Polygon, castle,
                    cam, tools_cfg: dict, lenses=()) -> Footprint:
    """The frame front: its blank (and pad block) and the outline as placed,
    less its lens openings, which nothing sweeps."""
    st = castle.stock
    extras = []
    if st.use_pad_block and st.pad_block_length_mm > 0 and st.pad_block_width_mm > 0:
        pad = _blank(st.pad_block_length_mm, st.pad_block_width_mm)
        extras.append(_translate(pad, st.pad_block_dx_mm, st.pad_block_dy_mm))
    names = cam.tools_in_use() if cam is not None else []
    body = outline
    holes = [p for p in lenses if p is not None and not p.is_empty]
    if holes:
        cut = outline.difference(unary_union(holes))
        if not cut.is_empty:
            body = cut
    return Footprint(component_id, "frame_front", label,
                     _blank(st.blank_length_mm, st.blank_width_mm), body,
                     _radius(tools_cfg, names), 0.0, extras)


def footprint_temple(component_id: str, kind: str, label: str, outline: Polygon,
                     hinge_polys: list, temple, tools_cfg: dict) -> Footprint:
    """A temple: its blank and the outline snapped onto it, as the program is."""
    from ..relief.flat import place_temple_on_blank
    placed, _h, _e = place_temple_on_blank(
        outline, list(hinge_polys), [], temple.blank_length_mm,
        stock_side=temple.stock_side, snap=temple.snap_to_blank_end,
        origin_from_drawing=temple.origin_from_drawing)
    default = 0.0 if temple.snap_to_blank_end else default_nest_rotation(kind)
    return Footprint(component_id, kind, label,
                     _blank(temple.blank_length_mm, temple.blank_width_mm), placed,
                     _radius(tools_cfg, (temple.engrave_tool, temple.hinge_tool,
                                         temple.profile_tool)),
                     default)


def footprint_block(component_id: str, kind: str, label: str, lens: Polygon,
                    block, tools_cfg: dict) -> Footprint:
    """A base-curve block: its blank and the lens centered on it. The mounting
    holes are drilled at the fixture's screws on purpose and are not part of
    the cut the clearance check grows."""
    from .block_ops import center_on_origin
    return Footprint(component_id, kind, label,
                     _blank(block.blank_length_mm, block.blank_width_mm),
                     center_on_origin(lens), _radius(tools_cfg, (block.profile_tool,)),
                     default_nest_rotation(kind), ring_only=True)


# ------------------------------------------------------------------ placing

def placed(shape, placement):
    """`shape` under the placement: rotated about the design origin, then moved."""
    out = shape
    if placement.rotation_deg:
        out = _rotate(out, placement.rotation_deg, origin=(0.0, 0.0))
    return _translate(out, placement.dx, placement.dy)


def placement_center(fp: Footprint, placement) -> tuple[float, float]:
    """The placed blank's center: the point a drag snaps to a zone by."""
    c = placed(fp.blank, placement).centroid
    return (float(c.x), float(c.y))


def _zone_pools(worktable) -> dict:
    from ..project.schema import BedRole
    pools: dict = {}
    for z in worktable.placement_zones():
        pools.setdefault(BedRole(z.role), []).append(z)
    for zs in pools.values():
        zs.sort(key=lambda z: (round(z.bbox()[1], 3), round(z.bbox()[0], 3), z.id))
    return pools


def auto_place(footprints: list, worktable, nest) -> list:
    """Place every footprint that has no placement in `nest` on a free zone of
    its role, bottom-left zone first; a part with no free matching zone is
    left as it is. The part starts at its default orientation with its design
    origin on the zone's center, then registers against the zone's stops
    where the fixture has them. Returns the placements made, each already put
    into `nest`."""
    from ..project.schema import BedRole, WorktablePlacement
    pools = _zone_pools(worktable)
    zone_ids = {z.id for z in worktable.zones}
    taken = {pl.zone_id for pl in nest.placements if pl.zone_id in zone_ids}
    made: list = []
    for fp in footprints:
        have = nest.get(fp.component_id)
        if have is not None and have.zone_id in zone_ids:
            continue
        try:
            role = BedRole(fp.kind)
        except ValueError:
            continue
        zone = next((z for z in pools.get(role, []) if z.id not in taken), None)
        if zone is None:
            continue
        cx, cy = zone.bbox_center()
        pl = WorktablePlacement(component_id=fp.component_id, zone_id=zone.id,
                                dx=round(cx, 3), dy=round(cy, 3),
                                rotation_deg=fp.rotation_default_deg)
        register_to_zone(fp, pl, zone)      # against the zone's stop, if it has one
        nest.put(pl)
        taken.add(zone.id)
        made.append(pl)
    return made


def send_to_zone(fp: Footprint, placement, zone) -> None:
    """Move a placement onto `zone`: its design origin to the zone's center,
    then against the zone's stop if it has one, its orientation kept."""
    cx, cy = zone.bbox_center()
    placement.zone_id = zone.id
    placement.dx, placement.dy = round(cx, 3), round(cy, 3)
    register_to_zone(fp, placement, zone)


def _axis_targets(b0: float, b1: float, z0: float, z1: float, stop: str,
                  low: str, high: str) -> dict:
    """Where the blank's span ``[b0, b1]`` can register on the zone's
    ``[z0, z1]`` on one axis: the delta to each named place. A stop names the
    one place the fixture allows; otherwise the two ends and the center."""
    at = {"center": (z0 + z1) / 2.0 - (b0 + b1) / 2.0, low: z0 - b0, high: z1 - b1}
    if stop in (low, high):
        return {stop: at[stop]}
    return at


def zone_targets(fp: Footprint, placement, zone) -> tuple[dict, dict]:
    """The registration targets per axis, ``({name: ddx}, {name: ddy})``, for
    the placed — rotated — blank, so a part flipped 180° registers the same way
    round."""
    bx0, by0, bx1, by1 = placed(fp.blank, placement).bounds
    zx0, zy0, zx1, zy1 = zone.bbox()
    return (_axis_targets(bx0, bx1, zx0, zx1, getattr(zone, "stop_x", "none"), "left", "right"),
            _axis_targets(by0, by1, zy0, zy1, getattr(zone, "stop_y", "none"), "bottom", "top"))


def _pick(targets: dict, nearest: bool) -> tuple[str, float]:
    """The stop when the zone has one; else the center, or with ``nearest`` the
    nearer of the two ends. The center is not a Snap target: a 160 mm blank in
    a 170 mm zone has 5 mm of play a side, and "push it to that end" would
    land in the middle more often than not."""
    if len(targets) == 1 or not nearest:
        name = next(iter(targets)) if len(targets) == 1 else "center"
        return name, targets[name]
    ends = {k: v for k, v in targets.items() if k != "center"}
    return min(ends.items(), key=lambda kv: abs(kv[1]))


def zone_register_delta(fp: Footprint, placement, zone, *,
                        nearest: bool = False) -> tuple[float, float]:
    """The move that registers the placed blank on `zone` (M20 session two):
    flush against the zone's stop on an axis with a stop; otherwise its
    center, or with ``nearest`` whichever of the two ends the blank is nearer —
    the Snap action's reading of "push it to that end"."""
    tx, ty = zone_targets(fp, placement, zone)
    return (_pick(tx, nearest)[1], _pick(ty, nearest)[1])


def register_to_zone(fp: Footprint, placement, zone, *, nearest: bool = False) -> bool:
    """Put the placed blank where the zone says, whatever the distance: the
    stop, else the center (Auto-place, Send to zone), else with ``nearest`` the
    end or center it is nearest to (Snap). True when it moved."""
    ddx, ddy = zone_register_delta(fp, placement, zone, nearest=nearest)
    if abs(ddx) < 1e-9 and abs(ddy) < 1e-9:
        return False
    nudge(placement, ddx, ddy)
    return True


def nudge(placement, ddx: float, ddy: float) -> None:
    placement.dx = round(placement.dx + ddx, 3)
    placement.dy = round(placement.dy + ddy, 3)


def rotate_about_center(fp: Footprint, placement, ddeg: float) -> None:
    """Spin a placement by `ddeg` about its placed blank's center, so the part
    stays in its pocket: the same composition `BedPlacement.rotate` uses."""
    cx, cy = placement_center(fp, placement)
    th = math.radians(ddeg)
    c, s = math.cos(th), math.sin(th)
    ddx, ddy = placement.dx - cx, placement.dy - cy
    placement.dx = round(c * ddx - s * ddy + cx, 3)
    placement.dy = round(s * ddx + c * ddy + cy, 3)
    placement.rotation_deg = round((placement.rotation_deg + ddeg) % 360.0, 3)


def snap_to_zone(fp: Footprint, placement, zone, snap_mm: float = SNAP_MM) -> bool:
    """Settle a dragged placement, axis by axis: a blank pushed past the zone's
    edge comes back flush to it (the pocket has a wall), and one that ends
    within `snap_mm` of a registration place — an end, the center, the stop —
    snaps to it. Elsewhere it stays where it was dropped. Returns True when it
    moved."""
    tx, ty = zone_targets(fp, placement, zone)
    bx0, by0, bx1, by1 = placed(fp.blank, placement).bounds
    zx0, zy0, zx1, zy1 = zone.bbox()

    def settle(targets: dict, b0: float, b1: float, z0: float, z1: float) -> float:
        # The pocket's walls hold whatever the stop says: a blank that fits
        # cannot be left past either edge.
        if (b1 - b0) <= (z1 - z0) + 1e-6:
            if b0 < z0 - 1e-6:
                return z0 - b0
            if b1 > z1 + 1e-6:
                return z1 - b1
        d = min(targets.values(), key=abs)
        return d if abs(d) <= snap_mm else 0.0

    ddx = settle(tx, bx0, bx1, zx0, zx1)
    ddy = settle(ty, by0, by1, zy0, zy1)
    if abs(ddx) < 1e-9 and abs(ddy) < 1e-9:
        return False
    nudge(placement, ddx, ddy)
    return True


# ------------------------------------------------------------------ clearance

def keep_out_shapes(worktable) -> list:
    """The bed's keep-outs as shapely shapes (a screw its exact circle)."""
    out: list = []
    for z in worktable.keep_outs():
        if z.radius_mm is not None and z.radius_mm > 0:
            cx, cy = z.center()
            out.append(Point(cx, cy).buffer(float(z.radius_mm), quad_segs=24))
        elif len(z.polygon) >= 3:
            p = Polygon(z.polygon)
            if p.is_valid and not p.is_empty:
                out.append(p)
    return out


def footprint_violations(fp: Footprint, placement, worktable,
                         keep_outs: list | None = None) -> list[str]:
    """The live check (M20 §5.2.2): the placed cut, grown by the part's largest
    tool, against the keep-outs. One message per keep-out it reaches."""
    keep = keep_out_shapes(worktable) if keep_outs is None else keep_outs
    if not keep:
        return []
    guard = placed(fp.swept(), placement)
    if fp.tool_radius_mm > 0:
        guard = guard.buffer(fp.tool_radius_mm)
    out: list[str] = []
    for k in keep:
        if guard.intersects(k):
            c = k.centroid
            out.append(f"{fp.label}: reaches a keep-out near machine "
                       f"({c.x:.1f}, {c.y:.1f})")
    return out


def off_bed_violations(fp: Footprint, placement, worktable) -> list[str]:
    """The placed blank must lie within the work area."""
    w, h = worktable.work_area_width_mm, worktable.work_area_height_mm
    x0, y0, x1, y1 = placed(fp.blank, placement).bounds
    if x0 < -1e-6 or y0 < -1e-6 or x1 > w + 1e-6 or y1 > h + 1e-6:
        return [f"{fp.label}: its blank runs off the bed"]
    return []


# ------------------------------------------------------------------ keys

def _digest(obj) -> str:
    text = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def geometry_fingerprint(layers: dict, *extra) -> str:
    """A digest of a workspace's authored geometry (its layer polylines, to a
    tenth of a micron) and whatever else shapes its program."""
    rounded = {str(k): [[(round(float(x), 4), round(float(y), 4)) for x, y in c]
                        for c in v] for k, v in (layers or {}).items()}
    return _digest([rounded, *extra])


def part_program_key(kind: str, params, cam, *, cam_overrides=None,
                     material: str = "", machine: str = "", geometry: str = "",
                     tools: dict | None = None) -> str:
    """What a part's design-frame ops depend on: its kind and parameters, the
    project CAM and the part's overrides, the material and machine, its
    geometry, and the tool library."""
    # No overrides and an override model with nothing set are the same program:
    # a workspace carries None until a save gives it the empty model back.
    overrides = (cam_overrides.model_dump(exclude_none=True)
                 if cam_overrides is not None else {})
    return _digest({
        "kind": kind,
        "params": params.model_dump() if params is not None else None,
        "cam": cam.model_dump() if cam is not None else None,
        "overrides": overrides,
        "material": material, "machine": machine, "geometry": geometry,
        "tools": tools or {},
    })


def placement_key(placement, zone, worktable) -> str:
    """What the placed ops and the bed program's header depend on: the offset
    and turn, the zone and its stock, and the bed's zero, hold-downs and size."""
    return _digest({
        "zone": (zone.id, zone.role.value if hasattr(zone.role, "value") else str(zone.role),
                 [(round(x, 3), round(y, 3)) for x, y in zone.polygon],
                 zone.stock_thickness_mm) if zone is not None else None,
        "dx": round(placement.dx, 3), "dy": round(placement.dy, 3),
        "rot": round(placement.rotation_deg, 3),
        "hold_down": round(worktable.hold_down_height_mm, 3),
        "zero": worktable.program_zero.model_dump(),
        "area": (worktable.work_area_width_mm, worktable.work_area_height_mm),
    })


def program_key(part_key: str, place_key: str) -> str:
    return f"{part_key}:{place_key}"


def bed_program_key(placement_keys: list[str]) -> str:
    """The whole bed program's key: every placement's, in a fixed order."""
    return _digest(sorted(placement_keys))


# ------------------------------------------------------------------ the nest, from placements

def nest_from_placements(parts: list[BedPart], nest, worktable) -> BedNest:
    """`BedPlacement`s with machine-coordinate ops from saved placements (M20).

    Each part's ops are its design-frame ops under its placement; a part with
    no placement, or whose zone is gone, is returned unplaced. The result is
    what `build_nest_program` posts and the bed simulation reads, exactly as
    `nest_components_on_worktable` produced before placements were saved.
    """
    zone_ids = {z.id for z in worktable.zones}
    placements: list[BedPlacement] = []
    unplaced: list[BedPart] = []
    for part in parts:
        pl = nest.get(part.component_id) if part.component_id else None
        if pl is None or pl.zone_id not in zone_ids:
            unplaced.append(part)
            continue
        placements.append(BedPlacement(
            kind=part.kind, label=part.label, zone_id=pl.zone_id, role=part.kind,
            dx=pl.dx, dy=pl.dy, rotation_deg=pl.rotation_deg,
            ops=transform_ops(part.ops, pl.dx, pl.dy, pl.rotation_deg),
            contour_names=set(part.contour_names), drill_names=set(part.drill_names)))
    return BedNest(placements, unplaced,
                   (worktable.work_area_width_mm, worktable.work_area_height_mm))


#: The 1.7-era `ComponentPlacement.kind` literals as the kinds they stand for,
#: in the order the parts of a kind take them.
_LEGACY_KINDS = {
    "frame_front": ("frame_front",),
    "temple": ("temple_right", "temple_left"),
    "base_curve_block": ("base_curve_right", "base_curve_left"),
}


def legacy_layout_to_nest(bed_layout, components) -> "WorktableNest":
    """A 1.7-era `BedLayout` as a `WorktableNest` (M20): its placements, by
    the kind each stands for, for the kinds the project has. A placement's
    component id is the kind, as the window keys its placements."""
    from ..project.schema import WorktableNest, WorktablePlacement
    nest = WorktableNest()
    if bed_layout is None:
        return nest
    have = {c.kind.value for c in components or []}
    for cp in bed_layout.placements:
        kind = next((k for k in _LEGACY_KINDS.get(cp.kind, ())
                     if k in have and nest.get(k) is None), None)
        if kind is None:
            continue
        nest.put(WorktablePlacement(component_id=kind, zone_id=cp.fixture_zone,
                                    dx=cp.x_mm, dy=cp.y_mm, rotation_deg=cp.rotation_deg))
    return nest
