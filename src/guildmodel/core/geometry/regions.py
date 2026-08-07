"""Castle zone partitioning (BUILDPLAN M1.3).

Partitions the frame-front body (OUTLINE minus LENS holes) into castle zones
using the SCULPT section cuts, and auto-labels them when the standard
5-cuts-per-side pattern matches:

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
# kinds. These are the keys of the footing fillet schedule
# (project.schema.FootingSchedule).
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

#: The nine zone names of the standard castle layout.
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


#: Rounding for `_ring_key`, decimal places on a millimetre. Well below any
#: machining tolerance, and coarse enough to absorb float noise from GEOS.
_RING_KEY_DP = 6


def _ring_key(coords) -> tuple:
    """A hashable identity for a ring: vertex count plus bounding box.

    **Deliberately invariant to where the ring starts and which way it winds.**
    The first attempt keyed on the start point and two points around the ring,
    and it failed on two of three rings: `outline.difference(lenses)` hands back
    geometry whose coordinates are the same set but rotated to a different start
    vertex, and sometimes reversed. Count and extent survive that; a start point
    does not.

    It is also correctly *fragile* in the one way that matters. If Shapely
    genuinely modifies a ring — nodes it against an intersecting cut, inserts a
    vertex — the count changes, the key misses, and the caller falls back to the
    polyline. That is the right answer, because a modified ring is no longer the
    curve the drawing authored.
    """
    n = len(coords)
    if n > 1 and tuple(coords[0][:2]) == tuple(coords[-1][:2]):
        n -= 1                            # closed or not must not change the key
    xs = [float(p[0]) for p in coords]
    ys = [float(p[1]) for p in coords]
    return (n,
            round(min(xs), _RING_KEY_DP), round(min(ys), _RING_KEY_DP),
            round(max(xs), _RING_KEY_DP), round(max(ys), _RING_KEY_DP))


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
    # The exact curves the drawing was made of, where the source had them
    # (`core.geometry.curves`). Optional and purely additive: everything here
    # works unchanged without them, and the B-Rep path uses them to build one
    # exact edge per ring instead of one straight edge per flattened point.
    # Keyed by ring so a caller can ask about a specific boundary — Shapely
    # rings are not hashable, so `ring_curve` matches on the ring's coordinates.
    source_curves: dict = field(default_factory=dict, repr=False)

    def ring_curve(self, ring):
        """The authored `NurbsCurve` for `ring`, or None.

        Matched on the ring's start point and length rather than by identity:
        `partition_zones` runs the rings through Shapely booleans, so the object
        that comes out is never the one that went in, but an *uncut* ring — the
        body exterior and the lens apertures — still has the same coordinates.
        A ring that Shapely genuinely modified will not match, which is the
        correct answer: its curve is no longer the authored one.
        """
        try:
            coords = list(ring.coords)
        except AttributeError:
            coords = list(ring)
        if not coords:
            return None
        return self.source_curves.get(_ring_key(coords))

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

    def curve_list(self) -> list:
        """Every distinct authored curve, for callers matching *partial* rings.

        `ring_curve` answers "is this whole ring one authored curve?", which is
        true for the body exterior and the apertures. A zone boundary is not —
        it is arcs of those curves joined by straight SCULPT cuts — so rebuilding
        one needs the candidates to test each vertex against.
        """
        out: list = []
        for curve in self.source_curves.values():
            if not any(curve is seen for seen in out):
                out.append(curve)
        return out

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
    source_curves: dict | None = None,
) -> CastlePartition:
    """Partition the frame body into castle zones along the SCULPT cuts.

    outline / lenses: posterior-coordinate Shapely polygons (from normalize).
    sculpt_cuts: raw open SCULPT polylines (point lists, >= 2 points each)
    straight from import_dxf — they are open curves, so they never survive
    normalize() and must be passed as points.

    source_curves: optional `{ring_key: NurbsCurve}` from
    `curves_by_ring(...)` — the exact curves the drawing was authored with, for
    the B-Rep path. Purely additive; omit it and everything behaves as before.
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
                               matched=False, holes=holes,
                               source_curves=dict(source_curves or {}))

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
        source_curves=dict(source_curves or {}),
    )


def curves_by_ring(point_lists, curves) -> dict:
    """Build the `source_curves` map `partition_zones` takes.

    `point_lists` and `curves` are the index-aligned pair `import_curves`
    returns for one layer — the flattened points, and what each was flattened
    from. Entries with no source curve are skipped, so a drawing made of
    polylines produces an empty map and the B-Rep path behaves exactly as it
    did before.

    Keyed on the *flattened* ring because that is what survives into Shapely and
    therefore what a later lookup will be holding. `_ring_key` already ignores
    whether the ring repeats its first point, so one entry covers both
    spellings.
    """
    out: dict = {}
    for pts, curve in zip(point_lists, curves or []):
        if curve is None or len(pts) < 3:
            continue
        out[_ring_key([tuple(p[:2]) for p in pts])] = curve
    return out
