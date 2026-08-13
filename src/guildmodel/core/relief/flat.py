"""Flat-part relief + mesh for temples and base-curve blocks (per-component 3D).

Temples and base-curve blocks have no castle relief — they are flat acetate/acetal
blanks with shallow features. This builds the **same** heightfield structure the
castle mesher consumes (a z-field + an inside mask + the true boundary rings), so
`build_castle_mesh` turns them into watertight solids unchanged: the outline
extruded to the blank thickness, a flat anterior at z = 0, blind pockets/grooves
carved into the top, and drilled holes as real through-holes (excluded from the
mask, exactly like the frame's lens openings).

  * **Temple** — extrude the OUTLINE; carve the HINGE polys as blind pockets
    (floor = thickness − hinge_pocket_depth); carve the ENGRAVING curves (buffered
    to the engrave tool) as shallow grooves. Optionally snapped so the hinge/butt
    end registers to one end of the 170 mm blank (the injected metal core runs the
    temple's length); the core itself is a 3D **visual reference**, not machined.
  * **Base-curve block** — a blank-size box extruded to the blank thickness; the
    lens-interior footprint scribed on the top as the forming reference; the M4
    mounting holes as through-holes; centerd on the origin.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Optional

import numpy as np
from shapely import contains_xy, prepare
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from ..geometry.regions import CastlePartition
from ..project.schema import BaseCurveBlockParams, TempleParams
from .castle import GRID_MARGIN_MM, PREVIEW_RES_MM, ProgressFn, _report
from .heightfield import Heightfield


@dataclass
class FlatRelief:
    """A flat-part relief, duck-compatible with what `build_castle_mesh` reads:
    `field`, `inside`, `partition.body`, `pocket_polys`."""
    field: Heightfield
    inside: np.ndarray
    partition: CastlePartition
    pocket_polys: list = dc_field(default_factory=list)


# ------------------------------------------------------------------ core builder

def _build_flat_relief(
    body: Polygon,
    thickness: float,
    resolution: float,
    *,
    pockets: list[tuple[Polygon, float]] = (),
    grooves: list[tuple[Polygon, float]] = (),
    margin: float = GRID_MARGIN_MM,
    progress: Optional[ProgressFn] = None,
) -> FlatRelief:
    """Rasterize a flat part: thickness inside `body`, with `pockets` / `grooves`
    carved down (min). `body`'s interior rings become through-holes (excluded from
    the mask). `pockets` (blind, walled) are returned for rim conforming; `grooves`
    (shallow scribes) are just z-depressions.
    """
    _report(progress, "Rasterizing part", 0.10)
    minx, miny, maxx, maxy = body.bounds
    ox, oy = minx - margin, miny - margin
    rows = max(2, int(round((maxy - miny + 2 * margin) / resolution)))
    cols = max(2, int(round((maxx - minx + 2 * margin) / resolution)))
    xs = ox + np.arange(cols) * resolution
    ys = oy + np.arange(rows) * resolution
    Xs, Ys = np.meshgrid(xs, ys)
    fx, fy = Xs.ravel(), Ys.ravel()

    prepare(body)
    inside = contains_xy(body, fx, fy).reshape(rows, cols)
    z = np.where(inside, float(thickness), 0.0).astype(np.float64)

    _report(progress, "Carving features", 0.45)
    pocket_polys: list[Polygon] = []
    for poly, floor_z in pockets:
        if poly is None or poly.is_empty:
            continue
        prepare(poly)
        m = contains_xy(poly, fx, fy).reshape(rows, cols) & inside
        z[m] = np.minimum(z[m], float(floor_z))
        pocket_polys.append(poly)
    for poly, floor_z in grooves:
        if poly is None or poly.is_empty:
            continue
        prepare(poly)
        m = contains_xy(poly, fx, fy).reshape(rows, cols) & inside
        z[m] = np.minimum(z[m], float(floor_z))

    z[~inside] = 0.0
    _report(progress, "Relief ready", 0.55)
    field = Heightfield(z=z, origin=(ox, oy), resolution=resolution)
    return FlatRelief(field=field, inside=inside,
                      partition=CastlePartition(body=body), pocket_polys=pocket_polys)


# ------------------------------------------------------------------ temple

def temple_snap_offset(
    outline: Polygon, hinge_polys: list[Polygon], blank_length: float,
) -> tuple[float, float]:
    """Translation (dx, dy) that centers the temple across the blank width and
    butts its HINGE/butt end against one short end of the 170 mm blank.

    The temple's long axis is x (as GuildDraw draws/exports it). The hinge end is
    the x-extreme nearer the HINGE centroid (falling back to the +x extreme); the
    blank is centerd on the origin, so the hinge extreme lands on ±blank_length/2.
    """
    minx, miny, maxx, maxy = outline.bounds
    dy = -(miny + maxy) / 2.0
    hx = unary_union(hinge_polys).centroid.x if hinge_polys else maxx
    half = blank_length / 2.0
    if abs(hx - maxx) <= abs(hx - minx):          # hinge on the +x end
        dx = half - maxx
    else:                                          # hinge on the -x end
        dx = -half - minx
    return dx, dy


def _hinge_on_plus_x(outline: Polygon, hinge_polys: list[Polygon]) -> bool:
    """True when the temple's HINGE end is at its +x extreme (its long axis is x)."""
    minx, _, maxx, _ = outline.bounds
    hx = unary_union(hinge_polys).centroid.x if hinge_polys else maxx
    return abs(hx - maxx) <= abs(hx - minx)


def temple_snap_transform(
    outline: Polygon, hinge_polys: list[Polygon], blank_length: float,
    *, stock_side: str = "right", snap: bool = True,
) -> tuple[bool, float, float]:
    """The rigid design→blank-frame transform the snap applies (BUILDPLAN M11):
    ``(flipped, dx, dy)`` such that a design point q maps to the blank frame as
    ``p = (−q if flipped else q) + (dx, dy)``. The GUI inverts this to draw the
    blank box / datum marker / toolpath overlay back in the design frame, so the
    2D view shows exactly where the cut lands on the blank. ``snap=False`` is the
    identity."""
    if not snap:
        return False, 0.0, 0.0
    flipped = _hinge_on_plus_x(outline, hinge_polys) != (stock_side != "left")
    if flipped:
        from shapely.affinity import scale
        outline = scale(outline, xfact=-1.0, yfact=-1.0, origin=(0, 0))
        hinge_polys = [scale(h, xfact=-1.0, yfact=-1.0, origin=(0, 0))
                       for h in hinge_polys]
    dx, dy = temple_snap_offset(outline, hinge_polys, blank_length)
    return flipped, dx, dy


def place_temple_on_blank(
    outline: Polygon, hinge_polys: list[Polygon], engraving: list,
    blank_length: float, *, stock_side: str = "right", snap: bool = True,
) -> tuple[Polygon, list[Polygon], list]:
    """Position a temple on its blank (BUILDPLAN M11). When ``snap``, butt the HINGE
    end against the chosen short end (``stock_side`` "right"=+x / "left"=-x), keeping
    the hinge pocket up. If the hinge naturally points at the wrong end, the temple is
    rotated 180° in-plane (x,y)->(-x,-y) — the same posterior flip the import applies —
    so the body runs inward from the chosen end rather than off the blank. Returns the
    placed (outline, hinge_polys, engraving)."""
    from shapely.affinity import scale, translate as _translate
    hinge_polys = list(hinge_polys)
    engraving = [list(c) for c in engraving]
    if not snap:
        return outline, hinge_polys, engraving
    flipped, dx, dy = temple_snap_transform(
        outline, hinge_polys, blank_length, stock_side=stock_side, snap=True)
    if flipped:
        outline = scale(outline, xfact=-1.0, yfact=-1.0, origin=(0, 0))
        hinge_polys = [scale(h, xfact=-1.0, yfact=-1.0, origin=(0, 0)) for h in hinge_polys]
        engraving = [[(-x, -y) for x, y in c] for c in engraving]
    outline = _translate(outline, dx, dy)
    hinge_polys = [_translate(h, dx, dy) for h in hinge_polys]
    engraving = [[(x + dx, y + dy) for x, y in c] for c in engraving]
    return outline, hinge_polys, engraving


def temple_core_guide(
    outline: Polygon, hinge_polys: list[Polygon], temple: TempleParams,
) -> Polygon:
    """The injected-core visual reference (BUILDPLAN M7): a `core_guide_width` ×
    `core_guide_length` bar laid along the temple's long axis from the hinge end,
    centerd across the width. A 3D reference only — never machined."""
    minx, miny, maxx, maxy = outline.bounds
    cy = (miny + maxy) / 2.0
    w = temple.core_guide_width_mm
    length = min(temple.core_guide_length_mm, maxx - minx)
    hx = unary_union(hinge_polys).centroid.x if hinge_polys else maxx
    if abs(hx - maxx) <= abs(hx - minx):          # core runs in from the +x (hinge) end
        x0, x1 = maxx - length, maxx
    else:
        x0, x1 = minx, minx + length
    return box(x0, cy - w / 2.0, x1, cy + w / 2.0)


def build_temple_relief(
    outline: Polygon,
    temple: TempleParams,
    hinge_polys: list[Polygon] = (),
    engraving_curves: list = (),
    *,
    resolution: float = PREVIEW_RES_MM,
    engrave_tool_radius: float = 0.25,
    progress: Optional[ProgressFn] = None,
) -> FlatRelief:
    """A temple solid: extrude the outline to the blank thickness, carve the HINGE
    pockets (1 mm default) and the ENGRAVING grooves (0.3 mm default). The geometry
    is taken as-drawn; the GUI applies the blank-end snap before calling this."""
    thickness = temple.blank_thickness_mm
    pocket_floor = thickness - temple.hinge_pocket_depth_mm
    pockets = [(p, pocket_floor) for p in hinge_polys
               if p is not None and p.is_valid and p.area > 0.0]

    groove_floor = thickness - temple.engrave_depth_mm
    grooves: list[tuple[Polygon, float]] = []
    r = max(engrave_tool_radius, 0.15)
    if engraving_curves and temple.engrave_centerline:   # match the program (M11 #7)
        from ..cam.engrave_centerline import engraving_centerlines
        engraving_curves = engraving_centerlines(engraving_curves)
    for curve in engraving_curves:
        if len(curve) >= 2:
            g = LineString([(float(x), float(y)) for x, y in curve]).buffer(r)
            if not g.is_empty:
                grooves.append((g, groove_floor))

    return _build_flat_relief(outline, thickness, resolution,
                              pockets=pockets, grooves=grooves, progress=progress)


# ------------------------------------------------------------------ base-curve block

def build_block_relief(
    lens_outline: Polygon,
    block: BaseCurveBlockParams,
    *,
    resolution: float = PREVIEW_RES_MM,
    progress: Optional[ProgressFn] = None,
) -> FlatRelief:
    """A base-curve block solid: the **lens shape** extruded to the blank thickness,
    centerd on the origin, with the M4 mounting holes as real through-holes. The
    block *is* the lens shape (it holds the eyewire on the base-curve press) — there
    is no scribe and no surrounding box, matching the cutting program."""
    from ..cam.block_ops import center_on_origin

    centered = center_on_origin(lens_outline)
    r_hole = block.hole_diameter_mm / 2.0
    holes = [Point(hx, hy).buffer(r_hole) for hx, hy in block.hole_centers()]
    body = centered.difference(unary_union(holes)) if holes else centered

    return _build_flat_relief(body, block.blank_thickness_mm, resolution,
                              progress=progress)
