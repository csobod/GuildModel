"""Triangles -> Heightfield: the one thing the CAM ever sees.

BUILDPLAN Stage 2 established that the model becomes the master representation
and the raster becomes a *derived* one, so `cam/dropcutter.py`,
`cam/castle_ops.py`, `sim/bed.py`, the worktable and the entire posting chain
keep consuming a `Heightfield` with exactly today's semantics and need no
changes at all. The drop-cutter is hardware-proven and carries the
INCIDENT-2026-07-29 fix in `CUT_RES_MM`; nothing here touches it.

**Why this is a module of its own** *(2026-08-08)*. It was written inside
`core/solid`, and only its first two lines were ever OCCT-specific — the rest
takes vertices and faces. Living there meant the Manifold kernel had no way to
reach the CAM without importing the kernel it replaces, which is how the
`model_kernel` preference came to drive the 3D viewer and nothing else: every
G-code path calls `relief.castle.build_castle_relief` regardless. Splitting the
rasteriser out is what lets a mesh post.

**Why rasterisation rather than ray casting.** BREP-REWRITE-REPORT §4.2
suggested a grid of vertical rays against the tessellation. Taking the max Z of
every triangle covering a cell computes the same answer — the posterior surface
is the upper envelope of a closed solid — but does it in one vectorised pass per
triangle instead of one query per cell, and it is exact within each triangle
rather than sampled at a point.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from shapely import contains_xy, prepare
from shapely.geometry import Polygon

from .geometry.regions import CastlePartition
from .project.schema import CastleParams
from .relief.castle import CUT_RES_MM, GRID_MARGIN_MM, CastleRelief
from .relief.heightfield import Heightfield

ProgressFn = Callable[[str, float], None]

__all__ = ["grid_for", "masks_for", "relief_from_zmap", "triangles_to_zmap"]


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


def triangles_to_zmap(vertices, faces, origin: tuple[float, float],
                      rows: int, cols: int, resolution: float,
                      background: float = 0.0,
                      progress: Optional[ProgressFn] = None) -> np.ndarray:
    """Upper envelope of a triangle soup on the grid, as a (rows, cols) array.

    Cells no triangle covers keep `background`. Nothing here knows or cares
    which kernel produced the triangles.
    """
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
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

    _report(progress, "Sampling the model", 0.40)
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


def masks_for(partition: CastlePartition, origin, rows, cols, resolution,
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


def groove_body(partition: CastlePartition, castle: CastleParams):
    """The footprint the masks use, and the groove params, if it is enabled.

    Returns `(body, groove_or_None)`. With the lens groove on, the visible
    aperture is the rim lip rather than the drawn ring, and both the raster and
    the derived paths have to mask against that same undersized body or they
    disagree over the whole annulus.
    """
    groove = getattr(castle, "lens_groove", None)
    if groove is None or not groove.enabled or groove.depth_mm <= 0:
        return partition.body, None
    # From `geometry.rings`, its home, rather than from `solid.features`, which
    # only re-exports it — going through there would drag OCCT into every
    # G-code build and is exactly the coupling this module exists to break.
    from .geometry.rings import lip_body
    return lip_body(partition.body, groove.depth_mm, partition.is_hole), groove


def relief_from_zmap(z: np.ndarray, partition: CastlePartition,
                     castle: CastleParams, origin, rows: int, cols: int,
                     resolution: float, body: Polygon,
                     groove) -> CastleRelief:
    """Assemble the `CastleRelief` the CAM consumes around a sampled Z-map.

    Everything downstream — ops generation, posting, simulation — reads this
    exactly as it reads the raster builder's output. The masks are 2D and come
    from the partition either way; only `field` changes provenance.
    """
    inside, zone_index = masks_for(partition, origin, rows, cols, resolution,
                                   body)
    return CastleRelief(
        field=Heightfield(z=np.where(inside, z, 0.0), origin=origin,
                          resolution=resolution),
        inside=inside,
        zone_index=zone_index,
        partition=partition,
        groove=groove,
        groove_lens_polys=([Polygon(r) for r in partition.body.interiors
                            if not partition.is_hole(r)] if groove else []),
        mask_body_override=body if groove else None,
    )
