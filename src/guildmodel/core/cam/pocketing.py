"""Pocketing via inward pyclipper offsets."""
from __future__ import annotations
from shapely.geometry import Polygon
import pyclipper

_SCALE = 1_000_000

#: The least the passes of a pocket overlap at its middle, as a fraction of
#: the tool's diameter (2.0): where a cascade's last passes would meet with
#: less, `core_rings` adds one more round the core they leave.
CENTER_OVERLAP = 0.1


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
    if rings:
        rings += core_rings(region, tool_radius_mm, stepover_mm)
    return rings


def core_rings(region: Polygon, tool_radius_mm: float,
               stepover_mm: float) -> list[list[tuple[float, float]]]:
    """The passes a ring cascade lacks in a pocket's middle (2.0).

    The cascade's rings are the region's insets a tool radius in and then
    every `stepover_mm`; the last ring of each branch stops within a stepover
    of the middle. Where the middle lies farther from those rings than the
    tool radius less `CENTER_OVERLAP` of the diameter, the passes from either
    side overlap by less than that, or leave material standing between them.
    A slot exactly two diameters wide was cut by one ring whose passes met on
    the center line with no overlap at all: a fin of no thickness on paper, a
    real one under an end mill a hair under size, and a column of cells in
    the simulation. Each such core, level by level, is ridden once round its
    outline; it is narrower than the tool, so that pass clears it. A
    cascade whose passes already overlap there gets nothing, and posts as
    before. Closed rings, mm.
    """
    r = float(tool_radius_mm)
    if region is None or region.is_empty or r <= 0.0:
        return []
    s = float(stepover_mm) if stepover_mm > 0.0 else max(r, 0.1)
    reach = r * (1.0 - CENTER_OVERLAP)
    kw = {"join_style": "round", "quad_segs": 32}
    out: list[list[tuple[float, float]]] = []
    depth = r
    level = region.buffer(-depth, **kw)
    while not level.is_empty:
        deeper = region.buffer(-(depth + s), **kw)
        core = level.buffer(-reach, **kw)
        if not core.is_empty and not deeper.is_empty:
            # what the next ring's passes overlap is theirs
            core = core.difference(deeper.buffer(reach, **kw))
        for g in getattr(core, "geoms", [core]):
            if g.geom_type != "Polygon" or g.is_empty or g.buffer(-0.005).is_empty:
                continue                      # a sliver of the arithmetic, not a core
            for ring in (g.exterior, *g.interiors):
                out.append([(float(x), float(y)) for x, y in ring.coords])
        level, depth = deeper, depth + s
    return out


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
    offset_px = int(tool_radius_mm * _SCALE)
    step_px = int(stepover_mm * _SCALE)

    def shrink(path, by):
        pco = pyclipper.PyclipperOffset()
        pco.AddPath(path, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
        return pco.Execute(-by)

    # Depth first: a ring that splits (a neck narrower than the tool) has each
    # branch cleared to its center before the next is begun. Breadth first,
    # the cascade crossed the neck between the branches on every ring. A
    # ring that never splits has one child, and the order is unchanged.
    all_contours: list[list[list[int]]] = []   # open: castle_ops closes its own copies
    stack = list(reversed(shrink(scaled_poly, offset_px)))
    while stack:
        ring = stack.pop()
        all_contours.append(ring)
        stack.extend(reversed(shrink(ring, step_px)))
    return all_contours
