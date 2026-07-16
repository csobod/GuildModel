"""Hinge / shield pocket generator (dormant — CHA-catalog companion).

Production hinge pockets are cut by ``cam.castle_ops.hinge_pocket_op`` (a
pocketing cascade WITH inward tool-radius offsets); this module is kept with
``relief/hinge.py`` for the post-1.0 catalog work.

WARNING — no inward tool-radius offset: :func:`hinge_pocket` traces the given
polygon's boundary at full depth as-is. The CALLER must pre-offset the polygon
inward by the tool radius, or the cut pocket comes out one tool radius
oversize all around.
"""
from __future__ import annotations
from shapely.geometry import Polygon


_SCALE = 1_000_000   # pyclipper integer scaling factor


def hinge_pocket(
    pocket_poly: Polygon,
    depth_mm: float,
    stepdown_mm: float,
) -> list[list[list[tuple[float, float, float]]]]:
    """Return depth passes for a flat-bottomed pocket.

    Returns a list of depth passes; each pass is a list of contour polylines
    (each a list of (x, y, z) points).
    """
    exterior = list(pocket_poly.exterior.coords)
    scaled = [[int(x * _SCALE), int(y * _SCALE)] for x, y in exterior]

    passes = []
    z = -stepdown_mm
    while z > -depth_mm - 1e-9:
        z_actual = max(z, -depth_mm)
        contour = [[(p[0] / _SCALE, p[1] / _SCALE, z_actual) for p in scaled]]
        passes.append(contour)
        z -= stepdown_mm

    return passes
