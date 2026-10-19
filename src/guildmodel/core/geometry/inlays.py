"""Seats for plaques, laminates and plates: the INLAY layer, resolved into the
one list of cuts every kernel and the CAM read (BUILDPLAN §8a, 2026-10-15).

GuildDraw sends a closed INLAY curve per seat and nothing else; its validator
keeps the geometry cuttable (inside the OUTLINE profile, clear of every LENS,
DRILL and HINGE curve, two seats nesting or apart). Everything a seat needs
beyond its shape lives on the part's parameters as an `InlayFeature`
(`project.schema`), one per curve, and this module is the seam between the two:

* **The containment tree.** A seat inside another seat is a step down from the
  parent's floor; a seat inside a HINGE curve is a step in the hinge pocket's
  floor and inherits its plane, tilt and all. `containment` reads that off the
  polygons, and `ordered` puts the seats in the canonical order the parameters
  are kept in: parents first, then the larger seat, then by centroid.
* **The match.** `reconcile` pairs a drawing's seats with the features a
  project already holds, by containment order and centroid, so a re-imported
  drawing keeps every seat's depth, face and mode, and a new seat starts from
  the part's defaults.
* **The cuts.** `inlay_cuts` turns features plus polygons into `InlayCut`s: a
  region (the seat less its islands), a face, and the plane of its floor. The
  raster carves them, the mesh and the B-Rep subtract them as prisms, the CAM
  pockets the posterior ones, and all four read this list and nothing else:
  the bezel's lesson (`EyewireBezelParams.as_edge_features`), applied before
  the second copy of the maths exists.

**Pairing is positional, the tree is geometric.** The features list is kept
index-aligned with the ordered polygons; a caller that has placed the polygons
on a blank (a temple's snap flips and moves them) hands them over in the same
order, and the parents and hinges are found again from the moved shapes, which
containment does not care about. The order itself is never recomputed from
placed geometry, because a centroid tie-break is not invariant under a turn.

Nothing here imports a kernel, Qt or the CAM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from ..project.schema import InlayFeature
from .pocket_floor import PocketFloor

__all__ = ["InlayCut", "InlayNode", "MATCH_MM", "containment", "inlay_cuts",
           "nesting_levels", "ordered", "polygons_from_curves", "reconcile",
           "zone_reference"]

#: A seat whose centroid moved further than this between two imports is not
#: the same seat for the nearest-centroid pass; the order pass may still pair
#: it. Generous, because a redrawn seat keeps its place but rarely its exact
#: center.
MATCH_MM = 15.0

#: Smallest area a closed INLAY curve must enclose to count, mm².
_MIN_AREA_MM2 = 0.5

#: How much of a seat may lie outside a candidate parent before it is not
#: inside it, as a fraction of the seat's area. The validator forbids a
#: partial overlap, so this only absorbs a shared edge and float noise.
_OUTSIDE_FRACTION = 1e-3


def polygons_from_curves(curves: Sequence[Sequence[tuple[float, float]]]
                         ) -> list[Polygon]:
    """Valid polygons from the INLAY layer's point lists, drawing order kept.

    Mirrors what `derive_workspace` does for HINGE: a curve with too few points,
    an invalid ring or no area is not a seat and is left out.
    """
    from ..io_import.normalize import points_to_polygon

    out: list[Polygon] = []
    for c in curves:
        if len(c) < 3:
            continue
        try:
            p = points_to_polygon(list(c))
        except Exception:                                    # noqa: BLE001
            continue
        if p is not None and p.is_valid and p.area >= _MIN_AREA_MM2:
            out.append(p)
    return out


def _inside(inner: Polygon, outer: Polygon) -> bool:
    if inner.is_empty or outer.is_empty or outer.area <= inner.area:
        return False
    try:
        return inner.difference(outer).area <= _OUTSIDE_FRACTION * inner.area
    except Exception:                                        # noqa: BLE001
        return False


@dataclass(frozen=True)
class InlayNode:
    """One seat's place in the containment tree."""
    index: int
    polygon: Polygon
    parent: int | None       # index of the seat it is drawn inside, if any
    hinge: int | None        # index of the HINGE polygon it is drawn inside
    level: int               # enclosing seats, plus one for a hinge at the root

    @property
    def relative_to(self) -> str:
        if self.parent is not None:
            return "seat"
        return "hinge" if self.hinge is not None else "face"


def containment(polys: Sequence[Polygon], hinges: Sequence[Polygon] = ()
                ) -> list[InlayNode]:
    """The tree, in the order the polygons were given.

    A seat's parent is the smallest other seat that contains it; a root seat's
    hinge is the first HINGE polygon that contains it. Levels follow the
    parents, so a seat two deep in a seat that sits in a hinge is at level 3.
    """
    polys = list(polys)
    hinges = [h for h in hinges if h is not None and not h.is_empty]
    parents: list[int | None] = []
    for i, p in enumerate(polys):
        cands = [j for j, q in enumerate(polys) if j != i and _inside(p, q)]
        parents.append(min(cands, key=lambda j: polys[j].area) if cands else None)

    def root_hinge(i: int) -> int | None:
        for k, h in enumerate(hinges):
            if _inside(polys[i], h):
                return k
        return None

    levels: dict[int, int] = {}
    hinge_of: dict[int, int | None] = {}

    def resolve(i: int) -> int:
        if i in levels:
            return levels[i]
        par = parents[i]
        if par is None:
            hinge_of[i] = root_hinge(i)
            levels[i] = 1 if hinge_of[i] is not None else 0
        else:
            levels[i] = resolve(par) + 1
            hinge_of[i] = hinge_of[par]
        return levels[i]

    for i in range(len(polys)):
        resolve(i)
    return [InlayNode(i, polys[i], parents[i], hinge_of[i], levels[i])
            for i in range(len(polys))]


def ordered(polys: Sequence[Polygon], hinges: Sequence[Polygon] = ()
            ) -> list[Polygon]:
    """The seats in canonical order: parents before children (by level), the
    larger seat first, then by centroid. Deterministic for a drawing."""
    nodes = containment(polys, hinges)

    def key(n: InlayNode):
        c = n.polygon.centroid
        return (n.level, -round(n.polygon.area, 3), round(c.x, 3), round(c.y, 3))

    return [n.polygon for n in sorted(nodes, key=key)]


def nesting_levels(inlay_curves: Sequence[Sequence[tuple[float, float]]],
                   hinge_curves: Sequence[Sequence[tuple[float, float]]] = ()
                   ) -> list[int]:
    """Each INLAY curve's containment level, in the curves' own order, for a
    canvas that draws a nested seat darker. A curve that is not a seat is 0."""
    polys = polygons_from_curves(inlay_curves)
    if not polys:
        return [0] * len(inlay_curves)
    from ..io_import.normalize import points_to_polygon

    hinges = []
    for c in hinge_curves:
        if len(c) >= 3:
            try:
                h = points_to_polygon(list(c))
            except Exception:                                # noqa: BLE001
                continue
            if h is not None and h.is_valid and h.area > 0.5:
                hinges.append(h)
    by_poly = {id(n.polygon): n.level for n in containment(polys, hinges)}
    out: list[int] = []
    k = 0
    for c in inlay_curves:
        # polygons_from_curves kept the order and dropped the non-seats, so
        # walk the two lists together
        if k < len(polys) and len(c) >= 3:
            try:
                p = points_to_polygon(list(c))
            except Exception:                                # noqa: BLE001
                p = None
            if p is not None and p.is_valid and p.area >= _MIN_AREA_MM2:
                out.append(by_poly.get(id(polys[k]), 0))
                k += 1
                continue
        out.append(0)
    return out


# ------------------------------------------------------------------ the match

def _unique_id(taken: set[str]) -> str:
    n = 1
    while f"inlay_{n}" in taken:
        n += 1
    taken.add(f"inlay_{n}")
    return f"inlay_{n}"


def reconcile(features: Sequence[InlayFeature], polys: Sequence[Polygon],
              hinges: Sequence[Polygon] = (), *, default_depth_mm: float = 1.0,
              default_face: str = "anterior") -> list[InlayFeature]:
    """One feature per seat, index-aligned with `polys` (already `ordered`).

    An existing feature follows its seat: first the nearest centroid at the
    same place in the tree within `MATCH_MM`, then whatever is left at that
    place in containment order. A seat nothing matches starts from the part's
    defaults; a feature whose seat is gone is dropped. The derived fields are
    rewritten from the tree every time, so the stored face of a nested seat or
    one in a hinge can never disagree with its parent.

    Idempotent: reconciling a reconciled list against the same polygons hands
    back the same list.
    """
    nodes = containment(polys, hinges)
    kinds = [n.relative_to for n in nodes]
    centers = [(n.polygon.centroid.x, n.polygon.centroid.y) for n in nodes]

    matched: dict[int, InlayFeature] = {}
    free = list(range(len(features)))

    # pass one: the nearest centroid at the same level and kind
    pairs = []
    for fi, f in enumerate(features):
        for ni, n in enumerate(nodes):
            if f.level != n.level or f.relative_to != kinds[ni]:
                continue
            d = ((f.centroid[0] - centers[ni][0]) ** 2
                 + (f.centroid[1] - centers[ni][1]) ** 2) ** 0.5
            if d <= MATCH_MM:
                pairs.append((d, fi, ni))
    for _d, fi, ni in sorted(pairs):
        if fi in free and ni not in matched:
            matched[ni] = features[fi]
            free.remove(fi)

    # pass two: what is left, in containment order, like for like
    for ni, n in enumerate(nodes):
        if ni in matched:
            continue
        for fi in list(free):
            f = features[fi]
            if f.level == n.level and f.relative_to == kinds[ni]:
                matched[ni] = f
                free.remove(fi)
                break

    taken = {f.id for f in matched.values() if f.id}
    out: list[InlayFeature | None] = [None] * len(nodes)

    def build(ni: int) -> InlayFeature:
        if out[ni] is not None:
            return out[ni]
        n = nodes[ni]
        base = matched.get(ni)
        if base is None:
            base = InlayFeature(id=_unique_id(taken), label=f"Seat {ni + 1}",
                                depth_mm=float(default_depth_mm),
                                face=default_face)
        elif not base.id:
            base = base.model_copy(update={"id": _unique_id(taken)})
        face = base.face
        if n.parent is not None:
            face = build(n.parent).face
        elif n.hinge is not None:
            face = "posterior"
        out[ni] = base.model_copy(update={
            "face": face, "relative_to": n.relative_to, "level": n.level,
            "centroid": (float(centers[ni][0]), float(centers[ni][1])),
            "area_mm2": float(n.polygon.area),
        })
        return out[ni]

    for ni in range(len(nodes)):
        build(ni)
    return [f for f in out if f is not None]


# ------------------------------------------------------------------ the cuts

@dataclass(frozen=True)
class InlayCut:
    """One seat as every kernel cuts it.

    `plane` is the floor of the cut in the part's frame: for a posterior seat
    the height above the anterior datum the material is taken down to; for an
    anterior seat the height up to which material is taken off the front. It
    carries the hinge pocket's tilt where the seat sits in one. `reference` is
    the plane the depth was measured from.

    `region` is what is carved: the seat less any island drawn inside it.
    `outline` is the seat as drawn, for the rim the mesher conforms to.
    """
    index: int
    feature: InlayFeature
    outline: Polygon
    region: Polygon
    face: str
    plane: PocketFloor
    reference: PocketFloor
    parent: int | None
    hinge: int | None

    @property
    def posterior(self) -> bool:
        return self.face == "posterior"

    @property
    def depth_mm(self) -> float:
        return float(self.feature.cut_depth_mm())

    def floor_extremes(self) -> tuple[float, float]:
        """(lowest, highest) of the floor plane over the seat."""
        return self.plane.extremes(self.outline)


def _shift(plane: PocketFloor, dz: float) -> PocketFloor:
    return PocketFloor(z_fixed=plane.z_fixed + dz, axis=plane.axis,
                       edge=plane.edge, slope=plane.slope)


def _largest(geom) -> Polygon:
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda g: g.area)
    return geom


def zone_reference(partition, heights: dict[str, float]
                   ) -> Callable[[Polygon], float]:
    """The flat plane a posterior seat on a front measures from: the highest
    terrace it touches. A seat straddling a step is cut from the higher side;
    where the lower terrace already lies below the floor, nothing is cut there
    and the model shows the plaque spanning the step.

    Touching is overlapping by `pocket_floor._TOUCH_MM2`, as a mount's terrace
    is found: a seat that only met a higher neighbor along a seam was
    measured from it (the 2.0 bug hunt)."""
    from .pocket_floor import _TOUCH_MM2
    zones = list(getattr(partition, "zones", []) or [])
    fallback = max(heights.values()) if heights else 0.0

    def reference(poly: Polygon) -> float:
        hs = [heights[z.name] for z in zones
              if z.name in heights and z.polygon.intersects(poly)
              and z.polygon.intersection(poly).area >= _TOUCH_MM2]
        return max(hs) if hs else fallback

    return reference


def inlay_cuts(features: Sequence[InlayFeature], polys: Sequence[Polygon],
               hinge_floors: Sequence[tuple[Polygon, PocketFloor]] = (), *,
               posterior_reference: Callable[[Polygon], float] | float = 0.0,
               ) -> list[InlayCut]:
    """The cuts, parents before children, from features and polygons that are
    index-aligned (`reconcile` made them so).

    `hinge_floors` is what `geometry.pocket_floor.castle_pocket_floors` or
    `temple_pocket_floors` returns: each hinge pocket with its floor plane, the
    plane a seat drawn inside it inherits. `posterior_reference` gives the flat
    height a root posterior seat measures from — a temple's thickness, or
    `zone_reference` on a front.

    A disabled seat is not cut, and neither is anything drawn inside it: with
    the parent gone a child has nothing to be a step in.
    """
    polys = list(polys)
    n_feat = min(len(features), len(polys))
    if n_feat == 0:
        return []
    hinge_polys = [p for p, _ in hinge_floors]
    floors = [f for _, f in hinge_floors]
    nodes = containment(polys[:n_feat], hinge_polys)
    ref_of = (posterior_reference if callable(posterior_reference)
              else (lambda _poly, h=float(posterior_reference): h))

    children: dict[int, list[int]] = {}
    for n in nodes:
        if n.parent is not None:
            children.setdefault(n.parent, []).append(n.index)

    cuts: dict[int, InlayCut | None] = {}

    def resolve(i: int) -> InlayCut | None:
        if i in cuts:
            return cuts[i]
        n = nodes[i]
        f = features[i]
        if not f.enabled:
            cuts[i] = None
            return None
        if n.parent is not None:
            parent = resolve(n.parent)
            if parent is None:
                cuts[i] = None
                return None
            # A step goes down from the parent's floor; an island stands in
            # the parent's pocket and measures from what the parent measured
            # from, so a depth of 0 leaves it at the surrounding surface.
            face = parent.face
            reference = parent.reference if f.mode == "island" else parent.plane
        elif n.hinge is not None:
            face, reference = "posterior", floors[n.hinge]
        else:
            face = f.face
            reference = PocketFloor(z_fixed=(float(ref_of(n.polygon))
                                             if face == "posterior" else 0.0))
        depth = float(f.cut_depth_mm())
        plane = _shift(reference, -depth if face == "posterior" else depth)
        islands = [polys[c] for c in children.get(i, [])
                   if features[c].enabled and features[c].mode == "island"]
        region = n.polygon
        if islands:
            region = _largest(n.polygon.difference(unary_union(islands)))
        cuts[i] = InlayCut(index=i, feature=f, outline=n.polygon, region=region,
                           face=face, plane=plane, reference=reference,
                           parent=n.parent, hinge=n.hinge)
        return cuts[i]

    out: list[InlayCut] = []
    for i in range(n_feat):
        c = resolve(i)
        if c is not None:
            out.append(c)
    # parents first, whatever order the pairs arrived in
    return sorted(out, key=lambda c: (nodes[c.index].level, c.index))
