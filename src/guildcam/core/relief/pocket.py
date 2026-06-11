"""Hinge / shield pocket generator."""
from __future__ import annotations
import pyclipper
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
