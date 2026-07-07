"""Pocketing via inward pyclipper offsets."""
from __future__ import annotations
from shapely.geometry import Polygon
import pyclipper

_SCALE = 1_000_000


def pocket_paths(
    boundary: Polygon,
    tool_radius_mm: float,
    depth_mm: float,
    stepover_mm: float,
    stepdown_mm: float,
) -> list[list[list[tuple[float, float, float]]]]:
    """Return depth passes of inward-offset contours for a flat-bottomed pocket."""
    exterior = list(boundary.exterior.coords)
    scaled = [[int(x * _SCALE), int(y * _SCALE)] for x, y in exterior]

    passes = []
    z = -stepdown_mm
    while z > -depth_mm - 1e-9:
        z_actual = max(z, -depth_mm)
        contours = _inward_offsets(scaled, tool_radius_mm, stepover_mm)
        depth_pass = [[(p[0] / _SCALE, p[1] / _SCALE, z_actual) for p in contour] for contour in contours]
        passes.append(depth_pass)
        z -= stepdown_mm

    return passes


def _inward_offsets(
    scaled_poly: list[list[int]],
    tool_radius_mm: float,
    stepover_mm: float,
) -> list[list[list[int]]]:
    # A non-positive stepover makes Execute(-0) return the same ring forever (step_px
    # would be 0) — guard it so a hand-edited project can't hang the worker (matching
    # peck_drill's zero guard). Only fires for <= 0, so legitimate fine stepovers pass
    # through; the tool radius (else 0.1 mm) is a sane coarse fallback.
    if stepover_mm <= 0.0:
        stepover_mm = max(tool_radius_mm, 0.1)
    all_contours: list[list[list[int]]] = []
    current = [scaled_poly]
    offset_px = int(tool_radius_mm * _SCALE)
    step_px = int(stepover_mm * _SCALE)

    offset = offset_px
    while current:
        pco = pyclipper.PyclipperOffset()
        for path in current:
            pco.AddPath(path, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        shrunk = pco.Execute(-offset)
        if not shrunk:
            break
        all_contours.extend(shrunk)
        current = shrunk
        offset = step_px

    return all_contours
