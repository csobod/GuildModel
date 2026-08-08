"""Partial-span edge chamfers and fillets, on either face (BUILDPLAN M17).

The M13 features are whole-ring bands: the eyewire bezel runs all the way around
a lens, the pad splay sits under the bridge. The shape a thick modern frame needs
is neither — a chamfer along the **anterior brow**, over each eyewire, stopping
before the bridge so the two never meet. That needs three things the M13 carvers
do not have:

1. **A span.** Which part of the ring the run covers, named in castle-zone
   vocabulary (`eyewire_superior_od`, `endpiece_od`, …) rather than as an
   arc-length fraction, so it survives a re-imported drawing and mirrors by
   swapping `_od` for `_os`.
2. **A taper.** The cut feathers to nothing over `blend_mm` at each end instead
   of stopping at full depth against uncut material.
3. **A face.** The posterior is a min-carve into the castle surface (lower z is
   deeper); the anterior is the mirror image — a *max*-carve that raises the
   front surface up into the part. Both are expressed here as a positive `drop`
   and applied by `_apply`, so the profile maths is written once.

Composition follows the M13 rule: every feature reads the same pre-carve snapshot
and takes the deeper of (existing, target), so overlapping features never
compound and a carve can never add material back.

Geometry is built from the true shapely rings in world coordinates; the raster
only samples it.
"""
from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from shapely import distance, line_locate_point, points
from shapely.geometry import LineString, Point, Polygon

from ..geometry.regions import CastlePartition
from ..project.schema import EdgeFeature

ProgressFn = Callable[[str, float], None]

#: Station spacing when walking a ring to decide which zone owns each part of it.
#: Fine enough to place a span end within a fraction of a millimetre, coarse
#: enough that a 400 mm outline is a few thousand point-in-polygon tests.
_STATION_MM = 0.25


# ------------------------------------------------------------------ ring lookup

def lens_rings(partition: CastlePartition) -> list:
    """The body's lens apertures (not decorative holes), OD first.

    OD is +x in posterior coordinates, so ordering by centroid x descending puts
    the right eye first — the same convention `regions.py` labels zones with.
    """
    rings = [r for r in partition.body.interiors if not partition.is_hole(r)]
    return sorted(rings, key=lambda r: Polygon(r).centroid.x, reverse=True)


def ring_for(partition: CastlePartition, edge: str):
    """The `LineString` an `EdgeFeature.edge` names, or None when absent.

    A frame with one aperture (an unsplit OU lens) has no `lens_os`, and a
    feature pointing at it is skipped rather than raising — the mirrored twin of
    an OD feature must not blow up a build on such a frame.
    """
    if edge == "outline":
        return LineString(partition.body.exterior.coords)
    rings = lens_rings(partition)
    idx = {"lens_od": 0, "lens_os": 1}.get(edge)
    if idx is None or idx >= len(rings):
        return None
    return LineString(rings[idx].coords)


# ------------------------------------------------------------------ span → weight

def _zone_owner_at(partition: CastlePartition, pt: Point) -> str:
    """The name of the zone that owns a point on the body's boundary.

    Boundary points sit *on* a zone edge rather than inside one, so this is
    nearest-zone rather than containment — with the containing zone winning
    outright when there is one."""
    best, best_d = "", float("inf")
    for zone in partition.zones:
        if zone.polygon.contains(pt):
            return zone.name
        d = zone.polygon.distance(pt)
        if d < best_d:
            best, best_d = zone.name, d
    return best


def span_intervals(
    ring: LineString,
    partition: CastlePartition,
    zones: list[str],
    trim_start_mm: float = 0.0,
    trim_end_mm: float = 0.0,
    station_mm: float = _STATION_MM,
) -> list[tuple[float, float]]:
    """Arc-length intervals of `ring` covered by `zones`, after trimming.

    An empty `zones` means the whole ring — returned as one interval spanning it.
    Runs that meet across the ring's seam are merged, so a span that happens to
    straddle the arbitrary start of the coordinate list is still one run and gets
    one taper at each real end rather than two in the middle.
    """
    total = ring.length
    if total <= 0:
        return []
    if not zones:
        return [(0.0, total)]

    wanted = set(zones)
    n = max(4, int(np.ceil(total / max(station_mm, 1e-6))))
    stations = np.linspace(0.0, total, n, endpoint=False)
    owned = np.array([
        _zone_owner_at(partition, ring.interpolate(float(s))) in wanted
        for s in stations
    ])
    if not owned.any():
        return []
    if owned.all():
        return [(0.0, total)]

    # Contiguous runs of owned stations, then merge across the seam.
    runs: list[list[float]] = []
    step = total / n
    k = 0
    while k < n:
        if not owned[k]:
            k += 1
            continue
        j = k
        while j + 1 < n and owned[j + 1]:
            j += 1
        runs.append([stations[k], stations[j] + step])
        k = j + 1
    if len(runs) > 1 and owned[0] and owned[-1]:
        first, last = runs[0], runs[-1]
        runs = runs[1:-1] + [[last[0] - total, first[1]]]   # wrapped, may start < 0

    out: list[tuple[float, float]] = []
    for s0, s1 in runs:
        s0 += trim_start_mm
        s1 -= trim_end_mm
        if s1 - s0 > 1e-9:
            out.append((s0, s1))
    return out


def spans_whole_ring(interval: tuple[float, float], total: float) -> bool:
    """True when a run closes on itself — no ends, so nothing to cap or taper.

    Every feature here is written for an *open* run: it lays stations from `s0`
    to `s1` inclusive, sweeps them open, caps each end, and feathers the depth
    to nothing over `blend_mm` so the cut does not stop dead. On a run that goes
    all the way round, every one of those is wrong:

    * `s0` and `s1` are the **same point**, so the last station duplicates the
      first — a zero-length step, which the mesh strip's fold guard rejects and
      which `BRepOffsetAPI_ThruSections` lofts into a shape that fails
      `BRepCheck_Analyzer` and takes the whole castle build down with it.
    * the run is then swept open, so its two end caps sit exactly on top of each
      other *inside* the solid. That is the self-touch: a posterior 1.5 mm
      round-over round the demo outline carried 19 self-touching edges, the
      aviator 18, the gabriel 21, and all of them are these caps. Sweeping the
      run closed takes every one of them to zero.
    * the taper puts a dimple in the cut at the ring's *coordinate seam*, which
      is an artifact of where the DXF happened to start and nowhere the maker
      can see or ask for.

    A whole-ring run is what an empty `zones` means, and it is a reasonable
    thing to want — a round-over all the way round the back edge. Sweep it
    closed, drop the duplicate station, and leave the depth at full.

    **The B-Rep path does not take this exception, and that is deliberate.** It
    was tried: drop the duplicate wire, drop the taper, and repeat the first
    section last, which is the standard way to close a `ThruSections` loft. At a
    1.5 mm radius the loft still failed `BRepCheck_Analyzer` on all three
    fixtures, exactly as before. At 0.4 mm, where it does build, the change made
    it **worse** — a clean solid became one with 7 boundary edges — so it was
    reverted rather than shipped.

    What that measurement exposed is that OCCT's whole-ring cutter does not cut
    at all. The demo frame is 7825.881 mm3 uncut; with a 0.4 mm round-over run
    all the way round the back edge it is 7826.841 — *larger*, within
    tessellation noise of having done nothing. The mesh path removes 11.4 mm3
    for the same feature. So the B-Rep is not a control here and there is no
    parity to hold: it is a pre-existing defect in the kernel M-N4 retires,
    recorded rather than fixed.
    """
    s0, s1 = interval
    return (s1 - s0) >= total - 1e-9


def taper_weight(s: np.ndarray, intervals: list[tuple[float, float]],
                 blend_mm: float, total: float) -> np.ndarray:
    """Cut strength at each station: 1 inside a run, ramping to 0 over `blend_mm`
    at each end, 0 outside every run.

    Stations are compared against each interval both directly and shifted by a
    full ring length, so a run recorded as wrapping the seam (negative start)
    still matches the stations near the ring's end.
    """
    s = np.asarray(s, dtype=float)
    w = np.zeros_like(s)
    for s0, s1 in intervals:
        run = s1 - s0
        blend = min(blend_mm, run / 2.0) if run > 0 else 0.0
        for shift in (0.0, -total, total):
            d0 = s + shift - s0
            d1 = s1 - (s + shift)
            inside = (d0 >= 0) & (d1 >= 0)
            if not inside.any():
                continue
            if blend > 1e-9:
                ramp = np.minimum(np.minimum(d0, d1) / blend, 1.0)
            else:
                ramp = np.ones_like(s)
            w = np.maximum(w, np.where(inside, np.clip(ramp, 0.0, 1.0), 0.0))
    return w


def station_fraction(s: np.ndarray, intervals: list[tuple[float, float]],
                     total: float) -> np.ndarray:
    """Normalised position (0..1) within the owning run — drives a variable width."""
    s = np.asarray(s, dtype=float)
    t = np.zeros_like(s)
    for s0, s1 in intervals:
        run = s1 - s0
        if run <= 0:
            continue
        for shift in (0.0, -total, total):
            d0 = s + shift - s0
            inside = (d0 >= 0) & (d0 <= run)
            if inside.any():
                t = np.where(inside, np.clip(d0 / run, 0.0, 1.0), t)
    return t


# ------------------------------------------------------------------ profiles

def chamfer_drop(d: np.ndarray, width: np.ndarray, angle_deg: float) -> np.ndarray:
    """Depth removed at distance `d` in from the edge, for a straight chamfer.

    Full ``width * tan(angle)`` at the edge itself, zero at `width` in — the same
    ramp the M13 bezel cuts, but with a per-sample width so the run can taper.
    """
    tan_a = float(np.tan(np.radians(angle_deg)))
    return np.maximum(0.0, (width - d)) * tan_a


def fillet_drop(d: np.ndarray, radius: float) -> np.ndarray:
    """Depth removed at distance `d` in from the edge, for a round-over.

    The arc's centre sits `radius` in from the edge and `radius` below the face,
    so the surface is tangent to the face at ``d = radius`` (no crease where the
    fillet ends) and has dropped the full radius at the edge itself.
    """
    r = float(radius)
    inner = np.clip(r - d, 0.0, r)
    return np.where(d < r, r - np.sqrt(np.maximum(r * r - inner * inner, 0.0)), 0.0)


# ------------------------------------------------------------------ the carver

def _window(pts_xy: np.ndarray, pad: float, ox: float, oy: float, res: float,
            rows: int, cols: int) -> tuple[int, int, int, int]:
    xmin, ymin = pts_xy.min(axis=0) - pad
    xmax, ymax = pts_xy.max(axis=0) + pad
    c0 = int(np.clip(np.floor((xmin - ox) / res), 0, cols))
    c1 = int(np.clip(np.ceil((xmax - ox) / res) + 1, 0, cols))
    r0 = int(np.clip(np.floor((ymin - oy) / res), 0, rows))
    r1 = int(np.clip(np.ceil((ymax - oy) / res) + 1, 0, rows))
    return r0, r1, c0, c1


def carve_edge_feature(
    posterior: np.ndarray,
    anterior: np.ndarray,
    pre_posterior: np.ndarray,
    pre_anterior: np.ndarray,
    feature: EdgeFeature,
    partition: CastlePartition,
    inside: np.ndarray,
    ox: float, oy: float, res: float,
) -> np.ndarray:
    """Carve one resolved feature into whichever face it names. Returns the mask
    of cells it actually changed (empty when the ring or span is absent).

    Both grids are passed because the two faces constrain each other: an anterior
    cut may not eat past the posterior surface, and vice versa, so the part can
    never be carved into nothing from two sides at once.
    """
    rows, cols = posterior.shape
    touched = np.zeros_like(inside)
    ring = ring_for(partition, feature.edge)
    if ring is None or ring.length <= 0:
        return touched

    intervals = span_intervals(ring, partition, feature.zones,
                               feature.trim_start_mm, feature.trim_end_mm)
    if not intervals:
        return touched

    reach = feature.max_width_mm()
    ring_xy = np.asarray(ring.coords)[:, :2]
    r0, r1, c0, c1 = _window(ring_xy, reach + 2 * res, ox, oy, res, rows, cols)
    sub_inside = inside[r0:r1, c0:c1]
    if not sub_inside.any():
        return touched

    sub_x = ox + (c0 + np.arange(c1 - c0)) * res
    sub_y = oy + (r0 + np.arange(r1 - r0)) * res
    SX, SY = np.meshgrid(sub_x, sub_y)
    cand = sub_inside.ravel()
    pts = points(SX.ravel()[cand], SY.ravel()[cand])
    d = distance(pts, ring)
    near = d < reach
    if not near.any():
        return touched

    pts_near = pts[near]
    d_near = d[near]
    s = line_locate_point(ring, pts_near)
    w = taper_weight(s, intervals, feature.blend_mm, ring.length)
    live = w > 1e-9
    if not live.any():
        return touched

    d_live, w_live = d_near[live], w[live]
    if feature.profile == "fillet":
        drop = fillet_drop(d_live, feature.radius_mm)
    else:
        t = station_fraction(s[live], intervals, ring.length)
        width = np.array([feature.width_at(float(v)) for v in t])
        drop = chamfer_drop(d_live, width, feature.angle_deg)
    # Taper the DEPTH, not the width: the run then feathers out along the surface
    # instead of narrowing to a point and leaving a step at its end.
    drop = drop * w_live
    if feature.depth_limit_mm is not None:
        drop = np.minimum(drop, feature.depth_limit_mm)

    idx_cand = np.flatnonzero(cand)
    idx = idx_cand[np.flatnonzero(near)[np.flatnonzero(live)]]

    post_sub = posterior[r0:r1, c0:c1].ravel().copy()
    ant_sub = anterior[r0:r1, c0:c1].ravel().copy()
    pre_post = pre_posterior[r0:r1, c0:c1].ravel()
    pre_ant = pre_anterior[r0:r1, c0:c1].ravel()

    if feature.face == "posterior":
        # Min-carve down from the pre-carve castle surface, never closer to the
        # anterior surface than the minimum wall thickness.
        floor = ant_sub[idx] + feature.min_thickness_mm
        target = np.maximum(pre_post[idx] - drop, floor)
        moved = target < post_sub[idx] - 1e-12
        post_sub[idx[moved]] = target[moved]
        posterior[r0:r1, c0:c1] = post_sub.reshape(r1 - r0, c1 - c0)
    else:
        # Max-carve up from the pre-carve anterior face — the mirror image.
        ceiling = post_sub[idx] - feature.min_thickness_mm
        target = np.minimum(pre_ant[idx] + drop, ceiling)
        moved = target > ant_sub[idx] + 1e-12
        ant_sub[idx[moved]] = target[moved]
        anterior[r0:r1, c0:c1] = ant_sub.reshape(r1 - r0, c1 - c0)

    tflat = touched[r0:r1, c0:c1].ravel()
    tflat[idx[moved]] = True
    touched[r0:r1, c0:c1] = tflat.reshape(r1 - r0, c1 - c0)
    return touched


def apply_edge_features(
    posterior: np.ndarray,
    anterior: np.ndarray,
    partition: CastlePartition,
    castle,
    inside: np.ndarray,
    ox: float, oy: float, res: float,
    progress: Optional[ProgressFn] = None,
) -> tuple[np.ndarray | None, float]:
    """Carve every enabled edge feature (and its mirrored twin) into both grids.

    Returns ``(band, max_slope_deg)`` in the same shape as the M13 dispatcher, so
    the CAM feature-finish band and the mesher pick these up with no special
    casing. With no features the grids are untouched — a bit-identical fast path
    for every project that predates M17.
    """
    features = castle.resolved_edge_features()
    if not features:
        return None, 0.0

    pre_post = posterior.copy()
    pre_ant = anterior.copy()
    band = np.zeros_like(inside)
    max_slope = 0.0
    for i, feature in enumerate(features):
        if progress is not None:
            progress(f"Edge feature {i + 1}/{len(features)}",
                     0.885 + 0.005 * (i + 1) / len(features))
        touched = carve_edge_feature(posterior, anterior, pre_post, pre_ant,
                                     feature, partition, inside, ox, oy, res)
        # ONLY posterior features feed the returned band and slope. Those two
        # drive the posterior CAM's feature-finish rings, and an anterior feature
        # is not machined from this side at all — counting it added dozens of
        # phantom fine-relief passes to the back of the frame for a chamfer on
        # the front. The anterior band belongs to the flip setup (M9/V2).
        if feature.face != "posterior":
            continue
        band |= touched
        if feature.profile == "fillet":
            # A round-over's steepest tangent is vertical at the edge; the useful
            # number for a finishing stepover is its 45° mid-slope.
            max_slope = max(max_slope, 45.0)
        else:
            max_slope = max(max_slope, feature.angle_deg)
    band[~inside] = False
    return (band if band.any() else None), max_slope


def carve_anterior_bezel(
    posterior: np.ndarray,
    anterior: np.ndarray,
    pre_anterior: np.ndarray,
    partition: CastlePartition,
    bezel,
    inside: np.ndarray,
    ox: float, oy: float, res: float,
) -> np.ndarray:
    """The eyewire bezel's anterior band (M17): the M13.2 chamfer, cut into the
    front face around every lens aperture instead of / as well as the back.

    Expressed as whole-ring `EdgeFeature`s so there is exactly one chamfer
    implementation to trust rather than a copy of the same maths per kernel.
    The list comes from `EyewireBezelParams.as_edge_features`, which is where it
    lives so that the two solid kernels cut the identical band.
    """
    band = np.zeros_like(inside)
    if bezel.anterior_width_mm <= 0:
        return band
    for feature in bezel.as_edge_features():
        if ring_for(partition, feature.edge) is None:
            continue
        band |= carve_edge_feature(posterior, anterior, posterior, pre_anterior,
                                   feature, partition, inside, ox, oy, res)
    return band
