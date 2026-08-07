"""Tab insertion for profile cuts.

Tabs are small uncut bridges that hold the part in the stock until final release.
On the last depth pass the cutter rises to (z_cut + tab_height_mm) at the tab
entry, traverses the tab width at that height, then returns to z_cut at the exit.

The resulting profile at each tab is trapezoidal, and its ramps have an explicit
length set by `ramp_angle_deg` — **not** "whatever the gap to the neighbouring
path point happens to be". Tab centres are distributed evenly along the path.

The Z profile is defined as a function of distance along the path, and the path's
own points are then re-emitted at whatever height that function gives them. That
is what makes the result independent of how the caller's points are spaced: a
buffered contour has 140 mm straight runs and 0.2 mm corner steps in the same
ring, and a tab has to come out the same size on either.
"""
from __future__ import annotations
import math

# Default lead angle for the rise onto / fall off a tab. Shallow enough not to
# shock a small cutter, steep enough that the ramp is a fraction of the tab.
TAB_RAMP_ANGLE_DEG = 30.0


def _path_length(pts: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        total += math.sqrt(dx * dx + dy * dy)
    return total


def _cumulative(pts: list[tuple[float, float]]) -> list[float]:
    cum = [0.0]
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        cum.append(cum[-1] + math.sqrt(dx * dx + dy * dy))
    return cum


def _point_at(pts: list[tuple[float, float]], cum: list[float], d: float):
    """Linear interpolation of the XY path at distance `d` along it."""
    if d <= 0:
        return pts[0]
    if d >= cum[-1]:
        return pts[-1]
    lo, hi = 0, len(cum) - 1
    while lo + 1 < hi:                       # binary search for the segment
        mid = (lo + hi) // 2
        if cum[mid] <= d:
            lo = mid
        else:
            hi = mid
    span = cum[lo + 1] - cum[lo]
    t = (d - cum[lo]) / span if span > 0 else 0.0
    (x0, y0), (x1, y1) = pts[lo], pts[lo + 1]
    return (x0 + t * (x1 - x0), y0 + t * (y1 - y0))


def tab_schedule(
    total: float,
    tab_count: int,
    tab_width_mm: float,
    tab_height_mm: float,
    ramp_angle_deg: float = TAB_RAMP_ANGLE_DEG,
) -> list[tuple[float, float]]:
    """``(distance, height_above_z_cut)`` breakpoints for evenly spaced tabs.

    Each tab contributes four: ramp start, full height in, full height out, ramp
    end. Half-width and ramp length are capped against the tab spacing so tabs can
    never overlap however extreme the settings — the part would otherwise be held
    by one continuous uncut rim rather than by tabs.
    """
    if total <= 0 or tab_count <= 0 or tab_height_mm <= 0:
        return []
    interval = total / tab_count
    half_w = min(tab_width_mm / 2.0, interval * 0.4)
    ramp = (tab_height_mm / math.tan(math.radians(ramp_angle_deg))
            if ramp_angle_deg and ramp_angle_deg > 0 else 0.0)
    ramp = min(ramp, max(0.0, interval * 0.5 - half_w))
    breaks: list[tuple[float, float]] = []
    for i in range(tab_count):
        c = interval * (i + 0.5)
        breaks += [(c - half_w - ramp, 0.0), (c - half_w, tab_height_mm),
                   (c + half_w, tab_height_mm), (c + half_w + ramp, 0.0)]
    return breaks


def _height_at(breaks: list[tuple[float, float]], d: float) -> float:
    """Piecewise-linear tab height at distance `d` (0 outside every tab)."""
    if not breaks or d <= breaks[0][0] or d >= breaks[-1][0]:
        return 0.0
    for i in range(1, len(breaks)):
        d1, h1 = breaks[i]
        if d <= d1:
            d0, h0 = breaks[i - 1]
            if h0 == h1:
                return h0
            span = d1 - d0
            return h0 if span <= 0 else h0 + (h1 - h0) * (d - d0) / span
    return 0.0


def insert_tabs(
    pts: list[tuple[float, float]],
    tab_count: int,
    tab_width_mm: float,
    tab_height_mm: float,
    z_cut: float,
    ramp_angle_deg: float = TAB_RAMP_ANGLE_DEG,
) -> list[tuple[float, float, float]]:
    """Return the profile contour with tabs inserted at evenly-spaced intervals.

    Every original point is kept (at the height the tab schedule gives it) and the
    schedule's own breakpoints are interpolated in, so the trapezoid is exact
    regardless of the input's point spacing. An earlier version walked the points
    and injected boundary waypoints per segment; it merged any two tabs that fell
    on one segment into a single raised run — which on a buffered profile, whose
    straight runs are over a hundred millimetres, turned four 3 mm tabs into two
    80 mm uncut stretches.
    """
    if len(pts) < 2:
        return [(x, y, z_cut) for x, y in pts]
    cum = _cumulative(pts)
    total = cum[-1]
    breaks = tab_schedule(total, tab_count, tab_width_mm, tab_height_mm, ramp_angle_deg)
    if not breaks:
        return [(x, y, z_cut) for x, y in pts]

    # Merge the path's own stations with the tab breakpoints, in order.
    stations = sorted(set([round(d, 9) for d in cum]
                          + [round(d, 9) for d, _ in breaks if 0.0 <= d <= total]))
    out: list[tuple[float, float, float]] = []
    for d in stations:
        x, y = _point_at(pts, cum, d)
        out.append((x, y, z_cut + _height_at(breaks, d)))
    return out
