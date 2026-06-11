"""Castle relief builder (BUILDPLAN M2): terraces, footing blends, stock.

Builds the posterior surface of a frame front the way the maker models it
(DEMO_PROJECT_TEARDOWN.md): each castle zone is a flat terrace at its own
height (towers first, then walls), and every step edge between zones is
blended with a rolling-ball footing fillet pair — a convex (exterior) arc
tangent to the high terrace meeting a concave (interior) arc tangent to the
low terrace.

The footing is computed analytically per edge instead of by grey morphology:
for the demo's straight SCULPT cuts the cross-section profile depends only on
the signed distance to the cut line, so each edge band is an exact two-arc
S-blend (with a residual wall when the step is taller than the radii allow).
The arcs meet at the cut line. Composite rule at band overlaps: low-side
fills apply first, high-side carves win (a later fillet cuts).

Also here: the two-level stock heightfield (blank + pad block), the
heightfield analogue of the complex Fusion stock model.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np
from shapely import contains_xy, distance, points, prepare
from shapely.geometry import Polygon

from ..geometry.regions import CastlePartition
from ..project.schema import CastleParams, StockDefinition
from .heightfield import Heightfield

PREVIEW_RES_MM = 0.3
VALIDATE_RES_MM = 0.2
GRID_MARGIN_MM = 2.0


@dataclass
class CastleRelief:
    """Rasterized posterior surface plus the masks needed downstream."""
    field: Heightfield          # posterior z over the full grid (mm)
    inside: np.ndarray          # bool (rows, cols): inside body (lens holes excluded)
    zone_index: np.ndarray      # int (rows, cols): index into partition.zones, -1 outside
    partition: CastlePartition

    @property
    def Xs(self) -> np.ndarray:
        cols = self.field.z.shape[1]
        xs = self.field.origin[0] + np.arange(cols) * self.field.resolution
        return np.broadcast_to(xs, self.field.z.shape)

    @property
    def Ys(self) -> np.ndarray:
        rows = self.field.z.shape[0]
        ys = self.field.origin[1] + np.arange(rows) * self.field.resolution
        return np.broadcast_to(ys[:, None], self.field.z.shape)


# ------------------------------------------------------------------ stock

def stock_top_heightfield(
    stock: StockDefinition,
    resolution: float = PREVIEW_RES_MM,
    origin: tuple[float, float] | None = None,
    shape: tuple[int, int] | None = None,
) -> Heightfield:
    """Two-level stock top surface: blank thickness, pad-block region higher.

    Blank is centered on the world origin (frame coordinates); the pad block
    sits at (pad_block_dx_mm, pad_block_dy_mm) from the blank center. With no
    explicit grid the field covers exactly the blank.
    """
    if origin is None or shape is None:
        origin = (-stock.blank_length_mm / 2.0, -stock.blank_width_mm / 2.0)
        rows = max(1, int(round(stock.blank_width_mm / resolution)))
        cols = max(1, int(round(stock.blank_length_mm / resolution)))
        shape = (rows, cols)
    rows, cols = shape
    xs = origin[0] + np.arange(cols) * resolution
    ys = origin[1] + np.arange(rows) * resolution
    Xs, Ys = np.meshgrid(xs, ys)

    z = np.full(shape, stock.blank_thickness_mm, dtype=np.float64)
    half_l = stock.pad_block_length_mm / 2.0
    half_w = stock.pad_block_width_mm / 2.0
    in_pad = (
        (np.abs(Xs - stock.pad_block_dx_mm) <= half_l)
        & (np.abs(Ys - stock.pad_block_dy_mm) <= half_w)
    )
    z[in_pad] = stock.total_pad_height_mm
    return Heightfield(z=z, origin=origin, resolution=resolution)


# ------------------------------------------------------------------ footing profile
#
# Cross-section of a footing blend, as a function of signed distance s from
# the cut line (s < 0 on the high terrace, s > 0 on the low one). Sequential
# rolling-ball construction matching Fusion's fillet behaviour, verified
# against the Demo Project STL to < 0.01 mm rms (_probe_profiles.py):
#
#   * step taller than both radii combined: two independent quarter rounds
#     with a vertical wall between them.
#   * otherwise the FIRST fillet cannot be tangent to the (too short) wall,
#     so it rolls through the far corner of the step; the SECOND fillet then
#     lands tangent to the first arc and to its own terrace plane.
#
# The profile is fully described by the two circle centers: convex C1 at
# (a, h_high - r_ext), concave C2 at (b, h_low + r_int), a <= b.


def _footing_centers(
    delta_h: float, r_ext: float, r_int: float, first: str,
) -> tuple[float, float] | None:
    """Return (a, b) circle-center stations, or None for a degenerate edge."""
    if delta_h <= 0 or (r_ext <= 0 and r_int <= 0):
        return None
    if delta_h >= r_ext + r_int:        # both quarter rounds fit; wall remains
        return -r_ext, r_int
    reach = float(np.sqrt(delta_h * (2.0 * (r_ext + r_int) - delta_h)))
    if first == "exterior":
        # convex arc tangent to the high plane, through the step's bottom
        # corner (clamped to a quarter round if the radius can't reach it)
        arg = r_ext**2 - (r_ext - delta_h) ** 2
        a = -float(np.sqrt(arg)) if arg > 0 else -r_ext
        return a, a + reach
    # interior first: concave arc tangent to the low plane, through the top corner
    arg = r_int**2 - (r_int - delta_h) ** 2
    b = float(np.sqrt(arg)) if arg > 0 else r_int
    return b - reach, b


def _footing_spans(
    delta_h: float, r_ext: float, r_int: float, first: str = "interior",
) -> tuple[float, float]:
    """(span_high, span_low): how far the blend reaches into each terrace."""
    centers = _footing_centers(delta_h, r_ext, r_int, first)
    if centers is None:
        return 0.0, 0.0
    a, b = centers
    return max(0.0, -a), max(0.0, b)


def _footing_z(
    s: np.ndarray,
    h_high: float,
    h_low: float,
    r_ext: float,
    r_int: float,
    first: str = "interior",
) -> np.ndarray:
    """Blend height at signed distance s from the cut."""
    centers = _footing_centers(h_high - h_low, r_ext, r_int, first)
    z = np.where(s <= 0, h_high, h_low).astype(np.float64)
    if centers is None:
        return z
    a, b = centers
    cz1 = h_high - r_ext
    cz2 = h_low + r_int
    if h_high - h_low >= r_ext + r_int:
        tx_lo, tx_hi = 0.0, 0.0          # vertical wall at the cut line
    else:
        # arcs meet on the line between centers
        tx_lo = tx_hi = a + (b - a) * (r_ext / (r_ext + r_int) if r_ext + r_int > 0 else 0.5)
    on_c1 = (s > a) & (s <= tx_hi)
    if on_c1.any():
        z[on_c1] = cz1 + np.sqrt(np.maximum(0.0, r_ext**2 - (s[on_c1] - a) ** 2))
    on_c2 = (s > tx_lo) & (s < b)
    if on_c2.any():
        z[on_c2] = cz2 - np.sqrt(np.maximum(0.0, r_int**2 - (s[on_c2] - b) ** 2))
    return np.clip(z, h_low, h_high)


# ------------------------------------------------------------------ builder

def build_castle_relief(
    partition: CastlePartition,
    castle: CastleParams,
    hinge_polys: list[Polygon] = (),
    resolution: float = PREVIEW_RES_MM,
    margin: float = GRID_MARGIN_MM,
    heights: dict[str, float] | None = None,
) -> CastleRelief:
    """Rasterize the castle: terraces -> footing blends -> hinge pockets.

    heights: optional zone-name -> height override (used for generic
    partitions / tests). Defaults to castle.zones.for_kind per zone; requires
    partition.matched when omitted.
    """
    if heights is None:
        if not partition.matched:
            raise ValueError(
                "partition did not match the standard castle layout; "
                "pass explicit zone heights"
            )
        heights = {z.name: castle.zones.for_kind(z.kind) for z in partition.zones}

    body = partition.body
    minx, miny, maxx, maxy = body.bounds
    ox, oy = minx - margin, miny - margin
    rows = max(2, int(round((maxy - miny + 2 * margin) / resolution)))
    cols = max(2, int(round((maxx - minx + 2 * margin) / resolution)))
    xs = ox + np.arange(cols) * resolution
    ys = oy + np.arange(rows) * resolution
    Xs, Ys = np.meshgrid(xs, ys)
    flat_x, flat_y = Xs.ravel(), Ys.ravel()

    prepare(body)
    inside = contains_xy(body, flat_x, flat_y).reshape(rows, cols)

    # Zone raster: index into partition.zones, -1 where unassigned.
    zone_index = np.full((rows, cols), -1, dtype=np.int32)
    for i, zone in enumerate(partition.zones):
        prepare(zone.polygon)
        hit = contains_xy(zone.polygon, flat_x, flat_y).reshape(rows, cols)
        zone_index[hit] = i
    # Inside-body pixels that fell on zone boundaries: adopt the nearest zone.
    orphan = inside & (zone_index < 0)
    if orphan.any():
        from scipy.ndimage import distance_transform_edt
        _, (ir, ic) = distance_transform_edt(zone_index < 0, return_indices=True)
        zone_index[orphan] = zone_index[ir[orphan], ic[orphan]]

    # ---- Terraces (towers, then walls — same result, flat per zone) ----
    height_by_index = np.array(
        [heights[z.name] for z in partition.zones], dtype=np.float64
    )
    z = np.zeros((rows, cols), dtype=np.float64)
    assigned = zone_index >= 0
    z[assigned] = height_by_index[zone_index[assigned]]

    # ---- Footing blends: fills (low side) first, then carves (high side) ----
    zone_pos = {zone.name: i for i, zone in enumerate(partition.zones)}
    fill = z.copy()
    carve = np.full_like(z, np.inf)
    for edge in partition.edges:
        if len(edge.zone_names) != 2:
            continue
        ia, ib = (zone_pos[n] for n in edge.zone_names)
        ha, hb = height_by_index[ia], height_by_index[ib]
        if ha == hb:
            continue
        if ha < hb:
            ia, ib, ha, hb = ib, ia, hb, ha          # ia/ha = high side
        if edge.canonical:
            f = castle.footing.for_edge(edge.canonical)
            r_ext, r_int, first = f.exterior_mm, f.interior_mm, f.first
        else:
            r_ext, r_int, first = 0.0, 0.0, "interior"
        span_high, span_low = _footing_spans(ha - hb, r_ext, r_int, first)
        if span_high == 0 and span_low == 0:
            continue

        # Subgrid covering the band around this cut.
        pad = max(span_high, span_low) + 2 * resolution
        bx0, by0, bx1, by1 = edge.cut.bounds
        c0 = max(0, int((bx0 - pad - ox) / resolution))
        c1 = min(cols, int((bx1 + pad - ox) / resolution) + 2)
        r0 = max(0, int((by0 - pad - oy) / resolution))
        r1 = min(rows, int((by1 + pad - oy) / resolution) + 2)
        if c0 >= c1 or r0 >= r1:
            continue
        sub = (slice(r0, r1), slice(c0, c1))

        d = distance(points(Xs[sub].ravel(), Ys[sub].ravel()), edge.cut)
        d = d.reshape(r1 - r0, c1 - c0)
        zi = zone_index[sub]
        on_high = (zi == ia) & (d < span_high)
        on_low = (zi == ib) & (d < span_low)
        if on_high.any():
            prof = _footing_z(-d[on_high], ha, hb, r_ext, r_int, first)
            tgt = carve[sub]
            tgt[on_high] = np.minimum(tgt[on_high], prof)
            carve[sub] = tgt
        if on_low.any():
            prof = _footing_z(d[on_low], ha, hb, r_ext, r_int, first)
            tgt = fill[sub]
            tgt[on_low] = np.maximum(tgt[on_low], prof)
            fill[sub] = tgt

    z = np.minimum(fill, carve)

    # ---- Hinge pockets: sharp-walled cut below the endpiece height ----
    pocket_floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    for poly in hinge_polys:
        prepare(poly)
        in_pocket = contains_xy(poly, flat_x, flat_y).reshape(rows, cols)
        z[in_pocket & inside] = np.minimum(z[in_pocket & inside], pocket_floor)

    z[~inside] = 0.0
    field = Heightfield(z=z, origin=(ox, oy), resolution=resolution)
    return CastleRelief(field=field, inside=inside, zone_index=zone_index, partition=partition)


# ------------------------------------------------------------------ mesh

def build_castle_mesh(relief: CastleRelief) -> "trimesh.Trimesh":  # noqa: F821
    """Watertight solid: castle top, flat anterior at z=0, stitched rim.

    Works on the masked grid, so the rim follows every boundary ring —
    outline and lens holes alike (closes the spike's open-mesh issue).
    """
    import trimesh

    z = relief.field.z
    inside = relief.inside
    rows, cols = z.shape

    vid = np.full((rows, cols), -1, dtype=np.int64)
    valid = np.argwhere(inside)
    n = len(valid)
    if n == 0:
        return trimesh.Trimesh()
    vid[inside] = np.arange(n)

    rr, cc = valid[:, 0], valid[:, 1]
    res = relief.field.resolution
    x = relief.field.origin[0] + cc * res
    y = relief.field.origin[1] + rr * res
    verts = np.vstack([
        np.column_stack([x, y, z[rr, cc]]),       # top
        np.column_stack([x, y, np.zeros(n)]),     # anterior (z = 0)
    ])

    r0, c0 = np.mgrid[0:rows - 1, 0:cols - 1]
    r0, c0 = r0.ravel(), c0.ravel()
    i00 = vid[r0, c0]
    i01 = vid[r0, c0 + 1]
    i10 = vid[r0 + 1, c0]
    i11 = vid[r0 + 1, c0 + 1]
    ok = (i00 >= 0) & (i01 >= 0) & (i10 >= 0) & (i11 >= 0)
    i00, i01, i10, i11 = i00[ok], i01[ok], i10[ok], i11[ok]

    top = np.vstack([
        np.column_stack([i00, i01, i10]),
        np.column_stack([i10, i01, i11]),
    ])
    bottom = np.vstack([
        np.column_stack([i00 + n, i10 + n, i01 + n]),
        np.column_stack([i10 + n, i11 + n, i01 + n]),
    ])

    # Rim: boundary edges of the top surface (edges used by exactly one face),
    # stitched straight down to the matching anterior vertices.
    edges = np.vstack([top[:, [0, 1]], top[:, [1, 2]], top[:, [2, 0]]])
    key = np.sort(edges, axis=1)
    _, first_idx, counts = np.unique(
        key[:, 0].astype(np.int64) * (2 * n) + key[:, 1].astype(np.int64),
        return_index=True, return_counts=True,
    )
    boundary = edges[first_idx[counts == 1]]      # directed as in the top face
    a, b = boundary[:, 0], boundary[:, 1]
    rim = np.vstack([
        np.column_stack([b, a, a + n]),
        np.column_stack([b, a + n, b + n]),
    ])

    mesh = trimesh.Trimesh(
        vertices=verts, faces=np.vstack([top, bottom, rim]), process=True
    )
    if mesh.volume < 0:
        mesh.invert()
    return mesh
