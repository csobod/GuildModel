"""Arc fitting for toolpaths (BUILDPLAN M5 CAM quality).

Greedy least-squares circle fit that converts a linear 3D polyline into a
sequence of line and circular-arc moves. Arcs are fit in the XY plane (G17)
over runs whose Z is constant within tolerance; everything else stays linear.
The GRBL post uses this to emit smooth G2/G3 motion like Fusion, instead of
thousands of tiny G1 chords on the curved eyewire / footing passes.

A move is one of:
    ("line", (x, y, z))
    ("arc",  (x, y, z), (cx, cy), ccw)      # ccw: True -> G3, False -> G2
Each move *ends* at its point; the polyline's first point is the implicit start.
"""
from __future__ import annotations

import numpy as np

Point3 = tuple[float, float, float]


def _fit_circle(xy: np.ndarray) -> tuple[float, float, float, float]:
    """Kasa algebraic circle fit. Returns (cx, cy, R, max_radial_deviation)."""
    x, y = xy[:, 0], xy[:, 1]
    A = np.column_stack([x, y, np.ones(len(x))])
    b = x * x + y * y
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    R = float(np.sqrt(max(0.0, sol[2] + cx * cx + cy * cy)))
    dev = float(np.max(np.abs(np.hypot(x - cx, y - cy) - R))) if R > 0 else np.inf
    return cx, cy, R, dev


def _sweep_dir(xy: np.ndarray, cx: float, cy: float) -> int:
    """+1 (ccw) / -1 (cw) if the points sweep monotonically around the centre,
    else 0 (reverses direction — not a single arc)."""
    ang = np.arctan2(xy[:, 1] - cy, xy[:, 0] - cx)
    d = np.diff(ang)
    d = (d + np.pi) % (2 * np.pi) - np.pi      # wrap to (-pi, pi]
    if np.all(d > 1e-9):
        return 1
    if np.all(d < -1e-9):
        return -1
    return 0


def fit_arcs(
    points: list[Point3],
    tol_mm: float = 0.01,
    min_arc_pts: int = 5,
    min_radius_mm: float = 0.5,
    max_radius_mm: float = 300.0,
    z_tol_mm: float = 1e-3,
    max_window: int = 250,
) -> list[tuple]:
    """Convert a polyline into line / arc moves (see module docstring)."""
    pts = [(float(p[0]), float(p[1]), float(p[2])) for p in points]
    n = len(pts)
    if n < 2:
        return []
    P = np.asarray(pts, dtype=float)

    moves: list[tuple] = []
    i = 0
    while i < n - 1:
        best = None                       # (end_index, cx, cy, ccw)
        hi = min(n - 1, i + max_window)
        k = i + (min_arc_pts - 1)
        while k <= hi:
            seg = P[i:k + 1]
            if float(seg[:, 2].max() - seg[:, 2].min()) > z_tol_mm:
                break
            cx, cy, R, dev = _fit_circle(seg[:, :2])
            if dev > tol_mm or not (min_radius_mm <= R <= max_radius_mm):
                break
            d = _sweep_dir(seg[:, :2], cx, cy)
            if d == 0:
                break
            best = (k, cx, cy, d > 0)
            k += 1
        if best is not None:
            k, cx, cy, ccw = best
            moves.append(("arc", pts[k], (cx, cy), ccw))
            i = k
        else:
            moves.append(("line", pts[i + 1]))
            i += 1
    return moves
