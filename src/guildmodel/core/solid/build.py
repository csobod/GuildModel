"""The castle as a B-Rep solid (BUILDPLAN Stage 2).

The master representation. Where `core/relief/castle.py` paints heights into a
raster, this builds the same shape out of real surfaces meeting along real
curves — so a cut has an exact edge, the solid is closed by construction, and
the viewer can be handed a genuine edge set instead of a triangle soup.

**Terraces.** Each castle zone's polygon extruded to its own height and fused.

**Footings — swept cross-sections, not edge fillets.** The Stage 1 spike found
that `BRepFilletAPI_MakeFillet` cannot build these at all: 0 of 16 edges at the
Demo Project's scheduled radii. The reason is not kernel fragility. Those radii
are 4-48 mm while the steps they blend are 0.2-5.8 mm, so they were never 3D
edge fillets in Fusion either — they are radii of a *cross-section* S-blend,
which is precisely what `relief.castle._footing_z` already computes. Sweeping
that existing profile along the SCULPT cut line succeeds 10/10 in ~0.1 s, and it
reproduces the blend the Demo Project STL was verified against rather than
hoping a kernel fillet lands in the same place.

**Composite rule**, carried over verbatim from the raster so the two paths agree
where they should: low-side fills apply first, then high-side carves win — a
later fillet cuts. Here that is `(terraces ∪ fills) − carves`.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from shapely.geometry import Point

from ..geometry.regions import CastlePartition, ZoneEdge
from ..project.schema import CastleParams, FootingFillet
from ..relief.castle import _footing_spans, _footing_z
from .occ import (
    BooleanError,
    common,
    cut,
    extrude,
    fuse,
    fuse_all,
    is_valid,
    polygon_to_face,
    spline_wire,
)

from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_TransitionMode,
)
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Dir, gp_Pnt

ProgressFn = Callable[[str, float], None]

#: Stations sampled along a SCULPT cut when sweeping its footing profile. The
#: cut lines are gentle splines, so this is about capturing curvature, not
#: detail; 30 was ample on the demo frame and costs ~10 ms per edge.
FOOTING_STATIONS = 30

#: How far the swept cutter reaches above the tallest terrace and, for fills,
#: below the anterior face. Only needs to guarantee overlap for the boolean.
SWEEP_MARGIN_MM = 1.0


def _report(progress: Optional[ProgressFn], label: str, frac: float) -> None:
    if progress is not None:
        progress(label, frac)


def zone_heights(partition: CastlePartition, castle: CastleParams,
                 heights: dict[str, float] | None = None) -> dict[str, float]:
    """Zone name -> posterior height, same resolution order as the raster path."""
    if heights is not None:
        return dict(heights)
    if not partition.classified:
        raise ValueError(
            "the section cuts did not yield recognisable castle zones; "
            "pass explicit zone heights"
        )
    out = {z.name: castle.zones.for_kind(z.kind) for z in partition.zones}
    out.update({n: mm for n, mm in castle.zone_height_overrides.items()
                if n in out})
    return out


# ------------------------------------------------------------------ terraces

def build_terraces(partition: CastlePartition,
                   heights: dict[str, float]) -> TopoDS_Shape:
    """Every zone extruded to its height and fused — the stepped castle."""
    solids = []
    for zone in partition.zones:
        poly = zone.polygon
        if poly.is_empty or poly.area <= 0:
            continue
        solids.append(extrude(polygon_to_face(poly, 0.0), heights[zone.name]))
    if not solids:
        raise BooleanError("partition has no zones with area")
    return fuse_all(solids)


def body_prism(partition: CastlePartition, height: float) -> TopoDS_Shape:
    """The whole footprint extruded — used to clip fills back inside the part."""
    return extrude(polygon_to_face(partition.body, 0.0), height)


# ------------------------------------------------------------------ footings

def _stations(cut_line, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Points and unit left-normals along a SCULPT cut, ends trimmed slightly.

    The cut lines are deliberately extended past the body (`_CUT_EXTEND_MM`) so
    they always sever it; sampling the very ends would fit the spine through
    points beyond anything that matters.
    """
    total = cut_line.length
    ss = np.linspace(0.02 * total, 0.98 * total, n)
    pts, perps = [], []
    for s in ss:
        p = cut_line.interpolate(float(s))
        a = cut_line.interpolate(float(max(0.0, s - 0.05)))
        b = cut_line.interpolate(float(min(total, s + 0.05)))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= max(np.linalg.norm(t), 1e-12)
        pts.append([p.x, p.y])
        perps.append([-t[1], t[0]])
    return np.array(pts), np.array(perps)


def _orient_high_side(partition: CastlePartition, pts: np.ndarray,
                      perps: np.ndarray, names: tuple[str, ...],
                      heights: dict[str, float]) -> np.ndarray:
    """Flip the normals so that -u is the HIGH terrace, matching `_footing_z`.

    Decided by asking which zone actually owns the ground on that side, rather
    than by trusting the cut's direction — a SCULPT line's orientation is an
    artifact of how it was drawn.
    """
    mid, pn = pts[len(pts) // 2], perps[len(perps) // 2]
    probe = Point(*(mid - pn * 0.3))
    owner = next((z.name for z in partition.zones if z.polygon.contains(probe)),
                 None)
    if owner is None:
        return perps
    high = names[0] if heights[names[0]] > heights[names[1]] else names[1]
    return -perps if owner != high else perps


def _blend_section(p_xy, perp, h_high: float, h_low: float,
                   fillet: FootingFillet, above: bool, top: float,
                   n: int = 40):
    """Closed section either side of the S-blend, in the (perp, Z) plane.

    above=True  -> the material to CARVE: everything over the blend curve.
    above=False -> the material to FILL: everything under it, down to z = 0.
    """
    span_hi, span_lo = _footing_spans(
        h_high - h_low, fillet.exterior_mm, fillet.interior_mm, fillet.first)
    if span_hi <= 0 and span_lo <= 0:
        raise BooleanError("degenerate footing span")

    s = np.linspace(-span_hi, span_lo, n)
    z = _footing_z(s, h_high, h_low,
                   fillet.exterior_mm, fillet.interior_mm, fillet.first)

    px, py = float(p_xy[0]), float(p_xy[1])
    nx, ny = float(perp[0]), float(perp[1])

    def at(u, v):
        return gp_Pnt(px + nx * float(u), py + ny * float(u), float(v))

    mp = BRepBuilderAPI_MakePolygon()
    for si, zi in zip(s, z):
        mp.Add(at(si, zi))
    if above:
        mp.Add(at(s[-1], top))
        mp.Add(at(s[0], top))
    else:
        mp.Add(at(s[-1], -SWEEP_MARGIN_MM))
        mp.Add(at(s[0], -SWEEP_MARGIN_MM))
    mp.Close()
    return mp.Wire()


def _sweep(pts: np.ndarray, sections) -> TopoDS_Shape:
    ps = BRepOffsetAPI_MakePipeShell(spline_wire(pts, 0.0))
    # Fixed binormal, not Frenet: the blend profile must stay upright rather
    # than roll with the spine's curvature.
    ps.SetMode(gp_Dir(0.0, 0.0, 1.0))
    ps.SetTransitionMode(
        BRepBuilderAPI_TransitionMode.BRepBuilderAPI_RightCorner)
    for wire in sections:
        ps.Add(wire, False, False)
    ps.Build()
    if not ps.IsDone():
        raise BooleanError("footing sweep did not complete")
    if not ps.MakeSolid():
        raise BooleanError("footing sweep did not close into a solid")
    return ps.Shape()


def footing_bodies(partition: CastlePartition, zone_edge: ZoneEdge,
                   heights: dict[str, float], fillet: FootingFillet,
                   top: float, stations: int = FOOTING_STATIONS
                   ) -> tuple[TopoDS_Shape, TopoDS_Shape]:
    """(carve, fill) swept along one SCULPT cut."""
    names = zone_edge.zone_names
    if len(names) != 2 or not all(n in heights for n in names):
        raise BooleanError(f"edge {zone_edge.name!r} has no two known neighbours")
    h_high, h_low = max(heights[names[0]], heights[names[1]]), \
        min(heights[names[0]], heights[names[1]])
    if h_high - h_low < 1e-9:
        raise BooleanError("no step across this edge")

    pts, perps = _stations(zone_edge.cut, stations)
    perps = _orient_high_side(partition, pts, perps, names, heights)

    carve = _sweep(pts, [_blend_section(p, pn, h_high, h_low, fillet,
                                        above=True, top=top)
                         for p, pn in zip(pts, perps)])
    fill = _sweep(pts, [_blend_section(p, pn, h_high, h_low, fillet,
                                       above=False, top=top)
                        for p, pn in zip(pts, perps)])
    return carve, fill


# --------------------------------------------------------------------- build

def build_castle_solid(partition: CastlePartition, castle: CastleParams,
                       heights: dict[str, float] | None = None,
                       progress: Optional[ProgressFn] = None) -> TopoDS_Shape:
    """Terraces plus footing blends, as a valid solid.

    Features (bezel, splay, brow chamfer, groove, hinge pockets) are not applied
    here yet — they arrive as further boolean sweeps on top of this.
    """
    h = zone_heights(partition, castle, heights)
    top = max(h.values()) + SWEEP_MARGIN_MM

    _report(progress, "Building terraces", 0.10)
    solid = build_terraces(partition, h)

    carves, fills = [], []
    named = [e for e in partition.edges if e.canonical]
    for i, edge in enumerate(named):
        try:
            fillet = castle.footing.for_edge(edge.canonical)
        except AttributeError:
            continue
        try:
            carve, fill = footing_bodies(partition, edge, h, fillet, top)
        except BooleanError:
            # A degenerate or step-less seam contributes no blend. The raster
            # path treats these the same way — `_footing_centers` returns None
            # and the edge stays a hard step.
            continue
        carves.append(carve)
        fills.append(fill)
        _report(progress, "Blending footings",
                0.10 + 0.70 * (i + 1) / max(len(named), 1))

    # Composite rule, from the raster: fills first, then carves win.
    if fills:
        clip = body_prism(partition, top)
        solid = fuse(solid, common(fuse_all(fills), clip))
    if carves:
        solid = cut(solid, fuse_all(carves))

    _report(progress, "Solid ready", 1.0)
    if not is_valid(solid):
        raise BooleanError("castle solid failed BRepCheck_Analyzer")
    return solid
