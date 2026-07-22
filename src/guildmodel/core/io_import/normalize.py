"""Normalize raw polygon data from DXF/SVG into Shapely geometry.

Flattens arcs/splines/Beziers to polylines at a configurable chord tolerance,
auto-closes nearly-closed curves, and orients the outline so OD is on viewer's right.

The OUTLINE layer may carry more than one closed curve: the outermost is the
frame's profile, and any closed curve drawn *inside* it is a decorative opening
(an aviator's bridge keyhole, a cut-out temple, "swiss cheese" perforations).
:func:`assemble_outline` folds those into one Shapely polygon with interior
rings, which is the representation the whole downstream pipeline already speaks
— the relief mask, the mesh rim, and the inside-contour CAM all key off a
body's ``interiors``. Unlike LENS openings, these holes take no bevel groove.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import Polygon, LinearRing

CHORD_TOLERANCE_MM = 0.01   # default: flatten curves to within 0.01 mm

_MIN_HOLE_AREA_MM2 = 0.01   # drop degenerate slivers rather than punch pinholes


def close_if_nearly_closed(points: list[tuple[float, float]], tol: float = 0.1) -> list[tuple[float, float]]:
    if not points:
        return points
    p0, pn = np.array(points[0]), np.array(points[-1])
    if np.linalg.norm(p0 - pn) < tol:
        return points[:-1]
    return points


def points_to_polygon(points: list[tuple[float, float]]) -> Polygon:
    closed = close_if_nearly_closed(points)
    ring = LinearRing(closed)
    if not ring.is_valid:
        ring = ring.buffer(0).exterior  # attempt repair
    poly = Polygon(ring)
    if poly.area < 0:
        poly = poly.reverse()
    return poly


@dataclass
class OutlineAssembly:
    """The OUTLINE layer resolved into one profile plus its decorative holes.

    ``polygon`` is the profile with every hole as an interior ring — pass this
    wherever a single outline polygon was passed before. ``holes`` are the same
    openings as standalone polygons in Hole1..HoleN order, for the callers that
    must treat them separately from LENS openings (no bevel groove, no
    work-holding keep-out). ``stray`` are closed OUTLINE curves that fell
    outside the profile — an authoring mistake, reported by `validate`.
    """
    polygon: Polygon | None = None
    holes: list[Polygon] = field(default_factory=list)
    stray: list[Polygon] = field(default_factory=list)

    @property
    def hole_labels(self) -> list[str]:
        return [hole_label(i) for i in range(len(self.holes))]


def hole_label(index: int) -> str:
    """The user-facing name of the index-th decorative hole (0-based)."""
    return f"Hole{index + 1}"


def assemble_outline(curves: list[list[tuple[float, float]]]) -> OutlineAssembly:
    """Resolve the OUTLINE layer's closed curves into profile + holes.

    The largest-area curve is the profile; every other curve whose interior
    falls inside it becomes a hole. Holes are ordered top-to-bottom then
    left-to-right (the same reading order `regions._label_generic` uses), so
    Hole1..HoleN are stable across reloads of the same drawing.
    """
    polys = [points_to_polygon(c) for c in curves if len(c) >= 3]
    polys = [p for p in polys if p.area > 0]
    if not polys:
        return OutlineAssembly()

    shell = max(polys, key=lambda p: p.area)
    holes, stray = [], []
    for p in polys:
        if p is shell:
            continue
        # representative_point() is guaranteed inside p, so this is a true
        # containment test even when the curves share a tangent point.
        (holes if shell.contains(p.representative_point()) else stray).append(p)

    holes = [h for h in holes if h.area >= _MIN_HOLE_AREA_MM2]
    holes.sort(key=lambda p: (-round(p.centroid.y, 1), p.centroid.x))

    polygon = Polygon(shell.exterior, [h.exterior for h in holes]) if holes else shell
    if not polygon.is_valid:            # overlapping/nested holes: fall back clean
        polygon = polygon.buffer(0)
        if polygon.geom_type == "MultiPolygon":
            polygon = max(polygon.geoms, key=lambda g: g.area)
    return OutlineAssembly(polygon=polygon, holes=holes, stray=stray)


def normalize(
    raw_curves: dict[str, list[list[tuple[float, float]]]],
    chord_tol: float = CHORD_TOLERANCE_MM,
) -> dict[str, list[Polygon]]:
    """Convert layer-keyed raw polylines to layer-keyed Shapely polygons."""
    result: dict[str, list[Polygon]] = {}
    for layer, curves in raw_curves.items():
        polys = [points_to_polygon(c) for c in curves if len(c) >= 3]
        result[layer] = polys
    return result
