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
from dataclasses import dataclass, field as dc_field
from typing import Callable, Optional

import numpy as np
from shapely import contains_xy, distance, points, prepare
from shapely.geometry import Polygon

from ..geometry.regions import TOWER_KINDS, CastlePartition
from ..project.schema import CastleParams, StockDefinition
from .heightfield import Heightfield

# Optional progress hook (BUILDPLAN M4.6 Part B). Called at stage boundaries
# with a human label and a 0..1 fraction. Core stays headless — the default is
# None and no GUI is imported. A caller may raise from the callback to abort
# at a stage boundary (the GUI uses this for cancellation); core never catches.
ProgressFn = Callable[[str, float], None]


def _report(progress: Optional[ProgressFn], label: str, frac: float) -> None:
    if progress is not None:
        progress(label, frac)

PREVIEW_RES_MM = 0.3
VALIDATE_RES_MM = 0.2
GRID_MARGIN_MM = 2.0


@dataclass
class CastleRelief:
    """Rasterized posterior surface plus the masks needed downstream."""
    field: Heightfield          # posterior z over the full grid (mm) — WITH hinge pockets
    inside: np.ndarray          # bool (rows, cols): inside body (lens holes excluded)
    zone_index: np.ndarray      # int (rows, cols): index into partition.zones, -1 outside
    partition: CastlePartition
    pocket_polys: list[Polygon] = dc_field(default_factory=list)  # carved hinge pockets
    # The posterior surface BEFORE the pockets are carved (M8): the relief passes
    # follow this so they sail OVER the already-cut pockets instead of re-diving to the
    # floor — the Hinge Pockets op cuts the pockets, the sim verifies the full `field`.
    surface_field: "Heightfield | None" = None

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
    progress: Optional[ProgressFn] = None,
) -> CastleRelief:
    """Rasterize the castle: terraces -> footing blends -> hinge pockets.

    heights: optional zone-name -> height override (used for generic
    partitions / tests). Defaults to castle.zones.for_kind per zone; requires
    partition.matched when omitted.

    progress: optional stage-boundary hook (BUILDPLAN M4.6 Part B).
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

    _report(progress, "Rasterizing zones", 0.05)
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
    _report(progress, "Building terraces", 0.30)
    zone_pos = {zone.name: i for i, zone in enumerate(partition.zones)}
    fill = z.copy()
    carve = np.full_like(z, np.inf)
    n_edges = max(1, len(partition.edges))
    for ei, edge in enumerate(partition.edges):
        _report(progress, f"Footing edge {ei + 1}/{n_edges}",
                 0.30 + 0.55 * (ei / n_edges))
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
    surface = z.copy()                # posterior surface BEFORE the pockets (relief
                                      # passes sail over them; the Hinge Pockets op cuts)

    # ---- Hinge pockets: sharp-walled cut below the endpiece height ----
    _report(progress, "Hinge pockets", 0.88)
    pocket_floor = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    for poly in hinge_polys:
        prepare(poly)
        in_pocket = contains_xy(poly, flat_x, flat_y).reshape(rows, cols)
        z[in_pocket & inside] = np.minimum(z[in_pocket & inside], pocket_floor)

    z[~inside] = 0.0
    surface[~inside] = 0.0
    _report(progress, "Relief ready", 0.92)
    field = Heightfield(z=z, origin=(ox, oy), resolution=resolution)
    surface_field = Heightfield(z=surface, origin=(ox, oy), resolution=resolution)
    return CastleRelief(
        field=field, inside=inside, zone_index=zone_index,
        partition=partition, pocket_polys=list(hinge_polys),
        surface_field=surface_field,
    )


# ------------------------------------------------------------------ stages
#
# The teaching stepper (BUILDPLAN M4.4): show the castle being built the way
# the maker explains it — towers first, then the walls between them, then the
# footing blends, finally the hinge pockets. Stage names are the presentation
# vocabulary; the zone/edge identifiers they act on stay anatomical (§2).

CASTLE_STAGES = ("towers", "walls", "footing", "pockets")
STAGE_GROUND_MM = 0.6   # wall zones in the "towers" stage: thin ground slab


def build_castle_stage(
    partition: CastlePartition,
    castle: CastleParams,
    hinge_polys: list[Polygon] = (),
    stage: str = "pockets",
    resolution: float = PREVIEW_RES_MM,
    margin: float = GRID_MARGIN_MM,
    progress: Optional[ProgressFn] = None,
) -> CastleRelief:
    """Build the relief up to a teaching stage.

    towers  — endpiece / bridge / nosepad terraces only; eyewire zones left
              as a thin ground slab so the towers stand alone
    walls   — every zone at its terrace height, no footing blends
    footing — terraces + footing blends
    pockets — the complete relief (same as build_castle_relief)

    Requires a matched partition (zone kinds drive the stage split).
    """
    if stage not in CASTLE_STAGES:
        raise ValueError(f"stage must be one of {CASTLE_STAGES}, got {stage!r}")
    if not partition.matched:
        raise ValueError("castle stages require the standard matched zone layout")
    level = CASTLE_STAGES.index(stage)

    heights = None
    if level < 1:
        heights = {
            z.name: (castle.zones.for_kind(z.kind) if z.kind in TOWER_KINDS
                     else STAGE_GROUND_MM)
            for z in partition.zones
        }
    if level < 2:
        castle = castle.model_copy(deep=True)
        for name in type(castle.footing).model_fields:
            fillet = getattr(castle.footing, name)
            fillet.exterior_mm = 0.0
            fillet.interior_mm = 0.0
    hinges = list(hinge_polys) if level >= 3 else []
    return build_castle_relief(
        partition, castle, hinges,
        resolution=resolution, margin=margin, heights=heights,
        progress=progress,
    )


# ------------------------------------------------------------------ mesh
#
# M4.5 Part B: the masked-grid mesher emits axis-aligned boundary edges by
# construction (a Manhattan staircase at any resolution — topological, not a
# sampling problem). _conform_rim() fixes it by projecting every silhouette
# vertex onto the nearest point of the true ring it belongs to: the outline
# exterior / lens interiors for the mask boundary, and each hinge-pocket ring
# for the pocket walls. Only XY moves (each vertex keeps its z), so plateaus
# and footing blends are untouched and the M2 STL gate is unaffected.


def _snap_to_rings(xy: np.ndarray, rings: list, max_dist: float) -> np.ndarray:
    """Project (k, 2) points onto the nearest candidate ring within max_dist."""
    import shapely

    pts = shapely.points(xy[:, 0], xy[:, 1])
    best_d = np.full(len(xy), np.inf)
    best_ring = np.full(len(xy), -1, dtype=np.int64)
    for i, ring in enumerate(rings):
        d = shapely.distance(pts, ring)
        better = d < best_d
        best_d[better] = d[better]
        best_ring[better] = i
    out = xy.copy()
    for i, ring in enumerate(rings):
        sel = (best_ring == i) & (best_d <= max_dist)
        if not sel.any():
            continue
        station = shapely.line_locate_point(ring, pts[sel])
        moved = shapely.line_interpolate_point(ring, station)
        out[sel, 0] = shapely.get_x(moved)
        out[sel, 1] = shapely.get_y(moved)
    return out


def _pocket_wall_ids(relief: CastleRelief, vid: np.ndarray) -> list[tuple[np.ndarray, object]]:
    """Vertex ids flanking each hinge-pocket wall, paired with the true ring.

    A wall pixel pair is an inside-pocket / outside-pocket 4-neighbour pair
    with a real z jump between them (pockets shallower than the local relief
    carve nothing and get no snap).
    """
    z = relief.field.z
    inside = relief.inside
    rows, cols = z.shape
    ox, oy = relief.field.origin
    res = relief.field.resolution
    out: list[tuple[np.ndarray, object]] = []
    for poly in relief.pocket_polys:
        bx0, by0, bx1, by1 = poly.bounds
        c0 = max(0, int((bx0 - ox) / res) - 2)
        c1 = min(cols, int((bx1 - ox) / res) + 3)
        r0 = max(0, int((by0 - oy) / res) - 2)
        r1 = min(rows, int((by1 - oy) / res) + 3)
        if c0 >= c1 or r0 >= r1:
            continue
        sub = (slice(r0, r1), slice(c0, c1))
        xs = ox + np.arange(c0, c1) * res
        ys = oy + np.arange(r0, r1) * res
        Xs, Ys = np.meshgrid(xs, ys)
        prepare(poly)
        in_p = contains_xy(poly, Xs.ravel(), Ys.ravel()).reshape(r1 - r0, c1 - c0)
        ins = inside[sub]
        zs = z[sub]
        wall = np.zeros(in_p.shape, dtype=bool)
        # 8-neighbourhood: diagonal-only contacts at staircase corners still
        # share a top-surface face, so their vertices must snap too.
        pairs = [
            ((slice(1, None), slice(None)), (slice(None, -1), slice(None))),
            ((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
            ((slice(1, None), slice(1, None)), (slice(None, -1), slice(None, -1))),
            ((slice(1, None), slice(None, -1)), (slice(None, -1), slice(1, None))),
        ]
        for sl_a, sl_b in pairs:
            across = (in_p[sl_a] != in_p[sl_b]) & ins[sl_a] & ins[sl_b]
            jump = np.abs(zs[sl_a] - zs[sl_b]) > 0.02
            m = across & jump
            wall[sl_a] |= m
            wall[sl_b] |= m
        ids = vid[sub][wall]
        ids = ids[ids >= 0]
        if len(ids):
            out.append((ids, poly.exterior))
    return out


def _conform_rim(
    relief: CastleRelief,
    verts: np.ndarray,
    vid: np.ndarray,
    n: int,
    boundary: np.ndarray,
) -> np.ndarray:
    """Snap silhouette vertices onto the true outline / lens / pocket rings."""
    res = relief.field.resolution
    max_snap = 1.5 * res
    body = relief.partition.body

    # Mask boundary (outline + lens-hole rims): move top and anterior twins
    # together so the rim wall stays a vertical ribbon.
    rim_ids = np.unique(boundary)
    body_rings = [body.exterior] + list(body.interiors)
    snapped = _snap_to_rings(verts[rim_ids, :2], body_rings, max_snap)
    verts[rim_ids, 0:2] = snapped
    verts[rim_ids + n, 0:2] = snapped

    # Hinge-pocket walls: interior z discontinuities — top vertices only.
    rim_set = set(rim_ids.tolist())
    for ids, ring in _pocket_wall_ids(relief, vid):
        ids = np.array([i for i in ids if i not in rim_set], dtype=np.int64)
        if not len(ids):
            continue
        verts[ids, 0:2] = _snap_to_rings(verts[ids, :2], [ring], max_snap)
    return verts


def build_castle_mesh(
    relief: CastleRelief, conform: bool = True,
    progress: Optional[ProgressFn] = None,
) -> "trimesh.Trimesh":  # noqa: F821
    """Watertight solid: castle top, flat anterior at z=0, stitched rim.

    Works on the masked grid, so the rim follows every boundary ring —
    outline and lens holes alike (closes the spike's open-mesh issue).
    With conform=True (the default) the silhouette vertices are projected
    onto the true outline / lens / hinge-pocket curves, replacing the grid
    staircase with a chordal approximation of the splines (M4.5 Part B).

    progress: optional stage-boundary hook (BUILDPLAN M4.6 Part B).
    """
    import trimesh

    _report(progress, "Meshing surface", 0.94)
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

    if conform:
        _report(progress, "Conforming rim to curves", 0.97)
        verts = _conform_rim(relief, verts, vid, n, boundary)

    mesh = trimesh.Trimesh(
        vertices=verts, faces=np.vstack([top, bottom, rim]), process=True
    )
    if mesh.volume < 0:
        mesh.invert()
    _report(progress, "Mesh ready", 1.0)
    return mesh
