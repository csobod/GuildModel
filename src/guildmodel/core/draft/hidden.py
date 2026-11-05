"""Hidden-line removal for the blueprint's views (2.3): a depth buffer of
the formed solid in a view's direction, and the edges classified against
it, so each view draws every edge of the frame that can be seen from there
and dashes or drops the rest.

Numpy only. A view is a function world (N, 3) -> (N, 3) giving (u, v,
depth), depth growing toward the viewer. The solid's triangles are
rasterized into a grid of `cell_mm` keeping the nearest depth per cell; a
point on an edge is visible where nothing in its cell's neighborhood lies
nearer than it by more than `tol_mm`. Edges are sampled every `step_mm`
along their length and split where the answer changes.
"""
from __future__ import annotations

import math

import numpy as np

__all__ = ["DepthView", "chain_segments", "split_by_visibility"]

#: The depth buffer's cell, mm, and the tolerance a point on the surface
#: is allowed to sit behind the buffer by (the surface's own depth varies
#: across a cell on a slope).
CELL_MM = 0.25
TOL_MM = 0.35
STEP_MM = 0.5
#: Triangles rasterized per numpy batch: bounds the (triangle, cell) pairs
#: held at once.
_BATCH = 4000


class DepthView:
    """``dv = DepthView(project); dv.add(V, F); dv.visible(points)``."""

    def __init__(self, project, cell_mm: float = CELL_MM, tol_mm: float = TOL_MM) -> None:
        self.project = project
        self.cell = float(cell_mm)
        self.tol = float(tol_mm)
        self._buf = None
        self._u0 = self._v0 = 0.0
        self._meshes: list = []

    def add(self, V, F) -> None:
        """A closed mesh's triangles, world; the buffer is built lazily."""
        V = np.asarray(V, dtype=np.float64)
        F = np.asarray(F, dtype=np.int64)
        if len(V) and len(F):
            self._meshes.append((V, F))
            self._buf = None

    def _build(self) -> None:
        if not self._meshes:
            self._buf = np.zeros((1, 1))
            return
        P = [self.project(V) for V, _F in self._meshes]
        allp = np.vstack(P)
        pad = 2.0
        self._u0, self._v0 = float(allp[:, 0].min()) - pad, float(allp[:, 1].min()) - pad
        u1, v1 = float(allp[:, 0].max()) + pad, float(allp[:, 1].max()) + pad
        nu = int(math.ceil((u1 - self._u0) / self.cell)) + 1
        nv = int(math.ceil((v1 - self._v0) / self.cell)) + 1
        buf = np.full((nv, nu), -np.inf)
        for (V, F), Q in zip(self._meshes, P):
            self._raster(buf, Q, F)
        self._buf = buf

    def _raster(self, buf, Q, F) -> None:
        nv, nu = buf.shape
        for start in range(0, len(F), _BATCH):
            tri = Q[F[start:start + _BATCH]]           # (T, 3, 3): u, v, depth
            # the cells each triangle covers, by bounding box
            cu = (tri[:, :, 0] - self._u0) / self.cell
            cv = (tri[:, :, 1] - self._v0) / self.cell
            iu0 = np.clip(np.floor(cu.min(axis=1)).astype(int), 0, nu - 1)
            iu1 = np.clip(np.ceil(cu.max(axis=1)).astype(int), 0, nu - 1)
            iv0 = np.clip(np.floor(cv.min(axis=1)).astype(int), 0, nv - 1)
            iv1 = np.clip(np.ceil(cv.max(axis=1)).astype(int), 0, nv - 1)
            wu = iu1 - iu0 + 1
            wv = iv1 - iv0 + 1
            counts = wu * wv
            total = int(counts.sum())
            if total == 0:
                continue
            t_idx = np.repeat(np.arange(len(tri)), counts)
            # the cell offsets within each triangle's box
            offs = np.arange(total) - np.repeat(np.cumsum(counts) - counts, counts)
            ou = offs % np.repeat(wu, counts)
            ov = offs // np.repeat(wu, counts)
            iu = np.repeat(iu0, counts) + ou
            iv = np.repeat(iv0, counts) + ov
            # the cell centers, in view mm
            pu = self._u0 + (iu + 0.5) * self.cell
            pv = self._v0 + (iv + 0.5) * self.cell
            a, b, c = tri[t_idx, 0], tri[t_idx, 1], tri[t_idx, 2]
            # barycentric coordinates of the cell center
            d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
            ok = np.abs(d) > 1e-12
            d = np.where(ok, d, 1.0)
            l1 = ((b[:, 1] - c[:, 1]) * (pu - c[:, 0]) + (c[:, 0] - b[:, 0]) * (pv - c[:, 1])) / d
            l2 = ((c[:, 1] - a[:, 1]) * (pu - c[:, 0]) + (a[:, 0] - c[:, 0]) * (pv - c[:, 1])) / d
            l3 = 1.0 - l1 - l2
            # a cell whose center lies in the triangle, or within a cell's
            # width of it (so a thin triangle still marks its cells)
            slack = -0.02
            inside = ok & (l1 >= slack) & (l2 >= slack) & (l3 >= slack)
            if not inside.any():
                continue
            depth = l1 * a[:, 2] + l2 * b[:, 2] + l3 * c[:, 2]
            # a point just outside takes the nearest vertex's depth bound
            depth = np.where((l1 < 0) | (l2 < 0) | (l3 < 0), tri[t_idx][:, :, 2].max(axis=1), depth)
            np.maximum.at(buf, (iv[inside], iu[inside]), depth[inside])

    def visible(self, pts_world) -> np.ndarray:
        """True where nothing lies nearer than the point in its cell's
        3 x 3 neighborhood by more than the tolerance."""
        if self._buf is None:
            self._build()
        buf = self._buf
        Q = self.project(np.asarray(pts_world, dtype=np.float64).reshape(-1, 3))
        if buf.shape == (1, 1):
            return np.ones(len(Q), dtype=bool)
        nv, nu = buf.shape
        iu = np.clip(np.round((Q[:, 0] - self._u0) / self.cell - 0.5).astype(int), 0, nu - 1)
        iv = np.clip(np.round((Q[:, 1] - self._v0) / self.cell - 0.5).astype(int), 0, nv - 1)
        near = np.full(len(Q), np.inf)
        for du in (-1, 0, 1):
            for dv in (-1, 0, 1):
                ju = np.clip(iu + du, 0, nu - 1)
                jv = np.clip(iv + dv, 0, nv - 1)
                near = np.minimum(near, buf[jv, ju])
        return Q[:, 2] >= near - self.tol


def _resample(poly, step_mm: float):
    """A polyline resampled every `step_mm` (its own vertices kept)."""
    P = np.asarray(poly, dtype=np.float64)
    if len(P) < 2:
        return P
    out = [P[0]]
    for i in range(len(P) - 1):
        a, b = P[i], P[i + 1]
        L = float(np.linalg.norm(b - a))
        n = max(int(math.ceil(L / step_mm)), 1)
        for k in range(1, n + 1):
            out.append(a + (b - a) * (k / n))
    return np.asarray(out)


def split_by_visibility(poly, dv: DepthView, step_mm: float = STEP_MM,
                        closed: bool = False) -> tuple[list, list]:
    """A world polyline split into its visible runs and its hidden runs,
    each a list of (N, 3) arrays."""
    P = np.asarray(poly, dtype=np.float64)
    if closed and len(P) > 1:
        P = np.vstack([P, P[:1]])
    R = _resample(P, step_mm)
    if len(R) < 2:
        return [], []
    vis = dv.visible(R)
    # a run shorter than two samples is noise: smooth single flips
    if len(vis) >= 3:
        flips = vis.copy()
        flips[1:-1] = np.where((vis[:-2] == vis[2:]) & (vis[1:-1] != vis[:-2]), vis[:-2], vis[1:-1])
        vis = flips
    seen, hidden = [], []
    start = 0
    for i in range(1, len(R) + 1):
        if i == len(R) or vis[i] != vis[start]:
            run = R[start:i + 1] if i < len(R) else R[start:i]
            if len(run) >= 2:
                (seen if vis[start] else hidden).append(run)
            start = i
    return seen, hidden


def chain_segments(segments, tol: float = 1e-6) -> list:
    """Unordered (K, 2, 3) segments chained into polylines by shared
    endpoints, for drawing fewer, longer paths."""
    S = np.asarray(segments, dtype=np.float64).reshape(-1, 2, 3)
    if len(S) == 0:
        return []
    key = lambda p: tuple(np.round(p / tol).astype(np.int64))   # noqa: E731
    ends: dict = {}
    for i, (a, b) in enumerate(S):
        ends.setdefault(key(a), []).append((i, 0))
        ends.setdefault(key(b), []).append((i, 1))
    used = np.zeros(len(S), dtype=bool)
    out = []
    for i in range(len(S)):
        if used[i]:
            continue
        used[i] = True
        chain = [S[i, 0], S[i, 1]]
        # grow forward from the tail, then backward from the head
        for forward in (True, False):
            while True:
                tip = chain[-1] if forward else chain[0]
                nxt = None
                for j, end in ends.get(key(tip), []):
                    if not used[j]:
                        nxt = (j, end)
                        break
                if nxt is None:
                    break
                j, end = nxt
                used[j] = True
                other = S[j, 1 - end]
                if forward:
                    chain.append(other)
                else:
                    chain.insert(0, other)
        out.append(np.asarray(chain))
    return out
