"""Castle features as mesh bodies (BUILDPLAN-NEW M-N1).

The mesh-domain counterpart of `core/solid/features.py`. Same features, same
placement — the *where* comes from `core/geometry/rings.py`, shared by both
kernels — built as swept hull chains instead of lofted B-Rep sections.

**Why every sweep here is a chain of convex hulls.** The B-Rep path builds these
with `BRepOffsetAPI_ThruSections` and, where it tried them, `MakePipeShell`.
Both are where the season's worst failures came from: a bezel sweep that
produced a valid 4-face cutter whose *cut* took 260 s and returned negative
volume, a spine that took 401 s to fail, and the M-N0 tangency that left a
non-manifold edge. Hulling each consecutive pair of profiles cannot
self-intersect however tight the corner, and the union of the cells is a
manifold by construction. The spike measured the groove this way at 39 ms with
the undercut present at 40 of 40 stations.
"""
from __future__ import annotations

import numpy as np
from manifold3d import Manifold
from shapely.geometry import LineString, Polygon

from ..geometry.rings import inward_normals, ring_stations
from ..project.schema import CastleParams
from .kernel import hull_chain, surface_z_at, swept_profile

__all__ = ["bezel_cutter", "bezel_cutters", "edge_feature_cutters",
           "groove_cutters", "resolved_edge_cutters", "v_groove_cutter"]

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

    return hull_chain([profile(i) for i in range(stations)], closed=True)


#: Sections per millimetre along an edge-feature span. Matches the B-Rep path's
#: `EDGE_SECTIONS_PER_MM`, so both kernels sample the same run at the same
#: places and a volume difference is about the sweep rather than the sampling.
EDGE_SECTIONS_PER_MM = 1.2

#: The shallowest cut a taper is allowed to reach before it is simply zero.
MIN_TAPER_DROP_MM = 0.02


def _edge_profile(width: float, drop: float, radius: float, profile: str,
                  posterior: bool, n: int = 12) -> np.ndarray:
    """One edge-feature section as `(u, v)` offsets from the anchor.

    `u` runs from `-CUT_MARGIN_MM` (outside the edge, so the cutter crosses it
    rather than stopping on it) to `width`. `v` is signed relative to the
    anchor: down for a posterior feature, up for an anterior one, since the
    anterior face is just the underside of the same body.

    The chamfer is a straight ramp. The **fillet is concave** — see
    `kernel.swept_profile`, which is why edge features go through that rather
    than `hull_chain`.
    """
    us = np.linspace(0.0, width, n)
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
        # A miss means no material at that station. Anchoring it at `far` makes
        # the section collapse to nothing there, which removes nothing —
        # the safe reading. Never 0.0; see `kernel.surface_z_at`.
        anchors = np.where(np.isnan(anchors), far, anchors)

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

    anchors = surface_z_at(mesh, pts + into_wall * _RIM_PROBE_MM)
    # A ray that misses means there is no material at that station, so there is
    # nothing to chamfer; the clamp is the floor and the section collapses to a
    # sliver the boolean removes nothing with. Never 0.0 — see `surface_z_at`.
    anchors = np.where(np.isnan(anchors), clamp, anchors)

    drop = width * tan_a
    u0, u1 = -CUT_MARGIN_MM, width * _BEZEL_REACH

    def profile(i):
        p, n = pts[i % stations], into_wall[i % stations]
        rim_z = float(anchors[i % stations])
        v0 = max(rim_z - drop + u0 * tan_a, clamp)
        v1 = max(rim_z - drop + u1 * tan_a, clamp)
        a, b = p + n * u0, p + n * u1
        # Trapezoid in the (inward, Z) plane: the chamfer plane below, `top`
        # above. Convex, which is what `hull_chain` requires.
        return np.array([[a[0], a[1], v0], [b[0], b[1], v1],
                         [b[0], b[1], top], [a[0], a[1], top]])

    return hull_chain([profile(i) for i in range(stations)], closed=True)


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
