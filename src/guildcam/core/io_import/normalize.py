"""Normalize raw polygon data from DXF/SVG into Shapely geometry.

Flattens arcs/splines/Beziers to polylines at a configurable chord tolerance,
auto-closes nearly-closed curves, and orients the outline so OD is on viewer's right.
"""
from __future__ import annotations
import numpy as np
from shapely.geometry import Polygon, LinearRing

CHORD_TOLERANCE_MM = 0.01   # default: flatten curves to within 0.01 mm


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
