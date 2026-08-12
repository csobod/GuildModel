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

__all__ = ["CAP_CROSS_MM", "CUT_LEAD_MM", "cap_leads", "cut_stations",
           "orient_high_side"]

#: The FLOOR on how far the stations run past each end of a SCULPT cut, mm.
#:
#: `cap_leads` computes the lead each end actually needs from the geometry and
#: this is the least it will ever ask for. It was the whole answer until
#: 2026-08-12; the note below is why one number could never have been.
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
#:
#: **All of which was true, and 0.5 mm was still the wrong number — because
#: "clear of the zone" is a property of the frame, not a constant.** Reported
#: 2026-08-10 as a spike of material at the nosepad "across many frames", with
#: two drawings attached; the Calasanz builds a 2.4 mm fin at the nose notch on
#: the mesh kernel, which since M-N3 is also the surface the CAM posts from.
#:
#: The convergence table above is real and was measured honestly. What it could
#: not see is the meter it was read on: the lowest full-height cell in a nosepad
#: *zone*, on three fixtures. It converges at 0.5 mm because past that the cap
#: has left the part of the zone that meter looks at — not because the cap has
#: left the zone. Where the outline flares away from the seam's end (a nose
#: notch, a keyhole bridge) the zone reaches back under a cap that has already
#: passed it, and no constant covers that: `cap_leads` measures **every one of
#: the repo's own fixtures short**, demo included.
#:
#:     required lead, worst end   demo 1.14   gabriel 0.85   aviator 1.76
#:                                calasanz 2.00   aquinas 0.95
#:
#: So the lead is computed per end — and per *band* — from the zone it has to
#: clear, and this is the floor under it. Most ends still get exactly this.
#:
#: **Two things keep that affordable, and OpenCASCADE measures both.** The 2 mm
#: that broke it was 2 mm on every end of every seam; a lead spent only where it
#: is needed is a different animal. But "needed" has to be read correctly, and
#: the first attempt read it two ways too generously:
#:
#: * one lead per *seam*, the longer of the carve's and the raise's. Their zones
#:   and reaches differ by a factor of four on a nosepad, so each band was being
#:   dragged out over the other's ground;
#: * measured to `_footing_spans`, which is where the blend touches down
#:   *tangentially* — its last millimetres are flat to within microns, and
#:   chasing them cost the aviator 2.6 mm to cover nothing. `_footing_reach` and
#:   `FOOTING_FLAT_TOL_MM` ask how far the blend is genuinely not the terrace.
#:
#: With both, the worst lead on any fixture is 1.5 mm and every combination in
#: the parity gates closes on both kernels. `CAP_CROSS_MM` then has a valid band
#: from 0.05 to 0.75 mm rather than a knife edge, which is the difference between
#: a rule and a tuning.
CUT_LEAD_MM = 0.5

#: How far past the last material it would leave standing the cap is pushed, mm.
#:
#: The project's one rule about tools and surfaces, applied to a band's end: a
#: cap that lands exactly on the last of the zone is a face lying in a face.
#: Same reason as `CUT_MARGIN_MM`, `EDGE_CROSS_MM` and `FOOTING_CROSS_MM`.
#:
#: A quarter of a millimetre because a cap only ever has to clear a boundary the
#: `intersection` below already found for it, not an unknown — and because the
#: middle of a wide valid band is the honest place to sit. Both kernels build
#: every parity combination on every fixture for **0.05 through 0.75 mm**; only
#: 1.0 fails, and it fails by pushing the aviator's leads back past where OCCT
#: closes its booleans rather than by anything happening at the cap. A number
#: that worked at 0.5 and not at 0.9 would be a tuning; this one is not.
CAP_CROSS_MM = 0.25


def _end_tangents(coords: list) -> tuple[np.ndarray, np.ndarray,
                                         np.ndarray, np.ndarray]:
    """`(head, t_head, tail, t_tail)` — the two tips and their OUTWARD units."""
    head, nxt = np.asarray(coords[0], dtype=float), np.asarray(coords[1], dtype=float)
    tail, prv = np.asarray(coords[-1], dtype=float), np.asarray(coords[-2], dtype=float)
    t_head = head - nxt
    t_tail = tail - prv
    t_head = t_head / max(np.linalg.norm(t_head), 1e-12)
    t_tail = t_tail / max(np.linalg.norm(t_tail), 1e-12)
    return head, t_head, tail, t_tail


def cap_leads(cut_line, bands, minimum: float = CUT_LEAD_MM,
              cross_mm: float = CAP_CROSS_MM) -> tuple[float, float]:
    """`(head, tail)` leads that carry each square end cap clear of its zone.

    `bands` is one `(zone_polygon, reach_mm)` per band asking — in practice one,
    since the carve and the raise have different zones and different reaches and
    so get their own stations. `reach_mm` is `relief.castle._footing_reach`, not
    `_footing_spans`: the span runs to where the blend touches down *tangentially*,
    so its last stretch is flat to within microns and covering it or not is the
    same part. Asking for the span costs real length for nothing — on the aviator
    it was the difference between a 1.5 mm lead and a 2.6 mm one, and the second
    is past where OpenCASCADE will still close the booleans.

    The measurement is the whole idea, so it is worth being exact about what is
    being asked. A band is a ribbon: at every station it lays its profile down
    along the perpendicular, and the ribbon simply stops at the last station.
    Material of the acting zone lying beyond that final cap plane is never
    carved, however close to the seam it is. So the lead an end needs is

        max over q in (zone ∩ within-reach-of-the-cut) of (q - tip) · t

    with `t` the outward end tangent, plus `cross_mm` so the cap lands past that
    material rather than on it.

    **`within-reach` is a buffer of the line, and its round ends are the point.**
    Shapely's buffer caps the line with a half-disc of the same radius, so the
    region measured over is exactly the region the raster's distance-to-segment
    would carve — `hypot(perpendicular, beyond-the-end) <= reach`. That makes
    the answer self-bounding: no end can ever ask for more lead than the band's
    own reach, because past that the profile is the terrace and there is nothing
    left to carve. No arbitrary ceiling is needed, and none is imposed — a
    ceiling would be a silent return of the fin on some frame nobody has drawn
    yet, which is precisely how `CUT_LEAD_MM` came to be wrong.

    So the guarantee this makes is exact and worth stating in the form it holds:
    **no band leaves standing anything its own profile would have taken by more
    than `FOOTING_FLAT_TOL_MM`.** Not "no fin"; a fin under 0.02 mm.

    A straight ribbon is still not a round cap, and the last stretch carries
    slightly more than the raster's rounding would (`hypot` grows faster than
    the perpendicular alone). That residual is bounded by the profile's own
    depth over `cross_mm` of run and lands on material the rim wall is about to
    take anyway; the fin it replaces was up to 2.4 mm of raw blank.
    """
    coords = list(cut_line.coords)
    if len(coords) < 2:
        return (float(minimum), float(minimum))

    near_pts: list[np.ndarray] = []
    for poly, reach in bands:
        if poly is None or poly.is_empty or reach is None or reach <= 0.0:
            continue
        near = poly.intersection(cut_line.buffer(float(reach)))
        if near.is_empty:
            continue
        for geom in getattr(near, "geoms", (near,)):
            ring = getattr(geom, "exterior", None)
            if ring is None or ring.is_empty:
                continue
            near_pts.append(np.asarray(ring.coords, dtype=float)[:, :2])

    head, t_head, tail, t_tail = _end_tangents(coords)
    if not near_pts:
        return (float(minimum), float(minimum))
    q = np.vstack(near_pts)
    return tuple(float(max(minimum, ((q - tip) @ t).max() + cross_mm))
                 for tip, t in ((head, t_head), (tail, t_tail)))


def cut_stations(cut_line, n: int,
                 lead_mm: "float | tuple[float, float]" = CUT_LEAD_MM
                 ) -> tuple[np.ndarray, np.ndarray]:
    """Points and unit left-normals along a SCULPT cut, running past both ends.

    The cut lines are already extended past the body (`_CUT_EXTEND_MM`) so they
    always sever it, and this used to sample 2%..98% of that on the grounds that
    "sampling the very ends would fit the spine through points beyond anything
    that matters". It mattered: on a short seam that trim is a tenth of a
    millimetre, and a tenth of a millimetre of missing seam under a 9 mm blend
    is a 9 mm wedge of uncarved material. See `CUT_LEAD_MM`.

    So the stations cover the whole cut and `lead_mm` beyond each end,
    extrapolated along the end tangents. Straight-line extrapolation is safe at
    this distance — the cut is a gentle spline and the lead is short — and a
    band that reaches past its zone is clipped back by the caller.

    `lead_mm` may be a single number or a `(head, tail)` pair; `cap_leads`
    returns the pair each end actually needs, and the two ends of one cut
    routinely differ by more than a millimetre.

    **`n` is the station count, not a density**, so a long lead thins the
    sampling of the cut itself. Left that way on purpose: every caller zips a
    per-station list against these points, `len(pts) == n` is the contract they
    are written to, and the worst case in hand is 30 stations over a 6.0 mm cut
    with 2.25 mm of lead — 0.28 mm chords against a 0.15 mm CAM cell, on a
    curve whose radius is measured in tens of millimetres.
    """
    coords = list(cut_line.coords)
    lead_head, lead_tail = ((float(lead_mm), float(lead_mm))
                            if np.isscalar(lead_mm) else
                            (float(lead_mm[0]), float(lead_mm[1])))
    if len(coords) >= 2 and (lead_head > 0.0 or lead_tail > 0.0):
        head, t_head, tail, t_tail = _end_tangents(coords)
        cut_line = LineString([
            *([tuple(head + t_head * lead_head)] if lead_head > 0.0 else []),
            *coords,
            *([tuple(tail + t_tail * lead_tail)] if lead_tail > 0.0 else []),
        ])

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
