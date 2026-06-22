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
        the drop-profile height at each, for a grid of the given resolution."""
        R = self.radius_mm
        r_px = max(1, int(round(R / resolution)))
        jj, ii = np.mgrid[-r_px:r_px + 1, -r_px:r_px + 1]
        d = np.hypot(ii, jj) * resolution
        inside = d <= R + 1e-9
        di = ii[inside].astype(np.intp)
        dj = jj[inside].astype(np.intp)
        dd = np.minimum(d[inside], R)
        if self.kind == "ball":
            dz = R - np.sqrt(np.maximum(0.0, R * R - dd * dd))
        elif self.kind == "toroid" and self.corner_radius_mm > 0:
            rc = self.corner_radius_mm
            Rf = max(0.0, R - rc)
            dz = np.where(
                dd <= Rf, 0.0,
                rc - np.sqrt(np.maximum(0.0, rc * rc - (dd - Rf) ** 2)),
            )
        elif self.kind == "vbit" and self.included_angle_deg > 0:
            # a cone: the surface rises dz = d / tan(half-angle) above the tip, so
            # the groove width = 2·depth·tan(half-angle) (engraving / V-carving).
            t = math.tan(math.radians(self.included_angle_deg / 2.0))
            dz = dd / t if t > 1e-9 else np.zeros_like(dd)
        else:                      # flat (and toroid with rc=0)
            dz = np.zeros_like(dd)
        return di, dj, dz.astype(np.float64)


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


def _stamp_path(floor, path, kernel, origin, resolution, shape, spacing) -> None:
    """Stamp one cutting path's tool sweep into `floor` (in place, min-Z)."""
    di, dj, dz = kernel
    ox, oy = origin
    rows, cols = shape
    P = densify(path, spacing) if len(path) > 1 else np.asarray(path, float)
    ci = np.round((P[:, 0] - ox) / resolution).astype(np.intp)
    ri = np.round((P[:, 1] - oy) / resolution).astype(np.intp)
    z = P[:, 2]
    cc = (ci[:, None] + di[None, :]).ravel()
    rr = (ri[:, None] + dj[None, :]).ravel()
    zz = (z[:, None] + dz[None, :]).ravel()
    ok = (cc >= 0) & (cc < cols) & (rr >= 0) & (rr < rows)
    np.minimum.at(floor, (rr[ok], cc[ok]), zz[ok])


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
    only (rapids excluded). Vectorised disc/profile stamping per path.
    """
    floor = np.full(shape, float(init_z), dtype=np.float64)
    kernel = tool.kernel(resolution)
    spacing = point_spacing or resolution
    n = len(paths) or 1
    for idx, path in enumerate(paths):
        if len(path) < 1:
            continue
        _stamp_path(floor, path, kernel, origin, resolution, shape, spacing)
        if progress is not None and (idx % 16 == 0):
            progress(idx / n)
    if progress is not None:
        progress(1.0)
    return floor


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
    the bulk tool's relief are simulated with their own geometry. Kernels are
    cached per distinct profile.
    """
    floor = np.full(shape, float(init_z), dtype=np.float64)
    spacing = point_spacing or resolution
    kernels: dict = {}

    def _kern(prof: ToolProfile):
        key = (prof.kind, prof.radius_mm, prof.corner_radius_mm,
               prof.included_angle_deg)
        if key not in kernels:
            kernels[key] = prof.kernel(resolution)
        return kernels[key]

    n = len(groups) or 1
    for idx, (path, k) in enumerate(groups):
        if len(path) < 1:
            continue
        prof = profiles.get(k, default)
        _stamp_path(floor, path, _kern(prof), origin, resolution, shape, spacing)
        if progress is not None and (idx % 16 == 0):
            progress(idx / n)
    if progress is not None:
        progress(1.0)
    return floor
