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
        # pyclipper's rings come back open; closed here so the last segment
        # is cut (the rings `_inward_offsets` returns stay open, because the
        # hinge pockets and the relief close their own copies)
        depth_pass = [[(p[0] / _SCALE, p[1] / _SCALE, z_actual) for p in list(contour) + [contour[0]]]
                      for contour in contours]
        passes.append(depth_pass)
        z -= stepdown_mm

    return passes


def fill_rings(
    region: Polygon,
    tool_radius_mm: float,
    stepover_mm: float,
) -> list[list[tuple[float, float]]]:
    """Closed rings (mm) that clear `region` flat, holes respected: the tool
    center walks the boundary a tool radius in, then every `stepover_mm` further
    inward until nothing is left, and each hole is stood off the same way. An
    engraved logo drawn as a closed curve is filled with these (2026-10-05); a
    closed curve drawn inside it is an island and keeps its material. A region
    the tool cannot enter yields no rings."""
    from shapely.geometry.polygon import orient
    if region.is_empty or region.area <= 0:
        return []
    region = orient(region, sign=1.0)            # exterior CCW, holes CW: pyclipper's hole rule
    paths = [[[int(x * _SCALE), int(y * _SCALE)] for x, y in ring.coords[:-1]]
             for ring in (region.exterior, *region.interiors)]
    paths = [p for p in paths if len(p) >= 3]
    if not paths:
        return []
    if stepover_mm <= 0.0:
        stepover_mm = max(tool_radius_mm, 0.1)
    offset_px = int(tool_radius_mm * _SCALE)
    step_px = max(1, int(stepover_mm * _SCALE))
    rings: list[list[tuple[float, float]]] = []
    offset = offset_px
    while True:
        pco = pyclipper.PyclipperOffset()
        pco.AddPaths(paths, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        shrunk = pco.Execute(-offset)
        if not shrunk:
            break
        for contour in shrunk:
            if len(contour) >= 3:
                rings.append([(p[0] / _SCALE, p[1] / _SCALE) for p in list(contour) + [contour[0]]])
        offset += step_px
    return rings


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
        all_contours.extend(shrunk)          # open: castle_ops closes its own copies
        current = shrunk
        offset = step_px

    return all_contours
