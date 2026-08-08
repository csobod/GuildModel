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
from shapely.prepared import prep

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams, EyewireBezelParams
from .occ import (
    BooleanError,
    cut,
    cut_many,
    extrude,
    fuse_all,
    nurbs_edge,
    polygon_to_face,
    surface_z_at,
)

from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakePolygon,
                                BRepBuilderAPI_TransitionMode)
from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
from OCP.TopoDS import TopoDS_Shape
from OCP.gp import gp_Pnt

__all__ = ["anterior_bezel_features", "apply_edge_features",
           "apply_hinge_pockets", "apply_lens_groove",
           "apply_posterior_features", "apply_surface_features",
           "bezel_cutter", "bezel_cutters", "edge_feature_cutters",
           "groove_cutters", "hinge_pocket_cutters", "independent_cutters",
           "resolved_edge_cutters", "scoop_cutter", "splay_cutter"]

#: Sections lofted around an aperture ring for a bezel. The demo's lens rings
#: are ~132 mm round, so this is one section per ~0.73 mm.
#:
#: **What pins this number is chord error, not volume.** Volume converges early
#: and is therefore misleading: 120 stations removes 473.1 mm3 against 474.7 at
#: 240, an 0.3% difference that reads as plenty of headroom. It is not. The
#: sections are joined by ruled patches, so the cutter is a polygon inscribed in
#: the ring, and the sagitta is what the cut surface is actually wrong by:
#:
#:     240 -> 1.8 um    180 -> 3.2 um    150 -> 4.6 um
#:     120 -> 7.2 um     90 -> 12.8 um    60 -> 28.8 um
#:
#: `test_bezel_is_a_real_chamfer_not_an_offset` requires the solid to agree with
#: the raster to **5 um** over >80% of in-body cells. Dropping to 120 to buy
#: build time was tried and it fails that gate at 79.3%, exactly as the 7.2 um
#: sagitta predicts. 180 clears it with margin, and the build time was not here
#: anyway — see `cut_many`.
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
    return cut_many(solid, hinge_pocket_cutters(hinges, castle, top))


def hinge_pocket_cutters(hinges: Iterable[Polygon], castle: CastleParams,
                         top: float) -> list[TopoDS_Shape]:
    """The pocket prisms. Pure extrusions off the hinge polygons — no anchor
    ray, so like the groove these never care what has already been cut."""
    polys = [p for p in hinges if p is not None and not p.is_empty and p.area > 0]
    if not polys:
        return []
    floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    height = max(top - floor, CUT_MARGIN_MM)
    return [extrude(polygon_to_face(p, floor), height) for p in polys]


# ------------------------------------------------------------- eyewire bezel

# Ring geometry now lives in `core/geometry/rings.py` so the mesh kernel can use
# it without importing OCP. Re-exported under the old private names: these are
# the same functions, and duplicating them is how two kernels start disagreeing.
from ..geometry.rings import (                                   # noqa: E402
    crest_inside as _crest_inside,
    GROOVE_STATIONS,
    _LIP_AREA_TOL,
    _LIP_CHORD_TOL_MM,
    inward_normals as _inward,
    lip_body,
    lip_partition,
    offset_aperture as _offset_aperture,
    ring_stations as _ring_stations,
)

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

    # Lofted, not pipe-swept — and unlike the lens groove, which *is* swept
    # (`_swept_groove_cutter`), this one cannot be. Two measurements, and the
    # second is the one that decides it.
    #
    # `BRepOffsetAPI_MakePipeShell` was recorded here as failing above ~60
    # profiles on a closed spine ("BRepAdaptor_Curve::No geometry"). That is a
    # symptom of a *polyline* spine, not a limit of the operation: given the
    # ring's authored curve as a single-edge spine it takes all 180 profiles and
    # returns a valid solid of FOUR faces against this loft's 720, 0.16% larger
    # (exact against inscribed — the right direction).
    #
    # It is still not usable, because those four faces are the problem rather
    # than the prize. Interpolating 180 profiles into one surface per profile
    # edge produces a surface the boolean engine cannot work with: cutting the
    # demo castle with it takes **260 s and returns an invalid solid with
    # negative volume**, against 13 s and a valid one for the loft. The groove
    # sweeps cleanly because its profile is constant, so its three faces are
    # simple; a bezel section changes at every station, because each is anchored
    # by its own ray onto the surface below.
    #
    # `ThruSections` takes 60, 120 and 240 without complaint and the volume
    # converges (3179.5 / 3188.0 / 3189.9 mm^3), so the station count can be
    # chosen for fidelity. Adding the first section again closes the loop.
    ts = BRepOffsetAPI_ThruSections(True, True, 1e-6)     # solid, ruled
    for wire in sections:
        ts.AddWire(wire)
    ts.AddWire(sections[0])
    ts.Build()
    if not ts.IsDone():
        raise BooleanError("bezel loft did not complete")
    return ts.Shape()


def anterior_bezel_features(bezel: EyewireBezelParams) -> list:
    """The anterior bezel band, expressed as whole-ring `EdgeFeature`s.

    Exactly how the raster spells it (`relief.edges.carve_anterior_bezel`), and
    for the same reason: the anterior band *is* a chamfer round a whole ring, so
    describing it as one keeps a single chamfer implementation to trust instead
    of a second copy of the same maths on the other face.

    Empty `zones` is the whole ring; `blend_mm=0` because the band does not
    feather out — it closes on itself.
    """
    from ..project.schema import EdgeFeature

    if not bezel.cuts_anterior() or bezel.anterior_width_mm <= 0:
        return []
    return [
        EdgeFeature(
            id=f"anterior-bezel-{edge}", label="Anterior eyewire bezel",
            face="anterior", edge=edge, profile="chamfer",
            width_mm=bezel.anterior_width_mm, angle_deg=bezel.anterior_angle_deg,
            min_thickness_mm=bezel.min_thickness_mm,
            zones=[], blend_mm=0.0, mirror=False,
        )
        for edge in ("lens_od", "lens_os")
    ]


def bezel_cutters(solid: TopoDS_Shape, partition: CastlePartition,
                  castle: CastleParams, top: float) -> list[TopoDS_Shape]:
    """The eyewire bezel's cutters — posterior band, anterior band, or both.

    The two faces are built by different machinery, and that is not an oversight
    on either side. The posterior band is a purpose-built loft (`bezel_cutter`)
    anchored on the surface it seats the lens against. The anterior band is a
    plain whole-ring chamfer, which `edge_feature_cutters` already does — on the
    underside, via `surface_z_at(..., face="bottom")`, because in a solid the
    front of the frame is simply the other side of the same body.

    Only the posterior half was ported when the solid path was built, so
    `face="anterior"` removed 0.00 mm3 and `face="both"` removed exactly what
    `"posterior"` did (2026-08-07 finding 3). It was a porting gap rather than a
    missing capability — the anterior machinery was already carrying anterior
    edge features correctly.
    """
    bezel = castle.eyewire_bezel
    out = []
    if bezel.cuts_posterior():
        for interior in partition.body.interiors:
            # Lens apertures only. A decorative OUTLINE opening — an aviator's
            # bridge keyhole, a temple cut-out — is a through-cut, not an
            # eyewire: it seats no lens, so there is no bevel for a bezel band
            # to make room for, and chamfering its rim thins a deliberately
            # slender piece of the frame. Same rule the lens groove already
            # follows (`lip_body`), applied here for the reason it was applied
            # there.
            #
            # Found by M-N1 parity: the mesh kernel filtered these and this path
            # did not, 2 cutters against 3 on the aviator.
            if partition.is_hole(interior):
                continue
            try:
                out.append(bezel_cutter(solid, partition.body, interior, bezel, top))
            except BooleanError:
                continue
    for feature in anterior_bezel_features(bezel):
        try:
            out.extend(edge_feature_cutters(solid, partition, feature, top))
        except BooleanError:
            continue
    return out


def apply_surface_features(solid: TopoDS_Shape, partition: CastlePartition,
                           castle: CastleParams) -> TopoDS_Shape:
    """The features that read the surface *another feature already cut*.

    Pad splay, then bridge relief, each subtracted before the next is built —
    and the order is load-bearing, not incidental. Both anchor on the frame's
    centerline, so with the splay enabled the scoop's anchor ray lands on
    material the splay has already taken away. Measured on the demo frame: the
    scoop's thirteen anchors move by up to **2.59 mm** (0.94 mm mean) depending
    on whether the splay has been cut yet. On a 1.2 mm-deep scoop that is not a
    rounding difference — it is a different part.

    That is why these two cannot join the single-pass group in
    `independent_cutters`, and why this function exists separately rather than
    being folded in for the speed.
    """
    splay = castle.pad_splay
    if splay.enabled:
        try:
            solid = cut(solid, splay_cutter(solid, partition.body, splay))
        except BooleanError:
            pass

    scoop = castle.bridge_relief
    if scoop.enabled:
        try:
            solid = cut(solid, scoop_cutter(solid, partition.body, scoop))
        except BooleanError:
            pass
    return solid


def independent_cutters(solid: TopoDS_Shape, partition: CastlePartition,
                        castle: CastleParams, top: float) -> list[TopoDS_Shape]:
    """Every cutter that can be built against one target and subtracted at once.

    The membership rule is *measured*, not assumed. Firing each feature's anchor
    rays at the post-footing solid and again at the fully-featured one, on the
    demo frame:

    | feature | anchor drift |
    | --- | --- |
    | pad splay | 0.0000 mm |
    | bridge relief | **2.5898 mm** |
    | eyewire bezel (both rings) | 0.0000 mm |
    | brow chamfer (mirrored pair) | 0.0000 mm |

    The bezel and the edge features read only terrace-and-footing surface, which
    no other feature touches; the lens groove and the hinge pockets never read
    the solid at all — they are pure geometry off the partition. So all of them
    see the same target whether they are cut one at a time or together, and
    `cut_many` gets to do it in one pass: 32.9 s -> 7.5 s on the demo frame,
    volume delta 0.00 mm3 and the same 6,471 faces.

    Only the bridge relief drifts, and `apply_surface_features` keeps it
    sequential. **If a future feature anchors on something one of these removes,
    it belongs there and not here** — the two are not interchangeable, and the
    cost of getting it wrong is a quietly different part rather than an error.
    """
    cutters = bezel_cutters(solid, partition, castle, top)
    cutters.extend(resolved_edge_cutters(solid, partition, castle, top))
    cutters.extend(groove_cutters(partition, castle))
    return cutters


def apply_posterior_features(solid: TopoDS_Shape, partition: CastlePartition,
                             castle: CastleParams, top: float) -> TopoDS_Shape:
    """Pad splay, bridge relief and eyewire bezel, subtracted one at a time.

    The sequential spelling, kept because it is the reference the grouped path
    in `build_castle_solid` is checked against — same features, same anchors,
    same result, and a test pins that the two agree.
    """
    solid = apply_surface_features(solid, partition, castle)
    return cut_many(solid, bezel_cutters(solid, partition, castle, top))


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


def resolved_edge_cutters(solid: TopoDS_Shape, partition: CastlePartition,
                          castle: CastleParams, top: float) -> list[TopoDS_Shape]:
    """Cutters for every resolved edge feature, mirrored twins included."""
    cutters: list[TopoDS_Shape] = []
    for feature in castle.resolved_edge_features():
        try:
            cutters.extend(edge_feature_cutters(solid, partition, feature, top))
        except BooleanError:
            continue
    return cutters


def apply_edge_features(solid: TopoDS_Shape, partition: CastlePartition,
                        castle: CastleParams, top: float) -> TopoDS_Shape:
    """Every resolved edge feature, mirrored twins included."""
    return cut_many(solid, resolved_edge_cutters(solid, partition, castle, top))


# ---------------------------------------------------------------- pad splay

def splay_cutter(solid: TopoDS_Shape, body: Polygon, p, res_hint: float = 0.15
                 ) -> TopoDS_Shape:
    """The pad splay as a swept chamfer along the outline's bottom-center run.

    **Most of the raster's implementation does not survive, and should not.**
    `_splay_crest_tables` is an inventory of fixes for sampling artifacts — a
    slope limiter on the crest offset, `uniform_filter1d` on the tangents and
    again on the anchor heights, an EDT-filled surface to stop cells outside the
    body cratering the crest, and a cosine feather. All were traced to one field
    finding ("jagged points where the cut terminates", 2026-07-02) and all of
    them make the feature *less* crisp to hide a staircase that does not exist
    here. What is kept is the geometry they were protecting:

    * the crest as an inward offset of the outline, `crest_deviation_center_mm`
      at the bottom-center falling to `crest_deviation_end_mm` at each run end;
    * the clearance clamp that keeps the crest off the lens rims — real
      geometry, not a smoothing fix;
    * the toric angle blend;
    * the feather, as a depth taper at each end.

    `crest_blend_mm` is **not** applied. In the raster it defaults to a
    mandatory 2 mm round-over whose only job is to stop the crest shading as a
    jagged ridge; here the crest is a real edge and wants to be sharp. It
    returns later as the optional round-over it should always have been.
    """
    from shapely import distance as _distance, points as _points
    from shapely.ops import unary_union

    from ..relief.features import _bottom_center_station, _splay_angles_deg

    ring, L, s0 = _bottom_center_station(body)
    run = min(float(p.run_mm), 0.45 * L)
    if run <= res_hint or p.crest_deviation_center_mm <= 0.0:
        raise BooleanError("degenerate pad splay")

    n = max(9, int(run * 2.0 * EDGE_SECTIONS_PER_MM))
    u = np.linspace(-run, run, n)
    au = np.abs(u)
    stations = np.mod(s0 + u, L)

    pts, tans = [], []
    eps = max(3.0 * res_hint, 0.75)
    for s in stations:
        q = ring.interpolate(float(s))
        a = ring.interpolate(float((s - eps) % L))
        b = ring.interpolate(float((s + eps) % L))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= max(np.linalg.norm(t), 1e-12)
        pts.append([q.x, q.y])
        tans.append(t)
    pts, tans = np.array(pts), np.array(tans)
    inward = _inward(body, pts, tans)

    # Crest offset: centre -> end, held clear of the lens rims.
    c = (p.crest_deviation_center_mm
         + (p.crest_deviation_end_mm - p.crest_deviation_center_mm) * (au / run))
    rims = (unary_union([LineString(r) for r in body.interiors])
            if body.interiors else None)
    if rims is not None and not rims.is_empty:
        c = np.minimum(c, 0.8 * _distance(_points(pts), rims))
    c = np.maximum(c, 0.0)
    # ...and held inside the body, which the rim clamp above does not
    # guarantee. See `_crest_inside`.
    c = _crest_inside(body, pts, inward, c)

    tan_t = np.tan(np.radians(_splay_angles_deg(p, au, run)))
    feather = min(max(float(p.feather_mm), 0.0), run)
    if feather > 0.0:
        w = np.where(au <= run - feather, 1.0,
                     0.5 * (1.0 + np.cos(np.pi * (au - (run - feather)) / feather)))
    else:
        w = np.ones_like(au)

    drops = np.maximum(c * tan_t * w, MIN_TAPER_DROP_MM)
    widths = np.maximum(c, MIN_TAPER_DROP_MM)
    # Anchored at the CREST, not at the outline edge — the splay is defined as
    # falling *from* the crest toward the edge, and the crest sits up to
    # `crest_deviation_center_mm` (6 mm by default) inboard. Over that distance
    # the surface climbs out of the bridge footing and into the nosepad tower,
    # so anchoring at the edge measures the drop from the wrong datum and leaves
    # the cut ~0.1 mm rms shallow, up to 0.97 mm at the nosepads.
    #
    # Note this is the opposite choice from the bezel, and deliberately so: the
    # bezel's promise is a constant depth *at the rim*, the splay's is a crest
    # at the local surface height. Each is anchored where its own definition
    # pins it.
    anchors = surface_z_at(solid, pts + inward * np.maximum(c, _RIM_PROBE_MM)[:, None])
    top = float(anchors.max()) + CUT_MARGIN_MM

    # Floor the cut at `anterior_clamp_mm` above the front face, the same way
    # `scoop_cutter` and the bezel do. The parameter has always existed and
    # carried the comment "no knife edge"; this path simply never read it, so
    # the drop was whatever the crest offset and the angle multiplied out to.
    #
    # On the Gabriel fixture that reached 3.464 mm BELOW the anterior face with
    # 19 of 41 stations sitting over less material than that, and the splay cut
    # the frame **into two halves** — left x[-67.65, -1.38], right x[1.38,
    # 67.65]. Zero holes, zero non-manifold edges, `IsValid` true: a clean cut
    # in the wrong place, which is why only the body count caught it.
    #
    # The lower bound keeps the loft buildable where the surface is already
    # thinner than the clamp (an anchor ray that misses reads 0.0), matching
    # `scoop_cutter`; at 0.02 mm it cannot sever anything.
    floor = float(p.anterior_clamp_mm)
    drops = np.clip(drops, MIN_TAPER_DROP_MM,
                    np.maximum(anchors - floor, MIN_TAPER_DROP_MM))

    sections = [
        _edge_section(q, nn, float(a), float(wd), float(dr), "chamfer", 0.0,
                      top, True)
        for q, nn, a, wd, dr in zip(pts, inward, anchors, widths, drops)
    ]
    ts = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    for wire in sections:
        ts.AddWire(wire)
    ts.Build()
    if not ts.IsDone():
        raise BooleanError("pad splay loft did not complete")
    return ts.Shape()


# ------------------------------------------------------------- bridge relief

#: Sections lofted per millimetre along the bridge scoop's Y run.
SCOOP_SECTIONS_PER_MM = 2.0

#: Points sampled across one scoop section.
SCOOP_SECTION_POINTS = 28


def _scoop_section(y: float, half_w: float, depth: float, anchor: float,
                   top: float, n: int = SCOOP_SECTION_POINTS):
    """One cross-section of the conic scoop, in the plane of constant y.

    A half-ellipse of half-width `half_w` and depth `depth`, closed upward.
    That is the cone the raster was imitating: the raster substitutes a cosine
    bell — `0.5 + 0.5 cos(pi x / r)` — which the report lists among the
    compensating blurs, chosen because it is tangent to the surface at its edges
    and so hides the facets a sampled cone showed. A real cone meets the surface
    at an angle, and that meeting is an edge, which is the point.
    """
    xs = np.linspace(-half_w, half_w, n)
    zs = anchor - depth * np.sqrt(
        np.maximum(1.0 - (xs / max(half_w, 1e-9)) ** 2, 0.0))

    mp = BRepBuilderAPI_MakePolygon()
    for x, z in zip(xs, zs):
        mp.Add(gp_Pnt(float(x), float(y), float(z)))
    mp.Add(gp_Pnt(float(half_w), float(y), float(top)))
    mp.Add(gp_Pnt(float(-half_w), float(y), float(top)))
    mp.Close()
    return mp.Wire()


def scoop_cutter(solid: TopoDS_Shape, body: Polygon, p) -> TopoDS_Shape:
    """The bridge relief as a lofted elliptical cone running on Y.

    Base (widest, deepest) at the top edge of the bridge on the centreline,
    tapering at `taper_angle_deg` per side to a tip down the lower bridge. Depth
    scales with the local half-width, so it is a true cone imprint feathering to
    nothing — which is what the raster's own docstring claims it builds and what
    its cosine bell approximates.
    """
    half_w = float(p.width_mm) / 2.0
    depth = float(p.depth_mm)
    if depth <= 0.0 or half_w <= 0.0:
        raise BooleanError("degenerate bridge relief")
    tan_b = math.tan(math.radians(min(max(float(p.taper_angle_deg), 1.0), 89.0)))

    # The base is the highest point of the body on the centreline — the top
    # edge of the bridge over the nose.
    minx, miny, maxx, maxy = body.bounds
    centre = body.intersection(LineString([(0.0, miny - 1.0), (0.0, maxy + 1.0)]))
    if centre.is_empty:
        raise BooleanError("no body on the centreline")
    y_base = max(g.bounds[3] for g in getattr(centre, "geoms", [centre]))
    y_tip = y_base - half_w / tan_b

    n = max(8, int((y_base - y_tip) * SCOOP_SECTIONS_PER_MM))
    ys = np.linspace(y_tip, y_base, n + 1)[1:]        # skip the exact apex
    rs = np.clip((ys - y_tip) * tan_b, 0.0, half_w)
    ds = depth * (rs / half_w)
    keep = rs > MIN_TAPER_DROP_MM
    ys, rs, ds = ys[keep], rs[keep], np.maximum(ds[keep], MIN_TAPER_DROP_MM)
    if len(ys) < 2:
        raise BooleanError("bridge relief too small to loft")

    anchors = surface_z_at(solid, np.column_stack([np.zeros_like(ys), ys]))
    floor = float(p.anterior_clamp_mm)
    ds = np.minimum(ds, np.maximum(anchors - floor, 0.0))
    ds = np.maximum(ds, MIN_TAPER_DROP_MM)
    top = float(anchors.max()) + CUT_MARGIN_MM

    sections = [_scoop_section(float(y), float(r), float(d), float(a), top)
                for y, r, d, a in zip(ys, rs, ds, anchors)]

    # One prismatic station past the base, because `y_base` is *on* the body's
    # top edge: without it the loft's end cap is the plane y = y_base, which
    # touches the bridge wall along a single vertical line at x = 0 instead of
    # crossing it. The cut then leaves exactly one edge with four faces on it —
    # a non-manifold model that `BRepCheck_Analyzer` calls valid, that has no
    # gaps at all, and that will not export as an STL. Found on the aviator
    # fixture (BUILDPLAN-NEW M-N0); one edge of 33,683.
    #
    # A cutter has to *cross* every surface it exits. Nothing extra is removed:
    # y_base is the highest body point on the centreline, so the extension runs
    # through empty space.
    sections.append(_scoop_section(float(ys[-1]) + CUT_MARGIN_MM, float(rs[-1]),
                                   float(ds[-1]), float(anchors[-1]), top))

    ts = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    for wire in sections:
        ts.AddWire(wire)
    ts.Build()
    if not ts.IsDone():
        raise BooleanError("bridge relief loft did not complete")
    return ts.Shape()


def _groove_section(p_xy, outward, apex_z: float, depth: float, half_w: float):
    """The V notch as a closed section in (outward-from-lip, Z).

    Apex at `depth` into the wall — landing on the original LENS contour — and
    opening `2 * half_w` tall at the lip face. Extended a little *inside* the
    aperture (negative u, which is air) so the boolean overlaps the lip wall
    cleanly rather than meeting it tangentially.
    """
    px, py = float(p_xy[0]), float(p_xy[1])
    nx, ny = float(outward[0]), float(outward[1])

    def at(u, v):
        return gp_Pnt(px + nx * float(u), py + ny * float(u), float(v))

    # The lead-in points must sit ON the V's own flanks, extrapolated back into
    # the aperture — not offset by the lead in both axes. The half-width at u is
    # `half_w * (1 - u / depth)`, so at u = -lead it is `half_w * (1 + lead /
    # depth)`. Padding z by the lead instead shallows the flanks and cut the
    # groove ~7% narrow: 0.867 mm half-width at u = 0.05 where the spec is
    # 0.933 mm.
    lead_hw = half_w * (1.0 + _GROOVE_LEAD_MM / depth)
    mp = BRepBuilderAPI_MakePolygon()
    mp.Add(at(-_GROOVE_LEAD_MM, apex_z + lead_hw))
    mp.Add(at(depth, apex_z))
    mp.Add(at(-_GROOVE_LEAD_MM, apex_z - lead_hw))
    mp.Close()
    return mp.Wire()


#: How far the V is carried back into the open aperture before it starts
#: cutting. Pure overlap allowance — the aperture is air.
_GROOVE_LEAD_MM = 0.3


def _swept_groove_cutter(body: Polygon, ring, curve, p) -> TopoDS_Shape:
    """The V groove swept along the aperture's authored curve — 3 faces, not 540.

    The loft below approximates the ring with 180 straight-sided patches; this
    rides the curve itself, so it is both exact and vastly cheaper. On the demo
    frame: **540 faces to 3, and the boolean that applies it 4.9 s to 0.5 s.**

    **The spine is the original lens curve, not the lip.** Two reasons, and the
    first is not negotiable: `BRepOffsetAPI_MakePipeShell` refuses a
    `Geom_OffsetCurve` spine outright (`Standard_ConstructionError`). The second
    is that it does not matter — a pipe shell keeps the profile perpendicular to
    the spine, so a profile point `depth` inboard traces exactly the inward
    offset. Sweeping the lip's profile along the contour *is* sweeping it along
    the lip.

    **The placement is read, not derived.** The profile has to sit in the frame
    the sweep starts from, so it is built at the lip point nearest the spine's
    start, with "outward" the direction from there back to the start. Deriving
    that from the offset's sign instead needs OCCT's `Geom_OffsetCurve`
    convention to be exactly what you think it is, and it is not: the lip is
    `basis - d * (Z x T)`, not plus. Measuring costs one projection and cannot
    go stale. `_inward` is no help here either — it probes the body, and once
    the aperture has been shrunk the contour lies *inside* the material, so
    every probe lands in solid and the vote is meaningless.
    """
    basis = getattr(curve, "basis", None)
    if basis is None:
        raise BooleanError("aperture has no authored curve to sweep along")
    from shapely.ops import nearest_points
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire
    from OCP.BRepOffsetAPI import BRepOffsetAPI_MakePipeShell
    from OCP.gp import gp_Dir

    depth, half_w = float(p.depth_mm), float(p.width_mm) / 2.0
    spine_edge = nurbs_edge(basis, 0.0)
    adaptor = BRepAdaptor_Curve(spine_edge)
    start = adaptor.Value(adaptor.FirstParameter())
    head = np.array([start.X(), start.Y()])

    lip_pt = nearest_points(LineString(ring), Point(*head))[0]
    outward = head - np.array([lip_pt.x, lip_pt.y])
    reach = float(np.linalg.norm(outward))
    if abs(reach - depth) > 1e-6:
        # The lip is not this curve offset by the groove depth after all, so the
        # apex would not land on the contour. Refuse rather than cut it wrong.
        raise BooleanError(
            f"lip sits {reach:.4f} mm from the contour, expected {depth:.4f}")

    profile = _groove_section(np.array([lip_pt.x, lip_pt.y]), outward / reach,
                              float(p.anterior_offset_mm), depth, half_w)

    ps = BRepOffsetAPI_MakePipeShell(BRepBuilderAPI_MakeWire(spine_edge).Wire())
    # Fixed binormal, not Frenet: the V must stay upright rather than roll with
    # the ring's curvature — the same reason `build._sweep` does this.
    ps.SetMode(gp_Dir(0.0, 0.0, 1.0))
    ps.SetTransitionMode(
        BRepBuilderAPI_TransitionMode.BRepBuilderAPI_RightCorner)
    ps.Add(profile, False, False)
    ps.Build()
    if not ps.IsDone():
        raise BooleanError("lens groove sweep did not complete")
    if not ps.MakeSolid():
        raise BooleanError("lens groove sweep did not close into a solid")
    return ps.Shape()


def groove_cutter(body: Polygon, ring, p, stations: int = GROOVE_STATIONS,
                  curve=None) -> TopoDS_Shape:
    """The swept V groove for one aperture lip ring.

    Swept along the authored curve where the drawing supplied one
    (`_swept_groove_cutter`), and lofted over `stations` sections otherwise.
    The loft is the older path and stays as the fallback: a drawing made of
    polylines has no curve to ride, and neither does an aperture whose exact
    offset was refused (see `_offset_aperture`).
    """
    depth, half_w = float(p.depth_mm), float(p.width_mm) / 2.0
    if depth <= 0.0 or half_w <= 0.0:
        raise BooleanError("degenerate lens groove")

    if curve is not None:
        try:
            return _swept_groove_cutter(body, ring, curve, p)
        except Exception:                                    # noqa: BLE001
            pass                         # OCCT raises its own types; loft it

    pts, tans = _ring_stations(LineString(ring), stations)
    outward = _inward(body, pts, tans)      # from the aperture into the wall
    apex_z = float(p.anterior_offset_mm)

    sections = [_groove_section(q, nn, apex_z, depth, half_w)
                for q, nn in zip(pts, outward)]
    ts = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    for wire in sections:
        ts.AddWire(wire)
    ts.AddWire(sections[0])
    ts.Build()
    if not ts.IsDone():
        raise BooleanError("lens groove loft did not complete")
    return ts.Shape()


def apply_lens_groove(solid: TopoDS_Shape, partition: CastlePartition,
                      castle: CastleParams) -> TopoDS_Shape:
    """Cut the drageoir V into each aperture wall.

    This is the feature that most plainly justifies the rewrite: the V is an
    **undercut**, so it never existed in the heightfield at all. The raster
    reaches it by shrinking the aperture mask and then hand-building a notched
    rim strip in the *mesher* (`castle._groove_rim`) — geometry the model itself
    does not contain, which is why it cannot be measured, sectioned or posted
    from. Here it is a boolean like any other.
    """
    return cut_many(solid, groove_cutters(partition, castle))


def groove_cutters(partition: CastlePartition,
                   castle: CastleParams) -> list[TopoDS_Shape]:
    """One V cutter per aperture wall.

    Takes no solid and fires no anchor ray — the V is positioned entirely from
    the partition, which is why it can always join the single-pass group.

    `partition` must ALREADY be the lip partition: `build_castle_solid` re-runs
    the partitioner against the shrunk apertures before it builds the terraces,
    so `partition.body` is the lip body and its interiors are the lip rings.
    Shrinking again here put the V a further `depth_mm` inboard, which is open
    aperture — the loft built, the boolean succeeded, and it removed nothing.
    """
    groove = getattr(castle, "lens_groove", None)
    if groove is None or not groove.enabled or groove.depth_mm <= 0:
        return []
    lip = partition.body
    cutters = []
    for interior in lip.interiors:
        if partition.is_hole(interior):
            continue
        try:
            cutters.append(groove_cutter(lip, interior, groove,
                                         curve=partition.ring_curve(interior)))
        except BooleanError:
            continue
    return cutters
