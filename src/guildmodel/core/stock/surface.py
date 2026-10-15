"""What the viewer draws of a stock (BUILDPLAN M21 §6.4).

**The playback path** is one closed block: the top surface as a sheet of
quads over the blank's footprint, a flat bottom under it, and walls along the
footprint's edge. Its points are updated in place as the playhead moves —
only the top's Z changes — which the research measured at twice the frame
rate of the structured grid the viewer held before. A column cut through
drops its top onto the bottom, so the block stays closed. Columns that hold
more than one interval are tinted: the undercut is visible while it is cut,
even though the sheet can only show the top.

**The solid path**, at a pause and at the end, rasterizes the columns into an
occupancy volume and runs Flying Edges over it, which shows the walls and the
undercuts themselves. It is the only honest picture of a groove, and it is
built when a plan has an undercut to show.

Everything here is NumPy in and NumPy out; the one caller that turns it into
VTK objects is the viewer, through `pyvista`, imported there.
"""
from __future__ import annotations

import numpy as np

from .dexel import DexelStock

__all__ = ["block_faces", "block_points", "elevation_colors", "occupancy_grid",
           "undercut_tint"]

#: The elevation ramp the viewer has drawn since M7.12.1: deep cut dark, the
#: uncut top amber.
_LO = np.array([0.13, 0.08, 0.04])
_HI = np.array([0.86, 0.69, 0.32])
#: The tint of a column holding an undercut: toward the measure blue.
_UNDERCUT = np.array([0.30, 0.45, 0.80])


def block_points(top: np.ndarray, origin: tuple[float, float], resolution: float,
                 z_bottom: float) -> np.ndarray:
    """``(2 n, 3)`` points: the top sheet's, then the bottom's, in grid order.
    `top` is the top surface, ``(rows, cols)``; the viewer rewrites the first
    ``n`` z values as the playhead moves."""
    rows, cols = top.shape
    xs = origin[0] + np.arange(cols) * resolution
    ys = origin[1] + np.arange(rows) * resolution
    X, Y = np.meshgrid(xs, ys)
    base = np.column_stack([X.ravel(), Y.ravel()])
    n = rows * cols
    return np.vstack([np.column_stack([base, np.asarray(top, dtype=np.float64).ravel()]),
                      np.column_stack([base, np.full(n, float(z_bottom))])])


def block_faces(footprint: np.ndarray) -> np.ndarray:
    """The block's faces for `block_points`, as VTK's flat face array: quads
    over the top where all four corners stand on the footprint, the same
    quads under the bottom, and a wall quad on every edge the top sheet does
    not share with a neighbor — its boundary, which closes the block."""
    fp = np.asarray(footprint, dtype=bool)
    rows, cols = fp.shape
    n = rows * cols
    idx = np.arange(n).reshape(rows, cols)
    c00, c01, c10, c11 = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    ok = (fp[:-1, :-1] & fp[:-1, 1:] & fp[1:, :-1] & fp[1:, 1:]).ravel()
    a, b, c, d = c00.ravel()[ok], c01.ravel()[ok], c11.ravel()[ok], c10.ravel()[ok]
    four = np.full(a.shape, 4)
    top = np.column_stack([four, a, b, c, d])
    bottom = np.column_stack([four, a + n, d + n, c + n, b + n])
    # the sheet's boundary: edges one quad uses
    edges = np.vstack([np.column_stack([a, b]), np.column_stack([b, c]),
                       np.column_stack([c, d]), np.column_stack([d, a])])
    key = np.sort(edges, axis=1)
    flat = key[:, 0].astype(np.int64) * n + key[:, 1]
    _, first, counts = np.unique(flat, return_index=True, return_counts=True)
    rim = edges[first[counts == 1]]
    # down the near edge, along the bottom, up the far edge: outward, since the
    # exterior lies to the right of a counter-clockwise sheet's rim
    walls = np.column_stack([np.full(len(rim), 4), rim[:, 0], rim[:, 0] + n,
                             rim[:, 1] + n, rim[:, 1]]) if len(rim) else np.zeros((0, 5), int)
    return np.vstack([top, bottom, walls]).ravel()


def elevation_colors(z: np.ndarray, z_max: float) -> np.ndarray:
    """Per-point RGB on the elevation ramp, uint8."""
    t = np.clip(np.asarray(z, dtype=np.float64) / max(float(z_max), 1e-6), 0.0, 1.0)
    rgb = _LO[None, :] + (_HI - _LO)[None, :] * t[:, None]
    return (rgb * 255.0).astype(np.uint8)


def undercut_tint(colors: np.ndarray, stock: DexelStock, n_top: int) -> np.ndarray:
    """`colors` with the top points of columns holding more than one
    interval pulled toward the undercut tint, in place."""
    under = stock.undercut().ravel()
    if under.any():
        c = colors[:n_top][under].astype(np.float64) / 255.0
        colors[:n_top][under] = ((0.4 * c + 0.6 * _UNDERCUT[None, :]) * 255.0).astype(np.uint8)
    return colors


def occupancy_grid(stock: DexelStock, pitch: float | None = None,
                   max_cells: int = 60_000_000):
    """The occupancy volume for Flying Edges: ``(occ, origin, spacing)`` with
    `occ` ``(nz, rows, cols)`` bool, or None when the volume would be larger
    than `max_cells` at the coarsest pitch worth drawing (the grid step)."""
    pitch = stock.resolution if pitch is None else float(pitch)
    live = stock.count > 0
    if not live.any():
        return None
    occ, origin3 = stock.to_volume(pitch)
    if occ.size > max_cells:
        return None
    return occ, origin3, (stock.resolution, stock.resolution, pitch)
