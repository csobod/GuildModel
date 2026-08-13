"""The castle as a mesh (BUILDPLAN-NEW M-N1).

The mesh-domain counterpart of `core/solid/build.py`, built to the same public
shape — *(partition, castle params, hinges) -> a closed solid* — so the two can
be run side by side and diffed while the port proceeds.

**Deliberately the same construction, not a better one.** Every stage here
mirrors what the B-Rep path does, including the composite rule and the order,
because the point of this milestone is parity: the two kernels must produce the
same part before either can be trusted to replace the other. Improvements that
the mesh domain makes possible (live slider rebuilds, no cached base) come after
parity, not instead of it.

Reuses `core.solid.build.zone_heights`, the ring geometry in
`core.geometry.rings` and the SCULPT-cut geometry in `core.geometry.footings`.
All of it is kernel-neutral — it computes *where* things go from the partition
and the parameters — and duplicating any of it is how a port grows a second set
of subtly different answers.

One place this path does **not** mirror the B-Rep one, and deliberately: the
footing blends are applied per zone rather than as clipped tools, each carried a
hair past the seam, onto zones themselves grown a hair and clipped back. See
`build_base`. All three departures were forced by the same discovery — that a
part can be watertight, one body, and correct on volume to every digit printed
and still not be a surface a slicer will accept — and none of them moves it.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from manifold3d import Manifold

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams
from .kernel import (ManifoldError, drop_degenerate, extrude, intersect_all,
                     subtract_all, swept_profile, to_trimesh, union_all)

ProgressFn = Optional[Callable[[str, float], None]]

#: How far a cutter reaches beyond the material it removes. Same value and same
#: reason as the B-Rep path's `CUT_MARGIN_MM`: a tool must *cross* every surface
#: it exits, never stop on it. M-N0 is what a grazing cutter costs — one
#: tangency left a non-manifold edge that read as valid all the way to the user.
CUT_MARGIN_MM = 1.0

#: Stations sampled along a SCULPT cut when sweeping its footing profile. Same
#: as the B-Rep path's `FOOTING_STATIONS`, so both kernels inscribe the same
#: polyline in the same cut and a volume difference is about the sweep rather
#: than the sampling.
FOOTING_STATIONS = 30

#: Points across one S-blend half-section. Matches the B-Rep `_blend_section`
#: default for the same reason.
FOOTING_SECTION_POINTS = 40

#: How far past its outer end a blend profile ramps clear of the terrace it
#: meets there, mm. See `_blend_profile` — this is M-N0's rule, not a fudge.
FOOTING_LEAD_MM = 0.25

#: How far past the seam a blend profile is carried, into the terrace it does
#: **not** act on, mm. `FOOTING_LEAD_MM`'s counterpart at the inner end, and the
#: same rule: a tool must cross every surface it meets rather than stop on it.
#:
#: The surface being crossed here is the vertical zone wall at the seam, and it
#: was being landed on exactly — each half's profile ended at `u = 0`, which is
#: the boundary between the two zones. That put a face of the tool inside a face
#: of its target, and left the band's `u = 0` edge a 30-station chord of a seam
#: the prism carries at full resolution, so wherever the chord fell inside the
#: zone the subtraction left a standing hairline fin. Between them those two
#: accounted for most of the 157, 247 and 232 self-touching edges on the three
#: fixtures; `ZONE_WELD_MM` accounts for the rest.
#:
#: Nothing is added or removed by the crossing: a carve is only ever subtracted
#: from its own high zone's prism and a raise only ever acts inside its low
#: zone, so each extension is clipped off by the very zone it reaches into. All
#: it costs is that the last chord before the seam is three times the usual
#: length, which moves the base by 3e-7 of itself — thirty times inside the
#: parity gate, and a quarter-micron of chord error against a 0.01 mm budget.
#:
#: Must stay comfortably larger than `ZONE_WELD_MM` — the two grown zones
#: overlap by that much across the seam, and both must find the blend curve
#: there rather than one of them finding the terrace it came from.
FOOTING_CROSS_MM = 0.05

#: How far each zone polygon is grown before it is extruded, mm, undone by
#: clipping the union back to the frame outline. See `build_base`.
#:
#: Zone polygons tile the body exactly — neighbors share a seam with the same
#: endpoints, collinear, at distance 0.0 — so two plain prisms present the same
#: wall twice and the union cancels it. That holds right up until a boolean
#: touches one of them: subtracting a blend band re-nodes the wall it crosses
#: and returns it displaced by up to 7.6e-7 mm. Two walls that are no longer the
#: same wall do not cancel, and an exact kernel is right not to pretend
#: otherwise; what is left is a zero-thickness membrane standing on the seam.
#:
#: 1e-3 mm makes the neighbors genuinely overlap instead: ~1300x the measured
#: displacement, so there is real geometry for the boolean to resolve rather
#: than a coincidence to adjudicate; 10x below the finest step the machine can
#: take; and 1e-8 of the part by volume, which is four orders below the parity
#: gate. The terrace step it sits under moves by that micron and nothing else
#: does.
ZONE_WELD_MM = 1e-3

#: How far the slab that cuts a raised zone back down to its terrace overhangs
#: the part in XY, mm. Only has to be enough that none of the slab's walls comes
#: near the part's — see `build_base`.
SLAB_MARGIN_MM = 5.0


def _report(progress: ProgressFn, label: str, frac: float) -> None:
    if progress is not None:
        progress(label, frac)


def build_terraces(partition: CastlePartition,
                   heights: dict[str, float]) -> Manifold:
    """Every zone extruded to its height and unioned — the stepped castle."""
    parts = [extrude(zone.polygon, heights[zone.name])
             for zone in partition.zones
             if not zone.polygon.is_empty and zone.polygon.area > 0]
    if not parts:
        raise ManifoldError("partition has no zones with area")
    return union_all(parts)


def _weld_grown(poly):
    """A zone polygon grown by `ZONE_WELD_MM`, ready to extrude.

    Mitred rather than rounded, so a corner stays a corner: this is meant to be
    the same polygon a micron bigger, not a smoothed one. The mitre limit caps
    what an acute corner can throw out to twice the growth, which matters
    because a zone can come to a genuine point where three of them meet.

    A buffer can in principle hand back several polygons; it cannot here, since
    growing a single connected region only ever joins things. Guarded anyway
    rather than left to fail one ring at a time inside `cross_section`.
    """
    grown = poly.buffer(ZONE_WELD_MM, join_style=2, mitre_limit=2.0)
    if grown.geom_type == "MultiPolygon":
        grown = max(grown.geoms, key=lambda g: g.area)
    if grown.is_empty or grown.area <= 0:
        raise ManifoldError("growing a zone left nothing to extrude")
    return grown


def _blend_profile(h_high: float, h_low: float, fillet, side: str) -> np.ndarray:
    """One half of the S-blend as `(u, v)` — `u` across the seam, `v` in Z.

    `side="high"` is the material the blend CARVES off the high terrace, over
    `u in [-span_high, 0]`; `side="low"` is the material it RAISES the low one
    by, over `u in [0, span_low]`. Two halves rather than one band because they
    act on different terraces, which is the raster's rule and the B-Rep path's.

    The curve itself is `relief.castle._footing_z`, which the raster and the
    B-Rep path also call. Only the sweep differs between the three.

    **Each half runs `FOOTING_LEAD_MM` past its outer end**, and it is M-N0's
    rule rather than a fudge: a tool must cross every surface it meets, never
    lie flush against it. At `u = -span_high` the blend curve *equals* `h_high`
    and at `u = span_low` it equals `h_low`, so without the lead the carve's
    floor would be coplanar with the high terrace's top face and the raise's
    ceiling with the low one's. The carve ramps up into air above the high
    terrace; the raise ramps down into material already solid below the low one.
    Neither changes the part, and the parity gate pins that.

    **And `FOOTING_CROSS_MM` past its inner end**, for the same reason applied
    to a surface that went unnoticed for a whole milestone: `u = 0` is the
    vertical wall between the two zones, and stopping there put a face of the
    tool inside a face of its target. The sample that used to sit at `u = 0` is
    *moved* across rather than a new one appended — leaving it in place keeps a
    vertex lying exactly in the wall, which is the same defect one dimension
    down and measured 330 zero-area triangles against 0.

    Every other sample keeps the position it had, so the blend's own
    tessellation is unchanged and the extra reach is one chord long.

    `_footing_z` is defined across the whole range — it flattens to `h_high` /
    `h_low` outside the arcs — so both extensions are the real curve continued
    rather than an extrapolation.
    """
    from ..relief.castle import _footing_spans, _footing_z

    span_hi, span_lo = _footing_spans(h_high - h_low, fillet.exterior_mm,
                                      fillet.interior_mm, fillet.first)
    if (span_hi if side == "high" else span_lo) <= 0:
        raise ManifoldError(f"degenerate {side}-side footing span")

    lead = FOOTING_LEAD_MM
    if side == "high":
        u = np.linspace(-span_hi, 0.0, FOOTING_SECTION_POINTS)
        u[-1] = FOOTING_CROSS_MM
    else:
        u = np.linspace(0.0, span_lo, FOOTING_SECTION_POINTS)
        u[0] = -FOOTING_CROSS_MM
    v = _footing_z(u, h_high, h_low, fillet.exterior_mm, fillet.interior_mm,
                   fillet.first)
    uv = np.column_stack([u, v])

    if side == "high":
        return np.vstack([[-span_hi - lead, h_high + lead], uv])
    return np.vstack([uv, [span_lo + lead, h_low - lead]])


def footing_tools(partition: CastlePartition, castle: CastleParams,
                  heights: dict[str, float], top: float,
                  stations: int = FOOTING_STATIONS
                  ) -> tuple[dict[str, list[Manifold]], dict[str, list[Manifold]]]:
    """`(carve_by_zone, raise_by_zone)` for every named seam with a fillet.

    The bands come back **unclipped**, keyed by the zone each one acts on, and
    that is the whole trick — see `build_base`. A seam whose span is degenerate
    or whose neighbors are level contributes nothing and stays a hard step,
    exactly as on the other two paths.

    Swept with `swept_profile` rather than `hull_chain`: **neither half of the
    blend is a convex section**, checked over every fillet in the schedule
    rather than assumed. `kernel.hull_chain` carries the measurement. A hull
    would span the S and deliver a straight ramp — the same silent flattening
    that would have turned every round-over into a chamfer.

    The B-Rep path fits a spline through the stations and pipe-sweeps it; here
    the stations are the polyline. At 30 stations along a gentle SCULPT cut the
    two inscribe the same curve well inside the chord tolerance, and the parity
    gate measures that rather than trusting it.

    **Each band gets its own stations**, because each has its own zone to clear
    and its own reach to clear it over: the carve acts on the high terrace over
    `reach_high`, the raise on the low one over `reach_low`, and the two differ
    by a factor of four on a nosepad seam. One shared lead is the longer of the
    two, which drags each band out over ground that is not its business — and on
    the aviator that was 2.6 mm of raise-side reach spent on a carve band that
    needed 1.0.
    """
    from ..geometry.footings import cap_leads, cut_stations, orient_high_side
    from ..relief.castle import _footing_reach

    carve: dict[str, list[Manifold]] = {}
    raise_: dict[str, list[Manifold]] = {}
    for edge in partition.edges:
        if not edge.canonical:
            continue
        try:
            fillet = castle.footing.for_edge(edge.canonical)
        except AttributeError:
            continue
        names = edge.zone_names
        if len(names) != 2 or not all(n in heights for n in names):
            continue
        hi, lo = ((names[0], names[1]) if heights[names[0]] > heights[names[1]]
                  else (names[1], names[0]))
        if heights[hi] - heights[lo] < 1e-9:
            continue

        reach_hi, reach_lo = _footing_reach(heights[hi] - heights[lo],
                                            fillet.exterior_mm,
                                            fillet.interior_mm, fillet.first)
        for side, zone, far, into, reach in (
                ("high", hi, top, carve, reach_hi),
                ("low", lo, -CUT_MARGIN_MM, raise_, reach_lo)):
            try:
                profile = _blend_profile(heights[hi], heights[lo], fillet, side)
            except ManifoldError:
                continue
            leads = cap_leads(edge.cut,
                              [(partition.zone(zone).polygon, reach)])
            pts, perps = cut_stations(edge.cut, stations, leads)
            perps = orient_high_side(partition, pts, perps, names, heights)
            into.setdefault(zone, []).append(
                swept_profile(pts, perps, [profile] * len(pts), far,
                              closed=False))
    return carve, raise_


def build_base(partition: CastlePartition, castle: CastleParams,
               heights: dict[str, float], top: float) -> Manifold:
    """The terraces with the footing blends already in them.

    Two things here are not the obvious construction, and both were arrived at
    the same way — by a part that was watertight, one body, and correct on
    volume to every printed digit while still not being a surface a slicer would
    accept.

    **Every blend band cuts a zone prism; none of them is a clipped tool.** That
    is the difference between this and the obvious construction, and it is worth
    stating because the obvious one produces a valid, watertight, volumetrically
    exact part that is nonetheless wrong.

    The obvious construction clips each band to the zone it acts on and then
    applies it: `solid - (band & zone)` and `solid + (band & zone)`. But a zone
    prism's walls *are* the terraces' walls, so every clipped band arrives with
    a face lying exactly in a face of the target. Manifold's booleans are exact
    and answer with zero-thickness shells: on the demo base ten of them, seven
    inverted — internal voids in a part that was watertight, one body to look
    at, and correct to 7927.958 mm3. Only `decompose()` saw them.

    So neither band is clipped:

    * A **carve** is subtracted from its high zone's own prism, `A - B` instead
      of `A - (B & A)`. The zone restricts it for free and the band's faces cut
      the target transversally. Exact, and one boolean cheaper.
    * A **raise** is the mirror image, once a raised terrace is read as a cut
      rather than an addition. The zone is extruded to full height and cut back
      down to its terrace by a slab — and the band is subtracted from that slab
      first, so the cut stops short exactly where the blend rises. The slab
      overhangs the part in XY, so none of its walls sit near the part's.

    Zones with no blend are extruded plainly, so a frame with no footings builds
    exactly as `build_terraces` does.

    **And every zone is grown by `ZONE_WELD_MM` before it is extruded, with the
    frame outline clipping the union back.** Neighboring zones share a seam
    exactly — same endpoints, collinear, distance 0.0 — so two plain prisms
    raise the same wall twice and the union cancels it, which is why
    `build_terraces` is clean. But a blend band re-nodes every wall it crosses,
    and the wall comes back displaced by up to 7.6e-7 mm. Two walls that are no
    longer the same wall do not cancel, and the union is left holding a
    zero-thickness membrane standing on the seam from the anterior face up to
    the blend. Grown, the neighbors genuinely overlap and there is no
    coincidence to adjudicate; the outline puts the silhouette and the apertures
    back, and it cuts the grown walls transversally because they now stand a
    micron proud of it.

    Neither change moves the part. The seam crossing is clipped off by the zone
    it reaches into, the growth by the outline; the base agrees with the B-Rep
    to well inside the parity gate, and the three fixtures went from 157, 247
    and 232 self-touching edges to none.

    What remains after that is genuine numerical degeneracy rather than a
    construction error — two zero-volume tetrahedra on the aviator — which
    `drop_degenerate` discards.
    """
    from shapely.geometry import box as shapely_box

    carve, raise_ = footing_tools(partition, castle, heights, top)

    minx, miny, maxx, maxy = partition.body.bounds
    footprint = shapely_box(minx - SLAB_MARGIN_MM, miny - SLAB_MARGIN_MM,
                            maxx + SLAB_MARGIN_MM, maxy + SLAB_MARGIN_MM)

    parts = []
    for zone in partition.zones:
        if zone.polygon.is_empty or zone.polygon.area <= 0:
            continue
        poly = _weld_grown(zone.polygon)
        height = heights[zone.name]
        raises = raise_.get(zone.name)
        if raises:
            above = extrude(footprint, top + SLAB_MARGIN_MM - height,
                            base=height)
            solid = subtract_all(extrude(poly, top),
                                 [subtract_all(above, raises)])
        else:
            solid = extrude(poly, height)
        carves = carve.get(zone.name)
        if carves:
            solid = subtract_all(solid, carves)
        parts.append(solid)

    if not parts:
        raise ManifoldError("partition has no zones with area")

    # Deep enough in Z that only the outline's walls do any cutting: a clip
    # plane coincident with the anterior face would be the very coincidence
    # this is here to avoid.
    outline = extrude(partition.body, top + 2 * CUT_MARGIN_MM,
                      base=-CUT_MARGIN_MM)
    return drop_degenerate(intersect_all([union_all(parts), outline]))


def hinge_pockets(hinges, castle: CastleParams, top: float) -> list[Manifold]:
    """The pocket prisms. Pure extrusions off the hinge polygons — no anchor
    ray, so these never care what has already been cut."""
    polys = [p for p in hinges or []
             if p is not None and not p.is_empty and p.area > 0]
    if not polys:
        return []
    floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    height = max(top - floor, CUT_MARGIN_MM)
    return [extrude(p, height, base=floor) for p in polys]


def build_castle_model(partition: CastlePartition, castle: CastleParams,
                       hinges: list | None = None,
                       heights: dict[str, float] | None = None,
                       progress: ProgressFn = None) -> Manifold:
    """The whole castle: terraces, footing blends, every finishing feature,
    hinge pockets.

    Order mirrors the B-Rep path exactly — terraces, footings, surface features
    one at a time, then everything that can share a pass — because parity is the
    point of this milestone. The mesh domain makes a cheaper arrangement
    possible (no cached base, live slider rebuilds); that comes after parity,
    not instead of it.
    """
    from ..geometry.rings import lip_partition
    from ..geometry.heights import SWEEP_MARGIN_MM, zone_heights
    from .features import (bezel_cutters, groove_cutters,
                           resolved_edge_cutters, scoop_cutter,
                           splay_cutters, surface_feature_cutters)

    # With the groove on, the visible aperture is the rim *lip* — cut
    # `depth_mm` smaller — and the terraces have to reach it, so the zones grow
    # into the annulus the shrink exposes. Same rule and the same function as
    # the B-Rep path; every feature downstream is built against this partition,
    # not the original.
    groove = getattr(castle, "lens_groove", None)
    if groove is not None and groove.enabled and groove.depth_mm > 0:
        partition = lip_partition(partition, groove.depth_mm)

    h = zone_heights(partition, castle, heights)
    top = max(h.values()) + SWEEP_MARGIN_MM

    _report(progress, "Building terraces", 0.20)
    solid = build_base(partition, castle, h, top)

    # Splay then scoop, each subtracted before the next is built. The order is
    # load-bearing: both anchor on the centerline, so with the splay enabled the
    # scoop's rays land on material the splay has already taken away — measured
    # at up to 2.59 mm of anchor movement on the demo frame. Everything after
    # this point sees the same target either way and goes in one pass.
    _report(progress, "Surface features", 0.40)
    for kind, params in surface_feature_cutters(None, partition.body, castle):
        # The splay may be two bodies (non-contiguous, for a keyhole bridge), so
        # both features answer with a list and the gap simply produces one fewer.
        try:
            if kind == "splay":
                tools = splay_cutters(to_trimesh(solid), partition.body, params)
            else:
                tools = [scoop_cutter(to_trimesh(solid), partition.body, params)]
        except ManifoldError:
            continue
        if tools:
            solid = subtract_all(solid, tools)

    _report(progress, "Lens groove", 0.55)
    tools = groove_cutters(partition, castle)

    # The bezel anchors on the surface under it, so it needs the part as it
    # stands — but only the *terraces* under it, which is what the B-Rep path
    # feeds it too: the groove and the pockets do not touch the rim band, so
    # every cutter here still sees the same target and one pass suffices.
    # Tessellated lazily: the anchor rays need a mesh, and with no
    # surface-reading feature enabled that conversion is the whole build. It
    # cost 9 ms -> 828 ms on the demo frame before this was made conditional.
    surface = None
    bezel = getattr(castle, "eyewire_bezel", None)
    wants_rays = ((bezel is not None and bezel.enabled)
                  or castle.resolved_edge_features())
    if wants_rays:
        surface = to_trimesh(solid)

        _report(progress, "Eyewire bezel", 0.70)
        tools.extend(bezel_cutters(surface, partition, castle, top))

        _report(progress, "Edge features", 0.78)
        tools.extend(resolved_edge_cutters(surface, partition, castle, top))

    _report(progress, "Hinge pockets", 0.85)
    tools.extend(hinge_pockets(hinges, castle, top))
    solid = subtract_all(solid, tools)

    # Once more at the end, for the reason `build_base` gives. With the blends
    # in, every later feature has a finely triangulated curved surface to be
    # tangent to, and an exact boolean answers a near-tangency with a
    # zero-thickness shell. Without this the fully featured demo frame comes out
    # in four pieces, three of which total 1.6e-8 mm3.
    solid = drop_degenerate(solid)

    _report(progress, "Model ready", 1.0)
    return solid
