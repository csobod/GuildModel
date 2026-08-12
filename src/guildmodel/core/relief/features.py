"""Posterior finishing features (BUILDPLAN M13): min-carves into the footed castle.

Three maker features the castle itself doesn't model — the pad-splay chamfer
under the bridge (M13.1), the bezeled eyewire around each lens opening (M13.2),
and the bridge projection relief groove (M13.3). Each is OFF by default and
carves the relief grid AFTER the footing blends and BEFORE the surface snapshot
/ hinge pockets, so the fine relief pass machines it, the sim verifies it, and
the mesher shows it with no downstream changes.

Composition rule: every feature computes its target surface from the same
pre-carve snapshot and applies ``z = min(z, max(target, anterior_clamp))`` —
order-independent, overlapping features take the deepest cut without
compounding, and a carve can never raise material.

All geometry is constructed in world coordinates from the true shapely rings
(resolution-independent); the raster only samples it.
"""
from __future__ import annotations
from typing import Callable, Optional

import numpy as np
from shapely import distance, line_locate_point, points
from shapely.geometry import LineString, Point
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams, PadSplayParams

ProgressFn = Callable[[str, float], None]


def _sample_bilinear(zgrid: np.ndarray, x: np.ndarray, y: np.ndarray,
                     ox: float, oy: float, res: float) -> np.ndarray:
    """Bilinear sample of a heightfield grid at world points (clamped)."""
    rows, cols = zgrid.shape
    fc = np.clip((np.asarray(x, dtype=np.float64) - ox) / res, 0.0, cols - 1.0)
    fr = np.clip((np.asarray(y, dtype=np.float64) - oy) / res, 0.0, rows - 1.0)
    c0 = np.clip(np.floor(fc).astype(int), 0, cols - 2) if cols > 1 else np.zeros_like(fc, dtype=int)
    r0 = np.clip(np.floor(fr).astype(int), 0, rows - 2) if rows > 1 else np.zeros_like(fr, dtype=int)
    tc, tr = fc - c0, fr - r0
    z00 = zgrid[r0, c0]
    z01 = zgrid[r0, np.minimum(c0 + 1, cols - 1)]
    z10 = zgrid[np.minimum(r0 + 1, rows - 1), c0]
    z11 = zgrid[np.minimum(r0 + 1, rows - 1), np.minimum(c0 + 1, cols - 1)]
    return (z00 * (1 - tr) * (1 - tc) + z01 * (1 - tr) * tc
            + z10 * tr * (1 - tc) + z11 * tr * tc)


def _window(pts_xy: np.ndarray, pad: float, ox: float, oy: float, res: float,
            rows: int, cols: int) -> tuple[int, int, int, int]:
    """Grid index window covering the world-coordinate points grown by pad."""
    xmin, ymin = pts_xy.min(axis=0) - pad
    xmax, ymax = pts_xy.max(axis=0) + pad
    c0 = int(np.clip(np.floor((xmin - ox) / res), 0, cols))
    c1 = int(np.clip(np.ceil((xmax - ox) / res) + 1, 0, cols))
    r0 = int(np.clip(np.floor((ymin - oy) / res), 0, rows))
    r1 = int(np.clip(np.ceil((ymax - oy) / res) + 1, 0, rows))
    return r0, r1, c0, c1


# ------------------------------------------------------------------ pad splay

def _splay_angles_deg(p: PadSplayParams, au: np.ndarray, run: float) -> np.ndarray:
    """Splay angle at each |u| along the run: constant, or the toric blend
    through the center / half-run / run-end angles (PCHIP: shape-preserving,
    no overshoot when the middle angle is not between the ends)."""
    if not p.toric:
        return np.full_like(au, p.angle_center_deg)
    from scipy.interpolate import PchipInterpolator
    knots_u = np.array([0.0, run / 2.0, run])
    knots_a = np.array([p.angle_center_deg, p.angle_middle_deg, p.angle_end_deg])
    return PchipInterpolator(knots_u, knots_a)(np.clip(au, 0.0, run))


def _bottom_center_station(body) -> tuple:
    """(ring, length, station) of the outline's bottom-center point: the LOWEST
    crossing of the centerline x=0 (the bridge straddles x=0 in posterior
    coords) — on a frame front that is the nose-arch apex, the bridge underside
    the pad splay sits on. Nearest-point fallback for shapes that don't cross."""
    ring = orient(body, 1.0).exterior          # CCW => inward normal = left normal
    minx, miny, maxx, maxy = body.bounds
    centerline = LineString([(0.0, miny - 1.0), (0.0, maxy + 1.0)])
    hit = ring.intersection(centerline)
    if hit.is_empty:
        s0 = float(line_locate_point(ring, Point(0.0, miny)))
    else:
        pts = getattr(hit, "geoms", [hit])
        low = min(pts, key=lambda g: g.bounds[1])
        s0 = float(line_locate_point(ring, Point(low.coords[0][:2])))
    return ring, ring.length, s0


def default_splay_run_mm(partition: CastlePartition,
                         extra_mm: float = 5.0) -> float | None:
    """The maker's default splay run: from the outline's bottom-center to just
    past the LOWER NOSEPAD SCULPT line (user rule 2026-07-02: +5 mm). Measured
    as arc length along the outline to where each `nosepad_inferior_*` cut
    crosses it (max of OD/OS for asymmetric frames). None when the partition
    has no matched nosepad-inferior edges (caller keeps its own default)."""
    ring, L, s0 = _bottom_center_station(partition.body)
    best = None
    for edge in partition.edges:
        if not (edge.canonical or "").startswith("nosepad_inferior"):
            continue
        hit = ring.intersection(edge.cut)
        if hit.is_empty:
            continue
        pts = getattr(hit, "geoms", [hit])
        for g in pts:
            s = float(line_locate_point(ring, Point(g.coords[0][:2])))
            u = abs((s - s0 + L / 2.0) % L - L / 2.0)
            best = u if best is None else max(best, u)
    return None if best is None else best + extra_mm


def _rounded_chamfer_drop(g: np.ndarray, tan_t: np.ndarray,
                          blend_r: float) -> np.ndarray:
    """Depth of a crest-blended chamfer at signed distance g inside the crest
    (g > 0 toward the outline). A convex round-over of radius `blend_r`
    replaces the crest corner — tangent to the surface on one side and to the
    splay plane on the other (C1, footing-style: the M13 hard ridge shaded as
    a jagged pixellated crease). blend_r = 0 keeps the sharp chamfer."""
    if blend_r <= 0.0:
        return np.maximum(g, 0.0) * tan_t
    sec_t = np.sqrt(1.0 + tan_t**2)
    safe_tan = np.maximum(tan_t, 1e-9)
    g0 = blend_r * (1.0 - sec_t) / safe_tan     # arc start (inside the crest, <0)
    g1 = g0 + blend_r * tan_t / sec_t           # arc->plane tangency (= g0 + R sin)
    arc = blend_r - np.sqrt(np.maximum(blend_r**2 - (g - g0) ** 2, 0.0))
    return np.where(g > g1, g * tan_t, np.where(g > g0, arc, 0.0))


def _slope_limit(vals: np.ndarray, du: float, max_slope: float) -> np.ndarray:
    """Cap a table's rate of change by min-propagation in both directions:
    a clamp/bisection notch spreads into a gentle dip instead of a tooth.
    Values only ever decrease (staying on the safe side of every clamp)."""
    out = np.asarray(vals, dtype=np.float64).copy()
    step = max_slope * du
    for i in range(1, out.size):
        out[i] = min(out[i], out[i - 1] + step)
    for i in range(out.size - 2, -1, -1):
        out[i] = min(out[i], out[i + 1] + step)
    return out


_CREST_MAX_SLOPE = 0.5   # mm of crest offset per mm of run — teeth get flattened


def splay_spans(p: PadSplayParams, run: float) -> list[tuple[float, float]]:
    """The station intervals the splay covers, clipped to the achievable `run`.

    `PadSplayParams.spans` works from the *requested* run; the carvers clip that
    to a fraction of the outline's length first, so the gap has to be re-applied
    against the run actually in use or a non-contiguous splay on a small frame
    would come out with its halves in the wrong place.
    """
    if not p.non_contiguous:
        return [(-run, run)]
    half = float(p.gap_mm) / 2.0
    if half >= run:
        return []
    return [(-run, -half), (half, run)]


def splay_weight(u: np.ndarray, spans: list[tuple[float, float]],
                 feather: float) -> np.ndarray:
    """Section weight at each signed station: 1 inside a span, raised-cosine down
    to 0 over `feather` mm at **every** end of every span, 0 outside them all.

    The ends of a non-contiguous splay's inner edges are ends like any other, and
    they are the ones that face the maker across the keyhole. Feathering them
    identically is what stops the cut terminating in a wall there.

    **It LIFTS the chamfer, it does not flatten it.** Every caller adds
    `(1 - w) * full_depth` to the anchor and then cuts at full width and full
    angle, so the plane rises out of the material and the cut runs out because
    there is nothing left under it.

    Scaling the *drop* was the 2026-08-12 report ("a very abrupt end leaving
    sharp material no matter what I do"). It took the chamfer's angle to zero
    while its width stayed at the full crest, so the last millimetres of the run
    were a flat shelf planed at the crest's own anchor height — and then stopped
    dead at the station the sweep ended on. Nobody saw it in the contiguous case
    because `crest_deviation_end_mm` already tapers the crest toward each *outer*
    run end, so the width was running out there for an unrelated reason. A
    non-contiguous splay's inner ends sit at full crest: 7.5 mm of shelf on the
    reported frame.

    **Scaling the crest instead was the obvious repair, and it is worse.** It
    does give the right surface — the section shrinks self-similarly, the angle
    is kept, the cut narrows to a point — but it drives the tool through the
    boolean sideways. The crest edge sweeps inward by its whole width over a few
    millimetres of run while the section collapses toward zero size, and Manifold
    starts shedding collinear sliver triangles where the cut crosses the nosepad
    footing: **14 of 27** gap/feather settings around the maker's came back
    non-watertight, always one triangle a twentieth of a millimetre across, and
    always in the same place. A width floor, a crest lead, four station densities
    and `Manifold.simplify` each moved which settings failed without fixing any
    of them — `simplify` severed the part into three pieces at 0.01 mm.

    Lifting asks for none of that. Every section stays full size and the cutter
    only translates in Z, so the run-out is a plane sliding out of a surface —
    the best-conditioned thing a boolean can be handed — and the cut boundary it
    leaves is the intersection curve of the two, which is exactly the shape a
    hand-cut run-out has.
    """
    w = np.zeros_like(np.asarray(u, dtype=float))
    for lo, hi in spans:
        within = (u >= lo) & (u <= hi)
        if not within.any():
            continue
        # Clipped to half the span so the two feathers meet at the middle at
        # full depth instead of overlapping into a run that never reaches it.
        f = min(max(float(feather), 0.0), (hi - lo) / 2.0)
        edge = np.minimum(u - lo, hi - u)
        ramp = (0.5 * (1.0 - np.cos(np.pi * np.clip(edge / f, 0.0, 1.0)))
                if f > 0.0 else np.ones_like(w))
        w = np.maximum(w, np.where(within, ramp, 0.0))
    return w


def _splay_crest_tables(body, z_pre, inside, ox, oy, res, p: PadSplayParams):
    """The pad splay's 1-D crest tables over the signed station u in
    [-run, run]. Returns None when the splay is degenerate.

    Smoothness matters more than per-sample exactness here (2026-07-02 field
    finding: 'jagged points where the cut terminates'): the lens-rim clamp and
    the in-body bisection are per-sample and left tooth-like steps in the
    crest line, outline-polyline noise rippled the finite-difference normals,
    and — the deep teeth — crest anchor heights bilinear-sampled next to the
    body boundary blended in the outside-body zeros. So: wide-baseline
    smoothed normals, slope-limited crest offsets, anchor heights sampled from
    an EDT-filled surface (nearest INSIDE height) and lightly smoothed."""
    from scipy.ndimage import distance_transform_edt, uniform_filter1d

    ring, L, s0 = _bottom_center_station(body)
    run = min(p.run_mm, 0.45 * L)
    if run <= res or p.crest_deviation_center_mm <= 0.0:
        return None
    spans = splay_spans(p, run)
    if not spans:
        return None                 # the gap has swallowed the whole run

    n = max(9, int(np.ceil(2.0 * run / res)) + 1)
    step = 2.0 * run / (n - 1)
    u_tab = np.linspace(-run, run, n)
    au_tab = np.abs(u_tab)
    stations = np.mod(s0 + u_tab, L)
    p0 = np.array([ring.interpolate(float(s)).coords[0][:2] for s in stations])

    # Tangents over a wide baseline + vector smoothing: a noisy outline
    # polyline otherwise wiggles the normals and ripples the crest.
    eps = max(3.0 * res, 0.75)
    p_fwd = np.array([ring.interpolate(float((s + eps) % L)).coords[0][:2] for s in stations])
    p_bck = np.array([ring.interpolate(float((s - eps) % L)).coords[0][:2] for s in stations])
    tang = p_fwd - p_bck
    smooth = max(3, int(round(1.5 / step)))
    tang = uniform_filter1d(tang, size=smooth, axis=0, mode="nearest")
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-12)
    normal = np.column_stack([-tang[:, 1], tang[:, 0]])   # left of travel = inward (CCW)
    probe = p0[n // 2] + normal[n // 2] * (2.0 * res)
    if not body.contains(Point(probe)):
        normal = -normal

    # Crest deviation center -> end, kept off the lens rims (nosepad-width
    # guard) and inside the body (concave outlines) — then slope-limited.
    c_tab = (p.crest_deviation_center_mm
             + (p.crest_deviation_end_mm - p.crest_deviation_center_mm)
             * (au_tab / run))
    rims = unary_union([LineString(r) for r in body.interiors]) if body.interiors else None
    if rims is not None and not rims.is_empty:
        clearance = distance(points(p0), rims)
        c_tab = np.minimum(c_tab, 0.8 * clearance)
    c_tab = _slope_limit(np.maximum(c_tab, 0.0), step, _CREST_MAX_SLOPE)
    crest = p0 + normal * c_tab[:, None]
    bisected = False
    for i in range(n):
        while c_tab[i] > res and not body.contains(Point(crest[i])):
            c_tab[i] *= 0.5
            crest[i] = p0[i] + normal[i] * c_tab[i]
            bisected = True
    if bisected:
        c_tab = _slope_limit(c_tab, step, _CREST_MAX_SLOPE)
        crest = p0 + normal * c_tab[:, None]

    w_tab = splay_weight(u_tab, spans, p.feather_mm)

    # Anchor heights from the nearest-INSIDE surface (outside cells hold 0 at
    # carve time — bilinear next to the rim would crater the crest), smoothed.
    _, (iy, ix) = distance_transform_edt(~inside, return_indices=True)
    z_fill = z_pre[iy, ix]
    h_tab = _sample_bilinear(z_fill, crest[:, 0], crest[:, 1], ox, oy, res)
    h_tab = uniform_filter1d(h_tab, size=max(3, int(round(2.0 / step))),
                             mode="nearest")

    # Surface height just inside the OUTLINE, sampled and smoothed exactly as the
    # crest's is. The feather needs it: see `_carve_pad_splay`.
    rim_tab = _sample_bilinear(z_fill, p0[:, 0] + normal[:, 0] * res,
                               p0[:, 1] + normal[:, 1] * res, ox, oy, res)
    rim_tab = uniform_filter1d(rim_tab, size=max(3, int(round(2.0 / step))),
                               mode="nearest")

    tan_tab = np.tan(np.radians(_splay_angles_deg(p, au_tab, run)))
    return run, u_tab, p0, crest, c_tab, h_tab, tan_tab, w_tab, rim_tab


def _carve_pad_splay(
    z: np.ndarray, z_pre: np.ndarray, body,
    inside: np.ndarray, ox: float, oy: float, res: float, p: PadSplayParams,
) -> np.ndarray:
    """Chamfer under the bridge: crest = inward offset of the OUTLINE around its
    bottom-center; surface falls crest -> outline at the (possibly toric) splay
    angle through a tangent crest round-over, feathered at the run ends,
    floored at the anterior clamp."""
    rows, cols = z.shape
    tables = _splay_crest_tables(body, z_pre, inside, ox, oy, res, p)
    if tables is None:
        return np.zeros_like(inside)
    run, u_tab, p0, crest, c_tab, h_tab, tan_tab, w_tab, rim_tab = tables
    # The feather LIFTS the chamfer plane out of the surface instead of
    # flattening it — see `splay_weight`. Two terms, both needed: `c_tab *
    # tan_tab` is how far the plane falls between the crest and the rim, so it
    # clears the crest end; `rim_tab - h_tab` is how far the surface has climbed
    # back up under the low one. Without the second, a frame whose bridge rises
    # toward the outline is still cut a millimetre deep at a station whose weight
    # has all but run out, and the run-out reads from outside as the shelf it
    # replaced.
    h_tab = h_tab + (1.0 - w_tab) * (c_tab * tan_tab
                                     + np.maximum(0.0, rim_tab - h_tab))

    # ---- Raster: distance + station against the WINDOWED bottom-edge
    # polyline (not the whole ring — on a thin bridge strip the nearest whole-
    # ring point flips to the top edge past the strip midline, which would
    # truncate the chamfer with a wall instead of running it to the crest).
    wline = LineString(p0)
    w_station = np.concatenate([[0.0], np.cumsum(
        np.linalg.norm(np.diff(p0, axis=0), axis=1))])
    blend_r = max(p.crest_blend_mm, 0.0)
    r0, r1, c0, c1 = _window(np.vstack([p0, crest]),
                             c_tab.max() + blend_r + 2 * res,
                             ox, oy, res, rows, cols)
    sub_inside = inside[r0:r1, c0:c1]
    if not sub_inside.any():
        return np.zeros_like(inside)
    sub_x = ox + (c0 + np.arange(c1 - c0)) * res
    sub_y = oy + (r0 + np.arange(r1 - r0)) * res
    SX, SY = np.meshgrid(sub_x, sub_y)
    cand = sub_inside.ravel()
    pts = points(SX.ravel()[cand], SY.ravel()[cand])
    d = distance(pts, wline)
    u = np.interp(line_locate_point(wline, pts), w_station, u_tab)

    cu = np.interp(u, u_tab, c_tab)
    g = cu - d                                  # distance inside the crest
    weight = np.interp(u, u_tab, w_tab)
    # The round-over begins a little beyond the crest (g slightly negative), so
    # the selection reaches past it; drop() is zero there and min() is a no-op.
    # A zero weight is a station outside every span — the run ends, and the
    # keyhole gap of a non-contiguous splay — where the anchor height must not
    # be applied as a target at all.
    sel = (weight > 0.0) & (g > -blend_r)
    if not sel.any():
        return np.zeros_like(inside)
    drop = _rounded_chamfer_drop(g, np.interp(u, u_tab, tan_tab), blend_r)
    # `h_tab` already carries the feather as a lift, so the plane rises out of
    # the material on its own; multiplying the drop by the weight as well would
    # flatten the chamfer at the same time and is what left the shelf.
    # `weight` survives only in `sel`, as the span mask.
    target = np.interp(u, u_tab, h_tab) - drop
    target = np.maximum(target, p.anterior_clamp_mm)

    zsub = z[r0:r1, c0:c1].ravel().copy()
    idx = np.flatnonzero(cand)[sel]
    lowered = target[sel] < zsub[idx] - 1e-12
    zsub[idx[lowered]] = target[sel][lowered]
    z[r0:r1, c0:c1] = zsub.reshape(r1 - r0, c1 - c0)

    band = np.zeros_like(inside)
    bflat = band[r0:r1, c0:c1].ravel()
    bflat[idx[lowered]] = True
    band[r0:r1, c0:c1] = bflat.reshape(r1 - r0, c1 - c0)
    return band


# ------------------------------------------------------------------ eyewire bezel

def _carve_eyewire_bezel(
    z: np.ndarray, z_pre: np.ndarray, body,
    inside: np.ndarray, ox: float, oy: float, res: float, p,
) -> np.ndarray:
    """Constant-width chamfer band around each lens opening's posterior rim.

    Anchored to the local pre-carve surface: the drop is zero at the band's
    inner edge and width*tan(angle) at the rim, so the band keeps constant
    width and rim depth all the way round and rides the footing swells."""
    rows, cols = z.shape
    band = np.zeros_like(inside)
    width = p.width_mm
    if width <= 0.0:
        return band
    tan_a = float(np.tan(np.radians(p.angle_deg)))
    for interior in body.interiors:
        ring = LineString(interior)
        ring_xy = np.asarray(interior.coords)[:, :2]
        r0, r1, c0, c1 = _window(ring_xy, width + 2 * res, ox, oy, res, rows, cols)
        sub_inside = inside[r0:r1, c0:c1]
        if not sub_inside.any():
            continue
        sub_x = ox + (c0 + np.arange(c1 - c0)) * res
        sub_y = oy + (r0 + np.arange(r1 - r0)) * res
        SX, SY = np.meshgrid(sub_x, sub_y)
        cand = sub_inside.ravel()
        pts = points(SX.ravel()[cand], SY.ravel()[cand])
        d = distance(pts, ring)
        sel = d < width
        if not sel.any():
            continue
        zsub = z[r0:r1, c0:c1].ravel().copy()
        pre = z_pre[r0:r1, c0:c1].ravel()
        idx = np.flatnonzero(cand)[sel]
        target = np.maximum(pre[idx] - (width - d[sel]) * tan_a,
                            p.anterior_clamp_mm)
        lowered = target < zsub[idx] - 1e-12
        zsub[idx[lowered]] = target[lowered]
        z[r0:r1, c0:c1] = zsub.reshape(r1 - r0, c1 - c0)
        bflat = band[r0:r1, c0:c1].ravel()
        bflat[idx[lowered]] = True
        band[r0:r1, c0:c1] = bflat.reshape(r1 - r0, c1 - c0)
    return band


# ------------------------------------------------------------------ bridge relief

def _carve_bridge_relief(
    z: np.ndarray, z_pre: np.ndarray,
    inside: np.ndarray, ox: float, oy: float, res: float, p,
) -> np.ndarray:
    """Conic scoop on the posterior bridge, running on Y: the base (width
    `width_mm`, depth `depth_mm`) opens through the top edge of the frame at
    the centerline; the sides taper at `taper_angle_deg` per side down to a
    rounded tip on the lower bridge. At each station y the cut is the U section
    `geometry.blends.scoop_drop` builds — an exterior round-over at the rim, an
    interior fillet at the trough, a straight ramp between — and the center
    depth scales with the local half-width (a true cone imprint), so the whole
    scoop stays C1 against the footed surface: no creases, no polygon facets."""
    from ..geometry.blends import scoop_drop

    rows, cols = z.shape
    band = np.zeros_like(inside)
    half_w = p.width_mm / 2.0
    tan_b = float(np.tan(np.radians(min(max(p.taper_angle_deg, 1.0), 89.0))))
    if p.depth_mm <= 0.0 or half_w <= res:
        return band

    # Base = the top edge of the bridge strip on the centerline column; the
    # scoop descends from there, tip at y_base - half_w/tan(taper).
    col0 = int(np.clip(round((0.0 - ox) / res), 0, cols - 1))
    strip_rows = np.flatnonzero(inside[:, col0])
    if strip_rows.size == 0:
        return band                            # no body on the centerline
    y_base = oy + strip_rows.max() * res
    y_tip = y_base - half_w / tan_b

    ys = oy + np.arange(rows) * res
    r_col = np.clip((ys - y_tip) * tan_b, 0.0, half_w)   # half-width at each y
    xs = ox + np.arange(cols) * res
    R = r_col[:, None]
    X = np.abs(xs)[None, :]
    mask = inside & (R > res) & (X < R)
    if not mask.any():
        return band

    d_col = p.depth_mm * (r_col / half_w)                # cone: depth ~ width
    drop = scoop_drop(X, np.maximum(R, 1e-9), np.maximum(d_col[:, None], 1e-9),
                      p.exterior_radius_mm, p.interior_radius_mm)
    target = np.maximum(z_pre - drop, p.anterior_clamp_mm)
    lowered = mask & (target < z - 1e-12)
    z[lowered] = target[lowered]
    band[lowered] = True
    return band


# ------------------------------------------------------------------ dispatcher

def apply_posterior_features(
    z: np.ndarray,
    partition: CastlePartition,
    castle: CastleParams,
    inside: np.ndarray,
    ox: float, oy: float,
    resolution: float,
    progress: Optional[ProgressFn] = None,
) -> tuple[np.ndarray | None, float]:
    """Carve every enabled posterior feature into ``z`` in place.

    Returns ``(feature_band, max_slope_deg)`` — the bool mask of carved cells
    (for the CAM feature-finish band) and the steepest enabled feature angle.
    When every feature is disabled, returns ``(None, 0.0)`` and ``z`` is not
    touched at all (bit-identical fast path for the M2/M3/M4 gates).
    """
    splay = castle.pad_splay
    bezel = castle.eyewire_bezel
    groove = castle.bridge_relief
    # `cuts_posterior()` rather than `enabled` (M17): the bezel can now be aimed
    # at the front face, and an anterior-only bezel must leave the back alone.
    if not (splay.enabled or bezel.cuts_posterior() or groove.enabled):
        return None, 0.0

    z_pre = z.copy()
    band = np.zeros_like(inside)
    max_slope = 0.0
    if splay.enabled:
        if progress is not None:
            progress("Pad splay", 0.86)
        band |= _carve_pad_splay(z, z_pre, partition.body, inside,
                                 ox, oy, resolution, splay)
        angles = ((splay.angle_center_deg, splay.angle_middle_deg,
                   splay.angle_end_deg) if splay.toric
                  else (splay.angle_center_deg,))
        max_slope = max(max_slope, *angles)
    if bezel.cuts_posterior():
        if progress is not None:
            progress("Eyewire bezel", 0.87)
        band |= _carve_eyewire_bezel(z, z_pre, partition.body, inside,
                                     ox, oy, resolution, bezel)
        max_slope = max(max_slope, bezel.angle_deg)
    if groove.enabled:
        if progress is not None:
            progress("Bridge relief", 0.88)
        gb = _carve_bridge_relief(z, z_pre, inside, ox, oy, resolution, groove)
        band |= gb
        if gb.any():
            # The U's straight ramp — see `BridgeReliefParams.max_slope_deg`.
            max_slope = max(max_slope, groove.max_slope_deg())
    band[~inside] = False
    return (band if band.any() else None), max_slope
