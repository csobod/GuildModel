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

    Decorative OUTLINE openings (the polygon's interior rings, see
    normalize.assemble_outline) are cut too — offset *inward* so the tool stays
    inside the opening, and without tabs: the waste slug falls free and the part
    itself is still held by the tabbed perimeter.
    """
    def _offset(ring, delta: float) -> list[tuple[float, float]] | None:
        scaled = [[int(x * _SCALE), int(y * _SCALE)] for x, y in ring.coords]
        pco = pyclipper.PyclipperOffset()
        pco.AddPath(scaled, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        result = pco.Execute(delta * _SCALE)
        if not result:
            return None
        return [(p[0] / _SCALE, p[1] / _SCALE) for p in result[0]]

    offset_pts = _offset(outline.exterior, tool_radius_mm)
    if offset_pts is None:
        return []
    # A ring smaller than the tool offsets away to nothing — skip rather than emit
    # a degenerate path (pyclipper returns [] for it).
    hole_pts = [pts for pts in (_offset(r, -tool_radius_mm) for r in outline.interiors)
                if pts]

    passes = []
    z = -stepdown_mm
    while z > -stock_thickness_mm - 1e-9:
        z_actual = max(z, -stock_thickness_mm)
        is_last = abs(z_actual - (-stock_thickness_mm)) < 1e-9
        pts_with_tabs = insert_tabs(offset_pts, tab_count, tab_width_mm, tab_height_mm, z_actual) if is_last else [(x, y, z_actual) for x, y in offset_pts]
        polylines = [[(x, y, z_actual) for x, y in pts] for pts in hole_pts]
        polylines.append(pts_with_tabs)
        passes.append(polylines)
        z -= stepdown_mm

    return passes
