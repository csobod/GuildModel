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

A front may also have **more than one body** (2026-10-16): the separated rims
of a combination frame, acetate rims on a metal bridge, drawn as two closed
contours each holding its lens. GuildDraw sorts the OUTLINE the same way
(``framedraft/export/validate.py``, ``_outline_bodies``): of the contours
inside no other, the largest is a body and so is any that holds a lens; one
that holds no lens is a stray. The bodies come back as one ``MultiPolygon``.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import MultiPolygon, Polygon

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
    """The area a closed curve encloses; an empty polygon for a curve with
    fewer than three distinct points.

    A curve that crosses itself is repaired to the largest piece of what it
    encloses. The repair buffered the ring, a line, and a line's buffer by 0
    is empty: the curve vanished, an outline or a lens with it, and one too
    short to be a ring stopped the drawing from opening (the 2.0 bug hunt).
    """
    from shapely import make_valid
    closed = close_if_nearly_closed(points)
    if len({(round(float(x), 9), round(float(y), 9)) for x, y in closed}) < 3:
        return Polygon()
    poly = Polygon(closed)
    if not poly.is_valid:
        fixed = make_valid(poly)
        parts = [g for g in getattr(fixed, "geoms", [fixed])
                 for g in getattr(g, "geoms", [g])
                 if isinstance(g, Polygon) and g.area > 0]
        poly = max(parts, key=lambda g: g.area) if parts else Polygon()
    return poly


@dataclass
class OutlineAssembly:
    """The OUTLINE layer resolved into its bodies plus their decorative holes.

    ``polygon`` is the profile with every hole as an interior ring — pass this
    wherever a single outline polygon was passed before. A front with
    separated rims has a body per rim, and ``polygon`` is then their
    ``MultiPolygon``; ``bodies`` lists them one by one, OS (−x) first.
    ``holes`` are the openings as standalone polygons in Hole1..HoleN order,
    for the callers that must treat them separately from LENS openings (no
    bevel groove, no work-holding keep-out). ``stray`` are closed OUTLINE
    curves that fell outside every body — an authoring mistake, reported by
    `validate`.
    """
    polygon: Polygon | MultiPolygon | None = None
    holes: list[Polygon] = field(default_factory=list)
    stray: list[Polygon] = field(default_factory=list)
    bodies: list[Polygon] = field(default_factory=list)

    @property
    def hole_labels(self) -> list[str]:
        return [hole_label(i) for i in range(len(self.holes))]


def hole_label(index: int) -> str:
    """The user-facing name of the index-th decorative hole (0-based)."""
    return f"Hole{index + 1}"


def _body_with_holes(shell: Polygon, holes: list[Polygon]) -> Polygon:
    polygon = Polygon(shell.exterior, [h.exterior for h in holes]) if holes else shell
    if not polygon.is_valid:            # overlapping/nested holes: fall back clean
        polygon = polygon.buffer(0)
        if polygon.geom_type == "MultiPolygon":
            polygon = max(polygon.geoms, key=lambda g: g.area)
    return polygon


def assemble_outline(curves: list[list[tuple[float, float]]],
                     lenses: list[Polygon] = ()) -> OutlineAssembly:
    """Resolve the OUTLINE layer's closed curves into bodies + holes.

    The largest-area curve is the profile. Another curve inside no larger one
    that holds one of ``lenses`` is a body too: a separated rim. Every other
    curve whose interior falls inside a body becomes a hole of that body, and
    the rest are strays. Holes are ordered top-to-bottom then left-to-right
    (the same reading order `regions._label_generic` uses), so Hole1..HoleN
    are stable across reloads of the same drawing.

    Without ``lenses``, or with every lens in the profile, this is the single
    profile it always was.
    """
    polys = [points_to_polygon(c) for c in curves if len(c) >= 3]
    polys = [p for p in polys if p.area > 0]
    if not polys:
        return OutlineAssembly()

    shell = max(polys, key=lambda p: p.area)

    def top_level(p: Polygon) -> bool:
        return not any(q is not p and q.area > p.area
                       and q.contains(p.representative_point()) for q in polys)

    shells = [shell] + [p for p in polys if p is not shell and top_level(p)
                        and any(p.contains(lens.representative_point())
                                for lens in lenses)]
    owned: list[list[Polygon]] = [[] for _ in shells]
    stray = []
    for p in polys:
        if any(p is s for s in shells):
            continue
        # representative_point() is guaranteed inside p, so this is a true
        # containment test even when the curves share a tangent point.
        point = p.representative_point()
        owner = next((i for i, s in enumerate(shells) if s.contains(point)), None)
        if owner is None:
            stray.append(p)
        else:
            owned[owner].append(p)

    def reading_order(p: Polygon) -> tuple:
        return (-round(p.centroid.y, 1), p.centroid.x)

    # Each body's interior rings in Hole1..HoleN order too: the CAM cuts the
    # openings in the order the rings come.
    owned = [sorted((h for h in hs if h.area >= _MIN_HOLE_AREA_MM2), key=reading_order)
             for hs in owned]
    holes = sorted((h for hs in owned for h in hs), key=reading_order)

    bodies = [_body_with_holes(s, hs) for s, hs in zip(shells, owned)]
    if len(bodies) == 1:
        return OutlineAssembly(polygon=bodies[0], holes=holes, stray=stray,
                               bodies=bodies)
    merged = MultiPolygon(bodies)
    if not merged.is_valid:             # bodies drawn overlapping: one body
        merged = merged.buffer(0)
    parts = list(merged.geoms) if merged.geom_type == "MultiPolygon" else [merged]
    parts.sort(key=lambda p: p.centroid.x)
    polygon = MultiPolygon(parts) if len(parts) > 1 else parts[0]
    return OutlineAssembly(polygon=polygon, holes=holes, stray=stray, bodies=parts)


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
