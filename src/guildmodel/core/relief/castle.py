"""Castle relief builder (BUILDPLAN M2): terraces, footing blends, stock.

Builds the posterior surface of a frame front the way the maker models it
in Fusion 360: each castle zone is a flat terrace at its own
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

#: The grid **anything that becomes G-code** must be rasterized on.
#:
#: The relief is terraces joined by footing blends a millimetre or so wide. A
#: coarse grid aliases those blends into a staircase; the CAM's bilinear sample
#: (`castle_ops._bilinear_sample`) then rides the staircase, and every tread
#: becomes a Z direction reversal on a move whose XY step is one cell. Below
#: ~0.2 mm the blends are resolved and the sampled path is smooth; at 0.3-0.4 mm
#: Z-reversal density jumps by 4-8x and total Z travel roughly doubles.
#:
#: INCIDENT-2026-07-29: the worktable posting built its relief at the *preview*
#: resolution (0.4 mm) and posted those paths verbatim, so a bed program made the
#: Z axis reverse under full acceleration ~50 times per 100 mm of travel and had
#: to be E-stopped on real hardware. Preview/validate grids are for pixels; this
#: one is for steel. Every posting path shares it — do not take a resolution
#: from user preferences on a path that ends in a `.nc`.
CUT_RES_MM = 0.15


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
    # M13 posterior finishing features: mask of feature-carved cells (None when
    # every feature is off) + the steepest enabled feature angle. The CAM fine
    # pass adds band-confined rings at a chamfer-derived stepover from these.
    feature_band: "np.ndarray | None" = None
    feature_max_slope_deg: float = 0.0
    # Lens bevel groove (V1): when enabled, the mask / mesh / eyewire holes are
    # the UNDERSIZED apertures (rim lip = lens − depth) and the groove bottom
    # lands on the original LENS contours kept here. `groove` holds the
    # LensGrooveParams (None = off); `mask_body_override` is the aperture body.
    groove: "object | None" = None
    groove_lens_polys: list[Polygon] = dc_field(default_factory=list)
    mask_body_override: "Polygon | None" = None
    # The ANTERIOR (front) surface, sharing `field`'s grid (M17). Height above the
    # blank's anterior datum, so 0 = untouched front face and a positive value is
    # material taken off the front. Body thickness at any cell is
    # `field.z - anterior`. None = nothing cuts the front, which is every project
    # before M17 and the fast path the mesher and CAM still take.
    #
    # Machining this needs the flip setup (M9/V2). It is modelled and previewed
    # now so the shape can be designed and checked before the fixture work lands.
    anterior: "np.ndarray | None" = None

    @property
    def anterior_z(self) -> np.ndarray:
        """The anterior surface, or a flat zero field when nothing cuts the front."""
        if self.anterior is None:
            return np.zeros_like(self.field.z)
        return self.anterior

    def thickness(self) -> np.ndarray:
        """Remaining material at each cell — what a two-sided design must keep
        positive everywhere inside the body."""
        return self.field.z - self.anterior_z

    @property
    def mask_body(self) -> Polygon:
        """The body whose rings bound the mask / mesh rim / eyewires: the
        aperture body when the lens groove is on, else the partition's."""
        return (self.mask_body_override if self.mask_body_override is not None
                else self.partition.body)

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
    if (stock.use_pad_block and stock.pad_block_length_mm > 0
            and stock.pad_block_width_mm > 0):
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
    partitions / tests). Defaults to `castle.zones.for_kind` per zone, with
    `castle.zone_height_overrides` applied on top; requires a *classified*
    partition when omitted (every zone named anatomically — which is any frame
    the classifier could read, not just the standard 9-zone castle).

    progress: optional stage-boundary hook (BUILDPLAN M4.6 Part B).
    """
    if heights is None:
        if not partition.classified:
            raise ValueError(
                "the section cuts did not yield recognisable castle zones; "
                "pass explicit zone heights"
            )
        heights = {z.name: castle.zones.for_kind(z.kind) for z in partition.zones}
        heights.update({name: mm for name, mm in castle.zone_height_overrides.items()
                        if name in heights})

    body = partition.body
    # Lens bevel groove (V1): shrink each lens hole by the groove depth so the
    # rim LIP is the visible aperture and the groove bottom lands exactly on
    # the LENS contour (the boxed dimension). One change here propagates
    # everywhere at once — the raster mask, the conformed mesh wall, and the
    # eyewire contour all key off relief.mask_body. The annulus of lip cells
    # this exposes has no zone; the orphan nearest-zone fill below adopts the
    # neighbouring eyewire-wall height for it.
    groove = getattr(castle, "lens_groove", None)
    groove_on = bool(groove is not None and getattr(groove, "enabled", False)
                     and groove.depth_mm > 0)
    groove_lens_polys: list[Polygon] = []
    if groove_on:
        # Only LENS apertures are grooved; decorative OUTLINE holes share
        # `body.interiors` but take no bevel (they are through-cuts, not rims).
        groove_lens_polys = [Polygon(r) for r in body.interiors
                             if not partition.is_hole(r)]
        body = _undersized_lens_body(body, groove.depth_mm, skip=partition.is_hole)
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

    # ---- Posterior finishing features (M13): min-carves into the footed
    # surface, BEFORE the surface snapshot so the relief passes machine them.
    from .features import apply_posterior_features
    feature_band, feature_slope = apply_posterior_features(
        z, partition, castle, inside, ox, oy, resolution, progress=progress)

    # ---- Edge features + the anterior face (M17). The anterior surface only
    # exists when something actually cuts the front; otherwise `anterior` stays
    # None and every downstream reader takes the historical flat-z=0 path.
    anterior = None
    if castle.cuts_anterior() or any(
            f.face == "posterior" for f in castle.resolved_edge_features()):
        from .edges import apply_edge_features, carve_anterior_bezel
        anterior = np.zeros_like(z)
        pre_anterior = anterior.copy()
        # `feature_band` / `feature_max_slope_deg` are POSTERIOR CAM inputs — they
        # add fine-relief rings to the back of the frame — so anterior carving
        # deliberately contributes nothing to them. Machining the front is the
        # flip setup's job (M9/V2), and it will want its own band.
        if castle.eyewire_bezel.cuts_anterior():
            _report(progress, "Anterior eyewire chamfer", 0.883)
            carve_anterior_bezel(z, anterior, pre_anterior, partition,
                                 castle.eyewire_bezel, inside, ox, oy, resolution)
        eb, es = apply_edge_features(z, anterior, partition, castle, inside,
                                     ox, oy, resolution, progress=progress)
        if eb is not None:
            feature_band = eb if feature_band is None else (feature_band | eb)
        feature_slope = max(feature_slope, es)
        anterior[~inside] = 0.0
        if not anterior.any():
            anterior = None            # posterior-only edge features changed nothing here

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
        feature_band=feature_band, feature_max_slope_deg=feature_slope,
        groove=groove if groove_on else None,
        groove_lens_polys=groove_lens_polys,
        mask_body_override=body if groove_on else None,
        anterior=anterior,
    )


def _undersized_lens_body(body: Polygon, depth_mm: float,
                          skip=lambda ring: False) -> Polygon:
    """The body with each lens hole shrunk inward by the groove depth — the
    rim lip. A hole that vanishes at this depth is kept closed (degenerate
    designs; the groove lint flags it). Rings for which ``skip`` is true are
    decorative OUTLINE holes, which take no groove and so keep their size."""
    holes = []
    for ring in body.interiors:
        if skip(ring):
            holes.append(list(ring.coords))
            continue
        hole = Polygon(ring).buffer(-depth_mm)
        if hole.is_empty:
            continue
        if hole.geom_type == "MultiPolygon":
            hole = max(hole.geoms, key=lambda g: g.area)
        holes.append(list(hole.exterior.coords))
    return Polygon(list(body.exterior.coords), holes)


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

    Requires a classified partition (zone kinds drive the stage split).
    """
    if stage not in CASTLE_STAGES:
        raise ValueError(f"stage must be one of {CASTLE_STAGES}, got {stage!r}")
    if not partition.classified:
        raise ValueError("castle stages require recognisable castle zones")
    level = CASTLE_STAGES.index(stage)

    heights = None
    if level < 1:
        overrides = castle.zone_height_overrides
        heights = {
            z.name: (overrides.get(z.name, castle.zones.for_kind(z.kind))
                     if z.kind in TOWER_KINDS else STAGE_GROUND_MM)
            for z in partition.zones
        }
    if level < 2:
        castle = castle.model_copy(deep=True)
        for name in type(castle.footing).model_fields:
            fillet = getattr(castle.footing, name)
            fillet.exterior_mm = 0.0
            fillet.interior_mm = 0.0
        # Posterior finishing features (M13) anchor on the footed surface, so
        # they appear with the footing stage onward.
        castle.pad_splay.enabled = False
        castle.eyewire_bezel.enabled = False
        castle.bridge_relief.enabled = False
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
    # Aperture rings when the lens groove is on. getattr: the temple/block
    # FlatRelief duck-types into this mesher without the groove fields.
    body = getattr(relief, "mask_body", None) or relief.partition.body

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
    """Watertight solid: castle top, anterior face, stitched rim.

    The anterior is flat at z = 0 unless the relief carries an anterior surface
    (M17 edge features / anterior eyewire chamfer), in which case the bottom
    vertices ride it. `_conform_rim` only moves vertices in XY, so a non-flat
    anterior needs no special handling there.

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
    # The anterior face is flat at z = 0 unless something cuts it (M17), in which
    # case the bottom vertices ride the anterior surface — so an anterior chamfer
    # shows in the 3D model and the exported STL, not just in the numbers.
    anterior = relief.anterior_z if hasattr(relief, "anterior_z") else np.zeros_like(z)
    verts = np.vstack([
        np.column_stack([x, y, z[rr, cc]]),           # posterior (castle) surface
        np.column_stack([x, y, anterior[rr, cc]]),    # anterior surface
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

    if conform:
        _report(progress, "Conforming rim to curves", 0.97)
        verts = _conform_rim(relief, verts, vid, n, boundary)

    # Lens bevel groove (V1): the aperture walls get a PROFILED ribbon — a V
    # notch whose apex pushes out to the original LENS contour — instead of the
    # straight top→anterior quad, so the STL shows the real groove. getattr:
    # the temple/block FlatRelief duck-types in without the groove fields.
    if (getattr(relief, "groove", None) is not None
            and getattr(relief, "groove_lens_polys", None)):
        verts, rim = _groove_rim(relief, verts, boundary, n)
    else:
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
    _report(progress, "Mesh ready", 1.0)
    return mesh


def _groove_rim(relief: CastleRelief, verts: np.ndarray,
                boundary: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Rim faces with the lens-bevel V notch on the aperture walls.

    Aperture-ring rim vertices gain three profile rings — flank top, apex
    (pushed outward onto the original LENS contour), flank bottom — and their
    boundary edges become a four-band strip; every other boundary edge keeps
    the plain vertical quad. Bands share ring vertices, so the solid stays
    watertight; degenerate bands (clamped flanks) collapse to zero-area faces
    that trimesh's `process=True` removes."""
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    from shapely.prepared import prep

    groove = relief.groove
    z_apex = float(groove.anterior_offset_mm)
    half_w = float(groove.width_mm) / 2.0

    rim_ids = np.unique(boundary)
    lens_prepared = [(poly, prep(poly)) for poly in relief.groove_lens_polys]

    # Which rim vertices sit on an aperture ring, and on which lens: the
    # aperture ring lies strictly inside its lens polygon; the outline (and
    # any pocket rim) does not.
    slot: dict[int, int] = {}
    lens_of: dict[int, int] = {}
    for vid_ in rim_ids.tolist():
        p = Point(verts[vid_, 0], verts[vid_, 1])
        for li, (poly, prepared) in enumerate(lens_prepared):
            if prepared.contains(p):
                lens_of[vid_] = li
                slot[vid_] = len(slot)
                break

    m = len(slot)
    base = len(verts)
    gt = np.zeros((m, 3)); ap = np.zeros((m, 3)); gb = np.zeros((m, 3))
    for vid_, k in slot.items():
        x, y = verts[vid_, 0], verts[vid_, 1]
        z_top = verts[vid_, 2]
        z_gt = min(z_apex + half_w, max(z_top - 0.05, 0.05))
        z_gb = max(z_apex - half_w, 0.05)
        near = nearest_points(
            relief.groove_lens_polys[lens_of[vid_]].exterior, Point(x, y))[0]
        gt[k] = (x, y, z_gt)
        ap[k] = (near.x, near.y, min(z_apex, z_gt))
        gb[k] = (x, y, min(z_gb, z_gt))
    verts = np.vstack([verts, gt, ap, gb])

    def _gt(i): return base + slot[i]
    def _ap(i): return base + m + slot[i]
    def _gb(i): return base + 2 * m + slot[i]

    faces: list[tuple[int, int, int]] = []
    for a_, b_ in boundary.tolist():
        if a_ in slot and b_ in slot and lens_of[a_] == lens_of[b_]:
            rings = [(a_, b_), (_gt(a_), _gt(b_)), (_ap(a_), _ap(b_)),
                     (_gb(a_), _gb(b_)), (a_ + n, b_ + n)]
            for (ua, ub), (va, vb) in zip(rings, rings[1:]):
                faces.append((ub, ua, va))
                faces.append((ub, va, vb))
        else:
            faces.append((b_, a_, a_ + n))
            faces.append((b_, a_ + n, b_ + n))
    return verts, np.array(faces, dtype=np.int64)
