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
from shapely.geometry import LineString, Point

from .regions import CastlePartition

__all__ = ["CUT_LEAD_MM", "cut_stations", "orient_high_side"]

#: How far the stations run *past* each end of a SCULPT cut, mm.
#:
#: A footing band is a ribbon swept along the seam, so it has square ends, and
#: material in the corner just off an end is never carved. The raster has no
#: such notion — it carves by Euclidean distance to the seam, which rounds the
#: corner for free — so the two disagree exactly there, and both solid kernels
#: disagree with it identically.
#:
#: That is the sharp fin at the inferior nosepad, present since before UI-0
#: ("a visibly corrupt model — a spike of material off the nosepad") and never
#: caught by a gate, because the part is watertight, one body, and correct to
#: 0.04% on volume with it. Only an eye on the render found it.
#:
#: It bites where the fillet is large against the seam it runs along. Gabriel's
#: `nosepad_inferior` seam is **5.19 mm** long with **9.0 / 10.0 mm** fillet
#: radii — the blend reaches nearly twice as far as the seam is long — so the
#: uncarved corner came out as a 9 mm wedge tapering to a point. The demo's same
#: seam is 10.14 mm and shows nothing at all, which is why three drawings' worth
#: of parity gates all passed.
#:
#: **The length is the measured convergence point, and margin on top of it is
#: not free.** Lowest full-height cell in the nosepad zones, gabriel then
#: aviator, against the raster's own -4.747 / -7.016:
#:
#:     shipped (2%..98%)   -6.697 / -5.797     -8.366
#:     0.00 (the full cut) -5.947 / -5.797     -7.766
#:     0.25                -4.897 / -4.747     -7.016
#:     0.50                -4.597 / -4.747     -7.016   <- converged
#:     2.00                -4.597 / -4.747     -7.016
#:
#: 2 mm shipped first, on the reasoning that convergence plus margin costs
#: nothing because `build_base` clips every band to the zone it acts on. The
#: clip does bound where the blend lands, but not what the boolean has to
#: adjudicate on the way there: at 2 mm **OpenCASCADE stops building the
#: aviator** with the lens groove on — zero volume on two combinations and 320
#: self-overlapping edges on a third — while Manifold takes the same input
#: without complaint. The mesh kernel's tolerance for a longer band is not a
#: reason to spend length it does not need.
#:
#: A lead cannot round the cap; it only moves a square one out of the zone. The
#: exact fix is a round cap — the raster's Euclidean distance to a *segment* is
#: rounded at the ends by construction — which means fanning the profile about
#: the endpoint, and consecutive stations at the same point are the degenerate
#: case `kernel.sweep_sections` was rewritten to avoid. Convergence at 0.5 mm
#: says the square cap is clear of the zone by then, so the rounding it is
#: missing is rounding of empty space.
CUT_LEAD_MM = 0.5


def cut_stations(cut_line, n: int, lead_mm: float = CUT_LEAD_MM
                 ) -> tuple[np.ndarray, np.ndarray]:
    """Points and unit left-normals along a SCULPT cut, running past both ends.

    The cut lines are already extended past the body (`_CUT_EXTEND_MM`) so they
    always sever it, and this used to sample 2%..98% of that on the grounds that
    "sampling the very ends would fit the spine through points beyond anything
    that matters". It mattered: on a short seam that trim is a tenth of a
    millimetre, and a tenth of a millimetre of missing seam under a 9 mm blend
    is a 9 mm wedge of uncarved material. See `CUT_LEAD_MM`.

    So the stations now cover the whole cut and `lead_mm` beyond each end,
    extrapolated along the end tangents. Straight-line extrapolation is safe at
    this distance — the cut is a gentle spline and the lead is short — and a
    band that reaches past its zone is clipped back by the caller.
    """
    coords = list(cut_line.coords)
    if lead_mm > 0.0 and len(coords) >= 2:
        head, nxt = np.asarray(coords[0]), np.asarray(coords[1])
        tail, prv = np.asarray(coords[-1]), np.asarray(coords[-2])
        t_head = head - nxt
        t_tail = tail - prv
        t_head = t_head / max(np.linalg.norm(t_head), 1e-12)
        t_tail = t_tail / max(np.linalg.norm(t_tail), 1e-12)
        cut_line = LineString([tuple(head + t_head * lead_mm), *coords,
                               tuple(tail + t_tail * lead_mm)])

    total = cut_line.length
    ss = np.linspace(0.0, total, n)
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
