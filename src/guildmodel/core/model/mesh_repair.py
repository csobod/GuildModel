"""Mesh repair for sculpts (BUILDPLAN M22 §7.2, redone 2026-11-01).

An STL a maker drops is rarely a solid. The ladder `sculpt.load_sculpt`
climbs is here, Qt-free and importable headless:

* **Capping.** `boundary_loops` walks every hole along the faces' own fans,
  so a vertex two holes share (a pinch) is passed through on the right
  side, and `cap_holes` closes each loop: a fan for a small hole, an ear
  clip in the loop's fitted plane for a large one (a relief whose back was
  cut away at export, the common case). A fin, a face that repeats a
  directed edge, is dropped first. Measured on the maker's elements: 16 open
  pieces capped and unioned in 0.8 s where the mesh fixer took 6.9 s and
  lost a tenth of the volume.
* **Relief remesh.** `relief_remesh` rebuilds a sculpt as a heightfield
  over its back plane: the upper envelope on a grid, a flat bottom, walls
  along the footprint. Deterministic and indifferent to the topology, at
  the price of undercuts (which a three-axis tool cannot cut anyway) and a
  resampling at a fraction of the sculpt's size. A 326 mm filigree with
  pinches the fixer destroyed (one corner of it came back) rebuilds whole.
* **The loss guard.** `kept_enough` is what the mesh fixer's result must
  pass: most of the surface and the whole of the extent.
"""
from __future__ import annotations

import math

import numpy as np

__all__ = [
    "boundary_loops", "cap_holes", "drop_fins", "ear_clip", "kept_enough",
    "relief_remesh", "relief_resolution",
]

#: A loop up to this many vertices is capped by a fan from its centroid; a
#: longer one is ear-clipped in its fitted plane.
FAN_UP_TO = 8
#: The surface fraction and the extent fraction a repair must keep.
KEEP_AREA = 0.7
KEEP_EXTENT = 0.95
#: The relief remesh samples at the longest extent over this, floored.
REMESH_DIVISIONS = 600
REMESH_MIN_MM = 0.02


# ------------------------------------------------------------------ halfedges

def _halfedges(F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Directed edges of every face, 3 per face in face order, and the twin
    of each (the index of the opposite directed edge, -1 for none, -2 when
    the opposite occurs more than once)."""
    F = np.asarray(F, dtype=np.int64)
    n = int(F.max()) + 1 if len(F) else 1
    a = F[:, [0, 1, 2]].ravel()
    b = F[:, [1, 2, 0]].ravel()
    key = a * n + b
    rkey = b * n + a
    order = np.argsort(key, kind="stable")
    skey = key[order]
    # the position of each reverse key in the sorted keys, if present once
    pos = np.searchsorted(skey, rkey)
    pos_c = np.minimum(pos, len(skey) - 1)
    hit = skey[pos_c] == rkey
    twin = np.where(hit, order[pos_c], -1)
    # an opposite that occurs twice: the next sorted key is the same
    nxt = np.minimum(pos_c + 1, len(skey) - 1)
    dup = hit & (skey[nxt] == rkey) & (nxt != pos_c)
    twin[dup] = -2
    return np.c_[a, b], twin


def boundary_loops(F: np.ndarray) -> tuple[list[np.ndarray], int]:
    """The holes of a triangle mesh as closed vertex loops, in the order the
    hole sees them (a cap's triangles run each loop forward and pair with
    the faces), plus the count of directed edges that occur more than once
    (fins, to drop before capping).

    Each loop is walked from boundary halfedge to boundary halfedge by
    rotating around the shared vertex through the faces' fans, which is
    what carries the walk through a pinch vertex on the right side; a loop
    that meets a repeated edge on the way is abandoned.
    """
    F = np.asarray(F, dtype=np.int64)
    if len(F) == 0:
        return [], 0
    he, twin = _halfedges(F)
    dups = int((twin == -2).sum())
    boundary = np.flatnonzero(twin == -1)
    if len(boundary) == 0:
        return [], dups
    prev_in_face = lambda h: h - 1 if h % 3 else h + 2        # noqa: E731
    seen = np.zeros(len(he), dtype=bool)
    loops: list[np.ndarray] = []
    for start in boundary:
        if seen[start]:
            continue
        loop: list[int] = []
        h = int(start)
        ok = True
        while True:
            if seen[h]:
                ok = h == start
                break
            seen[h] = True
            loop.append(int(he[h, 1]))               # the hole runs b -> a
            # rotate around a = he[h, 0] to the next boundary halfedge into a
            p = prev_in_face(h)
            guard = 0
            while twin[p] >= 0:
                p = prev_in_face(int(twin[p]))
                guard += 1
                if guard > 10_000:
                    ok = False
                    break
            if not ok or twin[p] == -2:
                ok = False
                break
            h = int(p)
        if ok and len(loop) >= 3:
            loops.extend(_split_at_repeats(loop))
    return loops, dups


def _split_at_repeats(loop: list[int]) -> list[np.ndarray]:
    """A walked loop as simple loops: two holes that share a vertex walk as
    one figure of eight through it, and a cap over that would draw the
    pinch's edges twice. Each return to a vertex closes the loop since its
    last visit."""
    out: list[np.ndarray] = []
    path: list[int] = []
    where: dict[int, int] = {}
    for v in loop:
        if v in where:
            i = where[v]
            sub = path[i:]
            if len(sub) >= 3:
                out.append(np.asarray(sub, dtype=np.int64))
            for u in sub:
                where.pop(u, None)
            path = path[:i]
        where[v] = len(path)
        path.append(v)
    if len(path) >= 3:
        out.append(np.asarray(path, dtype=np.int64))
    return out


def drop_fins(F: np.ndarray, areas: np.ndarray) -> tuple[np.ndarray, int]:
    """Faces that repeat a directed edge, all but the largest at each: a fin
    standing on a surface, a sliver drawn twice."""
    F = np.asarray(F, dtype=np.int64)
    if len(F) == 0:
        return F, 0
    n = int(F.max()) + 1
    key = (F[:, [0, 1, 2]].ravel() * n + F[:, [1, 2, 0]].ravel())
    uniq, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
    bad = np.flatnonzero(counts[inverse.ravel()] > 1)
    if len(bad) == 0:
        return F, 0
    face_of = bad // 3
    drop = set()
    for k in np.unique(key[bad]):
        faces = np.unique(face_of[key[bad] == k])
        order = faces[np.argsort(areas[faces], kind="stable")]
        drop.update(int(f) for f in order[:-1])
    keep = np.ones(len(F), dtype=bool)
    keep[list(drop)] = False
    return F[keep], len(drop)


# ------------------------------------------------------------------ capping

def _plane(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """PCA frame of `points`: (centroid, u, v, normal)."""
    c = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - c, full_matrices=False)
    u, v, n = vt[0], vt[1], vt[2]
    return c, u, v, n


def ear_clip(uv: np.ndarray) -> list[tuple[int, int, int]]:
    """Triangles of a simple polygon given as 2-D points in order, by ear
    clipping (the inside test over the remaining points is vectorized, so a
    loop of a thousand vertices clips in well under a second); the
    triangles follow the polygon's own winding. Raises ValueError when no
    ear is found, a folded projection."""
    pts = np.asarray(uv, dtype=np.float64)
    n = len(pts)
    if n < 3:
        return []
    area2 = float(np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1]))
    sign = 1.0 if area2 >= 0 else -1.0
    idx = list(range(n))
    out: list[tuple[int, int, int]] = []
    while len(idx) > 3:
        m = len(idx)
        arr = np.asarray(idx)
        P = pts[arr]
        prev = np.roll(P, 1, axis=0)
        nxt = np.roll(P, -1, axis=0)
        convex = sign * ((P[:, 0] - prev[:, 0]) * (nxt[:, 1] - prev[:, 1])
                         - (P[:, 1] - prev[:, 1]) * (nxt[:, 0] - prev[:, 0])) > 1e-18
        found = False
        for i in np.flatnonzero(convex):
            a, b, c = prev[i], P[i], nxt[i]
            keep = np.ones(m, dtype=bool)
            keep[[(i - 1) % m, i, (i + 1) % m]] = False
            Q = P[keep]
            if len(Q):
                d1 = sign * ((b[0] - a[0]) * (Q[:, 1] - a[1]) - (b[1] - a[1]) * (Q[:, 0] - a[0]))
                d2 = sign * ((c[0] - b[0]) * (Q[:, 1] - b[1]) - (c[1] - b[1]) * (Q[:, 0] - b[0]))
                d3 = sign * ((a[0] - c[0]) * (Q[:, 1] - c[1]) - (a[1] - c[1]) * (Q[:, 0] - c[0]))
                if np.any((d1 >= 0) & (d2 >= 0) & (d3 >= 0)):
                    continue
            out.append((idx[(i - 1) % m], idx[i], idx[(i + 1) % m]))
            del idx[i]
            found = True
            break
        if not found:
            raise ValueError("no ear: the loop folds in projection")
    out.append((idx[0], idx[1], idx[2]))
    return out


def _cap(V: np.ndarray, loop: np.ndarray, extra_index: int
         ) -> tuple[list[list[int]], np.ndarray | None]:
    """Triangles closing `loop` (hole order): a fan from a new centroid
    vertex (numbered `extra_index`, returned) for a small loop, an ear clip
    in the fitted plane for a long one, a fan again when the clip fails."""
    P = V[loop]
    n = len(loop)
    if n > FAN_UP_TO:
        c, u, v, _ = _plane(P)
        uv = np.c_[(P - c) @ u, (P - c) @ v]
        try:
            tris = ear_clip(uv)
            return [[int(loop[a]), int(loop[b]), int(loop[c3])] for a, b, c3 in tris], None
        except ValueError:
            pass
    c = P.mean(axis=0)
    return [[int(loop[i]), int(loop[(i + 1) % n]), extra_index] for i in range(n)], c


def cap_holes(V: np.ndarray, F: np.ndarray, passes: int = 3
              ) -> tuple[np.ndarray, np.ndarray, dict]:
    """Close every hole of (V, F) and drop the fins, `passes` times over
    (a cap can leave a fin where two holes met). Returns the new arrays and
    a dict with `capped` (holes closed) and `fins` (faces dropped)."""
    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    info = {"capped": 0, "fins": 0}
    for _ in range(passes):
        if len(F) == 0:
            break
        tri = V[F]
        areas = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        F, nd = drop_fins(F, areas)
        info["fins"] += nd
        loops, dups = boundary_loops(F)
        if not loops and not dups:
            break
        new_faces: list[list[int]] = []
        new_verts: list[np.ndarray] = []
        for loop in loops:
            tris, extra = _cap(V, loop, len(V) + len(new_verts))
            if extra is not None:
                new_verts.append(extra[None, :])
            new_faces.extend(tris)
            info["capped"] += 1
        if new_verts:
            V = np.vstack([V] + new_verts)
        if new_faces:
            F = np.vstack([F, np.asarray(new_faces, dtype=np.int64)])
    return V, F, info


# ------------------------------------------------------------------ the relief remesh

def relief_resolution(extents) -> float:
    """The grid step for a relief remesh: the longest extent over
    `REMESH_DIVISIONS`, never under `REMESH_MIN_MM`."""
    longest = float(np.max(np.asarray(extents, dtype=np.float64)))
    return max(REMESH_MIN_MM, longest / REMESH_DIVISIONS)


def _frame_from_normal(normal: np.ndarray) -> np.ndarray:
    """A rotation taking `normal` onto -z (the back down, the relief up)."""
    n = np.asarray(normal, dtype=np.float64)
    n = n / np.linalg.norm(n)
    target = np.array([0.0, 0.0, -1.0])
    v = np.cross(n, target)
    c = float(n @ target)
    if c < -1.0 + 1e-12:
        return np.diag([1.0, -1.0, -1.0])
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K / (1.0 + c)


def relief_remesh(V: np.ndarray, F: np.ndarray, back_normal, back_point, *,
                  resolution: float | None = None, min_height: float = 1e-4
                  ) -> tuple[np.ndarray, np.ndarray, float]:
    """The mesh rebuilt as a solid heightfield over its back plane.

    The soup is turned so the back's outward normal points down and the
    back lies at z = 0; its upper envelope is sampled on a grid of
    `resolution` (default `relief_resolution`); every sample above
    `min_height` is a column of the relief. Returns vertices and faces in
    the original frame, closed and consistently wound, plus the resolution
    used. The lattice vertices are the sample centers, so a strand only one
    sample wide has no quad and is lost (a 600th of the extent).
    """
    from ..zmap import triangle_envelopes

    V = np.asarray(V, dtype=np.float64)
    F = np.asarray(F, dtype=np.int64)
    R = _frame_from_normal(back_normal)
    p0 = np.asarray(back_point, dtype=np.float64)
    W = (V - p0) @ R.T
    lo, hi = W.min(axis=0), W.max(axis=0)
    res = float(resolution) if resolution else relief_resolution(hi - lo)
    origin = (float(lo[0]) - res, float(lo[1]) - res)
    cols = int(math.ceil((hi[0] - lo[0]) / res)) + 3
    rows = int(math.ceil((hi[1] - lo[1]) / res)) + 3
    # both windings: the envelope reads front faces only, and a shell that
    # reaches this rung may be inside out or mixed
    FF = np.vstack([F, F[:, ::-1]])
    up, _ = triangle_envelopes(W, FF, origin, rows, cols, res, background=np.nan)
    h = np.where(np.isfinite(up), up, 0.0)
    covered = h > min_height
    if not covered.any():
        raise ValueError("the relief has no height over its back")
    h = np.where(covered, h, 0.0)
    # lattice vertices: top at (x, y, h) and bottom at (x, y, 0), by sample
    index = -np.ones((rows, cols), dtype=np.int64)
    rr, cc = np.nonzero(covered)
    index[rr, cc] = np.arange(len(rr))
    xs = origin[0] + cc * res
    ys = origin[1] + rr * res
    top = np.c_[xs, ys, h[rr, cc]]
    bottom = np.c_[xs, ys, np.zeros(len(rr))]
    nv = len(rr)
    verts = np.vstack([top, bottom])
    # quads between four covered samples, split on the diagonal
    q = covered[:-1, :-1] & covered[1:, :-1] & covered[:-1, 1:] & covered[1:, 1:]
    qr, qc = np.nonzero(q)
    i00 = index[qr, qc]
    i10 = index[qr + 1, qc]
    i01 = index[qr, qc + 1]
    i11 = index[qr + 1, qc + 1]
    # top faces counter-clockwise seen from +z; bottom reversed
    faces = [np.c_[i00, i01, i11], np.c_[i00, i11, i10],
             np.c_[i00 + nv, i11 + nv, i01 + nv], np.c_[i00 + nv, i10 + nv, i11 + nv]]
    # walls: a lattice edge between covered samples with exactly one quad beside it
    # horizontal edges (r, c)-(r, c+1): quads above (r, c) and below (r-1, c)
    qpad = np.zeros((rows + 1, cols + 1), dtype=bool)
    qpad[1:rows, 1:cols] = q
    hcov = covered[:, :-1] & covered[:, 1:]
    above = qpad[1:, 1:cols]            # quad (r, c)
    below = qpad[:-1, 1:cols]           # quad (r-1, c)
    for mask, outward_up in ((hcov & above & ~below, False), (hcov & below & ~above, True)):
        r_, c_ = np.nonzero(mask)
        a, b = index[r_, c_], index[r_, c_ + 1]
        # the wall faces -y when the quad is above it, +y when below
        if outward_up:
            faces.append(np.c_[a, b, b + nv]); faces.append(np.c_[a, b + nv, a + nv])
        else:
            faces.append(np.c_[b, a, a + nv]); faces.append(np.c_[b, a + nv, b + nv])
    vcov = covered[:-1, :] & covered[1:, :]
    right = qpad[1:rows, 1:]            # quad (r, c)
    left = qpad[1:rows, :-1]            # quad (r, c-1)
    for mask, outward_right in ((vcov & right & ~left, False), (vcov & left & ~right, True)):
        r_, c_ = np.nonzero(mask)
        a, b = index[r_, c_], index[r_ + 1, c_]
        if outward_right:
            faces.append(np.c_[b, a, a + nv]); faces.append(np.c_[b, a + nv, b + nv])
        else:
            faces.append(np.c_[a, b, b + nv]); faces.append(np.c_[a, b + nv, a + nv])
    kept = [f for f in faces if len(f)]
    if not kept:
        raise ValueError("the relief is nowhere two samples wide")
    faces_arr = np.vstack(kept).astype(np.int64)
    # drop samples no face uses (isolated covered cells), re-index
    used = np.zeros(len(verts), dtype=bool)
    used[faces_arr.ravel()] = True
    remap = -np.ones(len(verts), dtype=np.int64)
    remap[used] = np.arange(int(used.sum()))
    verts = verts[used]
    faces_arr = remap[faces_arr]
    # back to the original frame
    out_v = verts @ R + p0
    return out_v, faces_arr, res


# ------------------------------------------------------------------ the loss guard

def kept_enough(before_v, before_f, after_v, after_f) -> bool:
    """True when a repair kept most of the surface and the whole extent:
    the mesh fixer can hand back one corner of a mesh with NoError."""
    bv, bf = np.asarray(before_v, dtype=np.float64), np.asarray(before_f, dtype=np.int64)
    av, af = np.asarray(after_v, dtype=np.float64), np.asarray(after_f, dtype=np.int64)
    if len(af) == 0 or len(bf) == 0:
        return False

    def area(v, f):
        t = v[f]
        return float(0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1).sum())

    if area(av, af) < KEEP_AREA * area(bv, bf):
        return False
    b_ext = bv.max(axis=0) - bv.min(axis=0)
    a_ext = av[np.unique(af)].max(axis=0) - av[np.unique(af)].min(axis=0)
    scale = max(float(b_ext.max()), 1e-9)
    return bool(np.all(a_ext >= KEEP_EXTENT * b_ext - 1e-6 * scale))
