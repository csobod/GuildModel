"""Castle features as boolean bodies (BUILDPLAN Stage 2).

Each of these replaces a `min`-carve painted into a raster with the operation a
maker would actually reach for in Fusion — which is the point, and also a good
sign the mapping is natural rather than forced (report §4.3).

| Feature | Raster | Here |
| --- | --- | --- |
| Hinge pockets | `min` inside a polygon | extrude the polygon, subtract |
| Eyewire bezel | `min` over a distance band | sweep a chamfer along the ring, subtract |

The bezel is the one with a subtlety worth stating, and it is a real change in
what the feature *means*.

The raster carves `pre(cell) - (width - d) * tan(angle)`: the surface pushed
down by an amount that falls off with distance from the rim. That is a variable
offset of whatever is underneath, not a chamfer — it has no flat face and no
edge, and it is only a chamfer at all where the surface beneath it happens to be
flat.

Here it is a real chamfer: a ruled plane rising inward at `angle` from
`rim_z - width * tan(angle)`, anchored per station by an exact vertical ray
fired just inside the rim. On a flat terrace the two are identical, and on the
demo frame they agree to 5 um over 83% of in-body cells. They diverge where the
surface is *not* flat across the band — chiefly the nosepad and bridge, where
footing blends sweep through it — because a plane cannot follow a swell and a
variable offset must. That divergence is the feature behaving like the Fusion
chamfer it is named after, and it is what gives it an edge to be crisp at.
"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
from shapely.geometry import LineString, Point, Polygon

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams, EyewireBezelParams
from .occ import (
    BooleanError,
    cut,
    extrude,
    fuse_all,
    polygon_to_face,
    surface_z_at,
)

from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Pnt

__all__ = ["apply_edge_features", "apply_hinge_pockets",
           "apply_posterior_features", "bezel_cutter", "edge_feature_cutters"]

#: Sections lofted around an aperture ring for a bezel. The demo's lens rings
#: are ~132 mm round, so this is one section per ~0.73 mm — past the point where
#: the cutter's volume stops moving (60 -> 120 -> 240 gives 3179.5 / 3188.0 /
#: 3189.9 mm^3).
BEZEL_STATIONS = 180

#: How far a cutter reaches past the material it trims, mm.
CUT_MARGIN_MM = 1.0

#: How far past `width` the chamfer plane runs, as a multiple of the band width.
#: The cut is self-limiting — beyond the point where the plane leaves the
#: material the boolean removes nothing — so this only has to be generous.
_BEZEL_REACH = 1.0

#: How far inside the rim the anchoring ray is fired, mm.
_RIM_PROBE_MM = 0.05


# ------------------------------------------------------------- hinge pockets

def apply_hinge_pockets(solid: TopoDS_Shape, hinges: Iterable[Polygon],
                        castle: CastleParams, top: float) -> TopoDS_Shape:
    """Sharp-walled pockets cut below the endpiece height.

    Matches the raster exactly: the floor is `endpiece_mm - hinge_pocket_depth_mm`
    and the walls are vertical. No tool-radius offset here — that belongs to
    `cam.castle_ops.hinge_pocket_op`, which does the pocketing cascade.
    """
    polys = [p for p in hinges if p is not None and not p.is_empty and p.area > 0]
    if not polys:
        return solid
    floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    height = max(top - floor, CUT_MARGIN_MM)
    cutters = [extrude(polygon_to_face(p, floor), height) for p in polys]
    return cut(solid, fuse_all(cutters))


# ------------------------------------------------------------- eyewire bezel

def _ring_stations(ring: LineString, n: int):
    """Points and unit tangents evenly spaced around a closed ring."""
    total = ring.length
    ss = np.linspace(0.0, total, n, endpoint=False)
    pts, tans = [], []
    eps = max(total / (8 * n), 1e-4)
    for s in ss:
        p = ring.interpolate(float(s))
        a = ring.interpolate(float((s - eps) % total))
        b = ring.interpolate(float((s + eps) % total))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= max(np.linalg.norm(t), 1e-12)
        pts.append([p.x, p.y])
        tans.append(t)
    return np.array(pts), np.array(tans)


def _inward(body: Polygon, pts: np.ndarray, tans: np.ndarray,
            probe: float = 0.05) -> np.ndarray:
    """Unit normals pointing into the material, voted rather than assumed.

    An aperture ring's winding is whatever Shapely handed over; guessing it
    wrong would cut the chamfer into thin air inside the lens hole.
    """
    n = np.column_stack([-tans[:, 1], tans[:, 0]])
    votes = 0
    for p, nn in zip(pts, n):
        if body.contains(Point(*(p + nn * probe))):
            votes += 1
        elif body.contains(Point(*(p - nn * probe))):
            votes -= 1
    return n if votes >= 0 else -n


def _bezel_section(p_xy, inward, rim_z: float, width: float, tan_a: float,
                   clamp: float, top: float):
    """Material above the chamfer plane, as a closed section in (inward, Z).

    **Anchored at the rim, not at the band's inner edge.** The band's promise is
    a constant *rim depth* — `width * tan(angle)` below the surface at the rim,
    all the way round — so that is what has to be measured from. Anchoring at
    the inner edge instead lets the rim depth drift by the surface's slope times
    the band width wherever the band crosses a footing swell, which on the demo
    frame was worth up to 0.7 mm.

    The section is a straight chamfer plane rising inward at `tan_a` from
    `rim_z - width * tan_a`, floored at `clamp`. It runs past `width` on
    purpose: where the real surface is already below the plane the boolean
    removes nothing, so the cut terminates itself exactly where the chamfer runs
    out of material — which is how the equivalent Fusion chamfer behaves, and
    why the band does not need to know where the surface goes.
    """
    # The plane passes through (u = 0, rim_z - drop) with slope tan_a. Both
    # endpoints have to be evaluated on that line: putting `rim_z - drop` at
    # u = -CUT_MARGIN instead of at the rim silently flattens the slope to
    # drop / (reach + margin) — 0.412 rather than tan(30 deg) = 0.577 at the
    # defaults, which under-cut the whole band by up to 0.36 mm.
    drop = width * tan_a
    reach = width * _BEZEL_REACH
    u0, u1 = -CUT_MARGIN_MM, reach
    v0 = max(rim_z - drop + u0 * tan_a, clamp)
    v1 = max(rim_z - drop + u1 * tan_a, clamp)

    px, py = float(p_xy[0]), float(p_xy[1])
    nx, ny = float(inward[0]), float(inward[1])

    def at(u, v):
        return gp_Pnt(px + nx * float(u), py + ny * float(u), float(v))

    mp = BRepBuilderAPI_MakePolygon()
    mp.Add(at(u0, v0))
    mp.Add(at(u1, v1))
    mp.Add(at(u1, top))
    mp.Add(at(u0, top))
    mp.Close()
    return mp.Wire()


def bezel_cutter(solid: TopoDS_Shape, body: Polygon, ring,
                 p: EyewireBezelParams, top: float,
                 stations: int = BEZEL_STATIONS) -> TopoDS_Shape:
    """The swept chamfer band for one aperture ring."""
    width = float(p.width_mm)
    if width <= 0:
        raise BooleanError("bezel width is zero")
    tan_a = math.tan(math.radians(float(p.angle_deg)))

    line = LineString(ring)
    pts, tans = _ring_stations(line, stations)
    inward = _inward(body, pts, tans)

    # Anchor on the surface AT THE RIM — sampled just inside it, since a ray
    # exactly on the aperture boundary hits the vertical wall ambiguously.
    anchors = surface_z_at(solid, pts + inward * _RIM_PROBE_MM)

    sections = [
        _bezel_section(p_xy, nn, float(a), width, tan_a,
                       float(p.anterior_clamp_mm), top)
        for p_xy, nn, a in zip(pts, inward, anchors)
    ]

    # Lofted, not pipe-swept. `BRepOffsetAPI_MakePipeShell` builds this shape
    # only up to ~60 profiles on a closed spine and then throws
    # "BRepAdaptor_Curve::No geometry" — measured: 40 and 60 fine, 80/100/120/160
    # all fail. `ThruSections` takes 60, 120 and 240 without complaint and the
    # volume converges (3179.5 / 3188.0 / 3189.9 mm^3), so the station count can
    # be chosen for fidelity instead of to appease the kernel. Adding the first
    # section again closes the loop around the ring.
    ts = BRepOffsetAPI_ThruSections(True, True, 1e-6)     # solid, ruled
    for wire in sections:
        ts.AddWire(wire)
    ts.AddWire(sections[0])
    ts.Build()
    if not ts.IsDone():
        raise BooleanError("bezel loft did not complete")
    return ts.Shape()


def apply_posterior_features(solid: TopoDS_Shape, partition: CastlePartition,
                             castle: CastleParams, top: float) -> TopoDS_Shape:
    """Every enabled posterior finishing feature, as boolean subtractions."""
    bezel = castle.eyewire_bezel
    if bezel.cuts_posterior():
        cutters = []
        for interior in partition.body.interiors:
            try:
                cutters.append(bezel_cutter(solid, partition.body, interior,
                                            bezel, top))
            except BooleanError:
                continue
        if cutters:
            solid = cut(solid, fuse_all(cutters))
    return solid


# ------------------------------------------------- edge features (M17 / brow)

#: Sections lofted per millimetre of run along an edge feature's span.
EDGE_SECTIONS_PER_MM = 1.2

#: Smallest depth a tapered section may carry, mm. The taper law goes to zero at
#: each end of a run, and a section that collapses to a true point fails
#: `MakeSolid()` / `ThruSections` outright — Stage 1's §5.1 finding. Two
#: hundredths of a millimetre is a fiftieth of the finishing tool's radius and
#: invisible in acetate, so the run still reads as feathering out to nothing.
MIN_TAPER_DROP_MM = 0.02


def _edge_section(p_xy, inward, anchor: float, width: float, drop: float,
                  profile: str, radius: float, top: float, posterior: bool,
                  n: int = 20):
    """One station's cutting section for an edge feature, in (inward, Z).

    Posterior runs remove material above the profile; anterior runs are the
    mirror image and remove it below. In a solid that is the whole of the
    difference — there is no second surface to keep in step, because the
    anterior face *is* the underside of the same body.
    """
    us = np.linspace(0.0, width, n)
    if profile == "fillet":
        r = max(radius, 1e-6)
        inner = np.clip(r - us, 0.0, r)
        prof = np.where(us < r, r - np.sqrt(np.maximum(r * r - inner * inner, 0.0)), 0.0)
        prof = prof * (drop / max(prof[0], 1e-9)) if prof[0] > 0 else prof
    else:
        prof = np.maximum(0.0, width - us) * (drop / max(width, 1e-9))

    sign = -1.0 if posterior else 1.0
    vs = anchor + sign * prof
    far = top if posterior else -CUT_MARGIN_MM

    px, py = float(p_xy[0]), float(p_xy[1])
    nx, ny = float(inward[0]), float(inward[1])

    def at(u, v):
        return gp_Pnt(px + nx * float(u), py + ny * float(u), float(v))

    mp = BRepBuilderAPI_MakePolygon()
    mp.Add(at(-CUT_MARGIN_MM, vs[0]))
    for u, v in zip(us, vs):
        mp.Add(at(u, v))
    mp.Add(at(width, far))
    mp.Add(at(-CUT_MARGIN_MM, far))
    mp.Close()
    return mp.Wire()


def edge_feature_cutters(solid: TopoDS_Shape, partition: CastlePartition,
                         feature, top: float) -> list[TopoDS_Shape]:
    """Swept cutters for one resolved `EdgeFeature`, one per span it covers.

    The span comes from the same `span_intervals` the raster uses, so a feature
    named by castle zone covers exactly the same run of ring either way — the
    M17 decision that a span is named, not measured, survives the rewrite
    untouched.
    """
    from ..geometry.regions import CastlePartition as _CP    # noqa: F401
    from ..relief.edges import ring_for, span_intervals, station_fraction, taper_weight

    ring = ring_for(partition, feature.edge)
    if ring is None or ring.length <= 0:
        return []
    intervals = span_intervals(ring, partition, feature.zones,
                               feature.trim_start_mm, feature.trim_end_mm)
    if not intervals:
        return []

    posterior = feature.face == "posterior"
    tan_a = math.tan(math.radians(float(feature.angle_deg)))
    total = ring.length
    out: list[TopoDS_Shape] = []

    for s0, s1 in intervals:
        run = s1 - s0
        n = max(6, int(run * EDGE_SECTIONS_PER_MM))
        ss = np.linspace(s0, s1, n)

        pts, tans = [], []
        for s in ss:
            p = ring.interpolate(float(s % total))
            a = ring.interpolate(float((s - 0.05) % total))
            b = ring.interpolate(float((s + 0.05) % total))
            t = np.array([b.x - a.x, b.y - a.y])
            t /= max(np.linalg.norm(t), 1e-12)
            pts.append([p.x, p.y])
            tans.append(t)
        pts, tans = np.array(pts), np.array(tans)
        inward = _inward(partition.body, pts, tans)

        w = taper_weight(ss, intervals, feature.blend_mm, total)
        frac = station_fraction(ss, intervals, total)
        widths = np.array([float(feature.width_at(float(v))) for v in frac])
        if feature.profile == "fillet":
            widths = np.full_like(widths, float(feature.radius_mm))
            base = np.full_like(widths, float(feature.radius_mm))
        else:
            base = widths * tan_a
        drops = np.maximum(base * w, MIN_TAPER_DROP_MM)
        if feature.depth_limit_mm is not None:
            drops = np.minimum(drops, float(feature.depth_limit_mm))

        anchors = surface_z_at(solid, pts + inward * _RIM_PROBE_MM,
                               face="top" if posterior else "bottom")

        sections = [
            _edge_section(p, nn, float(a), float(wd), float(dr),
                          feature.profile, float(feature.radius_mm), top,
                          posterior)
            for p, nn, a, wd, dr in zip(pts, inward, anchors, widths, drops)
        ]
        ts = BRepOffsetAPI_ThruSections(True, True, 1e-6)
        for wire in sections:
            ts.AddWire(wire)
        ts.Build()
        if ts.IsDone():
            out.append(ts.Shape())
    return out


def apply_edge_features(solid: TopoDS_Shape, partition: CastlePartition,
                        castle: CastleParams, top: float) -> TopoDS_Shape:
    """Every resolved edge feature, mirrored twins included."""
    cutters: list[TopoDS_Shape] = []
    for feature in castle.resolved_edge_features():
        try:
            cutters.extend(edge_feature_cutters(solid, partition, feature, top))
        except BooleanError:
            continue
    if cutters:
        solid = cut(solid, fuse_all(cutters))
    return solid
