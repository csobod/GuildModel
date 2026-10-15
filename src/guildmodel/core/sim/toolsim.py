"""Tool-profile material-removal Z-buffer (BUILDPLAN M5).

The simulator sweeps the tool along cutting moves and keeps, per XY cell, the
lowest Z the tool body reaches — the machined surface ("achieved floor").

Each tool has a *drop profile* ``dz(d)`` = how far the tool's lower surface sits
above its tip at radial offset ``d`` from the axis:

  * flat   — ``dz = 0`` for ``d ≤ R`` (a cylinder; the flat bottom is the tip)
  * ball   — ``dz = R - sqrt(R² - d²)`` (a sphere tangent at the tip)
  * toroid — flat to ``Rf = R - rc``, then a corner radius ``rc`` to ``R``

So a tool whose tip is at ``z`` removes material down to ``z + dz(d)`` at offset
``d``. The achieved floor at a cell is the min of that over every swept point.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class ToolProfile:
    kind: str = "flat"            # flat | ball | toroid | vbit
    radius_mm: float = 1.5875
    corner_radius_mm: float = 0.0  # toroid corner radius (0 = flat/ball)
    included_angle_deg: float = 0.0  # vbit tip (included) angle

    @classmethod
    def from_tool(cls, tool: dict) -> "ToolProfile":
        return cls(
            kind=tool.get("type", "flat"),
            radius_mm=tool["radius_mm"],
            corner_radius_mm=tool.get("corner_radius_mm", 0.0) or 0.0,
            included_angle_deg=tool.get("included_angle_deg", 0.0) or 0.0,
        )

    def kernel(self, resolution: float):
        """Return (di, dj, dz) integer cell offsets within the tool radius and
        the drop-profile height at each, for a grid of the given resolution.

        The stock engine's `ToolShape.footprint` since M21, which carries the
        same arithmetic; the groove form, whose occupancy has a top, stamps
        nothing here — the Lens Groove op is verified geometrically
        (castle_ops.verify_groove_op) and the stock engine simulates it."""
        from ..stock.tools import ToolShape
        if self.kind == "groove":
            e = np.zeros(0, dtype=np.intp)
            return e, e.copy(), np.zeros(0, dtype=np.float64)
        fp = ToolShape(kind=self.kind, radius_mm=self.radius_mm,
                       corner_radius_mm=self.corner_radius_mm,
                       included_angle_deg=self.included_angle_deg).footprint(resolution)
        return fp.di, fp.dj, fp.z_lo

    def shape(self):
        """The stock engine's shape for this profile."""
        from ..stock.tools import ToolShape
        return ToolShape(kind=self.kind, radius_mm=self.radius_mm,
                         corner_radius_mm=self.corner_radius_mm,
                         included_angle_deg=self.included_angle_deg)


def densify(path: list[Point3], spacing: float) -> np.ndarray:
    """Resample a 3D polyline to ~`spacing` point spacing (XY-arclength based)."""
    pts = np.asarray(path, dtype=np.float64)
    if len(pts) < 2:
        return pts
    out = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        d = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        n = max(1, int(d / spacing))
        for k in range(1, n + 1):
            out.append(a + (b - a) * (k / n))
    return np.asarray(out)


#: Most (tool positions x kernel cells) stamped in one batch: about 100 MB of
#: temporaries. See `_stamp_points`.
_STAMP_BUDGET = 2_000_000


def _stamp_points(floor, P, kernel, origin, resolution, shape) -> None:
    """Stamp pre-densified tool positions ``P`` (N×3) into ``floor`` (in place,
    min-Z). The per-position kernel disc/profile is broadcast and ``np.minimum``-
    reduced. Shared by `_stamp_path` and the M7.12.1 removal playback (which stamps
    sub-path batches for fine-grained frames)."""
    P = np.asarray(P, dtype=np.float64)
    di, dj, dz = kernel
    if P.size == 0 or di.size == 0:
        return
    ox, oy = origin
    rows, cols = shape
    ci = np.round((P[:, 0] - ox) / resolution).astype(np.intp)
    ri = np.round((P[:, 1] - oy) / resolution).astype(np.intp)
    z = P[:, 2]
    # In batches: the broadcast is (positions x kernel cells), at about fifty
    # bytes an element across its index, height and mask temporaries. A whole
    # path at once was unbounded: a 1 mm tool on a 0.02 mm grid is 7,854 cells,
    # and one pocket path of 50,000 positions asked for 15 GB (2026-09-30: it
    # took the maker's machine down mid-suite). A minimum is the same taken in
    # parts, so the floor is identical bit for bit.
    step = max(1, _STAMP_BUDGET // di.size)
    for s in range(0, len(z), step):
        e = s + step
        cc = (ci[s:e, None] + di[None, :]).ravel()
        rr = (ri[s:e, None] + dj[None, :]).ravel()
        zz = (z[s:e, None] + dz[None, :]).ravel()
        ok = (cc >= 0) & (cc < cols) & (rr >= 0) & (rr < rows)
        np.minimum.at(floor, (rr[ok], cc[ok]), zz[ok])


def _stamp_path(floor, path, kernel, origin, resolution, shape, spacing) -> None:
    """Stamp one cutting path's tool sweep into `floor` (in place, min-Z)."""
    P = densify(path, spacing) if len(path) > 1 else np.asarray(path, float)
    _stamp_points(floor, P, kernel, origin, resolution, shape)


def achieved_floor(
    paths: list[list[Point3]],
    tool: ToolProfile,
    origin: tuple[float, float],
    shape: tuple[int, int],
    resolution: float,
    init_z: float,
    point_spacing: float | None = None,
    progress: Callable[[float], None] | None = None,
) -> np.ndarray:
    """Lowest Z the tool reaches at each cell over all cutting `paths`.

    Cells the tool never passes over keep `init_z`. `paths` are cutting moves
    only (rapids excluded).

    A facade over the stock engine since M21: a one-interval stock with no
    bottom, cut by `core.stock.cut` (the C++ kernel where installed), reads
    back as the floor this stamped — the same array, bit for bit
    (`test_stock_reference`), at a fraction of the time.
    """
    return achieved_floor_grouped([(p, None) for p in paths], {}, tool, origin, shape,
                                  resolution, init_z, point_spacing, progress)


def achieved_floor_grouped(
    groups: list[tuple[list[Point3], object]],
    profiles: dict,
    default: ToolProfile,
    origin: tuple[float, float],
    shape: tuple[int, int],
    resolution: float,
    init_z: float,
    point_spacing: float | None = None,
    progress: Callable[[float], None] | None = None,
) -> np.ndarray:
    """Multi-tool achieved floor (BUILDPLAN M6.1).

    `groups` is ``(path, key)`` per cutting move; each path is stamped with the
    tool profile ``profiles.get(key, default)`` — so a small tool's pocket and
    the bulk tool's relief are simulated with their own geometry.

    `init_z` may be a heightfield of the grid's shape (M20): a bed of blanks of
    different thicknesses starts each cell at its own stock top.

    Through the stock engine since M21 (see `achieved_floor`); the groove
    form stamps nothing here, as it never did.
    """
    from ..relief.heightfield import Heightfield
    from ..stock.cutting import cut, poses_from_path
    from ..stock.dexel import DexelStock

    rows, cols = shape
    if np.ndim(init_z) == 2:
        field = Heightfield(z=np.array(init_z, dtype=np.float64), origin=origin,
                            resolution=resolution)
    else:
        field = Heightfield(z=np.full((rows, cols), float(init_z)), origin=origin,
                            resolution=resolution)
    stock = DexelStock.from_heightfield(field, z_bottom=-np.inf, k=1)
    spacing = point_spacing or resolution
    footprints: dict = {}
    n = len(groups) or 1
    for idx, (path, k) in enumerate(groups):
        if len(path) < 1:
            continue
        prof = profiles.get(k, default)
        if prof.kind == "groove":
            continue                              # stamps nothing, as it never did
        shp = prof.shape()
        if shp not in footprints:
            footprints[shp] = shp.footprint(resolution)
        if len(footprints[shp]) == 0:
            continue
        cut(stock, poses_from_path(path, spacing), shp, footprint=footprints[shp])
        if progress is not None and (idx % 16 == 0):
            progress(idx / n)
    if progress is not None:
        progress(1.0)
    return stock.top().z
