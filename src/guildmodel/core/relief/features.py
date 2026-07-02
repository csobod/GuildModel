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


def _carve_pad_splay(
    z: np.ndarray, z_pre: np.ndarray, body,
    inside: np.ndarray, ox: float, oy: float, res: float, p: PadSplayParams,
) -> np.ndarray:
    """Chamfer under the bridge: crest = inward offset of the OUTLINE around its
    bottom-center; surface falls crest -> outline at the (possibly toric) splay
    angle, feathered at the run ends, floored at the anterior clamp."""
    rows, cols = z.shape
    ring = orient(body, 1.0).exterior          # CCW => inward normal = left normal
    L = ring.length
    run = min(p.run_mm, 0.45 * L)
    if run <= res or p.crest_deviation_center_mm <= 0.0:
        return np.zeros_like(inside)

    # Bottom-center of the outline: the LOWEST crossing of the centerline x=0
    # (the bridge straddles x=0 in posterior coords) — on a frame front that is
    # the nose-arch apex, the bridge underside the pad splay sits on. Nearest-
    # point fallback for shapes that don't cross the centerline.
    minx, miny, maxx, maxy = body.bounds
    centerline = LineString([(0.0, miny - 1.0), (0.0, maxy + 1.0)])
    hit = ring.intersection(centerline)
    if hit.is_empty:
        s0 = float(line_locate_point(ring, Point(0.0, miny)))
    else:
        pts = getattr(hit, "geoms", [hit])
        low = min(pts, key=lambda g: g.bounds[1])
        s0 = float(line_locate_point(ring, Point(low.coords[0][:2])))

    # ---- 1D crest tables over the signed station u in [-run, run] ----
    n = max(9, int(np.ceil(2.0 * run / res)) + 1)
    u_tab = np.linspace(-run, run, n)
    au_tab = np.abs(u_tab)
    stations = np.mod(s0 + u_tab, L)
    p0 = np.array([ring.interpolate(float(s)).coords[0][:2] for s in stations])
    eps = max(res, 1e-3)
    p_fwd = np.array([ring.interpolate(float((s + eps) % L)).coords[0][:2] for s in stations])
    p_bck = np.array([ring.interpolate(float((s - eps) % L)).coords[0][:2] for s in stations])
    tang = p_fwd - p_bck
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-12)
    normal = np.column_stack([-tang[:, 1], tang[:, 0]])   # left of travel = inward (CCW)
    probe = p0[n // 2] + normal[n // 2] * (2.0 * res)
    if not body.contains(Point(probe)):
        normal = -normal

    # Crest deviation center -> end, kept off the lens rims (nosepad-width
    # guard) and inside the body (concave outlines).
    c_tab = (p.crest_deviation_center_mm
             + (p.crest_deviation_end_mm - p.crest_deviation_center_mm)
             * (au_tab / run))
    rims = unary_union([LineString(r) for r in body.interiors]) if body.interiors else None
    if rims is not None and not rims.is_empty:
        clearance = distance(points(p0), rims)
        c_tab = np.minimum(c_tab, 0.8 * clearance)
    c_tab = np.maximum(c_tab, 0.0)
    crest = p0 + normal * c_tab[:, None]
    for i in range(n):
        while c_tab[i] > res and not body.contains(Point(crest[i])):
            c_tab[i] *= 0.5
            crest[i] = p0[i] + normal[i] * c_tab[i]

    h_tab = _sample_bilinear(z_pre, crest[:, 0], crest[:, 1], ox, oy, res)
    tan_tab = np.tan(np.radians(_splay_angles_deg(p, au_tab, run)))
    feather = min(max(p.feather_mm, 0.0), run)
    if feather > 0.0:
        w_tab = np.where(
            au_tab <= run - feather, 1.0,
            0.5 * (1.0 + np.cos(np.pi * (au_tab - (run - feather)) / feather)))
    else:
        w_tab = np.ones_like(au_tab)

    # ---- Raster: distance + station against the WINDOWED bottom-edge
    # polyline (not the whole ring — on a thin bridge strip the nearest whole-
    # ring point flips to the top edge past the strip midline, which would
    # truncate the chamfer with a wall instead of running it to the crest).
    wline = LineString(p0)
    w_station = np.concatenate([[0.0], np.cumsum(
        np.linalg.norm(np.diff(p0, axis=0), axis=1))])
    r0, r1, c0, c1 = _window(np.vstack([p0, crest]), c_tab.max() + 2 * res,
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
    sel = (np.abs(u) <= run) & (d < cu)
    if not sel.any():
        return np.zeros_like(inside)
    target = (np.interp(u, u_tab, h_tab)
              - (cu - d) * np.interp(u, u_tab, tan_tab) * np.interp(u, u_tab, w_tab))
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
    if not (splay.enabled or bezel.enabled or groove.enabled):
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
    band[~inside] = False
    return (band if band.any() else None), max_slope
