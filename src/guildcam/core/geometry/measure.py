"""2D measurement helpers for the on-canvas measure tools (BUILDPLAN M7.13).

Pure geometry — no Qt — so the distance / angle / snap math is unit-testable apart
from the canvas. The maker uses these to verify a lens opening, the DBL (distance
between lenses), hinge spacing, or a corner angle before committing to a cut.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

Point = tuple[float, float]


def distance(a: Point, b: Point) -> float:
    """Euclidean distance between two points (same units in → out)."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def angle_at(a: Point, b: Point, c: Point) -> float:
    """Interior angle at vertex ``b`` (degrees, 0..180) for the corner a-b-c.

    Returns 0.0 if either arm has (near-)zero length, so a degenerate pick reads as
    an obvious 0° rather than raising.
    """
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(v1[0], v1[1])
    n2 = math.hypot(v2[0], v2[1])
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    cos = max(-1.0, min(1.0, cos))         # guard FP drift outside acos' domain
    return math.degrees(math.acos(cos))


def snap_to_vertices(click: Point, vertices: Iterable[Point],
                     tol: float) -> Optional[Point]:
    """The vertex nearest ``click`` within ``tol`` (same units), or None.

    Lets a click latch onto a real curve point so a measurement reads the drawn
    geometry rather than wherever the cursor happened to land.
    """
    best: Optional[Point] = None
    best_d = tol
    cx, cy = click
    for v in vertices:
        d = math.hypot(v[0] - cx, v[1] - cy)
        if d <= best_d:
            best_d = d
            best = v
    if best is None:
        return None
    return (float(best[0]), float(best[1]))
