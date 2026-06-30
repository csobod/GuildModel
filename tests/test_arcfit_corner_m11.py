"""Arc-fit must not bulge off the real toolpath across a corner (BUILDPLAN M11).

The greedy circle fit checked only the radial deviation of the sampled *points*; a
long straight chord between two on-circle points could bulge off the path by the
sagitta, fitting a fat arc that silently rounded a sharp hinge-pocket corner. The fix
bounds each segment's chord→arc gap by the same tolerance.
"""
import math

import numpy as np
from shapely.geometry import LineString, Point

from guildmodel.core.post.arcfit import fit_arcs

TOL = 0.01


def _reconstruct(moves, start):
    pts = [(start[0], start[1])]
    cur = start
    for m in moves:
        if m[0] == "line":
            pts.append((m[1][0], m[1][1])); cur = m[1]
        else:
            end, (cx, cy), ccw = m[1], m[2], m[3]
            R = math.hypot(cur[0] - cx, cur[1] - cy)
            a0 = math.atan2(cur[1] - cy, cur[0] - cx)
            a1 = math.atan2(end[1] - cy, end[0] - cx)
            sweep = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
            for t in np.linspace(0, 1, 24)[1:]:
                ang = a0 + sweep * t
                pts.append((cx + R * math.cos(ang), cy + R * math.sin(ang)))
            cur = end
    return pts


def _max_dev(path):
    rec = _reconstruct(fit_arcs(path, tol_mm=TOL), path[0])
    line = LineString([(x, y) for x, y, *_ in path])
    return max(Point(p).distance(line) for p in rec)


def _straight_into_corner():
    """A long sparse straight → a 1 mm tool-radius fillet → another straight: exactly
    the hinge-pocket-corner shape the old fit rounded by ~0.4 mm."""
    pts = [(0.0, 0.0, 0.0), (8.0, 0.0, 0.0)]              # long straight, only 2 points
    cx, cy = 8.0, 1.0
    for a in np.linspace(-math.pi / 2, 0.0, 8):           # 1 mm fillet
        pts.append((cx + math.cos(a), cy + math.sin(a), 0.0))
    pts.append((9.0, 9.0, 0.0))                           # straight out
    return pts


def test_emitted_path_does_not_bulge_across_a_corner():
    assert _max_dev(_straight_into_corner()) <= 0.02      # was ~0.4 mm before the guard


def test_dense_circle_still_collapses_to_arcs():
    th = np.linspace(0, 2 * math.pi, 80, endpoint=False)
    pts = [(5 * math.cos(t), 5 * math.sin(t), 0.0) for t in th]
    moves = fit_arcs(pts, tol_mm=TOL)
    assert sum(1 for m in moves if m[0] == "arc") >= 1    # legit curves still fit
    assert _max_dev(pts) <= 0.02
