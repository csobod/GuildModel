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

__all__ = ["grid_for", "masks_for", "relief_from_zmap", "triangle_envelopes",
           "triangles_to_zmap"]

#: Cap on (triangle, cell) pairs held at once by `triangle_envelopes`. The
#: barycentric test needs about a dozen float64 temporaries per pair, so 4M
#: pairs is roughly 200 MB. The cap exists for the blank's underside, which is
#: a handful of triangles each spanning the entire grid; the average triangle
#: covers a few cells.
_MAX_PAIRS = 4_000_000


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


def _envelope_pass(idx, up, dn, want_up, want_dn, ncell, nw, lo_c, lo_r,
                   x0, x1, x2, y0, y1, y2, tz, denom, cols) -> None:
    """Accumulate one facing's triangles into `up` / `dn`, in bounded batches."""
    start = 0
    while start < len(idx):
        end, taken = start, 0
        while end < len(idx) and (taken == 0
                                  or taken + ncell[idx[end]] <= _MAX_PAIRS):
            taken += ncell[idx[end]]
            end += 1
        batch, start = idx[start:end], end

        counts = ncell[batch]
        t = np.repeat(batch, counts)
        # Each pair's offset within its own triangle's bounding box.
        ends = np.cumsum(counts)
        k = np.arange(ends[-1], dtype=np.int64) - np.repeat(ends - counts, counts)
        w = nw[t]
        px = (lo_c[t] + k % w).astype(np.float64)
        py = (lo_r[t] + k // w).astype(np.float64)

        # Barycentric weights; inside when all three are non-negative.
        d = denom[t]
        w0 = ((y1[t] - y2[t]) * (px - x2[t]) + (x2[t] - x1[t]) * (py - y2[t])) / d
        w1 = ((y2[t] - y0[t]) * (px - x2[t]) + (x0[t] - x2[t]) * (py - y2[t])) / d
        w2 = 1.0 - w0 - w1
        hit = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not hit.any():
            continue

        t, w0, w1, w2 = t[hit], w0[hit], w1[hit], w2[hit]
        flat = py[hit].astype(np.int64) * cols + px[hit].astype(np.int64)
        zt = w0 * tz[t, 0] + w1 * tz[t, 1] + w2 * tz[t, 2]

        # Group by cell, then reduce. `np.maximum.at` says this directly and is
        # an order of magnitude slower than sorting first.
        order = np.argsort(flat, kind="stable")
        flat, zt = flat[order], zt[order]
        edges = np.flatnonzero(np.r_[True, flat[1:] != flat[:-1]])
        cells = flat[edges]
        if want_up:
            up[cells] = np.maximum(up[cells], np.maximum.reduceat(zt, edges))
        if want_dn:
            dn[cells] = np.minimum(dn[cells], np.minimum.reduceat(zt, edges))


def triangle_envelopes(vertices, faces, origin: tuple[float, float],
                       rows: int, cols: int, resolution: float,
                       background: float = 0.0,
                       progress: Optional[ProgressFn] = None
                       ) -> tuple[np.ndarray, np.ndarray]:
    """Upper *and* lower envelope of a triangle soup, as two (rows, cols) arrays.

    The upper envelope is the posterior surface the CAM cuts. The lower is the
    anterior face: flat zero on every frame that does not cut the front, and
    exactly what `CastleRelief.anterior` wants on one that does. They come out
    of one pass because the expensive part — locating each triangle's cells and
    solving the barycentric test there — is shared. Cells no triangle covers
    keep `background`, and nothing here knows which kernel made the triangles.

    **Batched, rather than a loop over triangles.** The loop this replaced
    issued about ten numpy calls per triangle, and the average triangle covers
    a handful of cells, so nearly all of its 0.3 s on a real frame was call
    overhead rather than arithmetic. One flat array of (triangle, cell) pairs
    makes it a single vectorised pass — but that array cannot be unbounded,
    because the blank's underside is a few triangles whose bounding box is the
    whole grid. Hence `_MAX_PAIRS`. Measured bit-identical to the loop on the
    gabriel and the aviator, at 5-6.5x.

    **The two envelopes come from disjoint sets of triangles.** `denom` is
    twice the signed area of the triangle projected on the grid, so its sign is
    the sign of the normal's z. On a closed, outward-wound solid only an
    upward-facing face can reach the upper envelope and only a downward-facing
    one the lower; a vertical wall projects to a line and is already dropped as
    degenerate. That halves the arithmetic and takes the underside out of the
    upper pass entirely — those being the largest triangles in the model, it is
    most of the speedup.

    Outward winding is not taken on faith. Inverted or inconsistent winding
    would put the upper envelope *below* the lower one, which is a body of
    negative thickness; that is checked, and the split abandoned for a single
    pass over every triangle if it fails.
    """
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if len(f) == 0:
        bg = np.full((rows, cols), float(background), dtype=np.float64)
        return bg, bg.copy()

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

    nw = np.maximum(hi_c - lo_c, 0)
    ncell = nw * np.maximum(hi_r - lo_r, 0)
    live = (ncell > 0) & (np.abs(denom) >= 1e-12)     # edge-on / degenerate out
    args = (ncell, nw, lo_c, lo_r, x0, x1, x2, y0, y1, y2, tz, denom, cols)

    _report(progress, "Sampling the model", 0.40)
    up = np.full(rows * cols, -np.inf, dtype=np.float64)
    dn = np.full(rows * cols, np.inf, dtype=np.float64)
    _envelope_pass(np.flatnonzero(live & (denom > 0)), up, dn, True, False, *args)
    _envelope_pass(np.flatnonzero(live & (denom < 0)), up, dn, False, True, *args)

    both = np.isfinite(up) & np.isfinite(dn)
    if np.any(up[both] < dn[both] - 1e-9):
        up = np.full(rows * cols, -np.inf, dtype=np.float64)
        dn = np.full(rows * cols, np.inf, dtype=np.float64)
        _envelope_pass(np.flatnonzero(live), up, dn, True, True, *args)

    _report(progress, "Z-map ready", 1.0)
    up = up.reshape(rows, cols)
    dn = dn.reshape(rows, cols)
    up[~np.isfinite(up)] = background
    dn[~np.isfinite(dn)] = background
    return up, dn


def triangles_to_zmap(vertices, faces, origin: tuple[float, float],
                      rows: int, cols: int, resolution: float,
                      background: float = 0.0,
                      progress: Optional[ProgressFn] = None) -> np.ndarray:
    """Just the upper envelope — the posterior surface, and the historical API.

    Kept because that is all the parity gates and the viewer ever wanted; the
    lower envelope costs a second reduction over pairs that are already
    gathered, so asking for both is barely dearer than asking for one.
    """
    return triangle_envelopes(vertices, faces, origin, rows, cols, resolution,
                              background, progress)[0]


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
