"""The flat front prepared to be formed (BUILDPLAN M18, the 2026-09-25 rework).

`ThermoformMap` moves vertices; what it can show depends on which vertices
there are. The first M18 build refined the whole part to one edge length and
warped that, and in practical use the maker saw two things wrong with it:
streaks across the rims, and a ragged crease at the bridge. Both were the
tessellation, not the map, and this module is the answer to both:

1. **The base is simplified before it is refined.** A castle straight from
   the booleans carries three vertices for every one its shape needs, and
   between them run slivers thinner than the chord sag of their own length.
   A sliver like that comes out of the warp with a normal along the surface
   instead of out of it, and smooth shading draws that as a streak. Manifold's
   `simplify` at `SIMPLIFY_TOL_MM` takes 84 % of them out of the gabriel
   without moving a dimension; area-weighted vertex normals (below) make the
   rest weightless.
2. **The flat mesh is cut along the creases.** The crease is a fold in the
   map — a slope discontinuity in the bump — and a triangle straddling it
   shows the fold as a zigzag between its vertices. `split_by_planes` puts a
   vertex chain exactly on each crease plane (and on the top edge, where the
   apex profile kinks), so the fold is a mesh edge and the two sides are
   planar to within the die's own facets.
3. **The band is refined finely and the rest coarsely.** The die is 2-10 mm
   in radius against the rim's 144, so `refine_band` halves the edges inside
   the bump's region (`ThermoformMap.in_band`) two or three times more than
   the rest — a conforming red-green subdivision with no T-junctions.
4. **Vertex normals are the map's, area-weighted, split at the creases.**
   The viewer used to let VTK derive normals from the formed faces and split
   them at 40 degrees; a 30 degree crease came out smooth-shaded and a
   sliver's normal counted as much as its neighbours'. `FormingMesh.formed`
   hands over normals it computed itself: area-weighted over the formed
   faces, with a vertex duplicated wherever the flat part has a real edge
   (walls, pockets) and wherever a live crease runs, so a crease is sharp at
   any angle and a blended crease is not.
5. **A sliver borrows its neighbours' normal.** The simplification moves
   vertices by up to a micron, and a face thinner than that
   (`SLIVER_HEIGHT_MM`) has a normal pointing anywhere. Read as a fold it
   cut the smooth patch at the outline into flat wedges with a hairline
   between them — the chatter the maker saw along the posterior outline of
   the Paula; joined blindly it could bridge a wall and a top face into one
   patch and put a spot at the corner. So it takes the normal of the smooth
   side it lies on — the largest mutually smooth group among its
   neighbours — and is judged like any other face, while a face thick
   enough to have a normal of its own keeps it, however thin. Slivers weigh
   nothing in the vertex normals, and no edge is drawn along a face under
   `THIN_HEIGHT_MM`.
6. **The file is welded in float32.** An STL carries float32, which at
   x = 60 mm resolves 4 microns, coarser than the band's finest nodes sit;
   `weld_for_file` rounds, merges and drops the faces that collapse, so a
   slicer that welds by position reads one closed body rather than 141
   edges shared by four faces.

Everything here is numpy over `(vertices, faces)`; Manifold is used once, to
simplify and coarsely refine the base, and nothing goes back through it. The
formed mesh returned is a `trimesh.Trimesh` with `process=False` whose
vertices along the creases and edges are duplicated *by design*: every
consumer — `feature_edges`, `verify_mesh`, the STL writer, `volume` — welds
by position or does not care. It is not fed back into Manifold. The export
goes through `weld_for_file` first.
"""
from __future__ import annotations

import numpy as np

from .thermoform import (EXPORT_FINE_MM, EXPORT_REFINE_MM, PREVIEW_FINE_MM,
                         PREVIEW_REFINE_MM, SIMPLIFY_TOL_MM, ThermoformMap,
                         manifold_from_trimesh)

#: How many crease layouts `FormingMesh` keeps prepared: the live one and a few behind it.
_PREPARED_KEEP = 4

__all__ = [
    "DRAW_ANGLE_DEG",
    "FormingMesh",
    "SLIVER_HEIGHT_MM",
    "SPLIT_ANGLE_DEG",
    "THIN_HEIGHT_MM",
    "area_weighted_normals",
    "refine_band",
    "split_by_plane",
    "split_by_planes",
    "weld_for_file",
    "split_sharp_vertices",
]

#: Dihedral angle above which two flat faces meeting at an edge get their own
#: normals, degrees — the same figure the viewer used for VTK's split, so the
#: footing blends stay soft and the walls stay hard.
SPLIT_ANGLE_DEG = 40.0

#: Dihedral angle above which an edge is one the viewer draws in the edge
#: display modes: `core.model.edges`'s own crease threshold.
DRAW_ANGLE_DEG = 20.0

#: Vertices closer to a cut plane than this are snapped onto it rather than
#: cut a hair away from it, mm. Well under any dimension and well over the
#: rounding a projection onto the plane leaves.
_SNAP_MM = 1e-6

#: Under this height over its longest edge, mm, a face is a sliver whose
#: normal is noise: the simplification moves vertices by up to
#: `SIMPLIFY_TOL_MM`, which can tilt the normal of a face this thin by 27
#: degrees and one half as thick by 45. It borrows its neighbours' normal
#: for the split (see `prepared`) and weighs nothing in the vertex normals.
SLIVER_HEIGHT_MM = 2e-6

#: Under this height a face's normal is still good to a degree, but not to
#: the edge detector's twenty: no edge is drawn along it.
THIN_HEIGHT_MM = 1e-4

_EDGE = np.array([[0, 1], [1, 2], [2, 0]])


def _rotate_rows(F, shift):
    """Each row of ``F`` rotated left by its own ``shift`` (0, 1 or 2)."""
    idx = (np.arange(3)[None, :] + shift[:, None]) % 3
    return np.take_along_axis(F, idx, axis=1)


def _unique_edges(F):
    """``(edges, inverse)``: the mesh's unique undirected edges, and for each
    face its three edges' indices into them, in ``_EDGE`` order. Keyed as one
    integer per edge: five times faster than a row-wise unique on a mesh
    this size, and the refinement runs it once a round."""
    e = np.sort(F[:, _EDGE].reshape(-1, 2), axis=1)
    n = int(F.max()) + 1 if len(F) else 1
    key = e[:, 0] * n + e[:, 1]
    uniq, inv = np.unique(key, return_inverse=True)
    edges = np.stack([uniq // n, uniq % n], axis=1)
    return edges, inv.reshape(-1, 3)


# ---------------------------------------------------------------- plane cuts

def split_by_plane(V, F, normal, offset, snap_mm: float = _SNAP_MM):
    """Cut every face that crosses the plane ``normal . q = offset``, keeping
    both sides, so the plane's trace is a chain of mesh edges.

    Conforming: a crossing edge gets one new vertex, shared by both faces on
    it, so a closed input stays closed. A vertex within ``snap_mm`` of the
    plane is moved onto it and treated as on it. Returns ``(V, F)``.
    """
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    n = np.asarray(normal, dtype=np.float64)
    n = n / np.linalg.norm(n)
    s = V @ n - float(offset)
    near = np.abs(s) < snap_mm
    if near.any():
        V = V.copy()
        V[near] -= s[near, None] * n
        s = s.copy()
        s[near] = 0.0
    sg = np.sign(s[F])                                 # (m, 3): -1, 0, +1
    cross = sg[:, _EDGE[:, 0]] * sg[:, _EDGE[:, 1]] < 0     # (m, 3) per edge
    if not cross.any():
        return V, F
    edges = np.sort(F[:, _EDGE][cross], axis=1)        # (k, 2)
    uniq, inv = np.unique(edges, axis=0, return_inverse=True)
    a, b = uniq[:, 0], uniq[:, 1]
    t = s[a] / (s[a] - s[b])
    new = V[a] + t[:, None] * (V[b] - V[a])
    new -= ((new @ n) - float(offset))[:, None] * n    # exactly on the plane
    ids = len(V) + np.arange(len(uniq))
    V = np.vstack([V, new])
    mid = np.full(F.shape, -1, dtype=np.int64)
    mid[cross] = ids[inv.ravel()]
    k = cross.sum(axis=1)

    out = [F[k == 0]]
    # two crossings: the lone vertex is the one both crossing edges share —
    # rotate it to position 0, where its edges are e0 = (0,1) and e2 = (2,0)
    two = k == 2
    if two.any():
        Ft, Mt = F[two], mid[two]
        lone = np.where(~cross[two][:, 1], 0, np.where(~cross[two][:, 2], 1, 2))
        Ft, Mt = _rotate_rows(Ft, lone), _rotate_rows(Mt, lone)
        v0, v1, v2, m01, m20 = Ft[:, 0], Ft[:, 1], Ft[:, 2], Mt[:, 0], Mt[:, 2]
        out += [np.stack([v0, m01, m20], 1), np.stack([m01, v1, v2], 1),
                np.stack([m01, v2, m20], 1)]
    # one crossing: the third vertex sits on the plane — rotate the crossing
    # edge to e0
    one = k == 1
    if one.any():
        Fo, Mo = F[one], mid[one]
        which = np.argmax(cross[one], axis=1)
        Fo, Mo = _rotate_rows(Fo, which), _rotate_rows(Mo, which)
        v0, v1, v2, m01 = Fo[:, 0], Fo[:, 1], Fo[:, 2], Mo[:, 0]
        out += [np.stack([v0, m01, v2], 1), np.stack([m01, v1, v2], 1)]
    return V, np.vstack(out)


def split_by_planes(V, F, planes):
    """`split_by_plane` for each ``(normal, offset, kind)`` in turn."""
    for normal, offset, _ in planes:
        V, F = split_by_plane(V, F, normal, offset)
    return V, F


# ---------------------------------------------------------- band refinement

def refine_band(V, F, target_mm: float, inside, max_rounds: int = 10):
    """Halve every edge in the band longer than ``target_mm``, and again,
    until none is: conforming subdivision, one edge at a time.

    A face with all three edges halved splits into four, with two into three
    (the quad along its shorter diagonal), with one into two; a face outside
    the band only ever splits to match a neighbour, so there is never a
    T-junction. The rule is per *edge*, not per face, on purpose: the castle's
    faces are slivers, and halving all three edges of a sliver makes four
    slivers, whereas halving only its long edges makes three shorter ones
    and leaves the short edge alone — the same geometry for a third fewer
    triangles per round (110 thousand against 44 on the gabriel's band).
    ``inside(V, edges)`` returns a boolean per edge. Returns ``(V, F)``.
    """
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    for _ in range(max_rounds):
        edges, inv = _unique_edges(F)
        length = np.linalg.norm(V[edges[:, 0]] - V[edges[:, 1]], axis=1)
        split = (length > target_mm) & inside(V, edges)
        if not split.any():
            break
        mids = 0.5 * (V[edges[split, 0]] + V[edges[split, 1]])
        mid_id = np.full(len(edges), -1, dtype=np.int64)
        mid_id[split] = len(V) + np.arange(int(split.sum()))
        V = np.vstack([V, mids])
        M = mid_id[inv]                                # (m, 3), -1 where unsplit
        k = (M >= 0).sum(axis=1)

        out = [F[k == 0]]
        three = k == 3
        if three.any():
            Ft, Mt = F[three], M[three]
            v0, v1, v2 = Ft[:, 0], Ft[:, 1], Ft[:, 2]
            m01, m12, m20 = Mt[:, 0], Mt[:, 1], Mt[:, 2]
            out += [np.stack([v0, m01, m20], 1), np.stack([m01, v1, m12], 1),
                    np.stack([m20, m12, v2], 1), np.stack([m01, m12, m20], 1)]
        two = k == 2
        if two.any():
            Ft, Mt = F[two], M[two]
            unsplit = np.argmin(Mt, axis=1)            # the one -1
            shift = (unsplit + 1) % 3                  # bring it to e2 = (2, 0)
            Ft, Mt = _rotate_rows(Ft, shift), _rotate_rows(Mt, shift)
            v0, v1, v2, m01, m12 = Ft[:, 0], Ft[:, 1], Ft[:, 2], Mt[:, 0], Mt[:, 1]
            out.append(np.stack([m01, v1, m12], 1))
            # the quad (v0, m01, m12, v2) along its shorter diagonal
            d_a = np.linalg.norm(V[v0] - V[m12], axis=1)
            d_b = np.linalg.norm(V[m01] - V[v2], axis=1)
            use_a = d_a <= d_b
            out += [np.stack([v0, m01, m12], 1)[use_a], np.stack([v0, m12, v2], 1)[use_a],
                    np.stack([v0, m01, v2], 1)[~use_a], np.stack([m01, m12, v2], 1)[~use_a]]
        one = k == 1
        if one.any():
            Fo, Mo = F[one], M[one]
            which = np.argmax(Mo, axis=1)
            Fo, Mo = _rotate_rows(Fo, which), _rotate_rows(Mo, which)
            v0, v1, v2, m01 = Fo[:, 0], Fo[:, 1], Fo[:, 2], Mo[:, 0]
            out += [np.stack([v0, m01, v2], 1), np.stack([m01, v1, v2], 1)]
        F = np.vstack(out)
    return V, F


# ---------------------------------------------------------- normal splitting

def _face_normals(V, F):
    """Unit normals and twice the areas of the faces; a degenerate face gets
    a zero normal and zero weight rather than NaN."""
    c = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    w = np.linalg.norm(c, axis=1)
    n = np.divide(c, w[:, None], out=np.zeros_like(c), where=w[:, None] > 0)
    return n, w


def _borrowed_normals(fn, w, sliver, nbr, cos_split, max_rounds: int = 64):
    """``fn`` with every sliver's normal replaced by that of the largest
    mutually smooth group among its three edge neighbours (``nbr``, -1 at a
    boundary): largest by count, then by area. A sliver in the middle of a
    smooth patch so joins both its sides, and one at a corner sides with the
    faces on one side of the corner and never bridges it. Zero where it has
    no neighbour with a normal (a cluster of slivers, which then stands
    alone); a fan of slivers resolves from both ends inward, one face a
    round, until nothing changes."""
    eff = fn.copy()
    eff[sliver] = 0.0
    S = np.where(sliver)[0]
    if len(S) == 0:
        return eff
    for _ in range(max_rounds):
        nb = nbr[S]                                       # (k, 3)
        has = nb >= 0
        safe = np.where(has, nb, 0)
        n = eff[safe] * has[:, :, None]                   # (k, 3, 3)
        a = w[safe] * has                                 # (k, 3)
        valid = np.linalg.norm(n, axis=2) > 0             # (k, 3)
        dots = np.einsum("kij,klj->kil", n, n)            # (k, i, l)
        group = valid[:, :, None] & valid[:, None, :] & (dots >= cos_split)
        count = group.sum(axis=2)
        area = (group * a[:, None, :]).sum(axis=2)
        score = count * (a.sum(axis=1, keepdims=True) + 1.0) + area
        g = group[np.arange(len(S)), np.argmax(score, axis=1)]   # (k, 3)
        acc = np.einsum("kj,kjl->kl", g * a, n)
        norm = np.linalg.norm(acc, axis=1)
        new = np.divide(acc, norm[:, None], out=np.zeros_like(acc),
                        where=norm[:, None] > 0)
        settled = np.abs(new - eff[S]).max() < 1e-12
        eff[S] = new
        if settled:
            break
    return eff


def split_sharp_vertices(V, F, sharp_edge):
    """Duplicate every vertex once per smooth patch it belongs to.

    ``sharp_edge(V, F, edges, adjacency)`` returns a boolean per unique
    edge, given ``(fa, fb, pair, ha, hb)``: the two faces on each two-sided
    edge, which edges those are, and their half-edges ``3 f + e``; faces
    are joined across every edge that is not sharp, and a
    vertex is copied for each connected patch of faces around it. Returns
    ``(F2, origin)``: faces over the split vertices, and for each split
    vertex the original it copies.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    edges, inv = _unique_edges(F)
    face_of = np.repeat(np.arange(len(F)), 3)
    order = np.argsort(inv.ravel(), kind="stable")
    counts = np.bincount(inv.ravel(), minlength=len(edges))
    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    pair = counts == 2
    ha, hb = order[starts[pair]], order[starts[pair] + 1]    # half-edges 3 f + e
    fa, fb = face_of[ha], face_of[hb]
    sharp = sharp_edge(V, F, edges, (fa, fb, pair, ha, hb))
    join = ~sharp[pair]
    m = len(F)
    graph = coo_matrix((np.ones(int(join.sum())), (fa[join], fb[join])), shape=(m, m))
    _, patch = connected_components(graph, directed=False)
    key = patch[:, None] * len(V) + F
    uniq, F2 = np.unique(key, return_inverse=True)
    return F2.reshape(F.shape), uniq % len(V)


def area_weighted_normals(V, F, n_vertices: int | None = None):
    """Per-vertex unit normals, each face's counted by its area, so a sliver
    contributes what it is: next to nothing."""
    n_vertices = len(V) if n_vertices is None else n_vertices
    fn, w = _face_normals(V, F)
    acc = np.zeros((n_vertices, 3))
    for i in range(3):
        for j in range(3):
            acc[:, j] += np.bincount(F[:, i], weights=fn[:, j] * w, minlength=n_vertices)
    norm = np.linalg.norm(acc, axis=1)
    return np.divide(acc, norm[:, None], out=np.zeros_like(acc), where=norm[:, None] > 0)


# ------------------------------------------------------------ for the file

def weld_for_file(mesh):
    """The formed part as an STL reader will see it: vertices rounded to
    float32 (all an STL carries), coincident ones merged, and the faces that
    collapse to a line dropped.

    The band's finest nodes can sit closer together than a float32 resolves
    at x = 60 mm (4 microns), and a reader that welds by position then finds
    the same edge in four faces and calls the part non-manifold (141 such
    edges on the maker's Paula export); welded here first, it reads as one
    closed body. Returns a `trimesh.Trimesh`, closed by index.
    """
    import trimesh

    V = np.asarray(mesh.vertices, dtype=np.float32).astype(np.float64)
    F = np.asarray(mesh.faces, dtype=np.int64)
    uniq, inv = np.unique(V, axis=0, return_inverse=True)
    F = np.asarray(inv).reshape(-1)[F]
    keep = (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 2] != F[:, 0])
    out = trimesh.Trimesh(vertices=uniq, faces=F[keep], process=False)
    out.remove_unreferenced_vertices()
    return out


# --------------------------------------------------------------- the object

class _Prepared:
    """One crease layout's cut, refined and split flat mesh, and the edges
    the viewer draws on it as vertex pairs into ``V``."""
    __slots__ = ("V", "F", "F2", "origin", "edge_pairs")

    def __init__(self, V, F, F2, origin, edge_pairs):
        self.V, self.F, self.F2, self.origin = V, F, F2, origin
        self.edge_pairs = edge_pairs


class FormingMesh:
    """A flat front, ready to be formed by any `ThermoformMap` quickly.

    Built once per flat mesh: the base is simplified and coarsely refined
    through Manifold (or, for a mesh Manifold rejects — a B-Rep tessellation
    is usually open — subdivided in place, which keeps the surface continuous
    but not watertight). Then, per crease layout (`ThermoformMap.layout_key`),
    cut along the crease planes, refined in the band and split at the sharp
    edges; that is cached, so a drag of the base curve, the face form, the
    projection or the die pays for the warp and the normals alone.
    """

    def __init__(self, flat, *, coarse_mm: float = PREVIEW_REFINE_MM,
                 fine_mm: float = PREVIEW_FINE_MM) -> None:
        self.flat = flat
        self.coarse_mm = float(coarse_mm)
        self.fine_mm = float(fine_mm)
        self._base = None
        self._exact = None
        self._prepared: dict = {}

    @classmethod
    def for_export(cls, flat) -> "FormingMesh":
        return cls(flat, coarse_mm=EXPORT_REFINE_MM, fine_mm=EXPORT_FINE_MM)

    @property
    def exact(self) -> bool:
        """True when the base went through Manifold: closed in, closed out."""
        self._coarse()
        return bool(self._exact)

    def _coarse(self):
        if self._base is None:
            import trimesh

            from guildmodel.core.model.kernel import ManifoldError, to_trimesh

            if len(self.flat.faces) == 0:
                raise ManifoldError("cannot form an empty mesh")
            try:
                man = manifold_from_trimesh(self.flat)
            except ManifoldError:
                v, f = trimesh.remesh.subdivide_to_size(
                    np.asarray(self.flat.vertices, dtype=np.float64),
                    np.asarray(self.flat.faces), max_edge=self.coarse_mm)
                self._base = (np.asarray(v, dtype=np.float64), np.asarray(f, dtype=np.int64))
                self._exact = False
            else:
                m = to_trimesh(man.simplify(SIMPLIFY_TOL_MM).refine_to_length(self.coarse_mm))
                self._base = (np.asarray(m.vertices, dtype=np.float64),
                              np.asarray(m.faces, dtype=np.int64))
                self._exact = True
        return self._base

    def prepared(self, fmap: ThermoformMap, *, quick: bool = False) -> _Prepared:
        """The flat mesh cut, refined and split for `fmap`'s crease layout,
        from the cache when it has been done. ``quick`` skips the cut and
        the band refinement — the coarse base, split at the part's own
        edges — for a handle that is moving the layout itself, where every
        tick would otherwise re-cut; the release does it properly."""
        key = ("quick",) if quick else fmap.layout_key()
        hit = self._prepared.get(key)
        if hit is not None:
            self._prepared[key] = self._prepared.pop(key)    # most recent last
            return hit
        V, F = self._coarse()
        planes = [] if quick else fmap.crease_planes()
        if planes:
            V, F = split_by_planes(V, F, planes)
            margin = fmap.bump_margin_mm()

            def inside(V, edges):
                a, b = V[edges[:, 0]], V[edges[:, 1]]
                m = 0.5 * (a + b)
                return (fmap.in_band(m[:, 0], m[:, 1], margin)
                        | fmap.in_band(a[:, 0], a[:, 1], margin)
                        | fmap.in_band(b[:, 0], b[:, 1], margin))

            V, F = refine_band(V, F, self.fine_mm, inside)
        live = [(n, d, kind) for n, d, kind in planes
                if fmap.is_creased and kind[0] != "top"]
        cos_split = float(np.cos(np.radians(SPLIT_ANGLE_DEG)))
        cos_draw = float(np.cos(np.radians(DRAW_ANGLE_DEG)))
        drawn = {}

        def sharp_edge(V, F, edges, adjacency):
            fa, fb, pair, ha, hb = adjacency
            fn, w = _face_normals(V, F)
            # A sliver thinner than the noise its vertices carry has a normal
            # that means nothing. Read as a fold, it cuts the smooth patch at
            # the outline into wedges, each drawn flat with a hairline
            # between them (the chatter the maker saw along the posterior
            # outline); joined blindly, it can bridge a wall and a top face
            # into one patch and put a 45-degree spot at the corner. So it
            # takes the normal of the smooth side it lies on (its
            # neighbours' largest mutually smooth group) and is then judged
            # like any other face; a face thick enough to have a normal of
            # its own keeps it, however thin.
            longest = np.linalg.norm(V[F[:, [1, 2, 0]]] - V[F], axis=2).max(axis=1)
            sliver = w <= SLIVER_HEIGHT_MM * longest
            thin = w <= THIN_HEIGHT_MM * longest
            nbr = np.full((len(F), 3), -1, dtype=np.int64)
            nbr[ha // 3, ha % 3] = fb
            nbr[hb // 3, hb % 3] = fa
            eff = _borrowed_normals(fn, w, sliver, nbr, cos_split)
            dot = np.einsum("ij,ij->i", eff[fa], eff[fb])
            sharp = np.zeros(len(edges), dtype=bool)
            sharp[pair] = dot < cos_split
            crease = np.zeros(len(edges), dtype=bool)
            for n, d, kind in live:
                on = (np.abs(V[edges[:, 0]] @ n - d) < 1e-6) & (
                    np.abs(V[edges[:, 1]] @ n - d) < 1e-6)
                if on.any():
                    mid = 0.5 * (V[edges[on, 0]] + V[edges[on, 1]])
                    on[np.where(on)[0][~fmap.crease_is_live(mid[:, :2], kind)]] = False
                    crease |= on
            # The edges the viewer draws: the part's own creases at the
            # detector's angle, plus the live crease lines. A smooth map
            # bends no other edge into a crease, so they are known here,
            # once, and warped by index on every tick instead of detected on
            # the formed surface (51 ms a tick on the gabriel).
            draw = np.zeros(len(edges), dtype=bool)
            draw[pair] = ~thin[fa] & ~thin[fb] & (dot < cos_draw)
            drawn["pairs"] = edges[draw | crease]
            return sharp | crease

        F2, origin = split_sharp_vertices(V, F, sharp_edge)
        out = _Prepared(V, F, F2, origin, drawn["pairs"])
        self._prepared[key] = out
        # A few layouts, not every one ever settled: an entry is 6.6 MB on
        # the gabriel preview, and a session exploring the crease layout
        # accumulated hundreds of MB before the base was next rebuilt.
        while len(self._prepared) > _PREPARED_KEEP:
            self._prepared.pop(next(iter(self._prepared)))
        return out

    def formed_edges(self, fmap: ThermoformMap, *, quick: bool = False):
        """The edges the viewer draws on the formed part, as a ``(K, 2, 3)``
        array of segments — what `core.model.feature_edges` would find on the
        formed surface, by index (see `prepared`)."""
        prep = self.prepared(fmap, quick=quick)
        return fmap(prep.V)[prep.edge_pairs]

    def formed(self, fmap: ThermoformMap, *, display: bool = False,
               quick: bool = False):
        """The formed part as a `trimesh.Trimesh`.

        Plain, it is the cut and refined flat mesh warped, closed by index
        exactly as the flat one was: what the export writes and the gates
        verify. With ``display=True`` it is the same surface over the split
        vertices, carrying the vertex normals the viewer should draw with
        (see the module docstring on why they are not VTK's); its vertices
        along every edge and crease are duplicated by design, so it welds
        to the plain one and is not one body by index. ``quick`` is
        `prepared`'s.
        """
        import trimesh

        prep = self.prepared(fmap, quick=quick)
        P = fmap(prep.V)
        if not display:
            return trimesh.Trimesh(vertices=P, faces=prep.F, process=False)
        P = P[prep.origin]
        N = area_weighted_normals(P, prep.F2)
        return trimesh.Trimesh(vertices=P, faces=prep.F2, vertex_normals=N,
                               process=False)
