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


# Zone kinds (towers + walls); "generic" is the unclassifiable fallback.
# A wall that spans BOTH lenses (an aviator's unified brow, a full-width lower
# wire) is still just an eyewire — it gets side "ou" (oculus uterque, both
# eyes) instead of od/os, and rides the same per-kind height control.
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
    # A unified (OU) superior eyewire reaches down to the nosepads directly —
    # an adjacency the standard split layout never produces (there the bridge
    # sits between), so this entry changes nothing for matched frames.
    frozenset({"nosepad", "eyewire_superior"}): "nosepad_superior",
}

#: The nine zone names of the standard castle layout (DEMO_PROJECT_TEARDOWN §2).
STANDARD_ZONE_NAMES = frozenset({
    "endpiece_od", "endpiece_os", "bridge", "nosepad_od", "nosepad_os",
    "eyewire_superior_od", "eyewire_inferior_od",
    "eyewire_superior_os", "eyewire_inferior_os",
})

_MIN_FACE_AREA_MM2 = 0.05   # drop numerical slivers from polygonize
_CUT_EXTEND_MM = 1.0        # extend cut ends so they always sever the body
_EDGE_ADJ_BUFFER_MM = 0.2   # half-width used to find a cut's adjacent zones


@dataclass
class Zone:
    name: str        # e.g. "endpiece_od", "bridge", or "zone_3" (generic)
    kind: str        # "endpiece" | "bridge" | "nosepad" | "eyewire_superior" | "eyewire_inferior" | "generic"
    side: str        # "od" | "os" | "ou" (both eyes) | "" (center / generic)
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
    # Decorative OUTLINE openings (Hole1..HoleN), carried through so callers can
    # tell them apart from the LENS apertures that share `body.interiors`: holes
    # get cut, but never grooved, and never seed a work-holding keep-out.
    holes: list[Polygon] = field(default_factory=list)

    @property
    def classified(self) -> bool:
        """True when every zone carries an anatomical kind, so the castle relief
        can look a height up for each one. False only for the generic fallback
        (`zone_1..N`), which needs heights supplied by hand."""
        return bool(self.zones) and all(z.kind != "generic" for z in self.zones)

    def is_hole(self, ring) -> bool:
        """True when a ring of ``body.interiors`` is a decorative hole rather
        than a lens opening."""
        point = Polygon(ring).representative_point()
        return any(h.contains(point) for h in self.holes)

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


def _classify_zones(regions: list[Polygon], lenses: list[Polygon]) -> list[Zone] | None:
    """Give every region an anatomical kind, using the LENS openings as the
    reference frame. Returns None when the drawing gives us nothing to reason
    from (fewer than two lenses) or a region can't be placed.

    This is the tolerant successor to the old all-or-nothing 9-zone matcher: it
    classifies each region on its own merits, so frames that aren't the standard
    5-cuts-per-side castle — an aviator's continuous brow bar, a bridge split by
    a decorative opening, extra section cuts — still come out fully named and
    therefore buildable. On the standard layout it reproduces exactly the nine
    canonical names, which is what `partition_zones` checks to set `matched`.
    """
    if len(lenses) < 2:
        return None
    ordered = sorted(lenses, key=lambda p: p.centroid.x)
    os_cx, od_cx = ordered[0].centroid.x, ordered[-1].centroid.x
    lens_cy = (ordered[0].centroid.y + ordered[-1].centroid.y) / 2.0

    remaining = list(regions)
    picked: list[tuple[str, str, Polygon]] = []       # (kind, side, polygon)

    def side_of(poly: Polygon) -> str:
        return "od" if poly.centroid.x > 0 else "os"

    def take(poly: Polygon, kind: str, side: str) -> None:
        picked.append((kind, side, poly))
        # By identity: shapely's __eq__ is geometric, so `list.remove` could
        # drop a different but congruent face (a symmetric frame has plenty).
        for i, r in enumerate(remaining):
            if r is poly:
                del remaining[i]
                break

    # 1 — unified (OU) walls: a region spanning from outboard of one lens
    # centre to outboard of the other is one eyewire serving both eyes — an
    # aviator's fused brow, or a full-width lower wire. Extracted FIRST: such a
    # band can reach the frame's outer corners, and letting the endpiece pick
    # see it could mis-file it on designs with no endpiece cuts. Superior or
    # inferior by its height against the lens centres.
    for r in list(remaining):
        x0, _y0, x1, _y1 = r.bounds
        if x0 < os_cx and x1 > od_cx:
            kind = ("eyewire_superior" if r.centroid.y >= lens_cy
                    else "eyewire_inferior")
            take(r, kind, "ou")

    # 2 — endpieces: per side, the region reaching furthest outboard.
    for want in ("os", "od"):
        candidates = [r for r in remaining if side_of(r) == want]
        if candidates:
            take(max(candidates, key=lambda r: abs(r.centroid.x)), "endpiece", want)

    # 3 — bridge: crosses the vertical centreline. A decorative opening can
    # split it into an over-bar and an under-bar; both are bridge.
    for r in list(remaining):
        if r.bounds[0] < 0.0 < r.bounds[2]:
            take(r, "bridge", "")

    # 4 — nosepads: per side, the region closest to the centreline.
    for want in ("os", "od"):
        candidates = [r for r in remaining if side_of(r) == want]
        if candidates:
            take(min(candidates, key=lambda r: abs(r.centroid.x)), "nosepad", want)

    # 5 — eyewire walls: each remaining region is a wall over its side's lens;
    # superior or inferior by its own height against the lens centres. (Not
    # "highest = superior, rest inferior" — extra section cuts can leave
    # several walls per side, and each deserves its true hemisphere.)
    for want in ("os", "od"):
        for wall in [r for r in remaining if side_of(r) == want]:
            kind = ("eyewire_superior" if wall.centroid.y >= lens_cy
                    else "eyewire_inferior")
            take(wall, kind, want)

    if remaining:
        return None                      # a region we have no story for

    # Stable, canonical-first ordering, then unique names.
    order = {"endpiece": 0, "bridge": 1, "nosepad": 2,
             "eyewire_superior": 3, "eyewire_inferior": 4}
    picked.sort(key=lambda t: (order[t[0]], t[1], -t[2].centroid.y, t[2].centroid.x))

    zones: list[Zone] = []
    used: dict[str, int] = {}
    for kind, side, poly in picked:
        base = f"{kind}_{side}" if side else kind
        used[base] = used.get(base, 0) + 1
        name = base if used[base] == 1 else f"{base}_{used[base]}"
        zones.append(Zone(name, kind, side, poly))
    return zones


def _label_generic(regions: list[Polygon]) -> list[Zone]:
    """Deterministic fallback labels: zone_1..N, top-to-bottom then OS->OD."""
    ordered = sorted(regions, key=lambda r: (-round(r.centroid.y, 1), r.centroid.x))
    return [Zone(f"zone_{i + 1}", "generic", "", p) for i, p in enumerate(ordered)]


def _name_edges(cuts: list[LineString], zones: list[Zone]) -> list[ZoneEdge]:
    edges: list[ZoneEdge] = []
    used: dict[str, int] = {}
    for i, cut in enumerate(cuts):
        buf = cut.buffer(_EDGE_ADJ_BUFFER_MM)
        adjacent = [z for z in zones if z.polygon.intersects(buf)
                    and z.polygon.intersection(buf).area > 1e-3]
        kinds = frozenset(z.kind for z in adjacent)
        canonical = CANONICAL_EDGES.get(kinds, "")
        if canonical and len(adjacent) == 2:
            # "ou" (a both-eyes wall) is side-neutral here: the edge inherits
            # its side from the sided neighbour (endpiece_superior_od, etc.).
            sides = {z.side for z in adjacent} - {"", "ou"}
            side = sides.pop() if len(sides) == 1 else ""
            name = f"{canonical}_{side}" if side else canonical
        else:
            canonical, side, name = "", "", f"edge_{i + 1}"
        # Two symmetric cuts can meet the same unsided zone pair (a brow bar
        # over a bridge); keep the names distinct for the log / inspector. The
        # fillet schedule keys off `canonical`, so this is display-only.
        used[name] = used.get(name, 0) + 1
        if used[name] > 1:
            name = f"{name}_{used[name]}"
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
    # Decorative openings arrive as the outline's own interior rings (see
    # normalize.assemble_outline); they survive the LENS difference untouched.
    holes = [Polygon(r) for r in outline.interiors]

    body = outline.difference(unary_union(lenses)) if lenses else Polygon(outline)
    if body.geom_type == "MultiPolygon":  # degenerate input; keep the main body
        body = max(body.geoms, key=lambda g: g.area)

    cuts = [LineString(_extend_cut(c, extend_mm)) for c in sculpt_cuts if len(c) >= 2]
    if not cuts:
        return CastlePartition(body=body, zones=_label_generic([body]),
                               matched=False, holes=holes)

    merged = unary_union([body.boundary, *cuts])
    faces = [
        f for f in polygonize(merged)
        if f.area >= _MIN_FACE_AREA_MM2 and body.contains(f.representative_point())
    ]

    zones = _classify_zones(faces, list(lenses))
    # `matched` stays narrow: the standard 5-cuts-per-side castle, exactly the
    # nine canonical zones. Everything else is still fully classified (and so
    # still buildable) — it just isn't the reference layout.
    matched = bool(
        zones is not None
        and len(cuts) == 10 and len(faces) == 9
        and {z.name for z in zones} == STANDARD_ZONE_NAMES
    )
    if zones is None:
        zones = _label_generic(faces)

    return CastlePartition(
        body=body,
        zones=zones,
        edges=_name_edges(cuts, zones),
        matched=matched,
        holes=holes,
    )
