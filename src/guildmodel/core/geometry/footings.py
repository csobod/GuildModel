"""SCULPT-cut placement shared by both model kernels (BUILDPLAN-NEW M-N1).

Where a footing blend sits along a zone seam, and which side of it is uphill.
Both `core/solid` (OpenCASCADE) and `core/model` (Manifold) sweep the same
S-profile through the same stations with the same orientation; only the sweep
itself differs.

Moved out of `core/solid/build.py` rather than copied, for the reason
`rings.py` gives: two copies of a placement rule become two rules. The
orientation vote especially — it took a real bug to get right, and a second
kernel quietly re-deriving it wrong is precisely what this port exists to catch
rather than to cause.

The *profile* is shared too, and was already: `_footing_spans` and `_footing_z`
live in `relief/castle.py` and all three paths — raster, B-Rep, mesh — call
them. So the only thing each kernel owns is the sweep.
"""
from __future__ import annotations

import numpy as np
from shapely.geometry import Point

from .regions import CastlePartition

__all__ = ["cut_stations", "orient_high_side"]


def cut_stations(cut_line, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Points and unit left-normals along a SCULPT cut, ends trimmed slightly.

    The cut lines are deliberately extended past the body (`_CUT_EXTEND_MM`) so
    they always sever it; sampling the very ends would fit the spine through
    points beyond anything that matters.
    """
    total = cut_line.length
    ss = np.linspace(0.02 * total, 0.98 * total, n)
    pts, perps = [], []
    for s in ss:
        p = cut_line.interpolate(float(s))
        a = cut_line.interpolate(float(max(0.0, s - 0.05)))
        b = cut_line.interpolate(float(min(total, s + 0.05)))
        t = np.array([b.x - a.x, b.y - a.y])
        t /= max(np.linalg.norm(t), 1e-12)
        pts.append([p.x, p.y])
        perps.append([-t[1], t[0]])
    return np.array(pts), np.array(perps)


def orient_high_side(partition: CastlePartition, pts: np.ndarray,
                     perps: np.ndarray, names: tuple[str, ...],
                     heights: dict[str, float], probe_mm: float = 0.2
                     ) -> np.ndarray:
    """Flip the normals so that -u is the HIGH terrace, matching `_footing_z`.

    Decided by asking which zone owns the ground either side, rather than by
    trusting the cut's direction — a SCULPT line's orientation is an artifact of
    how it was drawn.

    **Voted across every station, not probed once at the midpoint.** A single
    probe is wrong wherever that one point happens to land outside both
    neighbours — near a zone corner, or where the extended cut runs past the
    body — and getting it backwards is silent: the carve section is then built
    on the low side, clipping it to the high zone leaves nothing, and the step
    simply never gets blended. That showed up as 1,179 cells adrift in
    `nosepad_os` while `nosepad_od` had 11.
    """
    hi = names[0] if heights[names[0]] > heights[names[1]] else names[1]
    lo = names[1] if hi == names[0] else names[0]
    hi_poly, lo_poly = partition.zone(hi).polygon, partition.zone(lo).polygon

    votes = 0
    for p, pn in zip(pts, perps):
        minus, plus = Point(*(p - pn * probe_mm)), Point(*(p + pn * probe_mm))
        if hi_poly.contains(minus) or lo_poly.contains(plus):
            votes += 1
        elif hi_poly.contains(plus) or lo_poly.contains(minus):
            votes -= 1
    return perps if votes >= 0 else -perps
