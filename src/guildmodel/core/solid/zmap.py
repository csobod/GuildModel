"""Solid -> Heightfield: the one thing the CAM ever sees (BUILDPLAN Stage 2).

BREP-REWRITE-REPORT.md §4.2 is the whole argument for this module existing. The
B-Rep becomes the master representation and the raster becomes a *derived* one,
so `cam/dropcutter.py`, `cam/castle_ops.py`, `sim/bed.py`, the worktable and the
entire posting chain keep consuming a `Heightfield` with exactly today's
semantics and need no changes at all. The drop-cutter is hardware-proven and
carries the INCIDENT-2026-07-29 fix in `CUT_RES_MM`; nothing here touches it.

**Why rasterisation rather than ray casting.** The report suggested a grid of
vertical rays against the tessellation. Taking the max Z of every triangle
covering a cell computes the same answer — the posterior surface is the upper
envelope of a closed solid — but does it in one vectorised pass per triangle
instead of one query per cell, and it is exact within each triangle rather than
sampled at a point. On the demo frame that is a fraction of a second for the
whole 0.15 mm grid.

The remaining approximation is the tessellation itself, so this meshes at
`CAM_DEFLECTION_MM` (5 um) rather than the viewer's 20 um — a twentieth of the
M2 gate's 0.1 mm tolerance, and well under the 0.15 mm grid it lands on.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from shapely import contains_xy, prepare
from shapely.geometry import Polygon

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams
from ..relief.castle import CUT_RES_MM, GRID_MARGIN_MM, CastleRelief
from ..relief.heightfield import Heightfield
from .tessellate import tessellate

ProgressFn = Callable[[str, float], None]

#: Chordal tolerance for the mesh the Z-map is sampled from. Tighter than the
#: viewer's, because this one becomes G-code.
CAM_DEFLECTION_MM = 0.005

__all__ = ["CAM_DEFLECTION_MM", "grid_for", "solid_to_relief", "solid_to_zmap"]


def _report(progress: Optional[ProgressFn], label: str, frac: float) -> None:
    if progress is not None:
        progress(label, frac)


def grid_for(body: Polygon, resolution: float = CUT_RES_MM,
             margin: float = GRID_MARGIN_MM):
    """(origin, rows, cols) on the same convention as `build_castle_relief`.

    Deliberately mirrors the raster path's arithmetic so the two Z-maps land
    cell-for-cell on top of each other — the §3.5 gate compares them directly,
    and an off-by-one grid would make every comparison meaningless.
    """
    minx, miny, maxx, maxy = body.bounds
    origin = (minx - margin, miny - margin)
    rows = max(2, int(round((maxy - miny + 2 * margin) / resolution)))
    cols = max(2, int(round((maxx - minx + 2 * margin) / resolution)))
    return origin, rows, cols


def solid_to_zmap(solid, origin: tuple[float, float], rows: int, cols: int,
                  resolution: float, deflection: float = CAM_DEFLECTION_MM,
                  background: float = 0.0,
                  progress: Optional[ProgressFn] = None) -> np.ndarray:
    """Upper envelope of `solid` sampled onto the grid, as a (rows, cols) array.

    Cells no triangle covers keep `background`.
    """
    _report(progress, "Tessellating for CAM", 0.10)
    tess = tessellate(solid, deflection=deflection, with_edges=False)
    v, f = tess.vertices, tess.faces
    if len(f) == 0:
        return np.full((rows, cols), background, dtype=np.float64)

    z = np.full((rows, cols), -np.inf, dtype=np.float64)
    ox, oy = origin

    # Triangle coordinates in grid space (columns = x, rows = y).
    tri = v[f]                                        # (m, 3, 3)
    gx = (tri[:, :, 0] - ox) / resolution
    gy = (tri[:, :, 1] - oy) / resolution
    tz = tri[:, :, 2]

    lo_c = np.maximum(np.floor(gx.min(axis=1)).astype(np.int64), 0)
    hi_c = np.minimum(np.ceil(gx.max(axis=1)).astype(np.int64) + 1, cols)
    lo_r = np.maximum(np.floor(gy.min(axis=1)).astype(np.int64), 0)
    hi_r = np.minimum(np.ceil(gy.max(axis=1)).astype(np.int64) + 1, rows)

    x0, x1, x2 = gx[:, 0], gx[:, 1], gx[:, 2]
    y0, y1, y2 = gy[:, 0], gy[:, 1], gy[:, 2]
    denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)

    _report(progress, "Sampling the solid", 0.40)
    for t in range(len(f)):
        c0, c1, r0, r1 = lo_c[t], hi_c[t], lo_r[t], hi_r[t]
        if c1 <= c0 or r1 <= r0:
            continue
        d = denom[t]
        if abs(d) < 1e-12:
            continue                                  # edge-on / degenerate
        cc = np.arange(c0, c1, dtype=np.float64)
        rr = np.arange(r0, r1, dtype=np.float64)
        px, py = np.meshgrid(cc, rr)

        # Barycentric weights; inside when all three are non-negative.
        w0 = ((y1[t] - y2[t]) * (px - x2[t]) + (x2[t] - x1[t]) * (py - y2[t])) / d
        w1 = ((y2[t] - y0[t]) * (px - x2[t]) + (x0[t] - x2[t]) * (py - y2[t])) / d
        w2 = 1.0 - w0 - w1
        hit = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not hit.any():
            continue

        zt = w0 * tz[t, 0] + w1 * tz[t, 1] + w2 * tz[t, 2]
        sub = z[r0:r1, c0:c1]
        np.maximum(sub, np.where(hit, zt, -np.inf), out=sub)

    _report(progress, "Z-map ready", 1.0)
    z[~np.isfinite(z)] = background
    return z


def _masks(partition: CastlePartition, origin, rows, cols, resolution,
           body: Polygon | None = None):
    """`inside` and `zone_index`, built exactly as `build_castle_relief` does.

    Mirrored rather than shared because the raster builder computes them inline
    while carving; a test asserts the two agree cell for cell, which is what
    keeps this copy honest.

    `body` overrides the footprint — with the lens groove on, the visible
    aperture is the rim lip, so both paths mask against the *undersized* body
    or they disagree over the whole annulus.
    """
    ox, oy = origin
    xs = ox + np.arange(cols) * resolution
    ys = oy + np.arange(rows) * resolution
    Xs, Ys = np.meshgrid(xs, ys)
    fx, fy = Xs.ravel(), Ys.ravel()

    body = partition.body if body is None else body
    prepare(body)
    inside = contains_xy(body, fx, fy).reshape(rows, cols)

    zone_index = np.full((rows, cols), -1, dtype=np.int32)
    for i, zone in enumerate(partition.zones):
        prepare(zone.polygon)
        zone_index[contains_xy(zone.polygon, fx, fy).reshape(rows, cols)] = i

    orphan = inside & (zone_index < 0)
    if orphan.any():
        from scipy.ndimage import distance_transform_edt
        _, (ir, ic) = distance_transform_edt(zone_index < 0, return_indices=True)
        zone_index[orphan] = zone_index[ir[orphan], ic[orphan]]
    return inside, zone_index


def solid_to_relief(solid, partition: CastlePartition, castle: CastleParams,
                    resolution: float = CUT_RES_MM,
                    margin: float = GRID_MARGIN_MM,
                    deflection: float = CAM_DEFLECTION_MM,
                    progress: Optional[ProgressFn] = None) -> CastleRelief:
    """A `CastleRelief` whose surface came from the solid.

    Everything downstream — ops generation, posting, simulation — reads this
    exactly as it reads the raster builder's output. The masks are 2D and come
    from the partition either way; only `field` changes provenance.
    """
    groove = getattr(castle, "lens_groove", None)
    grooved = groove is not None and groove.enabled and groove.depth_mm > 0
    body = partition.body
    if grooved:
        from .features import lip_body
        body = lip_body(body, groove.depth_mm, partition.is_hole)

    origin, rows, cols = grid_for(body, resolution, margin)
    z = solid_to_zmap(solid, origin, rows, cols, resolution, deflection,
                      progress=progress)
    inside, zone_index = _masks(partition, origin, rows, cols, resolution, body)
    z = np.where(inside, z, 0.0)

    return CastleRelief(
        field=Heightfield(z=z, origin=origin, resolution=resolution),
        inside=inside,
        zone_index=zone_index,
        partition=partition,
        groove=groove if grooved else None,
        groove_lens_polys=([Polygon(r) for r in partition.body.interiors
                            if not partition.is_hole(r)] if grooved else []),
        mask_body_override=body if grooved else None,
    )
