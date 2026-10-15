"""The stock as a multi-interval Z-dexel grid (BUILDPLAN M21, §6.1 and §6.2).

A heightfield keeps one number per (x, y) column: the top of the material.
That is enough for a tool that only ever comes down from above onto a blank
that is solid all the way to the bed, and it is what every simulation here
has used since M5. It cannot hold an undercut — the lens-bevel groove's
side-cutting form takes a slot out of a wall and leaves material above it —
nor a cut from below, nor a stock that was half finished in an earlier setup.

A **dexel** column keeps a short sorted list of solid intervals instead:
``[z_top, z_bot]`` pairs, the topmost first. The heightfield is the
one-interval case. Cutting is interval subtraction per column, a set
operation, so the result does not depend on the order the cuts arrive in or
on how they are batched, which is what lets a threaded kernel be bit-identical
to the reference (§6.9). Memory is ``O(K · ny · nx)`` with Z exact.

Layout: ``z_top`` and ``z_bot`` are ``(K, ny, nx)`` float64, ``count`` is
``(ny, nx)`` uint8; slot ``k`` of a column is live for ``k < count``, and the
dead slots hold NaN. ``K`` is 4 by default — a column needs one interval per
undercut plus one, and a frame front has at most the groove's.

The grid convention is the relief's: cell ``(row, col)`` is at
``origin + (col, row) * resolution``, and a tool position lands on the cell
``round((p - origin) / resolution)``, exactly as `sim.toolsim` has always
placed it, so a floor read off a stock built on a relief's grid compares cell
for cell with the relief.

Qt-free and kernel-free: nothing here imports `core.model`, `core.solid` or
the CAM, and a test says so.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..relief.heightfield import Heightfield

__all__ = ["DEFAULT_K", "DexelStock", "DexelSnapshot"]

#: Intervals a column can hold before the thinnest void is merged away.
DEFAULT_K = 4


@dataclass
class DexelSnapshot:
    """A copy of a stock for playback keyframes, never cut into: only the
    layers any column uses (one, on every job without an undercut), as
    float32 unless `exact` asked for the float64 the live grid holds — the
    final keyframe, which the verdict and the rest state read."""
    z_top: np.ndarray
    z_bot: np.ndarray
    count: np.ndarray
    origin: tuple[float, float]
    resolution: float

    def top(self, empty: float = 0.0) -> np.ndarray:
        z = np.where(self.count > 0, self.z_top[0], empty)
        return np.nan_to_num(z.astype(np.float64), nan=float(empty))

    @property
    def nbytes(self) -> int:
        return int(self.z_top.nbytes + self.z_bot.nbytes + self.count.nbytes)


class DexelStock:
    """The stock. Build one with `from_box`, `from_heightfield` or
    `from_mesh`; cut it with `core.stock.cut`; read it back with `top`,
    `bottom`, `volume` or `snapshot`."""

    def __init__(self, z_top: np.ndarray, z_bot: np.ndarray, count: np.ndarray,
                 origin: tuple[float, float], resolution: float) -> None:
        if z_top.shape != z_bot.shape or z_top.shape[1:] != count.shape:
            raise ValueError("z_top, z_bot and count disagree on the grid")
        self.z_top = z_top
        self.z_bot = z_bot
        self.count = count
        self.origin = (float(origin[0]), float(origin[1]))
        self.resolution = float(resolution)
        #: How many times a column ran out of slots and had its thinnest void
        #: filled (`cut`). Material kept, never lost; the caller logs it.
        self.overflow_merges = 0

    # ------------------------------------------------------------ constructors

    @classmethod
    def empty(cls, shape: tuple[int, int], origin: tuple[float, float],
              resolution: float, k: int = DEFAULT_K) -> "DexelStock":
        rows, cols = shape
        return cls(np.full((k, rows, cols), np.nan), np.full((k, rows, cols), np.nan),
                   np.zeros((rows, cols), dtype=np.uint8), origin, resolution)

    @classmethod
    def from_box(cls, x0: float, y0: float, x1: float, y1: float,
                 z_bottom: float, z_top: float, resolution: float, *,
                 origin: tuple[float, float] | None = None,
                 shape: tuple[int, int] | None = None, margin: float = 0.0,
                 k: int = DEFAULT_K) -> "DexelStock":
        """A rectangular blank: one interval ``[z_top, z_bottom]`` in every
        column whose center lies on the box. On a given grid when `origin` and
        `shape` are passed (a relief's, so floors compare cell for cell), else
        on a grid that covers the box plus `margin`."""
        if z_top <= z_bottom:
            raise ValueError("a box needs z_top above z_bottom")
        if origin is None or shape is None:
            origin = (x0 - margin, y0 - margin)
            rows = max(2, int(round((y1 - y0 + 2 * margin) / resolution)) + 1)
            cols = max(2, int(round((x1 - x0 + 2 * margin) / resolution)) + 1)
            shape = (rows, cols)
        stock = cls.empty(shape, origin, resolution, k)
        xs, ys = stock.cell_centers()
        on = (xs >= x0 - 1e-9) & (xs <= x1 + 1e-9) & (ys >= y0 - 1e-9) & (ys <= y1 + 1e-9)
        stock.z_top[0][on] = float(z_top)
        stock.z_bot[0][on] = float(z_bottom)
        stock.count[on] = 1
        return stock

    @classmethod
    def from_heightfield(cls, field: Heightfield, inside: np.ndarray | None = None,
                         z_bottom: float = 0.0, k: int = DEFAULT_K) -> "DexelStock":
        """One interval ``[field.z, z_bottom]`` per column with material: the
        columns `inside` names, else those whose top stands above the bottom.
        The heightfield as the one-interval special case, on its own grid."""
        rows, cols = field.z.shape
        stock = cls.empty((rows, cols), field.origin, field.resolution, k)
        on = (field.z > z_bottom) if inside is None else (np.asarray(inside, bool) & (field.z > z_bottom))
        stock.z_top[0][on] = field.z[on]
        stock.z_bot[0][on] = float(z_bottom)
        stock.count[on] = 1
        return stock

    @classmethod
    def from_mesh(cls, vertices, faces, origin: tuple[float, float], rows: int, cols: int,
                  resolution: float, k: int = DEFAULT_K) -> "DexelStock":
        """Every column's intervals through a closed, outward-wound triangle
        mesh (§6.6): the generalization of `core.zmap.triangle_envelopes`,
        which keeps only the highest and lowest crossing per cell. Here every
        crossing is kept with its facing, sorted top first per cell, and an
        exit (an up-facing triangle) paired with the entry below it (a
        down-facing one) makes an interval. A box and a pad block are the
        one-interval case; a half-finished stock carried from an earlier setup
        (M24) and a pressed blank (M25) are other meshes; the target of a
        comparison (`compare`) is the model mesh through the same routine.

        Pairing is by order where the facings alternate as a closed solid's
        must, and by order alone where they do not (a sliver, a coincident
        edge): the crossings are then taken two by two from the top. A cell
        with more than `2 k` crossings keeps its topmost `k` intervals.
        """
        from ..zmap import triangle_crossings

        cell, z, up = triangle_crossings(vertices, faces, origin, rows, cols, resolution)
        stock = cls.empty((rows, cols), origin, resolution, k)
        if cell.size == 0:
            return stock
        order = np.lexsort((-z, cell))             # by cell, then top first
        cell, z, up = cell[order], z[order], up[order]
        # A column on an edge two triangles share crosses the same surface
        # twice at one height — a face's own diagonal does it at every cell
        # center it passes through. One crossing per surface, per cell.
        dup = np.r_[False, (cell[1:] == cell[:-1]) & (up[1:] == up[:-1])
                    & (np.abs(z[1:] - z[:-1]) <= 1e-9)]
        cell, z, up = cell[~dup], z[~dup], up[~dup]
        starts = np.flatnonzero(np.r_[True, cell[1:] != cell[:-1]])
        rank = np.arange(cell.size) - np.repeat(starts, np.diff(np.r_[starts, cell.size]))
        keep = rank < 2 * k
        cell, z, rank = cell[keep], z[keep], rank[keep]
        layer = rank // 2
        is_top = rank % 2 == 0
        rr, cc = cell // cols, cell % cols
        stock.z_top[layer[is_top], rr[is_top], cc[is_top]] = z[is_top]
        stock.z_bot[layer[~is_top], rr[~is_top], cc[~is_top]] = z[~is_top]
        # a top with no bottom under it (an odd crossing) is dropped
        counts = np.zeros(rows * cols, dtype=np.int64)
        np.add.at(counts, cell[~is_top], 1)
        stock.count[:] = counts.reshape(rows, cols).astype(np.uint8)
        live = np.arange(k)[:, None, None] < stock.count[None]
        stock.z_top[~live] = np.nan
        stock.z_bot[~live] = np.nan
        return stock

    @classmethod
    def from_intervals(cls, tops: np.ndarray, bots: np.ndarray, count: np.ndarray,
                       origin: tuple[float, float], resolution: float) -> "DexelStock":
        """From per-column interval arrays already sorted top first."""
        return cls(np.array(tops, dtype=np.float64), np.array(bots, dtype=np.float64),
                   np.array(count, dtype=np.uint8), origin, resolution)

    # ------------------------------------------------------------------ grid

    @property
    def k(self) -> int:
        return int(self.z_top.shape[0])

    @property
    def shape(self) -> tuple[int, int]:
        return self.count.shape

    def cell_centers(self) -> tuple[np.ndarray, np.ndarray]:
        """World (x, y) of every cell center, as two ``(rows, cols)`` arrays."""
        rows, cols = self.shape
        xs = self.origin[0] + np.arange(cols) * self.resolution
        ys = self.origin[1] + np.arange(rows) * self.resolution
        return np.broadcast_to(xs, (rows, cols)), np.broadcast_to(ys[:, None], (rows, cols))

    def cells_of(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        """``(rows, cols)`` of positions, the way the simulation has always
        placed a tool: the nearest cell center."""
        c = np.round((np.asarray(x, dtype=np.float64) - self.origin[0]) / self.resolution).astype(np.intp)
        r = np.round((np.asarray(y, dtype=np.float64) - self.origin[1]) / self.resolution).astype(np.intp)
        return r, c

    # ------------------------------------------------------------- read-back

    def top(self, empty: float = 0.0) -> Heightfield:
        """The top surface: the topmost interval's top, `empty` where a column
        holds nothing (cut through, or never stock)."""
        z = np.where(self.count > 0, self.z_top[0], float(empty))
        return Heightfield(z=np.nan_to_num(z, nan=float(empty)), origin=self.origin,
                           resolution=self.resolution)

    def bottom(self, empty: float = 0.0) -> Heightfield:
        """The bottom surface: the lowest interval's bottom."""
        rows, cols = self.shape
        last = np.clip(self.count.astype(np.intp) - 1, 0, self.k - 1)
        rr, cc = np.indices((rows, cols))
        z = np.where(self.count > 0, self.z_bot[last, rr, cc], float(empty))
        return Heightfield(z=np.nan_to_num(z, nan=float(empty)), origin=self.origin,
                           resolution=self.resolution)

    def clipped(self, z_lo, z_hi) -> "DexelStock":
        """The stock with every interval cut back to ``[z_lo, z_hi]`` (each a
        number or a ``(rows, cols)`` array), the intervals that vanish
        dropped and the rest compacted top first (M24: the verdict's box
        clipped to the blank before it is carried to the other side)."""
        rows, cols = self.shape
        k = self.k
        lo = np.broadcast_to(np.asarray(z_lo, dtype=np.float64), (rows, cols))
        hi = np.broadcast_to(np.asarray(z_hi, dtype=np.float64), (rows, cols))
        live = np.arange(k)[:, None, None] < self.count[None]
        top = np.where(live, np.minimum(self.z_top, hi[None]), np.nan)
        bot = np.where(live, np.maximum(self.z_bot, lo[None]), np.nan)
        keep = live & (top > bot + 1e-12)
        new_top = np.full_like(top, np.nan)
        new_bot = np.full_like(bot, np.nan)
        count = np.zeros((rows, cols), dtype=np.uint8)
        for i in range(k):
            sel = keep[i]
            if not sel.any():
                continue
            slot = count[sel].astype(np.intp)
            rr, cc = np.nonzero(sel)
            new_top[slot, rr, cc] = top[i][sel]
            new_bot[slot, rr, cc] = bot[i][sel]
            count[sel] += 1
        out = DexelStock(new_top, new_bot, count, self.origin, self.resolution)
        out.overflow_merges = self.overflow_merges
        return out

    def mirrored(self, mirror_x: float = 0.0, z_flip: float | None = None) -> "DexelStock":
        """The stock flipped over (M24): mirrored in X about ``x = mirror_x``
        and, with `z_flip`, turned upside down so that ``z -> z_flip - z`` —
        every interval's top becomes its bottom and the columns' intervals
        are read in the new top-first order. Bit for bit reversible: flipping
        twice returns the stock."""
        rows, cols = self.shape
        res = self.resolution
        ox, oy = self.origin
        ox2 = 2.0 * float(mirror_x) - (ox + (cols - 1) * res)
        top = self.z_top[:, :, ::-1].copy()
        bot = self.z_bot[:, :, ::-1].copy()
        count = self.count[:, ::-1].copy()
        if z_flip is not None:
            zf = float(z_flip)
            k = self.k
            new_top = np.full_like(top, np.nan)
            new_bot = np.full_like(bot, np.nan)
            # interval i (top first) becomes interval count-1-i, upside down
            for n in range(1, k + 1):
                sel = count == n
                if not sel.any():
                    continue
                for i in range(n):
                    j = n - 1 - i
                    new_top[j][sel] = zf - bot[i][sel]
                    new_bot[j][sel] = zf - top[i][sel]
            top, bot = new_top, new_bot
        out = DexelStock(top, bot, count, (ox2, oy), res)
        out.overflow_merges = self.overflow_merges
        return out

    def thickness(self) -> np.ndarray:
        """Material per column, summed over its intervals, mm."""
        live = np.arange(self.k)[:, None, None] < self.count[None, :, :]
        d = np.where(live, self.z_top - self.z_bot, 0.0)
        return d.sum(axis=0)

    def volume(self) -> float:
        """Material in the stock, mm³: every interval's height times a cell."""
        return float(self.thickness().sum() * self.resolution * self.resolution)

    def undercut(self) -> np.ndarray:
        """True where a column holds more than one interval — material above a
        void, which the top surface alone cannot show."""
        return self.count > 1

    def snapshot(self, exact: bool = False) -> DexelSnapshot:
        kmax = max(1, int(self.count.max()) if self.count.size else 1)
        dtype = np.float64 if exact else np.float32
        return DexelSnapshot(self.z_top[:kmax].astype(dtype), self.z_bot[:kmax].astype(dtype),
                             self.count.copy(), self.origin, self.resolution)

    def restore(self, snap: DexelSnapshot) -> "DexelStock":
        """Put a snapshot back into this stock, in place, and return it."""
        if snap.count.shape != self.shape:
            raise ValueError("the snapshot is on another grid")
        kmax = snap.z_top.shape[0]
        self.z_top[:] = np.nan
        self.z_bot[:] = np.nan
        self.z_top[:kmax] = snap.z_top
        self.z_bot[:kmax] = snap.z_bot
        self.count[:] = snap.count
        return self

    @classmethod
    def from_snapshot(cls, snap: DexelSnapshot, k: int = DEFAULT_K) -> "DexelStock":
        k = max(k, snap.z_top.shape[0])
        return cls.empty(snap.count.shape, snap.origin, snap.resolution, k).restore(snap)

    def copy(self) -> "DexelStock":
        out = DexelStock(self.z_top.copy(), self.z_bot.copy(), self.count.copy(),
                         self.origin, self.resolution)
        out.overflow_merges = self.overflow_merges
        return out

    def column(self, row: int, col: int) -> list[tuple[float, float]]:
        """One column's intervals as ``[(top, bottom), ...]``, topmost first."""
        n = int(self.count[row, col])
        return [(float(self.z_top[k, row, col]), float(self.z_bot[k, row, col]))
                for k in range(n)]

    def to_volume(self, pitch: float, z0: float | None = None, z1: float | None = None
                  ) -> tuple[np.ndarray, tuple[float, float, float]]:
        """Occupancy on a voxel lattice ``(nz, rows, cols)`` for a surface
        extractor (Flying Edges): a voxel is solid where its center lies in an
        interval. `pitch` is the Z step; the XY step stays the grid's. Returns
        the array and the world origin of voxel ``(0, 0, 0)``."""
        live = np.arange(self.k)[:, None, None] < self.count[None, :, :]
        tops = np.where(live, self.z_top, -np.inf)
        bots = np.where(live, self.z_bot, np.inf)
        lo = float(np.nanmin(bots[live])) if live.any() else 0.0
        hi = float(np.nanmax(tops[live])) if live.any() else 0.0
        z0 = lo if z0 is None else z0
        z1 = hi if z1 is None else z1
        nz = max(1, int(np.ceil((z1 - z0) / pitch)) + 1)
        zs = z0 + (np.arange(nz) + 0.5) * pitch
        occ = np.zeros((nz, *self.shape), dtype=bool)
        for k in range(self.k):
            inside = (zs[:, None, None] <= tops[k][None]) & (zs[:, None, None] >= bots[k][None])
            occ |= inside & live[k][None]
        return occ, (self.origin[0], self.origin[1], z0)
