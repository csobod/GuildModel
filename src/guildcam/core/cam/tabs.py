"""Tab insertion for profile cuts.

Tabs are small uncut bridges that hold the part in the stock until final release.
On the last depth pass the cutter rises to (z_cut + tab_height_mm) at the tab
entry, traverses the tab width at that height, then returns to z_cut at the exit.

The resulting profile at each tab is trapezoidal:
  - linear ramp up from the point just before entry to the entry boundary
  - flat traverse at z_cut + tab_height_mm across the tab
  - linear ramp down from the exit boundary to the point just after

Tab centres are distributed evenly along the path.
"""
from __future__ import annotations
import math


def _path_length(pts: list[tuple[float, float]]) -> float:
    total = 0.0
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        total += math.sqrt(dx * dx + dy * dy)
    return total


def insert_tabs(
    pts: list[tuple[float, float]],
    tab_count: int,
    tab_width_mm: float,
    tab_height_mm: float,
    z_cut: float,
) -> list[tuple[float, float, float]]:
    """Return the profile contour with tabs inserted at evenly-spaced intervals.

    Each tab is inserted as two boundary events:
      - entry at (centre - half_width): cutter rises to z_cut + tab_height_mm
      - exit  at (centre + half_width): cutter returns to z_cut

    Events within the same segment are handled in order so multiple tabs per
    segment (edge case) are still correct.
    """
    total = _path_length(pts)
    if total <= 0 or tab_count <= 0:
        return [(x, y, z_cut) for x, y in pts]

    interval = total / tab_count
    half_w = tab_width_mm / 2.0
    z_tab = z_cut + tab_height_mm

    # Build sorted (distance_along_path, is_entry) events for all tabs.
    # is_entry=True → cutter rises to z_tab; False → cutter falls to z_cut.
    events: list[tuple[float, bool]] = []
    for i in range(tab_count):
        centre = interval * (i + 0.5)
        start = centre - half_w
        end = centre + half_w
        if 0.0 <= start <= total:
            events.append((start, True))
        if 0.0 <= end <= total:
            events.append((end, False))
    events.sort()

    result: list[tuple[float, float, float]] = []
    dist = 0.0
    in_tab = False
    ev_idx = 0

    for i, (x, y) in enumerate(pts):
        if i == 0:
            result.append((x, y, z_tab if in_tab else z_cut))
            continue

        px, py = pts[i - 1]
        seg_len = math.sqrt((x - px) ** 2 + (y - py) ** 2)

        # Inject boundary waypoints that fall within this segment.
        while ev_idx < len(events) and dist < events[ev_idx][0] <= dist + seg_len:
            ev_dist, is_entry = events[ev_idx]
            t = (ev_dist - dist) / seg_len
            ix = px + t * (x - px)
            iy = py + t * (y - py)
            if is_entry:
                # Cutter rises to tab height here; ramp-up ends at this waypoint.
                result.append((ix, iy, z_tab))
                in_tab = True
            else:
                # Flat top ends at this waypoint; the next regular path point
                # (at z_cut) creates the ramp-down.
                result.append((ix, iy, z_tab))
                in_tab = False
            ev_idx += 1

        dist += seg_len
        result.append((x, y, z_tab if in_tab else z_cut))

    return result
