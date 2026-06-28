"""Profile cut with tabs — pyclipper offset of OUTLINE plus tab insertion."""
from __future__ import annotations
from shapely.geometry import Polygon
import pyclipper

from .tabs import insert_tabs

_SCALE = 1_000_000


def profile_cut(
    outline: Polygon,
    tool_radius_mm: float,
    stock_thickness_mm: float,
    stepdown_mm: float,
    tab_count: int = 4,
    tab_width_mm: float = 3.0,
    tab_height_mm: float = 1.0,
) -> list[list[list[tuple[float, float, float]]]]:
    """Return depth passes for the profile (perimeter) cut.

    Offsets the outline outward by tool_radius_mm, inserts tabs, and
    returns one contour per depth pass.
    Each pass: list of polylines, each polyline: list of (x, y, z).
    """
    exterior = list(outline.exterior.coords)
    scaled = [[int(x * _SCALE), int(y * _SCALE)] for x, y in exterior]

    pco = pyclipper.PyclipperOffset()
    pco.AddPath(scaled, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
    offset_scaled = pco.Execute(tool_radius_mm * _SCALE)

    if not offset_scaled:
        return []

    offset_pts = [(p[0] / _SCALE, p[1] / _SCALE) for p in offset_scaled[0]]

    passes = []
    z = -stepdown_mm
    while z > -stock_thickness_mm - 1e-9:
        z_actual = max(z, -stock_thickness_mm)
        is_last = abs(z_actual - (-stock_thickness_mm)) < 1e-9
        pts_with_tabs = insert_tabs(offset_pts, tab_count, tab_width_mm, tab_height_mm, z_actual) if is_last else [(x, y, z_actual) for x, y in offset_pts]
        passes.append([pts_with_tabs])
        z -= stepdown_mm

    return passes
