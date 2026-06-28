"""Lens groove / bevel-flank generator.

Entry point:
  bevel_flank  — ruled two-flank bevel; port of OLGA olgaV5/courbes2 algorithm.

Z convention throughout: Z = 0 is the top surface of the stock blank,
Z < 0 goes into the material.  The caller is responsible for offsetting
to absolute machine coordinates before passing to the GRBL post.
"""
from __future__ import annotations

import numpy as np
import pyclipper
from shapely.geometry import Polygon

_SCALE = 1_000_000
_MITER_LIMIT = 1000.0   # sharp corners everywhere (OLGA uses an effectively infinite limit)


# ── geometry helpers ──────────────────────────────────────────────────────────

def _offset_ring(
    pts: list[tuple[float, float]],
    delta_mm: float,
) -> list[tuple[float, float]]:
    """Offset a closed ring by delta_mm.

    Negative delta shrinks a CCW (Shapely exterior) ring inward.
    Uses JT_MITER with a very high limit so corners stay sharp.
    """
    scaled = [[int(x * _SCALE), int(y * _SCALE)] for x, y in pts]
    pco = pyclipper.PyclipperOffset()
    pco.MiterLimit = _MITER_LIMIT
    pco.AddPath(scaled, pyclipper.JT_MITER, pyclipper.ET_CLOSEDPOLYGON)
    result = pco.Execute(int(delta_mm * _SCALE))
    if not result:
        return []
    return [(p[0] / _SCALE, p[1] / _SCALE) for p in result[0]]


def _resample(pts: list[tuple[float, float]], n: int) -> list[tuple[float, float]]:
    """Resample a closed ring to exactly n uniformly arc-length-spaced points."""
    arr = np.asarray(pts, dtype=float)
    arr_c = np.vstack([arr, arr[:1]])           # close: last == first
    segs = np.linalg.norm(np.diff(arr_c, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(segs)])
    total = cum[-1]
    if total < 1e-9:
        return [(float(arr[0, 0]), float(arr[0, 1]))] * n
    t = np.linspace(0.0, total, n, endpoint=False)
    xs = np.interp(t, cum, arr_c[:, 0])
    ys = np.interp(t, cum, arr_c[:, 1])
    return list(zip(xs.tolist(), ys.tolist()))


def _signed_area(pts: list[tuple[float, float]]) -> float:
    arr = np.asarray(pts, dtype=float)
    x, y = arr[:, 0], arr[:, 1]
    return float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) / 2.0


def _force_cw(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return pts reversed if they are CCW (positive signed area), i.e. force CW."""
    return pts[::-1] if _signed_area(pts) > 0 else list(pts)


def _align_start(
    ring: list[tuple[float, float]],
    reference: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Rotate ring so that index 0 is the point nearest to reference[0].

    Critical for ruled-surface correctness: without this the zig-zag between
    two co-planar rings twists unpredictably.  Port of OLGA split_at_segment().
    """
    ref = np.asarray(reference[0])
    arr = np.asarray(ring, dtype=float)
    idx = int(np.argmin(np.linalg.norm(arr - ref, axis=1)))
    return ring[idx:] + ring[:idx]


# ── public API ────────────────────────────────────────────────────────────────

def bevel_flank(
    lens_poly: Polygon,
    tool_dia_mm: float = 3.0,
    n: int = 500,
    side: str = "inner",
    z_a: float = 0.0,
    z_b: float = -2.0,
    flank_offset_mm: float = 3.0,
) -> list[tuple[float, float, float]]:
    """Ruled two-flank bevel toolpath for one lens opening.

    Port of OLGA olgaV5 button1_Click / decal1() / decal2().  The algorithm
    builds a ruled surface between two cutter-radius-compensated offset rings
    at two Z levels, producing the chamfer wall that seats the lens edge.

    Parameters
    ----------
    lens_poly      : Shapely Polygon of the lens opening (CCW, Shapely standard).
    tool_dia_mm    : cutter diameter (OLGA default 3.0 mm).
    n              : resample point count per ring (OLGA default 500).
    side           : "inner" → offset toward lens centre; "outer" → outward.
    z_a            : Z of ring_a (tool_dia/2 offset from rim).  0 = stock top.
    z_b            : Z of ring_b (further offset ring).  Negative = into material.
    flank_offset_mm: distance between the two flanks (OLGA default 3.0 mm).

    Returns
    -------
    Flat list of (x, y, z) tool-centre positions forming the ruled zig-zag.
    Pass directly to GRBLPost.emit_polyline().
    """
    sign = -1.0 if side == "inner" else 1.0
    exterior = list(lens_poly.exterior.coords[:-1])  # drop Shapely's closing duplicate

    ring_a = _offset_ring(exterior, sign * tool_dia_mm / 2.0)
    ring_b = _offset_ring(exterior, sign * (tool_dia_mm / 2.0 + flank_offset_mm))

    if not ring_a or not ring_b:
        return []

    ring_a = _resample(_force_cw(ring_a), n)
    ring_b = _resample(_force_cw(ring_b), n)
    ring_b = _align_start(ring_b, ring_a)

    out: list[tuple[float, float, float]] = []
    for (xa, ya), (xb, yb) in zip(ring_a, ring_b):
        out.append((xa, ya, z_a))
        out.append((xb, yb, z_b))
    return out


