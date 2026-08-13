"""Centerline (medial-axis) engraving (BUILDPLAN M11 #7).

GuildDraw exports engraving text as **closed glyph outlines** on the ENGRAVING layer
(the perimeter of each letterform — an "O" is an outer ring plus its counter ring).
Tracing those outlines mills the *border* of every stroke, which double-cuts thin
strokes and leaves a ridge down their middle. Instead we engrave a single line down
the **center of each stroke** at one fixed depth — efficient (one pass per stroke)
and faithful to the drawn glyph (serif spurs included, since they fall out of the
medial axis naturally).

Pipeline, given the raw ENGRAVING curves:
  1. Open curves pass through unchanged — they are already centerlines.
  2. Closed rings are combined by the even-odd rule into the filled *ink* regions
     (outer ⊖ counter = the annulus of an "O"), so holes are respected.
  3. Each ink polygon's approximate medial axis is the set of Voronoi ridges whose
     both vertices lie inside it (Voronoi of densely resampled boundary points).
  4. Leaf branches shorter than `prune_len` are trimmed (the spurious spurs Voronoi
     throws toward convex corners), then segments are merged into polylines.
"""
from __future__ import annotations

from collections import defaultdict
from functools import reduce
from typing import Iterable

import numpy as np
from scipy.spatial import Voronoi
from shapely import contains_xy, prepare
from shapely.geometry import LineString, MultiLineString, Polygon
from shapely.ops import linemerge, unary_union

Curve = list[tuple[float, float]]

_CLOSE_TOL = 1e-6
_SNAP = 6              # decimals used to weld shared Voronoi-ridge endpoints


def _is_closed(curve: Curve) -> bool:
    if len(curve) < 4:
        return False
    (x0, y0), (xn, yn) = curve[0], curve[-1]
    return abs(x0 - xn) <= _CLOSE_TOL and abs(y0 - yn) <= _CLOSE_TOL


def _even_odd_fill(rings: list[Curve]) -> list[Polygon]:
    """The filled ink regions: even-odd combination of the closed glyph rings, so a
    counter (an "O"'s inner ring) becomes a hole rather than more ink."""
    polys = []
    for r in rings:
        p = Polygon(r)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty and p.area > 0:
            polys.append(p)
    if not polys:
        return []
    ink = reduce(lambda a, b: a.symmetric_difference(b), polys)
    return [g for g in getattr(ink, "geoms", [ink]) if isinstance(g, Polygon) and g.area > 0]


def _resample(coords, spacing: float) -> list[tuple[float, float]]:
    ls = LineString(coords)
    n = max(2, int(np.ceil(ls.length / max(spacing, 1e-3))))
    return [tuple(ls.interpolate(i / n, normalized=True).coords[0]) for i in range(n)]


def _medial_segments(poly: Polygon, spacing: float) -> list[tuple]:
    """Interior Voronoi ridges of `poly` (its approximate medial axis) as (p0, p1).

    Ridges that separate two *adjacent* boundary samples are the perpendicular
    bisectors of boundary edges (inward "spokes"), not medial edges — they are
    dropped via `vor.ridge_points`. What remains separates samples on different walls:
    the medial axis itself."""
    pts: list[tuple[float, float]] = []
    adjacent: set[frozenset] = set()              # consecutive-sample pairs on a ring
    for ring in (poly.exterior, *poly.interiors):
        rs = _resample(ring.coords, spacing)
        base, m = len(pts), len(rs)
        for k in range(m):
            adjacent.add(frozenset((base + k, base + (k + 1) % m)))
        pts.extend(rs)
    if len(pts) < 4:
        return []
    try:
        vor = Voronoi(np.asarray(pts))
    except Exception:
        return []
    prepare(poly)
    segs = []
    for (pi, pj), (ia, ib) in zip(vor.ridge_points, vor.ridge_vertices):
        if ia < 0 or ib < 0:
            continue
        if frozenset((int(pi), int(pj))) in adjacent:   # boundary-edge spoke — skip
            continue
        pa, pb = vor.vertices[ia], vor.vertices[ib]
        mid = (pa + pb) / 2.0
        xs = [pa[0], pb[0], mid[0]]
        ys = [pa[1], pb[1], mid[1]]
        if contains_xy(poly, xs, ys).all():        # ridge sits wholly inside the ink
            segs.append((tuple(pa), tuple(pb)))
    return segs


def _merge(lines: list) -> list[Curve]:
    """Merge connected segments/branches into maximal polylines, splitting at
    junctions (nodes where ≥3 branches meet)."""
    if not lines:
        return []
    geom = unary_union([LineString(s) for s in lines])
    # linemerge needs a multi-part geometry; a lone LineString comes back as-is.
    merged = linemerge(geom) if isinstance(geom, MultiLineString) else geom
    geoms = merged.geoms if isinstance(merged, MultiLineString) else [merged]
    return [[tuple(c) for c in g.coords] for g in geoms
            if isinstance(g, LineString) and g.length > 0]


def _bkey(pt) -> tuple:
    return (round(float(pt[0]), _SNAP), round(float(pt[1]), _SNAP))


def _prune_branches(lines: list[Curve], min_len: float) -> list[Curve]:
    """Drop leaf *branches* (a polyline whose end is touched by no other branch)
    shorter than `min_len` — the spurious spurs Voronoi throws toward convex corners.
    Operating on whole branches (not raw segments) keeps long runs intact; closed
    loops have no free end and are never pruned. Iterates so a stub revealed by a
    removal is reconsidered."""
    if min_len <= 0:
        return lines
    changed = True
    while changed and len(lines) > 1:
        changed = False
        deg: dict = defaultdict(int)
        for ln in lines:
            deg[_bkey(ln[0])] += 1
            deg[_bkey(ln[-1])] += 1
        kept = []
        for ln in lines:
            leaf = deg[_bkey(ln[0])] == 1 or deg[_bkey(ln[-1])] == 1
            if leaf and LineString(ln).length < min_len:
                changed = True
                continue
            kept.append(ln)
        if not kept:                  # never delete the whole glyph
            break
        if len(kept) != len(lines):
            lines = _merge(kept)      # re-merge across nodes that lost a leaf
    return lines


def engraving_centerlines(
    curves: Iterable[Curve], *, spacing: float = 0.1, prune_len: float = 0.15,
    simplify_tol: float = 0.02,
) -> list[Curve]:
    """Convert raw ENGRAVING curves into fixed-depth centerline polylines.

    Open curves pass through; closed glyph rings are reduced (even-odd) to ink
    regions whose medial axis becomes the engraved path. `spacing` is the boundary
    resample step (finer = smoother, slower); `prune_len` trims corner spurs (set 0
    to keep them); `simplify_tol` decimates the output. On any failure for a glyph,
    that glyph's original outline is kept so nothing silently vanishes.

    `spacing` must stay well below the stroke width or the Voronoi medial axis
    zig-zags between staggered boundary samples (a jagged engraving groove). At 0.1 mm
    it converges to the true smooth spine for the ~1 mm strokes of engraved text
    (0.25 mm left the center of a smooth stroke turning ~2× more than the stroke does).

    `prune_len` is coupled to `spacing`: the only spurs a clean glyph outline throws are
    the ~`spacing`-long ones from boundary discretisation, so prune just above that
    (~1.5·spacing). Set larger and it eats real terminal serifs (a serif branch is only
    0.15–0.4 mm on 3–4 mm text); the old 0.4 default was tuned for the old 0.25 spacing
    and dropped the fine serifs (S top, M tops, terminal of a 2).
    """
    closed: list[Curve] = []
    out: list[Curve] = []
    for c in curves:
        c = [(float(x), float(y)) for x, y in c]
        (closed if _is_closed(c) else out).append(c)
    if not closed:
        return out

    for poly in _even_odd_fill(closed):
        try:
            segs = _medial_segments(poly, spacing)
            lines = _merge(segs)                      # segments → branches
            lines = _prune_branches(lines, prune_len)  # trim short corner spurs
        except Exception:
            lines = []
        if not lines:                       # fall back to the outline for this glyph
            out.append(list(poly.exterior.coords))
            out.extend(list(r.coords) for r in poly.interiors)
            continue
        for ln in lines:
            g = LineString(ln).simplify(simplify_tol) if simplify_tol > 0 else LineString(ln)
            out.append([tuple(c) for c in g.coords])
    return out
