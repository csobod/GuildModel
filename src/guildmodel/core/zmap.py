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
rasterizer out is what lets a mesh post.

**Why rasterization rather than ray casting.** BREP-REWRITE-REPORT §4.2
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
from shapely.ops import unary_union

from .geometry.regions import (CastlePartition, body_exteriors, body_interiors,
                               body_parts)
from .kernels import resolve_kernel
from .project.schema import CastleParams
from .relief.castle import CUT_RES_MM, GRID_MARGIN_MM, CastleRelief
from .relief.heightfield import Heightfield

ProgressFn = Callable[[str, float], None]

__all__ = ["FEATURE_BAND_MM", "cam_relief", "castle_relief", "grid_for",
           "masks_for", "relief_from_zmap", "triangle_envelopes",
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


def triangle_crossings(vertices, faces, origin: tuple[float, float],
                       rows: int, cols: int, resolution: float
                       ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every crossing of a vertical column through the triangle soup, as
    three flat arrays: the cell index, the z, and whether the triangle faces
    up. `triangle_envelopes` keeps the extremes of these per cell; the stock
    engine's `DexelStock.from_mesh` keeps them all and pairs them into
    intervals (BUILDPLAN M21 §6.6). Same cells, same barycentric test, same
    batching, so the two agree on every cell they both report."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    empty = (np.zeros(0, dtype=np.int64), np.zeros(0), np.zeros(0, dtype=bool))
    if len(f) == 0:
        return empty
    ox, oy = origin
    tri = v[f]
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
    live = np.flatnonzero((ncell > 0) & (np.abs(denom) >= 1e-12))
    cells, zs, ups = [], [], []
    start = 0
    while start < len(live):
        end, taken = start, 0
        while end < len(live) and (taken == 0 or taken + ncell[live[end]] <= _MAX_PAIRS):
            taken += ncell[live[end]]
            end += 1
        batch, start = live[start:end], end
        counts = ncell[batch]
        t = np.repeat(batch, counts)
        ends = np.cumsum(counts)
        kk = np.arange(ends[-1], dtype=np.int64) - np.repeat(ends - counts, counts)
        w = nw[t]
        px = (lo_c[t] + kk % w).astype(np.float64)
        py = (lo_r[t] + kk // w).astype(np.float64)
        d = denom[t]
        w0 = ((y1[t] - y2[t]) * (px - x2[t]) + (x2[t] - x1[t]) * (py - y2[t])) / d
        w1 = ((y2[t] - y0[t]) * (px - x2[t]) + (x0[t] - x2[t]) * (py - y2[t])) / d
        w2 = 1.0 - w0 - w1
        hit = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not hit.any():
            continue
        t, w0, w1, w2 = t[hit], w0[hit], w1[hit], w2[hit]
        cells.append(py[hit].astype(np.int64) * cols + px[hit].astype(np.int64))
        zs.append(w0 * tz[t, 0] + w1 * tz[t, 1] + w2 * tz[t, 2])
        ups.append(denom[t] > 0)
    if not cells:
        return empty
    return np.concatenate(cells), np.concatenate(zs), np.concatenate(ups)


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
                     resolution: float, body: Polygon, groove,
                     surface_z: np.ndarray | None = None,
                     pocket_polys=(), feature_band: np.ndarray | None = None,
                     feature_max_slope_deg: float = 0.0,
                     anterior: np.ndarray | None = None,
                     anterior_pocket_polys=()) -> CastleRelief:
    """Assemble the `CastleRelief` the CAM consumes around a sampled Z-map.

    Everything downstream — ops generation, posting, simulation — reads this
    exactly as it reads the raster builder's output. The masks are 2D and come
    from the partition either way; only `field` changes provenance.

    The keyword fields default to what a *surface comparison* needs, which is
    nothing but `field`. Posting needs all of them, and `cam_relief` is what
    fills them; the defaults are here so the parity gates and the viewer can go
    on asking for one surface and paying for one build.
    """
    inside, zone_index = masks_for(partition, origin, rows, cols, resolution,
                                   body)
    surface_field = None
    if surface_z is not None:
        surface_field = Heightfield(z=np.where(inside, surface_z, 0.0),
                                    origin=origin, resolution=resolution)
    if anterior is not None:
        anterior = np.where(inside, anterior, 0.0)
        if not anterior.any():
            anterior = None           # nothing cuts the front: the M17 fast path
    if feature_band is not None:
        feature_band = feature_band & inside
        if not feature_band.any():
            feature_band, feature_max_slope_deg = None, 0.0
    return CastleRelief(
        field=Heightfield(z=np.where(inside, z, 0.0), origin=origin,
                          resolution=resolution),
        inside=inside,
        zone_index=zone_index,
        partition=partition,
        groove=groove,
        groove_lens_polys=([Polygon(r) for r in body_interiors(partition.body)
                            if not partition.is_hole(r)] if groove else []),
        mask_body_override=body if groove else None,
        pocket_polys=list(pocket_polys),
        anterior_pocket_polys=list(anterior_pocket_polys),
        surface_field=surface_field,
        feature_band=feature_band,
        feature_max_slope_deg=feature_max_slope_deg,
        anterior=anterior,
    )


#: A cell counts as feature-carved when the featured surface sits this far
#: below the unfeatured one, mm. Not a tolerance on the features — they cut
#: tenths of a millimeter at least — but a floor under the difference between
#: two tessellations of the same terraces, which have different boolean
#: histories and so triangulate curved ground differently.
FEATURE_BAND_MM = 0.005


def _unfeatured(castle: CastleParams):
    """`castle` with every posterior finishing feature off, or None if none was
    on — in which case there is no band to look for and no third build to pay.

    The lens groove stays *on*. It is cut by its own V-tool op rather than by
    the finishing pass, and counting its annulus into the band would add fine
    rings all the way round both rims for nothing.
    """
    if not castle.cuts_posterior_features():
        return None
    plain = castle.model_copy(deep=True)
    plain.pad_splay.enabled = False
    plain.eyewire_bezel.enabled = False
    plain.bridge_relief.enabled = False
    for feature in plain.edge_features:
        feature.enabled = False
    # A sculpt's footprint joins the band the same way (M22 §7.5): the
    # unfeatured build has no sculpts, so the difference finds them.
    plain.sculpts = []
    return plain


def cam_relief(build, partition: CastlePartition, castle: CastleParams,
               hinges=(), resolution: float = CUT_RES_MM,
               margin: float = GRID_MARGIN_MM,
               progress: Optional[ProgressFn] = None,
               inlays=()) -> CastleRelief:
    """A *complete* `CastleRelief` from whichever kernel `build` speaks for.

    `build(partition, castle, hinges, inlays) -> (vertices, faces)`. Both
    kernels supply one; nothing here knows which. `inlays` are the INLAY seat
    polygons, index-aligned with `castle.inlays` (§8a); the posterior seats
    are left out of the surface build like the pockets, since their own op
    cuts them and the relief passes sail over them.

    `relief_from_zmap` alone fills `field` and the groove fields and leaves the
    rest at their defaults. That was enough for the parity gates, which only
    ever compared surfaces, and it is not enough to post from — the CAM also
    reads `surface_field` (the pre-pocket surface the relief passes ride over,
    so they sail across an already-cut pocket instead of diving back to its
    floor), `pocket_polys`, `feature_band` and `feature_max_slope_deg` (the
    fine-relief rings), and `anterior`. Shipping a relief with those defaulted
    would post a program that machines the pockets twice, skips the feature
    finish and cannot see the front — none of it visible in a surface
    comparison, which is the shape of defect this milestone keeps finding.

    **Up to three builds, and usually one.** The pre-pocket surface needs a
    build with no pockets and the band needs one with the finishing features
    off; a frame with neither asks for neither. Fully featured with pockets the
    three cost about 2.2 s against the raster's 0.9 s on the gabriel. The
    raster gets its extra surfaces free because it carves them in sequence into
    one array, which is the one thing a raster is genuinely good at; buying
    them back at 2.5x is the price of a surface that is exact where the raster
    approximates, and it is paid inside a background worker.

    A cheaper arrangement exists — have the kernel hand back its intermediate
    solids rather than rebuild them from the parameters — and it needs surgery
    inside both kernels to save under a second. Measure before spending it.
    """
    body, groove = groove_body(partition, castle)
    origin, rows, cols = grid_for(body, resolution, margin)
    grid = (origin, rows, cols, resolution)

    from .geometry.heights import zone_heights
    from .geometry.inlays import inlay_cuts, zone_reference
    from .geometry.pocket_floor import castle_pocket_floors

    hinges, inlays = list(hinges), list(inlays)
    heights = zone_heights(partition, castle, None)
    seats = inlay_cuts(castle.inlays, inlays,
                       castle_pocket_floors(hinges, castle, partition, heights),
                       posterior_reference=zone_reference(partition, heights))
    posterior_seats = [seat.outline for seat in seats if seat.posterior]

    _report(progress, "Building the part", 0.10)
    z, anterior = triangle_envelopes(*build(partition, castle, hinges, inlays),
                                     *grid)

    surface_z = z
    if hinges or posterior_seats:
        _report(progress, "Building the surface under the pockets", 0.45)
        surface_z, _ = triangle_envelopes(*build(partition, castle, (), ()),
                                          *grid)

    band, slope = None, 0.0
    plain = _unfeatured(castle)
    if plain is not None:
        _report(progress, "Finding the feature band", 0.70)
        plain_z, _ = triangle_envelopes(*build(partition, plain, (), ()), *grid)
        # Either way: a chamfer or a scoop takes material off the plain
        # surface, an embossed sculpt (M22) stands above it.
        band = np.abs(plain_z - surface_z) > FEATURE_BAND_MM
        slope = castle.posterior_feature_slope()

    _report(progress, "Relief ready", 0.92)
    return relief_from_zmap(
        z, partition, castle, origin, rows, cols, resolution, body, groove,
        surface_z=surface_z, pocket_polys=hinges + posterior_seats,
        feature_band=band, feature_max_slope_deg=slope, anterior=anterior,
        anterior_pocket_polys=[seat.outline for seat in seats
                               if not seat.posterior])


#: A pre-formed part's body, for the relief and the verdict, is where it is
#: at least this thick (M25): the tilted walls' slivers are left out.
FORMED_WALL_MM = 1.0


def map_polygon_xy(fmap, poly: Polygon, z: float = 0.0) -> Polygon:
    """`poly`'s rings through the forming map at height `z`, as the polygon
    their formed x, y make: the formed part's footprint of a flat ring (M25).
    At the anterior face by default, where the lens seats and the front's
    edge are what a three-axis cut must get right. Separated rims map rim by
    rim."""
    def ring(coords):
        pts = np.array([(x, y, z) for x, y in coords], dtype=np.float64)
        out = fmap(pts)[:, :2]
        return [tuple(p) for p in out]

    def mapped(part: Polygon) -> Polygon:
        out = Polygon(ring(part.exterior.coords), [ring(r.coords) for r in part.interiors])
        return out if out.is_valid else out.buffer(0)

    parts = [mapped(part) for part in body_parts(poly)]
    if len(parts) == 1:
        return parts[0]
    return unary_union(parts)


def formed_partition(partition: CastlePartition, fmap, z: float = 0.0) -> CastlePartition:
    """The partition as the pressed part lies on the nest (M25): every
    polygon through the map at height `z` (the anterior face by default,
    the back at the blank's thickness), the zones keeping their names, the
    seams dropped (the footings are already in the formed model), the holes
    mapped so `is_hole` still tells an opening from an aperture."""
    from .geometry.regions import Zone
    zones = [Zone(zn.name, zn.kind, zn.side, map_polygon_xy(fmap, zn.polygon, z))
             for zn in partition.zones]
    return CastlePartition(
        body=map_polygon_xy(fmap, partition.body, z), zones=zones, edges=[],
        matched=partition.matched,
        holes=[map_polygon_xy(fmap, h, z) for h in partition.holes])


def castle_relief(partition: CastlePartition, castle: CastleParams,
                  hinges=(), kernel: str = "mesh",
                  resolution: float = CUT_RES_MM,
                  margin: float = GRID_MARGIN_MM,
                  progress: Optional[ProgressFn] = None,
                  inlays=(), sculpt_sources=None, forming=None,
                  bridge=None) -> CastleRelief:
    """The relief every G-code path posts from — one entry point, one choice.

    `kernel` is `gui.mesh_build.KERNELS`: "raster" is the M17 heightfield,
    "mesh" is Manifold, "brep" is OpenCASCADE. Anything else falls back rather
    than raising, because a prefs file is not a contract — and since M-N4
    neither is an *install*: `cadquery-ocp` is an optional extra, so
    `kernels.resolve_kernel` also catches a saved "brep" on a machine without
    it. A maker must never be unable to post a job because of either.

    The fallback is `resolve_kernel`'s and not a second opinion of our own.
    Deciding it here is how the viewer and the CAM would come to disagree about
    the same unrecognized name, which is the failure `_model_kernel` was
    written to prevent from the other end.

    **This is the line the `model_kernel` preference did not used to cross.**
    Through M-N3 the setting governed the 3D viewer and nothing a machine cut,
    because every posting path called `relief.castle.build_castle_relief`
    directly and a model had no way to become a `Heightfield`. Routing them all
    through here is what makes the choice mean the same thing on screen and on
    the spindle.

    The CAM itself is untouched and stays that way: it consumes a
    `CastleRelief` and cannot import either kernel, which `test_kernel_flip_mn3`
    checks by AST. Choosing the surface is the caller's job; cutting it is the
    CAM's.
    """
    kernel = resolve_kernel(kernel)
    # A pre-formed blank (M25): the target is the formed model, so the mesh
    # kernel builds it whatever the preference says (it is the one that
    # warps), and the pressed slab's envelopes ride on the relief.
    fmap = None
    if forming is not None and getattr(castle.stock, "preformed", False):
        from .forming import ThermoformMap, bridge_geometry
        # the slab as the dies press it, not the formed part's full shape
        fmap = ThermoformMap.from_metadata(
            forming.pressed(),
            bridge=bridge if bridge is not None else bridge_geometry(partition))
        if fmap.is_flat:
            fmap = None
    if fmap is not None:
        from .forming.blank import formed_blank_envelopes
        from .model.zmap import mesh_cam_relief
        # The formed part's walls lean with the curve, so its footprint at
        # the back sits inside its footprint at the front by the thickness
        # times the sine of the tilt. The masks, the hinge pockets and the
        # seats are cut from the back and take the drawing's polygons
        # through the map at the blank's thickness; the apertures and the
        # perimeter, which a three-axis cut makes vertical, take them at the
        # anterior face, where the lens seats and the front's edge are what
        # must be right. The wall's own sliver between the two is nobody's.
        T = float(castle.stock.blank_thickness_mm)
        fp_back = formed_partition(partition, fmap, z=T)
        fp_front = formed_partition(partition, fmap, z=0.0)
        hinges_f = [map_polygon_xy(fmap, h, z=T) for h in hinges]
        inlays_f = [map_polygon_xy(fmap, p, z=T) for p in inlays]
        relief = mesh_cam_relief(partition, castle, hinges, resolution, margin,
                                 progress, inlays=inlays,
                                 sculpt_sources=sculpt_sources, fmap=fmap,
                                 masks=(fp_back, hinges_f, inlays_f))
        relief.partition = fp_front
        if relief.mask_body_override is not None:
            # The groove's lip body, at the front's footprint with the
            # partition: left at the back's, the eyewires and the perimeter
            # were cut inside the front's edge by the walls' lean (the 2.0
            # bug hunt).
            relief.mask_body_override, _ = groove_body(fp_front, castle)
            relief.groove_lens_polys = [Polygon(r) for r in body_interiors(fp_front.body)
                                        if not fp_front.is_hole(r)]
        relief.hinge_polys_formed = hinges_f
        relief.inlay_polys_formed = inlays_f
        # The sculpts stand where the pressed part has them: their shadows in
        # the flat frame put Sculpt Finish over the wrong area (the 2.0 bug hunt).
        relief.sculpt_footprints = [map_polygon_xy(fmap, p, z=T)
                                    for p in relief.sculpt_footprints]
        relief.wall_lean_mm = max(
            (float(front.hausdorff_distance(back)) for front, back in
             zip(body_exteriors(fp_front.body), body_exteriors(fp_back.body))),
            default=0.0)
        f = relief.field
        rows, cols = f.z.shape
        apertures = ()
        if getattr(castle.stock, "apertures_first", False):
            # the openings the flat program cut: the rim lip when the groove
            # is on (the groove widens them later), the drawn apertures else
            body_cut, _ = groove_body(partition, castle)
            is_hole = partition.is_hole
            apertures = [Polygon(r) for r in body_interiors(body_cut) if not is_hole(r)]
        top, bottom = formed_blank_envelopes(castle.stock, fmap, f.origin, rows, cols,
                                             f.resolution, apertures=apertures)
        # Where the slab has no material (past its edge, or an aperture cut
        # before pressing) the stock reads far below everything, so a pass
        # finds nothing to cut there and no NaN reaches a toolpath.
        low = float(np.nanmin(bottom)) - 1.0 if np.isfinite(bottom).any() else -1.0
        top = np.where(np.isfinite(top), top, low)
        bottom = np.where(np.isfinite(bottom), bottom, low)
        relief.stock_top = Heightfield(z=top, origin=f.origin, resolution=f.resolution)
        relief.stock_bottom = Heightfield(z=bottom, origin=f.origin, resolution=f.resolution)
        # What the front carries to cut is what the flat front carries,
        # pressed along with the slab: the flat model's own lower envelope,
        # the depth off the flat front, mapped onto the formed grid and laid
        # on the slab's bottom. The formed mesh's lower envelope itself would
        # read every leaning wall as a cut into the front.
        from .model.zmap import _triangles
        fv, ff = _triangles(partition, castle, hinges, inlays, sculpt_sources, None)
        fo, fr, fc_ = grid_for(partition.body, resolution, margin)
        _, flat_depth = triangle_envelopes(fv, ff, fo, fr, fc_, resolution,
                                           background=np.nan)
        depth2 = np.zeros((rows, cols))
        # Every cell of the flat body is carried, cut or not, so a formed cell
        # that no flat cell lands on is told from one with nothing cut: each
        # flat cell lands on its nearest formed cell, and along the front's
        # edge some formed cells take none. They read as the uncut slab, a
        # cell wide at a chamfer's foot, where the cut is deepest, and held
        # the anterior's tools up off the chamfer (the 2.0 bug hunt); within the
        # front's footprint they take their nearest carried neighbor's depth.
        rr, cc = np.nonzero(np.isfinite(flat_depth))
        if len(rr):
            from scipy.ndimage import distance_transform_edt
            pts = np.column_stack([fo[0] + cc * resolution, fo[1] + rr * resolution,
                                   np.zeros(len(rr))])
            w = fmap(pts)
            ci = np.round((w[:, 0] - f.origin[0]) / resolution).astype(int)
            ri = np.round((w[:, 1] - f.origin[1]) / resolution).astype(int)
            ok = (ci >= 0) & (ci < cols) & (ri >= 0) & (ri < rows)
            np.maximum.at(depth2, (ri[ok], ci[ok]),
                          np.clip(flat_depth[rr[ok], cc[ok]], 0.0, None))
            hit = np.zeros((rows, cols), dtype=bool)
            hit[ri[ok], ci[ok]] = True
            X, Y = np.meshgrid(f.origin[0] + np.arange(cols) * resolution,
                               f.origin[1] + np.arange(rows) * resolution)
            prepare(fp_front.body)
            holes = ~hit & contains_xy(fp_front.body, X, Y)
            if holes.any():
                _, (iy, ix) = distance_transform_edt(~hit, return_indices=True)
                depth2[holes] = depth2[iy[holes], ix[holes]]
        relief.anterior = np.where(np.isfinite(bottom), bottom, low) + depth2
        # The formed part's walls tilt with the curve, so the footprint at the
        # anterior face runs outside the posterior edge by the thickness times
        # the sine of the tilt. A three-axis cut makes the wall vertical at the
        # front edge; the sliver between is not a surface the relief can reach
        # or the verdict should ask for, so the body is where the part has
        # real thickness (the wall's own cells excepted).
        thick = (relief.field.z - relief.stock_bottom.z) > FORMED_WALL_MM
        relief.inside = relief.inside & thick
        relief.zone_index = np.where(relief.inside, relief.zone_index, -1)
        return relief
    if kernel == "mesh":
        from .model.zmap import mesh_cam_relief
        return mesh_cam_relief(partition, castle, hinges, resolution, margin,
                               progress, inlays=inlays,
                               sculpt_sources=sculpt_sources)
    if kernel == "brep":
        from .solid.zmap import solid_cam_relief
        return solid_cam_relief(partition, castle, hinges, resolution, margin,
                                progress=progress, inlays=inlays)
    from .relief.castle import build_castle_relief
    return build_castle_relief(partition, castle, list(hinges),
                               resolution=resolution, margin=margin,
                               progress=progress, inlay_polys=list(inlays))
