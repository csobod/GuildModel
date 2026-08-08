"""Castle features as mesh bodies (BUILDPLAN-NEW M-N1).

The mesh-domain counterpart of `core/solid/features.py`. Same features, same
placement — the *where* comes from `core/geometry/rings.py`, shared by both
kernels — built as swept strips instead of lofted B-Rep sections.

**Why not the B-Rep's sweeps.** `BRepOffsetAPI_ThruSections` and `MakePipeShell`
are where the season's worst failures came from: a bezel sweep that produced a
valid 4-face cutter whose *cut* took 260 s and returned negative volume, a spine
that took 401 s to fail, and the M-N0 tangency that left a non-manifold edge.

**Why not a chain of convex hulls either, which is what these were.** That
construction cannot self-intersect however tight the corner, which is why
`kernel.hull_chain` is still there as a fallback — but its cells abut on a
shared section instead of overlapping, and the union does not reliably cancel
it. The lens groove reached the part with 76 self-touching edges from that
alone. `kernel.sweep_sections` builds the tube directly and is exact.
"""
from __future__ import annotations

import numpy as np
from manifold3d import Manifold
from shapely.geometry import LineString, Polygon

from ..geometry.rings import carry_anchors, inward_normals, ring_stations
from ..project.schema import CastleParams
from .kernel import (ManifoldError, surface_z_at, sweep_sections,
                     swept_profile)

__all__ = ["bezel_cutter", "bezel_cutters", "edge_feature_cutters",
           "groove_cutters", "resolved_edge_cutters", "scoop_cutter",
           "splay_cutter", "surface_feature_cutters", "v_groove_cutter"]

#: Stations around an aperture for a bezel band. Same as the B-Rep path's
#: `BEZEL_STATIONS`, and pinned by the same argument: what matters is chord
#: error, not volume. Volume converges early and misleads; the sagitta of the
#: inscribed polygon is what the cut surface is actually wrong by, and the
#: 5 um raster-agreement gate fails at 120 stations (7.2 um) and clears at 180
#: (3.2 um).
BEZEL_STATIONS = 180

#: How far past `width` the chamfer plane runs, as a multiple of the band width.
#: Self-limiting: beyond where the plane leaves the material the boolean removes
#: nothing, so this only has to be generous.
_BEZEL_REACH = 1.0

#: How far inside the rim the anchoring ray is fired, mm.
_RIM_PROBE_MM = 0.05

#: How far a cutter reaches past the material it trims, mm.
CUT_MARGIN_MM = 1.0

#: Stations around an aperture for the groove V. Matches the B-Rep path's
#: `GROOVE_STATIONS` so the two kernels inscribe the same polygon in the same
#: ring and their volumes are comparable at the chord level.
GROOVE_STATIONS = 180

#: How far the V's mouth reaches back out of the wall, mm. The cutter has to
#: *cross* the rim face rather than stop on it — the M-N0 lesson, and cheap
#: insurance here since the overshoot is in open air.
GROOVE_LEAD_MM = 0.3


def v_groove_cutter(body: Polygon, ring, groove,
                    stations: int = GROOVE_STATIONS) -> Manifold:
    """The drageoir V for one aperture, as a swept triangular tube.

    `body` must already be the **lip** body and `ring` one of its lip rings —
    the aperture after the groove depth has been taken off it. The V is then cut
    back outward so its apex lands exactly on the original LENS contour, which
    is what keeps the boxed dimension honest. Shrinking again here would put the
    V a further `depth_mm` inboard, into open aperture, where it removes
    nothing.

    The section is a triangle: apex `depth` into the wall at `anterior_offset`,
    opening to `width` at the rim face and overshooting it by `GROOVE_LEAD_MM`
    so the mouth breaks cleanly through.
    """
    depth = float(groove.depth_mm)
    half_w = float(groove.width_mm) / 2.0
    apex_z = float(groove.anterior_offset_mm)
    if depth <= 0.0 or half_w <= 0.0:
        raise ValueError("degenerate lens groove")

    pts, tans = ring_stations(LineString(ring), stations)
    # `inward_normals` means "into the material", and for an aperture ring that
    # is already into the wall — which is where the groove cuts. Negating it
    # here (the obvious reading of the name) buries the mouth in the wall and
    # puts the apex out in the hole: still a V, still removes material, no
    # undercut at all. Caught only by the ray test; the volume gate passed it.
    into_wall = inward_normals(body, pts, tans)

    # The mouth is opened in proportion, so the V's flanks stay straight lines
    # through the rim face instead of kinking at it.
    lead_half_w = half_w * (1.0 + GROOVE_LEAD_MM / depth)

    def profile(i):
        p, o = pts[i % stations], into_wall[i % stations]
        mouth, apex = p - o * GROOVE_LEAD_MM, p + o * depth
        return np.array([
            [mouth[0], mouth[1], apex_z + lead_half_w],
            [apex[0], apex[1], apex_z],
            [mouth[0], mouth[1], apex_z - lead_half_w],
        ])

    return sweep_sections([profile(i) for i in range(stations)], closed=True)


#: Sections per millimetre along an edge-feature span. Matches the B-Rep path's
#: `EDGE_SECTIONS_PER_MM`, so both kernels sample the same run at the same
#: places and a volume difference is about the sweep rather than the sampling.
EDGE_SECTIONS_PER_MM = 1.2

#: The shallowest cut a taper is allowed to reach before it is simply zero.
MIN_TAPER_DROP_MM = 0.02

#: How far outside the edge the section's first sample is moved, mm.
#:
#: `u = 0` is the ring the sweep runs along, and for the pad splay and the edge
#: features that ring **is the body outline** — so a sample there is a vertex of
#: the tool lying exactly in a face of its target. Same defect as
#: `model.build.FOOTING_CROSS_MM`, third instance, and found the same way: cut
#: the splay out of progressively simpler targets and it is clean against a
#: plain box, 102 degenerate faces against the real outline, before any terrace
#: or blend is involved.
#:
#: The sample is *moved* rather than added, so the section keeps its point count
#: and the ramp keeps its slope; `-CUT_MARGIN_MM` already stands well outside
#: the body, and this only has to clear the wall.
EDGE_CROSS_MM = 0.05


def _edge_profile(width: float, drop: float, radius: float, profile: str,
                  posterior: bool, n: int = 12) -> np.ndarray:
    """One edge-feature section as `(u, v)` offsets from the anchor.

    `u` runs from `-CUT_MARGIN_MM` (outside the edge, so the cutter crosses it
    rather than stopping on it) to `width`. `v` is signed relative to the
    anchor: down for a posterior feature, up for an anterior one, since the
    anterior face is just the underside of the same body.

    The chamfer is a straight ramp. The **fillet is concave** — see
    `kernel.swept_profile`, which is why edge features go through that rather
    than `sweep_sections`.
    """
    us = np.linspace(0.0, width, n)
    us[0] = -EDGE_CROSS_MM            # off the wall — see the constant
    if profile == "fillet":
        r = max(radius, 1e-6)
        inner = np.clip(r - us, 0.0, r)
        prof = np.where(us < r,
                        r - np.sqrt(np.maximum(r * r - inner * inner, 0.0)), 0.0)
        if prof[0] > 0:
            prof = prof * (drop / prof[0])
    else:
        prof = np.maximum(0.0, width - us) * (drop / max(width, 1e-9))

    vs = (-1.0 if posterior else 1.0) * prof
    # A leading point outside the edge at the section's own start height, so the
    # cutter opens out into air instead of terminating on the face it exits.
    return np.vstack([[-CUT_MARGIN_MM, vs[0]], np.column_stack([us, vs])])


def edge_feature_cutters(mesh, partition, feature, top: float) -> list[Manifold]:
    """Swept cutters for one resolved `EdgeFeature`, one per span it covers.

    The spans come from `relief.edges.span_intervals`, the same function the
    raster and the B-Rep path use, so a feature named by castle zone covers
    exactly the same run of ring in all three. A span is *named*, not measured —
    the M17 decision, and it survives every rewrite.

    Spans are open runs rather than closed rings, so the sweep is not closed and
    the end sections cap it.
    """
    import math

    from ..relief.edges import (ring_for, span_intervals, station_fraction,
                                taper_weight)

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
    far = top if posterior else -CUT_MARGIN_MM
    out: list[Manifold] = []

    for s0, s1 in intervals:
        n = max(6, int((s1 - s0) * EDGE_SECTIONS_PER_MM))
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
        into = inward_normals(partition.body, pts, tans)

        weight = taper_weight(ss, intervals, feature.blend_mm, total)
        frac = station_fraction(ss, intervals, total)
        widths = np.array([float(feature.width_at(float(v))) for v in frac])
        if feature.profile == "fillet":
            widths = np.full_like(widths, float(feature.radius_mm))
            base = np.full_like(widths, float(feature.radius_mm))
        else:
            base = widths * tan_a
        drops = np.maximum(base * weight, MIN_TAPER_DROP_MM)
        if feature.depth_limit_mm is not None:
            drops = np.minimum(drops, float(feature.depth_limit_mm))

        anchors = surface_z_at(mesh, pts + into * _RIM_PROBE_MM,
                               face="top" if posterior else "bottom")
        anchors = carry_anchors(anchors, far)

        profiles = [
            _edge_profile(float(w), float(d), float(feature.radius_mm),
                          feature.profile, posterior) + np.array([0.0, float(a)])
            for w, d, a in zip(widths, drops, anchors)
        ]
        out.append(swept_profile(pts, into, profiles, far, closed=False))
    return out


def resolved_edge_cutters(mesh, partition, castle: CastleParams,
                          top: float) -> list[Manifold]:
    """Cutters for every resolved edge feature, mirrored twins included."""
    cutters: list[Manifold] = []
    for feature in castle.resolved_edge_features():
        cutters.extend(edge_feature_cutters(mesh, partition, feature, top))
    return cutters


def bezel_cutter(mesh, body: Polygon, ring, bezel, top: float,
                 stations: int = BEZEL_STATIONS) -> Manifold:
    """The swept chamfer band for one aperture rim.

    A real chamfer, not a variable offset: a ruled plane rising inward at
    `angle_deg` from `rim_z - width*tan(angle)`, with `rim_z` sampled per
    station by a vertical ray onto the surface just inside the rim. That is what
    gives the band an actual edge, and it is the meaning the B-Rep path settled
    on — the two agree to 5 um over 83% of in-body cells on the demo frame and
    diverge only where the surface swells under the band, which is the feature
    behaving like the Fusion chamfer it is named after.

    **Anchored at the rim, not at the band's inner edge**, because the band's
    promise is a constant depth *at the rim* all the way round. Anchoring inward
    lets the rim depth drift by the surface slope times the band width, worth up
    to 0.7 mm across a footing swell.

    `mesh` is the part as it stands, for the anchor rays.
    """
    import math

    width = float(bezel.width_mm)
    if width <= 0.0:
        raise ValueError("bezel width is zero")
    tan_a = math.tan(math.radians(float(bezel.angle_deg)))
    clamp = float(bezel.anterior_clamp_mm)

    pts, tans = ring_stations(LineString(ring), stations)
    into_wall = inward_normals(body, pts, tans)

    anchors = carry_anchors(surface_z_at(mesh, pts + into_wall * _RIM_PROBE_MM),
                             clamp)

    drop = width * tan_a
    u0, u1 = -CUT_MARGIN_MM, width * _BEZEL_REACH

    def profile(i):
        p, n = pts[i % stations], into_wall[i % stations]
        rim_z = float(anchors[i % stations])
        v0 = max(rim_z - drop + u0 * tan_a, clamp)
        v1 = max(rim_z - drop + u1 * tan_a, clamp)
        a, b = p + n * u0, p + n * u1
        # Trapezoid in the (inward, Z) plane: the chamfer plane below, `top`
        # above. Convex, which mattered when this was a hull chain; the strip
        # in `sweep_sections` does not care, but the section is still ordered
        # around its boundary, which the strip very much does care about.
        return np.array([[a[0], a[1], v0], [b[0], b[1], v1],
                         [b[0], b[1], top], [a[0], a[1], top]])

    return sweep_sections([profile(i) for i in range(stations)], closed=True)


def bezel_cutters(mesh, partition, castle: CastleParams,
                  top: float) -> list[Manifold]:
    """One band per aperture rim, when the bezel cuts the posterior face.

    The anterior and edge-feature variants are `resolved_edge_cutters` on the
    B-Rep path and are not ported yet.
    """
    bezel = getattr(castle, "eyewire_bezel", None)
    if bezel is None or not bezel.enabled or not bezel.cuts_posterior():
        return []
    # Lens apertures only — a decorative OUTLINE opening seats no lens, so it
    # has no bevel to make room for. The B-Rep path used to bezel them; the
    # disagreement showed up as 2 cutters against 3 on the aviator, and the
    # maker confirmed the filter is the correct behaviour. Both kernels now skip
    # them.
    return [bezel_cutter(mesh, partition.body, ring, bezel, top)
            for ring in partition.body.interiors
            if not partition.is_hole(ring)]


#: Sections lofted per millimetre along the bridge scoop's Y run.
SCOOP_SECTIONS_PER_MM = 2.0

#: Points across one scoop section.
SCOOP_SECTION_POINTS = 28


def splay_cutter(mesh, body: Polygon, p, res_hint: float = 0.15) -> Manifold:
    """The pad splay as a swept chamfer along the outline's bottom-centre run.

    Falls from a crest — an inward offset of the outline — toward the outline
    edge at the splay angle. The crest is held off the lens rims and, because of
    what M-N0 found on the Gabriel drawing, held *inside the body*: inward from
    the outline is not into the material at the bottom centre, where the frame
    has the nose notch, and a crest out in that notch reads as no material at
    all.
    """
    import math

    from shapely import distance as _distance, points as _points
    from shapely.ops import unary_union

    from ..geometry.rings import crest_inside
    from ..relief.features import _bottom_center_station, _splay_angles_deg

    ring, total, s0 = _bottom_center_station(body)
    run = min(float(p.run_mm), 0.45 * total)
    if run <= res_hint or p.crest_deviation_center_mm <= 0.0:
        raise ManifoldError("degenerate pad splay")

    n = max(9, int(run * 2.0 * EDGE_SECTIONS_PER_MM))
    u = np.linspace(-run, run, n)
    au = np.abs(u)
    stations = np.mod(s0 + u, total)

    pts, tans = [], []
    eps = max(3.0 * res_hint, 0.75)
    for s in stations:
        q = ring.interpolate(float(s))
        a = ring.interpolate(float((s - eps) % total))
        b = ring.interpolate(float((s + eps) % total))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= max(np.linalg.norm(t), 1e-12)
        pts.append([q.x, q.y])
        tans.append(t)
    pts, tans = np.array(pts), np.array(tans)
    into = inward_normals(body, pts, tans)

    crest = (p.crest_deviation_center_mm
             + (p.crest_deviation_end_mm - p.crest_deviation_center_mm)
             * (au / run))
    rims = (unary_union([LineString(r) for r in body.interiors])
            if body.interiors else None)
    if rims is not None and not rims.is_empty:
        crest = np.minimum(crest, 0.8 * _distance(_points(pts), rims))
    crest = crest_inside(body, pts, into, np.maximum(crest, 0.0))

    tan_t = np.tan(np.radians(_splay_angles_deg(p, au, run)))
    feather = min(max(float(p.feather_mm), 0.0), run)
    if feather > 0.0:
        weight = np.where(
            au <= run - feather, 1.0,
            0.5 * (1.0 + np.cos(np.pi * (au - (run - feather)) / feather)))
    else:
        weight = np.ones_like(au)

    drops = np.maximum(crest * tan_t * weight, MIN_TAPER_DROP_MM)
    widths = np.maximum(crest, MIN_TAPER_DROP_MM)

    anchors = surface_z_at(mesh, pts + into * np.maximum(crest,
                                                         _RIM_PROBE_MM)[:, None])
    floor = float(p.anterior_clamp_mm)
    # No material at a station means nothing to splay. Anchoring at the clamp
    # collapses the section there; 0.0 would have cut the whole thickness away,
    # which is exactly the Gabriel failure.
    anchors = carry_anchors(anchors, floor)
    drops = np.clip(drops, MIN_TAPER_DROP_MM,
                    np.maximum(anchors - floor, MIN_TAPER_DROP_MM))
    top = float(np.nanmax(anchors)) + CUT_MARGIN_MM

    profiles = [
        _edge_profile(float(w), float(d), 0.0, "chamfer", True)
        + np.array([0.0, float(a)])
        for w, d, a in zip(widths, drops, anchors)
    ]
    return swept_profile(pts, into, profiles, top, closed=False)


def scoop_cutter(mesh, body: Polygon, p) -> Manifold:
    """The bridge relief as a lofted elliptical cone running on Y.

    Base widest and deepest at the top edge of the bridge on the centreline,
    tapering to a tip down the lower bridge. Sections are half-ellipses closed
    upward. Ordered around the section boundary — left to right along the
    ellipse, then the two corners at `top` — which is what `sweep_sections`
    needs to build the strip.
    """
    import math

    half_w = float(p.width_mm) / 2.0
    depth = float(p.depth_mm)
    if depth <= 0.0 or half_w <= 0.0:
        raise ManifoldError("degenerate bridge relief")
    tan_b = math.tan(math.radians(min(max(float(p.taper_angle_deg), 1.0), 89.0)))

    minx, miny, maxx, maxy = body.bounds
    centre = body.intersection(LineString([(0.0, miny - 1.0), (0.0, maxy + 1.0)]))
    if centre.is_empty:
        raise ManifoldError("no body on the centreline")
    y_base = max(g.bounds[3] for g in getattr(centre, "geoms", [centre]))
    y_tip = y_base - half_w / tan_b

    n = max(8, int((y_base - y_tip) * SCOOP_SECTIONS_PER_MM))
    ys = np.linspace(y_tip, y_base, n + 1)[1:]           # skip the exact apex
    rs = np.clip((ys - y_tip) * tan_b, 0.0, half_w)
    ds = depth * (rs / half_w)
    keep = rs > MIN_TAPER_DROP_MM
    ys, rs, ds = ys[keep], rs[keep], np.maximum(ds[keep], MIN_TAPER_DROP_MM)
    if len(ys) < 2:
        raise ManifoldError("bridge relief too small to loft")

    anchors = surface_z_at(mesh, np.column_stack([np.zeros_like(ys), ys]))
    floor = float(p.anterior_clamp_mm)
    anchors = carry_anchors(anchors, floor)
    ds = np.minimum(ds, np.maximum(anchors - floor, 0.0))
    ds = np.maximum(ds, MIN_TAPER_DROP_MM)
    top = float(anchors.max()) + CUT_MARGIN_MM

    xs = np.linspace(-1.0, 1.0, SCOOP_SECTION_POINTS)

    def section(y, r, d, a):
        px = xs * r
        pz = a - d * np.sqrt(np.maximum(1.0 - xs ** 2, 0.0))
        lower = np.column_stack([px, np.full_like(px, y), pz])
        return np.vstack([lower,
                          [[r, y, top], [-r, y, top]]])

    profiles = [section(float(y), float(r), float(d), float(a))
                for y, r, d, a in zip(ys, rs, ds, anchors)]
    # One prismatic station past the base, so the cone crosses the bridge wall
    # instead of ending tangent to it — the M-N0 defect, carried across as a
    # rule rather than as a bug to rediscover.
    profiles.append(section(float(ys[-1]) + CUT_MARGIN_MM, float(rs[-1]),
                            float(ds[-1]), float(anchors[-1])))
    return sweep_sections(profiles, closed=False)


def surface_feature_cutters(mesh, body: Polygon,
                            castle: CastleParams) -> list[Manifold]:
    """Pad splay and bridge relief.

    **These two read the surface each other leaves behind**, so on the B-Rep
    path they are cut one at a time: with the splay enabled the scoop's anchor
    rays land on material the splay has already removed, moving them by up to
    2.59 mm on the demo frame. The same is true here, and the caller applies
    them sequentially for the same reason — they are the one group that cannot
    be folded into a single pass.
    """
    out = []
    splay = getattr(castle, "pad_splay", None)
    if splay is not None and splay.enabled:
        out.append(("splay", splay))
    scoop = getattr(castle, "bridge_relief", None)
    if scoop is not None and scoop.enabled:
        out.append(("scoop", scoop))
    return out


def groove_cutters(partition, castle: CastleParams) -> list[Manifold]:
    """One V per lens aperture. Decorative OUTLINE holes are through-cuts and
    take no groove, so they keep their size.

    Takes no solid and fires no anchor ray — the V is positioned entirely from
    the partition, so unlike the surface features it never cares what has
    already been cut.
    """
    groove = getattr(castle, "lens_groove", None)
    if groove is None or not groove.enabled or groove.depth_mm <= 0:
        return []
    lip = partition.body
    return [v_groove_cutter(lip, ring, groove)
            for ring in lip.interiors if not partition.is_hole(ring)]
