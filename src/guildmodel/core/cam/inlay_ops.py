"""The Inlays operation: every posterior seat pocketed flat, parents first
(BUILDPLAN §8a, 2026-10-15).

A seat is a flat-bottomed pocket with a drawn outline, so this is the hinge
pocket's strategy with three additions:

* **The region may have holes.** A seat drawn inside another in *island* mode
  is left standing, so its parent is pocketed around it; the rings come from
  `pocketing.fill_rings`, which keeps a tool radius off every hole.
* **The floor is a plane, inherited.** A seat inside a HINGE curve steps the
  pocket's floor and keeps its tilt, so the levels run down to the plane's
  low point the way the tilted hinge op's do, every point is held at
  `floor + r·tan(angle)`, and the same finishing pass takes the ridges down.
* **It starts where its reference is.** The op runs after the relief has
  finished the surface a seat is measured from, so each seat's levels begin
  just above its reference plane rather than at the blank top: a seat in the
  endpiece terrace does not lap air from the stock top down.

One op per distinct tool: the part's pocket tool is *Inlays*, a seat on
another tool joins *Inlays 2*, *Inlays 3*. `inlay_op_groups` is that grouping
on its own, which the reach check reads so a seat its tool cannot enter is
named with a tool that fits rather than silently left out.

**Anterior seats are not here.** They are modeled in every kernel, shown in
3D and on the panel with "not posted", and the posted program is byte for
byte the one without them (`test_anterior_inlay_is_not_cut`), as the anterior
bezel has been since M17. M24 posts them on side two.

The thickness check is here too, because it is a check on a program: a seat's
floor against the other face's relief at the same cell must leave the
`min_thickness_mm` the seat asks for. The raster has both maps, so it costs
nothing; the dot and the setup sheet say which seat fails.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyclipper
from shapely import contains_xy, prepare
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from ..geometry.inlays import InlayCut
from ..project.schema import CastleCamParams
from .castle_ops import (CamOp, Point3, _rdp, pocket_levels, resolve_tool,
                         tilted_floor_finish)
from .pocketing import _SCALE

__all__ = ["CLEARANCE_MM", "InlayThicknessWarning", "OP_NAME", "anterior_inlay_notes",
           "inlay_op_groups", "inlay_ops", "inlay_thickness_warnings", "op_name_for"]

OP_NAME = "Inlays"

#: How far above its reference plane a seat's ramp begins, mm. The hinge op
#: starts the same distance above the blank.
CLEARANCE_MM = 0.5


def op_name_for(k: int) -> str:
    """The k-th Inlays op's name: the first is plain, the rest numbered."""
    return OP_NAME if k == 0 else f"{OP_NAME} {k + 1}"


def _signed_area(ring) -> float:
    xs = np.asarray([p[0] for p in ring], dtype=np.float64)
    ys = np.asarray([p[1] for p in ring], dtype=np.float64)
    return 0.5 * float(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1)))


def _seat_rings(region: Polygon, tool_radius_mm: float,
                stepover_mm: float) -> tuple[list, list]:
    """``(outer, rings)``: the ring the ramp laps, and every ring the level
    clears, outer first. Closed, in mm. Each offset is taken from the seat's
    own boundary, holes included, so an island keeps its tool radius of wall
    at every ring; a region the tool cannot enter yields nothing."""
    region = orient(region, sign=1.0)
    paths = [[[int(x * _SCALE), int(y * _SCALE)] for x, y in ring.coords[:-1]]
             for ring in (region.exterior, *region.interiors)]
    paths = [p for p in paths if len(p) >= 3]
    if not paths:
        return [], []
    if stepover_mm <= 0.0:
        stepover_mm = max(tool_radius_mm, 0.1)
    offset = int(tool_radius_mm * _SCALE)
    step = max(1, int(stepover_mm * _SCALE))
    rings: list = []
    outer = None
    while True:
        pco = pyclipper.PyclipperOffset()
        pco.AddPaths(paths, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        shrunk = pco.Execute(-offset)
        if not shrunk:
            break
        level = [[(p[0] / _SCALE, p[1] / _SCALE) for p in list(c) + [c[0]]]
                 for c in shrunk if len(c) >= 3]
        if outer is None and level:
            outer = max(level, key=_signed_area)
        rings.extend(level)
        offset += step
    if outer is None:
        return [], []
    return outer, [outer] + [r for r in rings if r is not outer]


def _seat_path(seat: InlayCut, tool_radius_mm: float, params: CastleCamParams,
               stepdown_mm: float) -> list[list[Point3]]:
    """The pocketing paths for one posterior seat, or none when the tool does
    not fit. Mirrors `castle_ops.hinge_pocket_op`, level by level."""
    outer, rings = _seat_rings(seat.region, tool_radius_mm, params.pocket_stepover_mm)
    if not rings:
        return []
    plane = seat.plane
    _, ref_high = seat.reference.extremes(seat.outline)
    start_z = float(ref_high) + CLEARANCE_MM
    ramp_step = params.ramp_step_mm if params.ramp_step_mm > 1e-9 else float("inf")
    tilted = not plane.flat
    if tilted:
        lift = tool_radius_mm * abs(plane.slope)
        inset = seat.region.buffer(-tool_radius_mm)
        low, _ = plane.extremes(inset if not inset.is_empty else seat.outline)
        levels = pocket_levels(start_z, low + lift, stepdown_mm)
    else:
        lift = 0.0
        levels = pocket_levels(start_z, plane.z_fixed, stepdown_mm)

    n = len(outer)
    z = start_z
    path: list[Point3] = [(*outer[0], z)]
    for k, level in enumerate(levels):
        while z > level + 1e-9:
            z_next = max(level, z - ramp_step)
            for i in range(1, n):
                t = i / (n - 1)
                path.append((*outer[i], z + (z_next - z) * t))
            z = z_next
        path += [(*p, level) for p in outer]
        for ring in rings[1:]:
            path += [(*p, level) for p in ring]
        if k + 1 < len(levels):
            path.append((*outer[0], level))
    if tilted:
        pts = np.asarray(path, dtype=np.float64)
        pts[:, 2] = np.maximum(pts[:, 2], plane.z(pts[:, 0], pts[:, 1]) + lift)
        path = [tuple(p) for p in pts.tolist()]
    out = [_rdp(path, params.simplify_tol_mm)]
    if tilted:
        out += [_rdp(p, params.simplify_tol_mm) for p in
                tilted_floor_finish(seat.region, plane, tool_radius_mm,
                                    params.pocket_finish_stepover_mm)]
    return out


def inlay_op_groups(seats: list[InlayCut], tools_cfg: dict | None,
                    default_tool: dict) -> list[tuple[str, dict, list[InlayCut]]]:
    """The posterior seats grouped by the tool that cuts them, as
    ``(op name, tool, seats)``: the part's pocket tool first, under the plain
    name, then one numbered op per further tool in order of appearance."""
    groups: dict[str, tuple[dict, list[InlayCut]]] = {}
    default_name = default_tool.get("name", "")
    for seat in seats:
        if not seat.posterior:
            continue
        name = seat.feature.tool or default_name
        tool = (resolve_tool(name, tools_cfg or {}, default=default_tool)
                if seat.feature.tool else default_tool)
        key = tool.get("name", name)
        groups.setdefault(key, (tool, []))[1].append(seat)
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] != default_name,))
    return [(op_name_for(k), tool, members)
            for k, (_key, (tool, members)) in enumerate(ordered)]


def inlay_ops(seats: list[InlayCut], params: CastleCamParams,
              tools_cfg: dict | None, default_tool: dict) -> list[CamOp]:
    """The Inlays op(s) for `seats`, parents first within each; an op whose
    every seat is too small for its tool is dropped and says so."""
    ops: list[CamOp] = []
    for name, tool, members in inlay_op_groups(seats, tools_cfg, default_tool):
        op = CamOp(name, tool=tool)
        for seat in members:
            if seat.depth_mm <= 0.0:
                continue                  # an island left at the surface: nothing to cut
            stepdown = (float(seat.feature.stepdown_mm)
                        if seat.feature.stepdown_mm else params.pocket_stepdown_mm)
            paths = _seat_path(seat, float(tool["radius_mm"]), params, stepdown)
            if not paths:
                x0, y0, x1, y1 = seat.outline.bounds
                op.notes.append(
                    f"{name}: seat '{seat.feature.label or seat.feature.id}' "
                    f"({x1 - x0:.1f} x {y1 - y0:.1f} mm) cannot admit the "
                    f"{2.0 * float(tool['radius_mm']):.3f} mm tool and was skipped; "
                    "give it a smaller tool")
                continue
            op.paths += paths
        if op.paths:
            ops.append(op)
    return ops


def anterior_inlay_notes(seats: list[InlayCut]) -> list[str]:
    """One line per anterior seat: modeled, shown, not posted — for the log."""
    return [f"{OP_NAME}: seat '{seat.feature.label or seat.feature.id}' is on the "
            "anterior face and is modeled and previewed, not posted; the flip "
            "setup (M24) cuts it on side two"
            for seat in seats if not seat.posterior]


# ------------------------------------------------------------------ the check

@dataclass
class InlayThicknessWarning:
    """A seat whose floor leaves less than its minimum against the other face.

    Measured on the relief the program posts from, cell by cell, with both
    maps in hand: a posterior seat against the anterior surface (flat, or
    carved by a brow chamfer or an anterior seat), an anterior seat against
    the posterior relief and its pockets. Two seats back to back is exactly
    the case this exists for, and it is what makes two-sided seats safe.
    """
    seat: str
    face: str
    thinnest_mm: float
    min_thickness_mm: float
    op_name: str = OP_NAME

    def message(self) -> str:
        return (f"{self.op_name}: seat '{self.seat}' ({self.face}) leaves "
                f"{self.thinnest_mm:.2f} mm of material against the other face, "
                f"under the {self.min_thickness_mm:.2f} mm it asks for — make it "
                "shallower, move it, or lower its minimum")


def inlay_thickness_warnings(relief, seats: list[InlayCut]
                             ) -> list[InlayThicknessWarning]:
    """Which seats fail their own minimum thickness on `relief` (a
    `CastleRelief` or a temple's `FlatRelief`: anything with `field`, `inside`
    and `anterior_z`)."""
    field = relief.field
    thickness = field.z - relief.anterior_z
    rows, cols = field.z.shape
    ox, oy = field.origin
    res = field.resolution
    out: list[InlayThicknessWarning] = []
    for seat in seats:
        need = float(seat.feature.min_thickness_mm)
        if need <= 0.0:
            continue
        bx0, by0, bx1, by1 = seat.outline.bounds
        c0 = max(0, int((bx0 - ox) / res) - 1)
        c1 = min(cols, int((bx1 - ox) / res) + 2)
        r0 = max(0, int((by0 - oy) / res) - 1)
        r1 = min(rows, int((by1 - oy) / res) + 2)
        if c0 >= c1 or r0 >= r1:
            continue
        xs = ox + np.arange(c0, c1) * res
        ys = oy + np.arange(r0, r1) * res
        Xs, Ys = np.meshgrid(xs, ys)
        prepare(seat.outline)
        m = (contains_xy(seat.outline, Xs.ravel(), Ys.ravel()).reshape(r1 - r0, c1 - c0)
             & relief.inside[r0:r1, c0:c1])
        if not m.any():
            continue
        thinnest = float(np.min(thickness[r0:r1, c0:c1][m]))
        if thinnest < need - 1e-6:
            out.append(InlayThicknessWarning(
                seat.feature.label or seat.feature.id, seat.face, thinnest, need))
    return out
