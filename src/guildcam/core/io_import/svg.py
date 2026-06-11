"""SVG importer.

Reads recognised layers from an SVG (see core.layers.ALL_LAYERS).
Uses svgelements to handle transforms and units. Flattens all path types
to polylines at chord_tol precision. Expects 1 user unit = 1 mm (confirmed
via units dialog in GUI before calling this function).
"""
from __future__ import annotations
from pathlib import Path
import svgelements as se

from guildcam.core.layers import ALL_LAYERS

SUPPORTED_LAYERS = ALL_LAYERS   # public alias kept for callers that import this name
CHORD_TOL_MM = 0.01


def import_svg(
    path: Path,
    px_per_mm: float = 3.7795275591,   # 96 dpi default; confirmed by user in GUI
    chord_tol: float = CHORD_TOL_MM,
) -> dict[str, list[list[tuple[float, float]]]]:
    """Return layer-keyed lists of point-list curves from an SVG file."""
    svg = se.SVG.parse(str(path))
    result: dict[str, list[list[tuple[float, float]]]] = {k: [] for k in ALL_LAYERS}

    for element in svg.elements():
        if not isinstance(element, se.Shape):
            continue

        label = _find_label(element)
        if label not in ALL_LAYERS:
            continue

        if isinstance(element, (se.Path, se.Rect, se.Circle, se.Ellipse, se.Polygon, se.Polyline)):
            path_obj = se.Path(element)
            pts_px = list(path_obj.npoint(chord_tol * px_per_mm))
            pts_mm = [(p[0] / px_per_mm, p[1] / px_per_mm) for p in pts_px]
            if len(pts_mm) >= 2:
                result[label].append(pts_mm)

    return result


def _find_label(element: se.Shape) -> str:
    """Resolve layer name from Inkscape label, id, or parent group."""
    label = (
        element.values.get("{http://www.inkscape.org/namespaces/inkscape}label", "")
        or element.values.get("id", "")
    ).upper()
    if label in ALL_LAYERS:
        return label
    parent = getattr(element, "_parent", None)
    if parent is not None:
        return _find_label(parent)
    return ""
