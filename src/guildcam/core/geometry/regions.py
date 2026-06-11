"""Castle zone partitioning (BUILDPLAN M1.3).

Partitions the frame-front body (OUTLINE minus LENS holes) into castle zones
using the SCULPT section cuts, and auto-labels them when the standard
5-cuts-per-side pattern matches (see DEMO_PROJECT_TEARDOWN.md §2-3):

    towers: endpiece_od / endpiece_os, bridge, nosepad_od / nosepad_os
    walls:  eyewire_superior_od/os, eyewire_inferior_od/os

Coordinates are posterior (import_dxf default): OD on +x, superior on +y.
Castle vocabulary (towers/walls/footing) is presentation-only; identifiers
here use the anatomical names per BUILDPLAN §2.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union


@dataclass
class FrameRegions:
    """Named polygon regions extracted from the imported drawing.

    All polygons are in world coordinates (mm), normalized so that
    OD (right eye) is on viewer's right (positive X).
    """
    outline: Polygon             # outer profile of the frame front
    lens_od: Polygon             # right-eye (OD) lens opening
    lens_os: Polygon             # left-eye (OS) lens opening
    bridge: Polygon | None = None      # bridge reference region (optional)
    hinge_od: Polygon | None = None    # right hinge/shield pocket location
    hinge_os: Polygon | None = None    # left hinge/shield pocket location


# Zone kinds (towers + walls); "generic" is the unmatched fallback.
TOWER_KINDS = ("endpiece", "bridge", "nosepad")
WALL_KINDS = ("eyewire_superior", "eyewire_inferior")

# Canonical step-edge names, keyed by the unordered pair of adjacent zone
# kinds. These are the keys of the footing fillet schedule (teardown §4).
CANONICAL_EDGES: dict[frozenset[str], str] = {
    frozenset({"endpiece", "eyewire_superior"}): "endpiece_superior",
    frozenset({"endpiece", "eyewire_inferior"}): "endpiece_inferior",
    frozenset({"bridge", "eyewire_superior"}): "bridge_superior",
    frozenset({"bridge", "nosepad"}): "nosepad_superior",
    frozenset({"nosepad", "eyewire_inferior"}): "nosepad_inferior",
}

_MIN_FACE_AREA_MM2 = 0.05   # drop numerical slivers from polygonize
_CUT_EXTEND_MM = 1.0        # extend cut ends so they always sever the body
_EDGE_ADJ_BUFFER_MM = 0.2   # half-width used to find a cut's adjacent zones


@dataclass
class Zone:
    name: str        # e.g. "endpiece_od", "bridge", or "zone_3" (generic)
    kind: str        # "endpiece" | "bridge" | "nosepad" | "eyewire_superior" | "eyewire_inferior" | "generic"
    side: str        # "od" | "os" | "" (center / generic)
    polygon: Polygon


@dataclass
class ZoneEdge:
    """A SCULPT section cut after partitioning: the seam between two zones.

    name is '<canonical>_<side>' (e.g. 'endpiece_superior_od') when both
    neighbours are canonical, else 'edge_N'. The footing fillet schedule is
    keyed by the canonical part (side pairs share one radius pair).
    """
    name: str
    canonical: str            # e.g. "endpiece_superior", "" if not canonical
    side: str                 # "od" | "os" | "" (center or generic)
    cut: LineString           # the extended cut line actually used to split
    zone_names: tuple[str, ...]   # adjacent zone names (normally 2)


@dataclass
class CastlePartition:
    body: Polygon                 # OUTLINE minus LENS holes (posterior coords)
    zones: list[Zone] = field(default_factory=list)
    edges: list[ZoneEdge] = field(default_factory=list)
    matched: bool = False         # True when the standard pattern auto-labeled

    def zone(self, name: str) -> Zone:
        for z in self.zones:
            if z.name == name:
                return z
        raise KeyError(name)


def _extend_cut(points: list[tuple[float, float]], ext: float) -> list[tuple[float, float]]:
    """Extend an open polyline beyond both endpoints along its end segments.

    SCULPT cuts are drawn endpoint-snapped to the outline/lens curves; the
    extension guarantees they fully sever the body despite snap tolerance.
    Over-extension is harmless: faces outside the body are discarded.
    """
    pts = [np.asarray(p, dtype=float) for p in points]
    d0 = pts[0] - pts[1]
    dn = pts[-1] - pts[-2]
    n0, nn = np.linalg.norm(d0), np.linalg.norm(dn)
    if n0 > 0:
        pts[0] = pts[0] + d0 / n0 * ext
    if nn > 0:
        pts[-1] = pts[-1] + dn / nn * ext
    return [tuple(p) for p in pts]


def _label_standard(regions: list[Polygon]) -> list[Zone] | None:
    """Label the 9 regions of the 5-cuts-per-side pattern, or None if the
    geometry doesn't behave like the standard castle layout."""
    remaining = list(regions)

    # Endpieces: the two regions reaching furthest outboard.
    remaining.sort(key=lambda r: -abs(r.centroid.x))
    endpieces, remaining = remaining[:2], remaining[2:]
    if endpieces[0].centroid.x * endpieces[1].centroid.x >= 0:
        return None  # both on one side — not the standard layout

    # Bridge: the only region crossing the vertical centerline.
    crossing = [r for r in remaining if r.bounds[0] < 0.0 < r.bounds[2]]
    if len(crossing) != 1:
        return None
    bridge = crossing[0]
    remaining.remove(bridge)

    # Nosepads: the two regions closest to the centerline.
    remaining.sort(key=lambda r: abs(r.centroid.x))
    nosepads, remaining = remaining[:2], remaining[2:]
    if nosepads[0].centroid.x * nosepads[1].centroid.x >= 0:
        return None

    # Walls: per side, superior is the higher of the remaining pair.
    od_walls = sorted((r for r in remaining if r.centroid.x > 0), key=lambda r: -r.centroid.y)
    os_walls = sorted((r for r in remaining if r.centroid.x < 0), key=lambda r: -r.centroid.y)
    if len(od_walls) != 2 or len(os_walls) != 2:
        return None

    def side(poly: Polygon) -> str:
        return "od" if poly.centroid.x > 0 else "os"

    zones = [Zone(f"endpiece_{side(p)}", "endpiece", side(p), p) for p in endpieces]
    zones.append(Zone("bridge", "bridge", "", bridge))
    zones += [Zone(f"nosepad_{side(p)}", "nosepad", side(p), p) for p in nosepads]
    zones.append(Zone("eyewire_superior_od", "eyewire_superior", "od", od_walls[0]))
    zones.append(Zone("eyewire_inferior_od", "eyewire_inferior", "od", od_walls[1]))
    zones.append(Zone("eyewire_superior_os", "eyewire_superior", "os", os_walls[0]))
    zones.append(Zone("eyewire_inferior_os", "eyewire_inferior", "os", os_walls[1]))
    return zones


def _label_generic(regions: list[Polygon]) -> list[Zone]:
    """Deterministic fallback labels: zone_1..N, top-to-bottom then OS->OD."""
    ordered = sorted(regions, key=lambda r: (-round(r.centroid.y, 1), r.centroid.x))
    return [Zone(f"zone_{i + 1}", "generic", "", p) for i, p in enumerate(ordered)]


def _name_edges(cuts: list[LineString], zones: list[Zone]) -> list[ZoneEdge]:
    edges: list[ZoneEdge] = []
    for i, cut in enumerate(cuts):
        buf = cut.buffer(_EDGE_ADJ_BUFFER_MM)
        adjacent = [z for z in zones if z.polygon.intersects(buf)
                    and z.polygon.intersection(buf).area > 1e-3]
        kinds = frozenset(z.kind for z in adjacent)
        canonical = CANONICAL_EDGES.get(kinds, "")
        if canonical and len(adjacent) == 2:
            sides = {z.side for z in adjacent} - {""}
            side = sides.pop() if len(sides) == 1 else ""
            name = f"{canonical}_{side}" if side else canonical
        else:
            canonical, side, name = "", "", f"edge_{i + 1}"
        edges.append(ZoneEdge(name, canonical, side, cut,
                              tuple(z.name for z in adjacent)))
    return edges


def partition_zones(
    outline: Polygon,
    lenses: list[Polygon],
    sculpt_cuts: list[list[tuple[float, float]]],
    extend_mm: float = _CUT_EXTEND_MM,
) -> CastlePartition:
    """Partition the frame body into castle zones along the SCULPT cuts.

    outline / lenses: posterior-coordinate Shapely polygons (from normalize).
    sculpt_cuts: raw open SCULPT polylines (point lists, >= 2 points each)
    straight from import_dxf — they are open curves, so they never survive
    normalize() and must be passed as points.
    """
    body = outline.difference(unary_union(lenses)) if lenses else Polygon(outline)
    if body.geom_type == "MultiPolygon":  # degenerate input; keep the main body
        body = max(body.geoms, key=lambda g: g.area)

    cuts = [LineString(_extend_cut(c, extend_mm)) for c in sculpt_cuts if len(c) >= 2]
    if not cuts:
        return CastlePartition(body=body, zones=_label_generic([body]), matched=False)

    merged = unary_union([body.boundary, *cuts])
    faces = [
        f for f in polygonize(merged)
        if f.area >= _MIN_FACE_AREA_MM2 and body.contains(f.representative_point())
    ]

    zones = None
    matched = False
    if len(cuts) == 10 and len(faces) == 9:
        zones = _label_standard(faces)
        matched = zones is not None
    if zones is None:
        zones = _label_generic(faces)

    return CastlePartition(
        body=body,
        zones=zones,
        edges=_name_edges(cuts, zones),
        matched=matched,
    )
