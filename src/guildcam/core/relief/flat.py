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
    mounting holes as through-holes; centred on the origin.
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
    """Translation (dx, dy) that centres the temple across the blank width and
    butts its HINGE/butt end against one short end of the 170 mm blank.

    The temple's long axis is x (as GuildDraw draws/exports it). The hinge end is
    the x-extreme nearer the HINGE centroid (falling back to the +x extreme); the
    blank is centred on the origin, so the hinge extreme lands on ±blank_length/2.
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


def temple_core_guide(
    outline: Polygon, hinge_polys: list[Polygon], temple: TempleParams,
) -> Polygon:
    """The injected-core visual reference (BUILDPLAN M7): a `core_guide_width` ×
    `core_guide_length` bar laid along the temple's long axis from the hinge end,
    centred across the width. A 3D reference only — never machined."""
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
    centred on the origin, with the M4 mounting holes as real through-holes. The
    block *is* the lens shape (it holds the eyewire on the base-curve press) — there
    is no scribe and no surrounding box, matching the cutting program."""
    from ..cam.block_ops import center_on_origin

    centered = center_on_origin(lens_outline)
    r_hole = block.hole_diameter_mm / 2.0
    holes = [Point(hx, hy).buffer(r_hole) for hx, hy in block.hole_centers()]
    body = centered.difference(unary_union(holes)) if holes else centered

    return _build_flat_relief(body, block.blank_thickness_mm, resolution,
                              progress=progress)
