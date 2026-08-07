"""The five-operation posterior CAM recipe (BUILDPLAN M3).

Reproduces the maker's proven Fusion 360 program from the castle relief,
in order:

  1. Hinge Pockets — while the stock is rigid; ramp entry, no straight plunge
  2. Rough Relief  — castle surface + axial stock to leave, stock-aware
  3. Fine Relief   — final castle surface
  4. Eyewires      — through-cut contours, onion skin (no tabs)
  5. Perimeter     — same

Z is posterior height above the flat anterior face (the model/NC frame).
Through-cuts stop at the onion skin; contours leave the hand-finishing
allowance radially. Depth passes start from the stock's highest level
(blank + pad block), as the reference program does, because both contours
cross the pad-block zone.

Deliberate deviations from the reference NC (documented, both improvements):
  * relief ops are raster (boustrophedon drop-cutter), not constant-stepover
    contours — same surface, different pattern;
  * the rough pass skips regions with no stock above the target (the
    reference air-cut the whole blank at target+2), which is the point of
    the complex stock model.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from shapely.geometry import Polygon

# Optional stage-boundary progress hook (BUILDPLAN M4.6 Part B); see
# relief.castle.ProgressFn. Default None — core never imports the GUI.
ProgressFn = Callable[[str, float], None]

from ..project.schema import (
    CastleCamParams, CastleParams, HoldingParams, StockDefinition,
)
from ..relief.castle import CastleRelief, stock_top_heightfield
from ..relief.heightfield import Heightfield
from .dropcutter import cutter_location_surface
from .pocketing import _inward_offsets, _SCALE
from .tabs import insert_tabs

Point3 = tuple[float, float, float]

# Facet-cusp target on the M13 posterior-feature chamfers: the feature-finish
# band's stepover is derived as cusp / tan(steepest feature angle).
FEATURE_CUSP_MM = 0.15


@dataclass
class CamOp:
    name: str
    paths: list[list[Point3]] = field(default_factory=list)
    # The tool this op is cut with (a tools.yaml entry dict, with a "name" key).
    # None = the program's single global tool (BUILDPLAN M1–M5 behaviour). Per-op
    # tools are assigned in generate_castle_program from CastleCamParams.op_tools
    # (multi-tool jobs, BUILDPLAN M6.1) — the post, sim, cut-time model and
    # fixture-clearance check all read it.
    tool: dict | None = None

    @property
    def tool_name(self) -> str | None:
        return self.tool.get("name") if self.tool else None

    def z_range(self) -> tuple[float, float]:
        zs = [p[2] for path in self.paths for p in path]
        return (min(zs), max(zs)) if zs else (np.nan, np.nan)

    def xy_bounds(self) -> tuple[float, float, float, float]:
        xs = [p[0] for path in self.paths for p in path]
        ys = [p[1] for path in self.paths for p in path]
        return min(xs), min(ys), max(xs), max(ys)

    def path_length_mm(self) -> float:
        """Total 3D cutting length over all paths (rapids between paths excluded)."""
        total = 0.0
        for path in self.paths:
            if len(path) > 1:
                pts = np.asarray(path, dtype=np.float64)
                total += float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
        return total


# CastleCamParams now lives in project.schema (persisted with the project and
# editable from the CAM tab, BUILDPLAN M4.8); re-exported here so existing
# callers keep importing it from cam.castle_ops.
_DEFAULT_CAM = CastleCamParams()


def resolve_tool(name: str, tools_cfg: dict, default: dict | None = None) -> dict:
    """A normalized tool dict for `name` from a tools.yaml mapping.

    Always carries a "name" key so downstream (post / sim / cut-time) can group
    by tool. Falls back to `default` (then the first available tool) when the
    name is unknown — generation never crashes on a stale assignment.
    """
    entry = tools_cfg.get(name)
    if entry is None:
        if default is not None:
            return default
        name, entry = next(iter(tools_cfg.items()))
    t = dict(entry)
    t.setdefault("name", name)
    return t


def _same_tool(a: dict, b: dict) -> bool:
    return (a.get("type") == b.get("type")
            and abs(a.get("radius_mm", 0.0) - b.get("radius_mm", 0.0)) < 1e-9)


# ------------------------------------------------------------------ helpers

def _rdp(points: list[Point3], tol: float) -> list[Point3]:
    """Ramer–Douglas–Peucker on 3D polylines (iterative)."""
    if len(points) < 3:
        return points
    pts = np.asarray(points, dtype=float)
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i0, i1 = stack.pop()
        if i1 - i0 < 2:
            continue
        seg = pts[i1] - pts[i0]
        norm = np.linalg.norm(seg)
        if norm == 0:
            d = np.linalg.norm(pts[i0 + 1:i1] - pts[i0], axis=1)
        else:
            d = np.linalg.norm(np.cross(pts[i0 + 1:i1] - pts[i0], seg / norm), axis=1)
        imax = int(np.argmax(d))
        if d[imax] > tol:
            mid = i0 + 1 + imax
            keep[mid] = True
            stack += [(i0, mid), (mid, i1)]
    return [tuple(p) for p in pts[keep]]


def _ring_to_points(scaled_ring: list[list[int]], z: float) -> list[Point3]:
    pts = [(p[0] / _SCALE, p[1] / _SCALE, z) for p in scaled_ring]
    pts.append(pts[0])          # close the loop
    return pts


def _poly_rings(poly: Polygon, tool_radius_mm: float, stepover_mm: float) -> list[list[list[int]]]:
    scaled = [[int(x * _SCALE), int(y * _SCALE)] for x, y in poly.exterior.coords]
    return _inward_offsets(scaled, tool_radius_mm, stepover_mm)


def work_holding_keepouts(
    body: Polygon, stock: StockDefinition, tool_radius_mm: float,
    *, screw_head_diameter_mm: float = 7.0, margin_mm: float = 2.0,
    is_hole=lambda ring: False,
) -> list[tuple[float, float, float]]:
    """Keep-out circles ``(cx, cy, radius)`` the tool CENTRE must stay outside when
    a pass-link retract is lowered below safe Z (BUILDPLAN M8). They mark the
    work-holding screws standing proud of the stock — the standard Guild fixture:
    one at each stock-blank corner and one at each lens centre (the body's interior
    holes). ``radius`` = screw radius + tool radius + margin, so the tool *edge*
    keeps ``margin`` clear of the head. Design coordinates (blank centred on origin).

    ``is_hole`` marks interior rings that are decorative OUTLINE openings rather
    than lens apertures — nothing is screwed through those, so they seed no
    keep-out (see geometry.regions.CastlePartition.is_hole)."""
    keep_r = screw_head_diameter_mm / 2.0 + tool_radius_mm + margin_mm
    hl, hw = stock.blank_length_mm / 2.0, stock.blank_width_mm / 2.0
    centers = [(hl, hw), (-hl, hw), (hl, -hw), (-hl, -hw)]      # blank corners
    for ring in body.interiors:                                 # lens centres
        if is_hole(ring):
            continue
        c = Polygon(ring).centroid
        centers.append((c.x, c.y))
    return [(x, y, keep_r) for x, y in centers]


# ------------------------------------------------------------------ op 1: hinge pockets

def pocket_levels(start_z: float, floor_z: float, stepdown_mm: float) -> list[float]:
    """Axial levels a pocket is cleared at, from just under `start_z` to the floor.

    The same shape as `contour_passes` but for a blind floor: the last level is
    always exactly `floor_z`, so the pocket finishes at size no matter how the
    stepdown divides. A non-positive stepdown collapses to a single floor level
    (the guard `contour_passes` and `peck_drill` take — a hand-edited project must
    not hang the worker)."""
    if stepdown_mm <= 1e-9:
        return [floor_z]
    zs: list[float] = []
    z = start_z
    while True:
        z -= stepdown_mm
        if z <= floor_z + 1e-9:
            break
        zs.append(round(z, 6))
    zs.append(floor_z)
    return zs


def hinge_pocket_op(
    hinge_polys: list[Polygon],
    floor_z: float,
    start_z: float,
    tool_radius_mm: float,
    params: CastleCamParams,
) -> CamOp:
    """Pocket each hinge outline to floor_z in ramped levels.

    Each level is entered by lapping the outermost tool ring, descending
    ramp_step_mm per lap — no straight plunge into material — and is then cleared
    by the full inward cascade at that level. Levels are `pocket_stepdown_mm`
    apart: a pocket deeper than one stepdown used to ramp its outer ring down and
    then take the ENTIRE remaining depth in one full-depth cascade, which buries
    the cutter on anything but a shallow recess. A pocket no deeper than one
    stepdown is a single level and posts exactly the historical path.
    """
    op = CamOp("Hinge Pockets")
    # A non-positive ramp step never descends (max(floor_z, z - 0) == z) — guard it
    # so a hand-edited project can't hang the worker (matching peck_drill): +inf ramps
    # straight to the level in one lap. The inward cascade's stepover is guarded in
    # _inward_offsets, the level spacing in pocket_levels.
    ramp_step = params.ramp_step_mm if params.ramp_step_mm > 1e-9 else float("inf")
    levels = pocket_levels(start_z, floor_z, params.pocket_stepdown_mm)
    for poly in hinge_polys:
        rings = _poly_rings(poly, tool_radius_mm, params.pocket_stepover_mm)
        if not rings:
            continue
        outer = rings[0]
        path: list[Point3] = []

        ring_xy = [(p[0] / _SCALE, p[1] / _SCALE) for p in outer]
        ring_xy.append(ring_xy[0])
        n = len(ring_xy)
        z = start_z
        path.append((*ring_xy[0], z))
        for k, level in enumerate(levels):
            # ramp laps on the outer ring down to this level
            while z > level + 1e-9:
                z_next = max(level, z - ramp_step)
                for i in range(1, n):
                    t = i / (n - 1)
                    path.append((*ring_xy[i], z + (z_next - z) * t))
                z = z_next
            # level laps: outer ring once more flat, then the inward cascade
            path += [(*p, level) for p in ring_xy]
            for ring in rings[1:]:
                path += _ring_to_points(ring, level)
            if k + 1 < len(levels):
                # The cascade ends on the innermost ring; come back out to the
                # outer ring's start to ramp the next level. Everything inside the
                # outer ring is already cleared AT this level, so the move is air.
                path.append((*ring_xy[0], level))
        op.paths.append(_rdp(path, params.simplify_tol_mm))
    return op


# ------------------------------------------------------------------ ops 2+3: relief

def _densify_xy(coords: list, spacing: float) -> np.ndarray:
    """Resample a 2D polyline to ~`spacing` point spacing (vectorised)."""
    pts = np.asarray(coords, dtype=np.float64)
    if len(pts) < 2:
        return pts
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = float(cum[-1])
    if total < spacing:
        return pts
    n = max(2, int(np.ceil(total / spacing)))
    s = np.linspace(0.0, total, n + 1)
    return np.column_stack([np.interp(s, cum, pts[:, 0]),
                            np.interp(s, cum, pts[:, 1])])


def _bilinear_sample(zgrid: np.ndarray, xs: np.ndarray, ys: np.ndarray,
                     ox: float, oy: float, res: float) -> np.ndarray:
    """Bilinearly sample a heightfield at arbitrary world (xs, ys).

    The relief path runs at an angle across the grid; the nearest-cell sample
    (`zgrid[round(y), round(x)]`) snaps between adjacent rows/cols and aliases
    into a zig-zag on steep walls — the nosepad jitter the maker saw (BUILDPLAN
    M8). Bilinear follows the true cutter-location height smoothly and, being the
    faithful CL value at the exact xy, never dips below it (no convex-peak gouge —
    unlike a moving average, which lowers convex tops)."""
    cx = (xs - ox) / res
    cy = (ys - oy) / res
    x0 = np.clip(np.floor(cx).astype(int), 0, zgrid.shape[1] - 2)
    y0 = np.clip(np.floor(cy).astype(int), 0, zgrid.shape[0] - 2)
    fx = np.clip(cx - x0, 0.0, 1.0)
    fy = np.clip(cy - y0, 0.0, 1.0)
    return (zgrid[y0, x0] * (1 - fx) * (1 - fy) + zgrid[y0, x0 + 1] * fx * (1 - fy)
            + zgrid[y0 + 1, x0] * (1 - fx) * fy + zgrid[y0 + 1, x0 + 1] * fx * fy)


def contour_parallel_rings(body: Polygon, stepover_mm: float,
                           max_rings: int = 4000,
                           max_depth_mm: float | None = None) -> list[list]:
    """Concentric boundary-offset rings tiling `body` (Fusion 'Scallop' style).

    Successive inward erosions of the material polygon: the exterior shrinks and
    the lens holes grow, so the rings wrap the outline *and* every eyewire. The
    relief finish then follows the frame instead of raster-sweeping it.
    `max_depth_mm` caps the erosion (M13: the feature-finish band only needs
    rings as deep as the band reaches).
    """
    rings: list[list] = []
    d = 0.0
    for _ in range(max_rings):
        if max_depth_mm is not None and d > max_depth_mm:
            break
        region = body if d <= 0 else body.buffer(-d, join_style="round")
        if region.is_empty:
            break
        geoms = region.geoms if region.geom_type == "MultiPolygon" else [region]
        added = False
        for g in geoms:
            if g.is_empty or g.area <= 0:
                continue
            rings.append(list(g.exterior.coords))
            rings += [list(r.coords) for r in g.interiors]
            added = True
        if not added:
            break
        d += stepover_mm
    return rings


def _ring_is_ccw(coords) -> bool:
    """Shoelace sign: True when the closed ring winds counter-clockwise (M12.5)."""
    s = 0.0
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        s += float(x0) * float(y1) - float(x1) * float(y0)
    return s > 0.0


def order_paths_for_travel(paths: list, start: tuple = (0.0, 0.0)) -> list:
    """Greedily reorder paths so the air hop between them is short — at each step take
    the path whose START is nearest the previous path's END (M12.1).

    Only the visiting order changes: each path keeps its own points and direction, so
    the cut geometry is identical and climb/conventional sense is preserved (no
    reversal). Relief paths come out in contour-ring order, which interleaves the
    separate regions (each eyewire / bridge / nosepads) and sends the tool hopping
    across the part; this collapses that air. O(n^2), fine for per-op path counts.
    """
    n = len(paths)
    if n < 3:
        return list(paths)
    remaining = list(range(n))
    ordered: list = []
    cx, cy = start
    while remaining:
        j = min(remaining,
                key=lambda i: (paths[i][0][0] - cx) ** 2 + (paths[i][0][1] - cy) ** 2)
        p = paths[j]
        ordered.append(p)
        cx, cy = p[-1][0], p[-1][1]
        remaining.remove(j)
    return ordered


def _stitch_close_paths(paths: list, zgrid, ox: float, oy: float, res: float,
                        max_gap: float) -> list:
    """Merge consecutive paths whose end→start gap is ≤ `max_gap` into one continuous
    sweep, joined by a connector that rides the drop-cutter surface `zgrid` (M12.2).

    The cutter steps from one ring to the next without a retract+plunge; the connector
    follows the cutter-location surface so it never gouges (and rides over a thin cap
    just like the M11 gap-link). A wider gap — a jump to a separate region — stays its
    own path with its own entry. Run after `order_paths_for_travel`, so "close" means
    genuinely adjacent."""
    if len(paths) < 2:
        return [list(p) for p in paths]
    g2 = max_gap * max_gap
    out = [list(paths[0])]
    for p in paths[1:]:
        ax, ay = out[-1][-1][0], out[-1][-1][1]
        bx, by = p[0][0], p[0][1]
        d2 = (bx - ax) ** 2 + (by - ay) ** 2
        if 0.0 < d2 <= g2:
            n = max(1, int(float(np.sqrt(d2)) / res))
            if n > 1:                       # surface-riding connector, endpoints excluded
                ts = np.arange(1, n) / n
                xs = ax + (bx - ax) * ts
                ys = ay + (by - ay) * ts
                zs = _bilinear_sample(zgrid, xs, ys, ox, oy, res)
                out[-1].extend((float(x), float(y), float(z))
                               for x, y, z in zip(xs, ys, zs))
            out[-1].extend(p)
        else:
            out.append(list(p))
    return out


def relief_ops(
    relief: CastleRelief,
    stock: StockDefinition,
    fine_tool: dict,
    params: CastleCamParams,
    rough_tool: dict | None = None,
) -> tuple[CamOp, CamOp]:
    """Rough (surface + axial stock, stock-aware) and fine (final surface).

    `fine_tool` finishes the surface; `rough_tool` (defaults to `fine_tool`)
    bulk-removes above it. The machining region and rim-reach band are defined by
    the **finishing** tool (it has to reach every rim); each pass rides its own
    tool's drop-cutter surface — when the two tools are identical the surface is
    computed once (BUILDPLAN M6.1: drop-cutter CLS keys off the op's tool).

    Both passes are **contour-parallel**: the toolpath is a set of boundary-
    offset rings that follow the outline and the eyewires, riding the drop-cutter
    surface — not an axis-aligned raster.

    **Rim-band clearing (BUILDPLAN M5).** A flat tool finishing a rim cannot get
    under the *not-yet-cut* lens openings / outside stock next to it — near those
    boundaries the drop-cutter rides up to stock height, leaving the rim floors
    uncut (badly so in the 10 mm pad-block zone, where the cut simulator measured
    ~14 % of the body left proud vs Fusion's ~4 %). The fix mirrors Fusion's
    rough: clear a tool-radius band of the to-be-removed material down to the
    neighbouring rim level so the finish pass can reach the rim. Beyond the band
    the openings stay at stock height — the eyewire / perimeter contours cut them
    through later — so the extra clearing (and cut time) stays bounded.
    """
    from scipy.ndimage import distance_transform_edt
    rough_tool = rough_tool or fine_tool
    fine_type, fine_r = fine_tool["type"], fine_tool["radius_mm"]
    rough_type, rough_r = rough_tool["type"], rough_tool["radius_mm"]
    f = relief.field
    # Relief passes follow the PRE-pocket surface so they sail over the already-cut
    # hinge pockets instead of re-diving to the floor (M8); the Hinge Pockets op cuts
    # the pockets, the sim verifies the full pocketed `field`.
    surf = relief.surface_field if relief.surface_field is not None else f
    res = f.resolution
    ox, oy = f.origin
    inside = relief.inside
    stock_hf = stock_top_heightfield(
        stock, resolution=res, origin=f.origin, shape=f.z.shape
    )

    # Machining region = body grown by a finishing-tool-radius band; the band's
    # target is the relief level of the nearest body cell (so the rim floor is
    # reachable by the finishing tool).
    band_mm = max(fine_r, params.relief_stepover_mm)
    dist, (iy, ix) = distance_transform_edt(
        ~inside, sampling=res, return_indices=True
    )
    nearest_relief = surf.z[iy, ix]
    band = inside | (dist <= band_mm + 1e-9)
    cam_z = np.where(band, np.minimum(nearest_relief, stock_hf.z), stock_hf.z)
    cam_hf = Heightfield(z=cam_z, origin=f.origin, resolution=res)

    cls_fine = cutter_location_surface(cam_hf, fine_type, fine_r)
    if _same_tool(rough_tool, fine_tool):
        cls_rough_surf = cls_fine
        stock_cls = cutter_location_surface(stock_hf, fine_type, fine_r)
    else:
        cls_rough_surf = cutter_location_surface(cam_hf, rough_type, rough_r)
        stock_cls = cutter_location_surface(stock_hf, rough_type, rough_r)

    eps = params.skim_epsilon_mm
    fine = CamOp("Fine Relief")
    rough = CamOp("Rough Relief")

    rows, cols = cls_fine.z.shape
    z_fine = cls_fine.z
    z_rough = np.minimum(cls_rough_surf.z + params.rough_axial_stock_mm, stock_cls.z)
    # rough only where stock actually sits above the rough target
    cut_rough = band & ((cls_rough_surf.z + params.rough_axial_stock_mm) < stock_cls.z - eps)

    machining = relief.partition.body.buffer(band_mm, join_style="round")

    # Bridge a ring's masked gaps up to `relief_link_gap_mm` (the cutter rides over the
    # thin cap at its drop-cutter height) so a ring shattered by the cut mask becomes
    # one long sweep instead of a string of retract+plunge stubs ("drill holes"); a run
    # still shorter than `relief_min_run_mm` is dropped (negligible material).
    gap_cells = max(1, int(round(params.relief_link_gap_mm / res)))
    min_cells = max(2, int(round(params.relief_min_run_mm / res)))

    def _emit(op: CamOp, zgrid: np.ndarray, mask: np.ndarray,
              rings: list[list] | None = None) -> None:
        if rings is None:
            rings = contour_parallel_rings(machining, params.relief_stepover_mm)
        for ring in rings:
            if not _ring_is_ccw(ring):        # uniform climb direction on the finish (M12.5)
                ring = list(reversed(ring))
            dp = _densify_xy(ring, res)
            if len(dp) < 2:
                continue
            ci = np.clip(((dp[:, 0] - ox) / res).round().astype(int), 0, cols - 1)
            ri = np.clip(((dp[:, 1] - oy) / res).round().astype(int), 0, rows - 1)
            m = mask[ri, ci]
            idx = np.flatnonzero(m)
            if idx.size < 2:
                continue
            zline = _bilinear_sample(zgrid, dp[:, 0], dp[:, 1], ox, oy, res)
            breaks = np.flatnonzero(np.diff(idx) > gap_cells) + 1
            for grp in np.split(idx, breaks):
                a, b = int(grp[0]), int(grp[-1])      # span the small internal gaps too
                if b - a + 1 < min_cells:
                    continue
                pts = [(float(dp[k, 0]), float(dp[k, 1]), float(zline[k]))
                       for k in range(a, b + 1)]
                op.paths.append(_rdp(pts, params.simplify_tol_mm))

    # Finish only where the target sits BELOW the stock surface; skip every flat-top
    # cell that already sits at stock height (the nosepad tower caps + the outside
    # band). Cutting those removes zero material but makes the concentric rings weave
    # in and out of the cap — Z bouncing 5↔10 (back-and-forth) and short runs with a
    # retract between (pecking), slow and hard on the tool. The cap is the highest
    # point of the frame = the uncut blank back; to give it a machined top, lower the
    # nosepad height a hair (a design param) rather than skim at stock height.
    # Fine and rough tile the same machining region at the same stepover, so their
    # concentric ring set is identical — build it once and share it (each _emit only
    # reads the rings, reversing/densifying its own copies, so sharing is safe).
    base_rings = contour_parallel_rings(machining, params.relief_stepover_mm)
    _emit(fine, z_fine, band & (z_fine < stock_cls.z - eps), rings=base_rings)
    _emit(rough, z_rough, cut_rough, rings=base_rings)
    # Feature-finish band (M13): on a chamfer the contour rings are its level
    # curves, so a flat tool leaves facet ridges of stepover*tan(slope) between
    # them — 0.52 mm at 30°/0.9 mm, over the sim's 0.5 mm completeness gate.
    # Add fine rings CONFINED to the posterior-feature bands at a cusp-derived
    # stepover (the rim-band pattern): cost stays proportional to feature area.
    fb = relief.feature_band
    if fb is not None and fb.any() and relief.feature_max_slope_deg > 0.0:
        from scipy.ndimage import binary_dilation
        slope = math.radians(min(85.0, max(5.0, relief.feature_max_slope_deg)))
        f_step = min(params.relief_stepover_mm,
                     max(0.12, FEATURE_CUSP_MM / math.tan(slope)))
        fb_wide = binary_dilation(fb, iterations=2)   # cover band-edge rounding
        dist_in = distance_transform_edt(inside, sampling=res)
        d_max = float(dist_in[fb_wide & inside].max()) + band_mm + f_step
        f_rings = contour_parallel_rings(machining, f_step, max_depth_mm=d_max)
        _emit(fine, z_fine, fb_wide & band & (z_fine < stock_cls.z - eps),
              rings=f_rings)
    # Contour-ring emission interleaves the separate regions; reorder each pass so the
    # tool works the part in nearest-neighbour order instead of hopping across it (M12.1),
    # then stitch the now-adjacent rings into continuous surface-riding sweeps so a region
    # takes one entry instead of one plunge per ring (M12.2).
    link = params.relief_link_gap_mm
    fine.paths = _stitch_close_paths(order_paths_for_travel(fine.paths),
                                     z_fine, ox, oy, res, link)
    rough.paths = _stitch_close_paths(order_paths_for_travel(rough.paths),
                                      z_rough, ox, oy, res, link)
    return rough, fine


# ------------------------------------------------------------------ ops 4+5: contours

class NoOperationsError(ValueError):
    """Every operation in a program was switched off (M16 per-op enable).

    Its own type so the GUI can report the maker's own choice as a plain sentence
    instead of the IndexError traceback the posting paths used to raise on
    ``ops[0]``.
    """


def require_ops(ops: list[CamOp], what: str = "This component") -> list[CamOp]:
    """Return `ops`, or raise `NoOperationsError` when there is nothing to cut."""
    if not ops:
        raise NoOperationsError(
            f"{what} has no operations to cut — every operation is switched off "
            f"in the Cut tab, or the geometry produced no toolpaths. Re-enable at "
            f"least one operation and generate again."
        )
    return ops


def contour_passes(top_z: float, skin_z: float, stepdown_mm: float) -> list[float]:
    """Depth passes from the stock's top level down to the onion skin."""
    # A non-positive stepdown never advances the loop below — guard the primitive
    # (the schema/UI floor it, but a hand-edited project, or a material/machine with
    # max_doc_mm <= 0 clamped in through model_copy, must not hang the worker, the
    # same guard peck_drill takes): collapse to a single full-depth pass to the skin.
    if stepdown_mm <= 1e-9:
        stepdown_mm = max(top_z - skin_z, 1e-9)
    zs: list[float] = []
    z = top_z
    while True:
        z -= stepdown_mm
        if z <= skin_z + 1e-9:
            break
        zs.append(round(z, 6))
    zs.append(skin_z)
    return zs


def contour_op(
    name: str,
    polys: list[Polygon],
    side: str,                    # "inside" (eyewires) | "outside" (perimeter)
    tool_radius_mm: float,
    allowance_mm: float,
    top_z: float,
    skin_z: float,
    params: CastleCamParams,
    holding: "HoldingParams | None" = None,
) -> CamOp:
    """Depth-stacked offset contour passes.

    `holding` (M16) applies only where the caller passes it — the op that RELEASES
    the part. With ``strategy="tabs"`` the stack runs to the anterior face (z = 0)
    instead of stopping at `skin_z`, and the last pass rises over the uncut
    bridges. Left None (or on ``skin``), the historical onion-skin stack is emitted
    unchanged. Inside contours deliberately never get tabs — see `HoldingParams`.
    """
    op = CamOp(name)
    offset = tool_radius_mm + allowance_mm
    # Climb (default): an inside contour runs CCW and an outside contour CW, so the
    # chip thins to zero against a uniform down-cut wall (M12.5). Conventional
    # reverses both — the choice on a machine whose backlash makes climb pull the
    # cutter in (M16). The buffered exterior's winding isn't guaranteed either way,
    # so the direction is forced here rather than assumed.
    want_ccw = (side == "inside") if params.cut_direction == "climb" else (side == "outside")
    rings: list[list[tuple[float, float]]] = []
    for poly in polys:
        buffered = poly.buffer(offset if side == "outside" else -offset, join_style="round")
        geoms = buffered.geoms if buffered.geom_type == "MultiPolygon" else [buffered]
        for g in geoms:
            if g.is_empty:
                continue
            coords = list(g.exterior.coords)
            if _ring_is_ccw(coords) != want_ccw:
                coords = coords[::-1]
            rings.append(coords)

    tabs = holding is not None and holding.tabs_on()
    # Tabs hold the part instead of the skin, so the stack must reach the anterior
    # face. Never below it: the fixture's blank zone and hold-down screws are there.
    floor_z = 0.0 if tabs else skin_z
    # Ring-major ordering: finish one ring through its full depth stack before
    # moving to the next (Fusion's order). Depth-major (the old order)
    # alternated lenses at each level, adding a long OD<->OS traverse per pass
    # — the back-and-forth that dramatically inflates eyewire cut time.
    passes = contour_passes(top_z, floor_z, params.contour_stepdown_mm)
    tab_h = tab_height_for(passes, top_z, holding.tab_height_mm) if tabs else 0.0
    for ring in rings:
        for i, z in enumerate(passes):
            if tabs and i == len(passes) - 1:
                # Only the last pass carries the bridges; the passes above it are at
                # depth the tab tops don't reach, so tabbing them would cut air.
                pts = insert_tabs([(x, y) for x, y, *_ in ring], holding.tab_count,
                                  holding.tab_width_mm, tab_h, z)
            else:
                pts = [(x, y, z) for x, y in ring]
            op.paths.append(_rdp(pts, params.simplify_tol_mm))
    return op


def tab_height_for(passes: list[float], top_z: float, requested_mm: float) -> float:
    """The tab height that can physically exist, given the depth stack.

    A tab is what the LAST pass leaves behind, so it can be no taller than that
    pass is deep: the pass above already removed everything higher, and asking for
    a 2 mm tab under a 1.5 mm final pass yields a 1.5 mm one whatever the G-code
    says. Clamping here keeps the toolpath honest; `tab_height_warning` gives the
    caller the sentence to show the maker so the silent difference is visible.
    """
    if not passes:
        return requested_mm
    prev = passes[-2] if len(passes) >= 2 else top_z
    return max(0.0, min(requested_mm, prev - passes[-1]))


def tab_height_warning(passes: list[float], top_z: float, requested_mm: float) -> str | None:
    """A one-line warning when the depth stack cannot deliver the tab asked for."""
    actual = tab_height_for(passes, top_z, requested_mm)
    if actual >= requested_mm - 1e-9:
        return None
    return (f"tab height {requested_mm:.2f} mm exceeds the final pass depth — tabs "
            f"will be {actual:.2f} mm tall; lower the depth per pass to get the "
            f"full height")


# ------------------------------------------------------------------ fixture safety

def fixture_clearance_violations(
    ops: list[CamOp],
    fixture: dict,
    tool_radius_mm: float,
    blank: str = "front",
) -> list[str]:
    """Check every toolpath point against the hold-down screw keep-outs.

    Frame coordinates are centered on the blank: frame (0,0) maps to the
    blank-zone center in machine coordinates.
    """
    zone = fixture["blank_zones"][blank]
    cx = zone["x_mm"] + zone["width_mm"] / 2.0
    cy = zone["y_mm"] + zone["height_mm"] / 2.0
    screw_r = fixture["hold_down_screw_radius_mm"]
    screws = np.array([[s["x"], s["y"]] for s in fixture["hold_down_screws"]])

    violations: list[str] = []
    for op in ops:
        # each op's own tool radius (multi-tool jobs, M6.1), else the default
        op_r = op.tool["radius_mm"] if op.tool else tool_radius_mm
        keep_r = screw_r + op_r
        for path in op.paths:
            pts = np.asarray([(p[0] + cx, p[1] + cy) for p in path])
            d2 = ((pts[:, None, :] - screws[None, :, :]) ** 2).sum(axis=2)
            hit = np.flatnonzero((d2 < keep_r**2).any(axis=1))
            if hit.size:
                x, y = pts[hit[0]]
                violations.append(
                    f"{op.name}: toolpath enters screw keep-out near "
                    f"machine ({x:.1f}, {y:.1f})"
                )
                break
    return violations


# ------------------------------------------------------------------ tool-reach gating

@dataclass
class ReachWarning:
    """An op whose assigned tool is too large to reach a feature (M6.1 task 3)."""
    op_name: str
    feature: str                 # human description, e.g. "hinge pocket"
    tool_name: str
    tool_radius_mm: float
    fits_radius_mm: float        # the largest tool radius the feature admits
    suggested_tool: str | None   # a tools.yaml entry that fits, if any

    def message(self) -> str:
        msg = (f"{self.op_name}: tool {self.tool_name} (r={self.tool_radius_mm:.2f} mm) "
               f"is too large to reach the {self.feature} "
               f"(needs r ≤ {self.fits_radius_mm:.2f} mm)")
        if self.suggested_tool:
            msg += f" — try {self.suggested_tool}"
        return msg


def _inscribed_radius(poly: Polygon, tol: float = 0.02) -> float:
    """Max inscribed-circle radius of `poly` — the largest tool that can enter
    the feature at all (the largest r with poly.buffer(-r) non-empty)."""
    if poly.is_empty or poly.area <= 0:
        return 0.0
    minx, miny, maxx, maxy = poly.bounds
    hi = 0.5 * min(maxx - minx, maxy - miny) + tol   # inradius ≤ half the min side
    lo = 0.0
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if poly.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return lo


def _suggest_fitting_tool(fits_radius_mm: float, tools_cfg: dict,
                          prefer_type: str | None = None) -> str | None:
    """The largest tool whose radius fits within `fits_radius_mm` (same type
    preferred). None if nothing in the table is small enough."""
    best: str | None = None
    best_r = -1.0
    for name, t in tools_cfg.items():
        r = t.get("radius_mm")
        if r is None or r > fits_radius_mm + 1e-9:
            continue
        score = r + (0.001 if prefer_type and t.get("type") == prefer_type else 0.0)
        if score > best_r:
            best, best_r = name, score
    return best


def reach_warnings(
    features: list[tuple[str, str, list[Polygon], dict]],
    tools_cfg: dict | None = None,
) -> list[ReachWarning]:
    """Warn when an op's tool can't enter a closed pocket-like feature.

    `features`: ``(op_name, feature_label, polys, tool_dict)`` per checked op.
    The check is the can-it-enter test (tool radius ≤ the feature's inscribed
    radius); when it fails and `tools_cfg` is given, a fitting tool is suggested.
    """
    out: list[ReachWarning] = []
    for op_name, label, polys, tool in features:
        good = [p for p in polys if not p.is_empty and p.area > 0]
        if not good:
            continue
        R = float(tool["radius_mm"])
        fits = min(_inscribed_radius(p) for p in good)
        if R > fits + 1e-6:
            suggested = (_suggest_fitting_tool(fits, tools_cfg, tool.get("type"))
                         if tools_cfg else None)
            out.append(ReachWarning(
                op_name, label, tool.get("name", "tool"), R, fits, suggested))
    return out


def analyze_program_reach(
    ops: list[CamOp],
    hinge_polys: list[Polygon],
    tools_cfg: dict | None = None,
) -> list[ReachWarning]:
    """Reach check for a generated program: today the hinge pockets (the case
    where a 2 mm pocket can't admit the 3.175 mm bulk tool). Extensible to other
    closed features as M6 grows."""
    by_name = {op.name: op for op in ops}
    features: list[tuple[str, str, list[Polygon], dict]] = []
    hinge_op = by_name.get("Hinge Pockets")
    if hinge_op is not None and hinge_op.tool and hinge_polys:
        features.append(("Hinge Pockets", "hinge pocket", list(hinge_polys), hinge_op.tool))
    return reach_warnings(features, tools_cfg)


@dataclass
class DepthReachWarning:
    """An op that cuts deeper than its tool's usable flute length (BUILDPLAN M7.9)."""
    op_name: str
    tool_name: str
    flute_length_mm: float
    cut_depth_mm: float

    def message(self) -> str:
        return (f"{self.op_name}: cut depth {self.cut_depth_mm:.1f} mm exceeds "
                f"{self.tool_name}'s {self.flute_length_mm:.1f} mm flute length — "
                f"the shank would rub (use a longer tool or a shallower pass)")


# Radial clearance the drageoir head keeps off the channel walls when it
# plunges (each side), before feeding out into the rim (V1 lens groove).
GROOVE_ENTRY_CLEARANCE_MM = 0.3


def lens_groove_op(
    lens_polys: list[Polygon],
    groove,                        # LensGrooveParams
    tool: dict,
) -> CamOp:
    """Side-cut the lens-bevel V with a drageoir (V1): one constant-Z climb
    loop per lens, tool center offset so the form's apex lands ON the lens
    contour — the groove bottom IS the boxed dimension. The path plunges
    inside the already-widened eyewire channel (clear of both walls), feeds
    radially out to engagement, runs the loop, and feeds back in; the posted Z
    is the TOOL TIP (the maker touches off the tip on the datum), apex =
    tip + form half-width."""
    op = CamOp("Lens Groove", tool=tool)
    head_r = float(tool.get("radius_mm") or 2.75)
    form_w = float(tool.get("groove_width_mm") or groove.width_mm)
    depth = float(groove.depth_mm)
    tip_z = float(groove.anterior_offset_mm) - form_w / 2.0
    pull = depth + GROOVE_ENTRY_CLEARANCE_MM
    for lens in lens_polys:
        center = lens.buffer(-head_r, join_style="round")
        if center.is_empty:
            continue
        if center.geom_type == "MultiPolygon":
            center = max(center.geoms, key=lambda g: g.area)
        ring = [(float(x), float(y)) for x, y in center.exterior.coords]
        # Climb (CW spindle): an inside contour runs CCW — the eyewire sense
        # (M12.5); the buffered exterior's winding isn't guaranteed.
        area2 = sum(x0 * y1 - x1 * y0
                    for (x0, y0), (x1, y1) in zip(ring, ring[1:]))
        if area2 < 0:
            ring.reverse()
        cx, cy = center.centroid.x, center.centroid.y
        sx, sy = ring[0]
        d = math.hypot(sx - cx, sy - cy) or 1.0
        entry = (sx + (cx - sx) / d * pull, sy + (cy - sy) / d * pull)
        pts = [entry] + ring + [entry]
        op.paths.append([(x, y, tip_z) for x, y in pts])
    return op


def verify_groove_op(op: CamOp, lens_polys: list[Polygon], groove,
                     tool: dict) -> list[str]:
    """Exact geometric verification of the side-cut Lens Groove op (V1).

    The top-down sim sweep deliberately skips this op — its removal is an
    undercut a Z-buffer cannot represent — so it is verified symbolically
    instead, which is STRONGER for this op class: one constant-Z loop per
    lens whose form apex lands ON the lens contour (the groove bottom is the
    boxed dimension), entered radially clear of the wall. Empty result =
    verified; any string is a defect in the generated geometry."""
    from shapely.geometry import Point
    out: list[str] = []
    head_r = float(tool.get("radius_mm") or 2.75)
    form_w = float(tool.get("groove_width_mm") or groove.width_mm)
    want_tip = float(groove.anterior_offset_mm) - form_w / 2.0
    if len(op.paths) != len(lens_polys):
        out.append(f"Lens Groove: {len(op.paths)} loop(s) for "
                   f"{len(lens_polys)} lens(es)")
    for i, (path, lens) in enumerate(zip(op.paths, lens_polys), start=1):
        zs = {round(p[2], 6) for p in path}
        if len(zs) != 1 or abs(next(iter(zs)) - want_tip) > 1e-6:
            out.append(f"Lens Groove loop {i}: not one constant-Z pass at "
                       f"the form tip ({want_tip:.3f} mm)")
        ring = path[1:-1]
        if len(ring) < 3:
            out.append(f"Lens Groove loop {i}: degenerate loop")
            continue
        dev = max(abs(lens.exterior.distance(Point(p[0], p[1])) - head_r)
                  for p in ring)
        if dev > 0.08:
            out.append(f"Lens Groove loop {i}: form apex misses the lens "
                       f"contour by up to {dev:.2f} mm")
        ex, ey = path[0][0], path[0][1]
        pull = math.hypot(ex - ring[0][0], ey - ring[0][1])
        if pull < float(groove.depth_mm):
            out.append(f"Lens Groove loop {i}: entry not pulled clear of "
                       f"the wall ({pull:.2f} mm)")
    return out


def groove_channel_width_mm(tool: dict) -> float:
    """The eyewire-channel width the drageoir needs to descend freely: its
    head plus entry clearance on both sides (feeding out only ADDS inner
    clearance, so the requirement is depth-independent)."""
    return (float(tool.get("diameter_mm") or 5.5)
            + 2.0 * GROOVE_ENTRY_CLEARANCE_MM)


def groove_warnings(groove, tool: dict, wall_top_z: float) -> list[str]:
    """Soft checks the GUI/log surface before cutting a groove (V1)."""
    out: list[str] = []
    if (tool.get("type") or "") != "groove":
        out.append(
            f"Lens Groove is assigned '{tool.get('display_name') or '?'}' — "
            "assign a groove-type (drageoir) form cutter.")
    form_d = float(tool.get("groove_depth_mm") or 0.0)
    form_w = float(tool.get("groove_width_mm") or 0.0)
    if form_d and groove.depth_mm > form_d + 1e-6:
        out.append(
            f"Groove depth {groove.depth_mm:.2f} mm exceeds the tool form's "
            f"{form_d:.2f} mm — the cut groove will be the tool's shape.")
    if form_w and abs(groove.width_mm - form_w) > 0.05:
        out.append(
            f"Groove width {groove.width_mm:.2f} mm ≠ the tool form's "
            f"{form_w:.2f} mm — the cut groove will be the tool's shape.")
    if groove.anterior_offset_mm + groove.width_mm / 2.0 >= wall_top_z:
        out.append(
            "Groove flank reaches the eyewire wall top — lower the anterior "
            "offset or narrow the groove.")
    if groove.anterior_offset_mm - groove.width_mm / 2.0 <= 0.0:
        out.append(
            "Groove flank reaches the anterior face — raise the anterior "
            "offset or narrow the groove.")
    return out


def depth_reach_warnings(
    ops: list[CamOp], stock_top_mm: float,
) -> list[DepthReachWarning]:
    """Warn when an op's deepest cut drops further below the stock top than its
    tool's flute length allows — the depth-axis sibling of `reach_warnings` (M7.9).

    Only tools that declare a `flute_length_mm` (> 0) are checked, so shipped jobs
    raise nothing new until a tool's reach is filled in.
    """
    out: list[DepthReachWarning] = []
    for op in ops:
        t = op.tool
        if not t:
            continue
        if (t.get("type") or "") == "groove":
            continue   # side cutter: its head rides at depth by design (V1)
        flute = float(t.get("flute_length_mm") or 0.0)
        if flute <= 0:
            continue
        zmin, _zmax = op.z_range()
        if not math.isfinite(zmin):
            continue
        depth = stock_top_mm - zmin
        if depth > flute + 1e-6:
            out.append(DepthReachWarning(
                op.name, t.get("name", "tool"), flute, depth))
    return out


@dataclass
class FeatureReachWarning:
    """An M13 posterior feature the Fine Relief tool can't fully finish
    (BUILDPLAN M13.3): the groove's U root needs a ball no larger than the
    root radius, and a chamfer falling INTO a rim (splay toe at the outline,
    bezel toe at a lens opening) needs a ball — a flat's trailing edge rides
    the slope behind it and leaves ~radius*tan(angle) proud at the rim edge."""
    detail: str
    tool_name: str
    tool_type: str
    suggested: str | None = None

    def message(self) -> str:
        hint = f" (try {self.suggested})" if self.suggested else ""
        return (f"Fine Relief: {self.detail} — {self.tool_name} "
                f"({self.tool_type}) leaves it proud{hint}")


def feature_reach_warnings(
    castle: CastleParams,
    ops: list[CamOp],
    tools_cfg: dict | None = None,
) -> list[FeatureReachWarning]:
    """M13 posterior-feature reach for the Fine Relief tool: the bridge-relief
    root wants a ball <= the root radius; the splay/bezel chamfer toes at the
    rims want a ball of any size (the feature-finish band handles their
    mid-band facets, but no flat tool can finish a downhill slope to an edge)."""
    fine = next((op for op in ops if op.name == "Fine Relief"), None)
    tool = fine.tool if fine is not None and fine.tool else None
    if tool is None:
        return []
    name = tool.get("name", "tool")
    ttype = str(tool.get("type", "?"))
    radius = float(tool["radius_mm"])
    is_ball = tool.get("type") == "ball"
    out: list[FeatureReachWarning] = []
    if castle.bridge_relief.enabled:
        # Tightest curvature of the cone-scaled cosine bell sits at the base
        # trough: R_c = width^2 / (2 pi^2 depth). A bigger tool bridges the
        # hollow and leaves the scoop centre proud.
        g = castle.bridge_relief
        r_c = g.width_mm**2 / (2.0 * math.pi**2 * max(g.depth_mm, 1e-6))
        if not (is_ball and radius <= r_c + 1e-6):
            balls = ({n: t for n, t in tools_cfg.items()
                      if t.get("type") == "ball"} if tools_cfg else None)
            suggested = _suggest_fitting_tool(r_c, balls, "ball") if balls else None
            out.append(FeatureReachWarning(
                f"the bridge-relief hollow (tightest ~R{r_c:.1f} at its base) "
                f"needs a ball tool with radius <= {r_c:.1f} mm",
                name, ttype, suggested))
    if (castle.pad_splay.enabled or castle.eyewire_bezel.enabled) and not is_ball:
        which = " / ".join(w for w, on in (
            ("pad-splay", castle.pad_splay.enabled),
            ("eyewire-bezel", castle.eyewire_bezel.enabled)) if on)
        angles = []
        if castle.pad_splay.enabled:
            s = castle.pad_splay
            angles += ([s.angle_center_deg, s.angle_middle_deg, s.angle_end_deg]
                       if s.toric else [s.angle_center_deg])
        if castle.eyewire_bezel.enabled:
            angles.append(castle.eyewire_bezel.angle_deg)
        lip = radius * math.tan(math.radians(max(angles)))
        balls = ({n: t for n, t in tools_cfg.items() if t.get("type") == "ball"}
                 if tools_cfg else None)
        suggested = _suggest_fitting_tool(radius, balls, "ball") if balls else None
        out.append(FeatureReachWarning(
            f"the {which} chamfer toe at the rim needs a ball tool "
            f"(a flat leaves ~{lip:.1f} mm at the rim edge)",
            name, ttype, suggested))
    return out


# ------------------------------------------------------------------ program assembly

def generate_castle_program(
    relief: CastleRelief,
    castle: CastleParams,
    hinge_polys: list[Polygon],
    tool: dict,
    params: CastleCamParams | None = None,
    progress: Optional[ProgressFn] = None,
    tools_cfg: dict | None = None,
) -> list[CamOp]:
    """The five ops, in machining order, from the castle relief.

    `tool` is the global/default tool. When `tools_cfg` is given, each op resolves
    its own tool from `params.op_tools` (BUILDPLAN M6.1 multi-tool jobs) and
    carries it on `CamOp.tool`; otherwise every op uses `tool` (single-tool, the
    M1–M5 behaviour). progress: optional per-op stage hook (BUILDPLAN M4.6 Part B).
    """
    params = params or CastleCamParams()
    stock = castle.stock
    body = relief.mask_body           # aperture holes when the lens groove is on
    groove = relief.groove            # LensGrooveParams | None (V1)
    skin = castle.onion_skin_mm
    allowance = castle.hand_finishing_allowance_mm
    top_z = stock.total_pad_height_mm

    def _tool_for(op_name: str) -> dict:
        # tool_for_op() now defaults small features (hinge pockets) to a fine tool
        # rather than the bulk global tool, so corners aren't over-rounded (M11).
        if tools_cfg is None:
            return tool
        return resolve_tool(params.tool_for_op(op_name), tools_cfg, default=tool)

    ops: list[CamOp] = []

    def _p(label: str, k: int) -> None:
        if progress is not None:
            progress(f"Op {k}/5 · {label}", k / 5.0)

    # 1 — hinge pockets (cut first, stock rigid). Hinges sit on the blank
    # outside the pad block, so the local stock top is the blank thickness.
    _p("Hinge pockets", 1)
    hinge_tool = _tool_for("Hinge Pockets")
    floor_z = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    op1 = hinge_pocket_op(
        hinge_polys, floor_z,
        start_z=stock.blank_thickness_mm + 0.5,
        tool_radius_mm=hinge_tool["radius_mm"], params=params,
    )
    op1.tool = hinge_tool
    ops.append(op1)

    # 2 + 3 — rough then fine relief
    _p("Rough + fine relief", 3)
    rough_tool = _tool_for("Rough Relief")
    fine_tool = _tool_for("Fine Relief")
    rough, fine = relief_ops(relief, stock, fine_tool, params, rough_tool=rough_tool)
    rough.tool, fine.tool = rough_tool, fine_tool
    ops += [rough, fine]

    # 4 — eyewires (lens holes are the body's interior rings; with the groove
    # on these are the UNDERSIZED apertures — the rim lip)
    _p("Eyewires", 4)
    eyewire_tool = _tool_for("Eyewires")
    # Decorative OUTLINE openings share `body.interiors` with the lens apertures
    # but are a separate op: no groove, no rim-lip widening, just an inside
    # through-cut (see normalize.assemble_outline).
    is_hole = relief.partition.is_hole
    apertures = [Polygon(r) for r in body.interiors if not is_hole(r)]
    hole_polys = [Polygon(r) for r in body.interiors if is_hole(r)]

    def _groove_tool() -> dict:
        # Explicit op_tools wins, then the groove param's tool, then the
        # shipped drageoir. (Not in POSTERIOR_OPS — see the schema note.)
        name = (params.op_tools.get("Lens Groove")
                or getattr(groove, "tool", "") or "groove_drageoir")
        return resolve_tool(name, tools_cfg or {}, default=tool)

    contour_polys: list[Polygon] = []
    if groove is not None:
        # Widen the channel so the drageoir head descends freely: extra inner
        # rings, interleaved per lens so each eyewire finishes ring-major.
        groove_tool = _groove_tool()
        need = groove_channel_width_mm(groove_tool)
        slot = eyewire_tool["radius_mm"] * 2.0
        widen = max(0.0, need - slot)
        n_extra = int(math.ceil(widen / (slot * 0.9))) if widen > 0 else 0
        for ap in apertures:
            contour_polys.append(ap)
            for k in range(1, n_extra + 1):
                inner = ap.buffer(-(widen * k / n_extra), join_style="round")
                if inner.is_empty:
                    continue
                if inner.geom_type == "MultiPolygon":
                    inner = max(inner.geoms, key=lambda g: g.area)
                contour_polys.append(inner)
    else:
        contour_polys = apertures
    op4 = contour_op(
        "Eyewires", contour_polys, "inside", eyewire_tool["radius_mm"],
        allowance, top_z, skin, params,
    )
    op4.tool = eyewire_tool
    ops.append(op4)

    # 4a — decorative OUTLINE holes, cut with the eyewire strategy right after
    # the eyewires so they share a tool (no extra change) while the part is
    # still held by its perimeter.
    if hole_polys:
        # Defaults to the eyewire tool (same inside-contour strategy) rather than
        # the global bulk tool, so holes add no tool change unless pinned. Like
        # "Lens Groove" this stays out of POSTERIOR_OPS — see the schema note.
        pinned = params.op_tools.get("Holes")
        holes_tool = (resolve_tool(pinned, tools_cfg or {}, default=eyewire_tool)
                      if pinned else eyewire_tool)
        op4a = contour_op(
            "Holes", hole_polys, "inside", holes_tool["radius_mm"],
            allowance, top_z, skin, params,
        )
        op4a.tool = holes_tool
        ops.append(op4a)

    # 4b — lens bevel groove (V1, optional): side-cut the V into each rim lip
    # with the drageoir, bottoming exactly on the original LENS contour. Runs
    # AFTER the eyewires open the channel, BEFORE the perimeter releases the
    # part. Not a contour op: entry is a radial feed, never a ramp.
    if groove is not None and relief.groove_lens_polys:
        op4b = lens_groove_op(relief.groove_lens_polys, groove, _groove_tool())
        if op4b.paths:
            ops.append(op4b)

    # 5 — perimeter. The op that releases the frame, so it is the one that carries
    # the hold-down strategy (M16): onion skin by default, tabs when the maker has
    # chosen them. The inside contours above keep the skin either way.
    _p("Perimeter", 5)
    perimeter_tool = _tool_for("Perimeter")
    op5 = contour_op(
        "Perimeter", [Polygon(body.exterior)], "outside",
        perimeter_tool["radius_mm"], allowance, top_z, skin, params,
        holding=castle.holding,
    )
    op5.tool = perimeter_tool
    ops.append(op5)
    return params.enabled_ops(ops)


# Strategy descriptions for the in-app setup sheet, keyed by op name.
_OP_STRATEGIES = {
    "Hinge Pockets": "Pocket 2D · ramped lap entry",
    "Rough Relief": "Raster drop-cutter · stock-aware, +axial stock",
    "Fine Relief": "Raster drop-cutter",
    "Eyewires": "Contour 2D (inside) · onion skin",
    "Holes": "Contour 2D (inside) · onion skin",
    "Lens Groove": "Groove side-cut · radial entry (drageoir)",
    "Perimeter": "Contour 2D (outside) · onion skin",
    "Engraving": "Engrave · trace at depth",
    "Temple Profile": "Contour 2D (outside) · onion skin",
    "Drill Holes": "Peck drill · G83 full-retract",
    "Block Profile": "Contour 2D (outside) · onion skin",
}


def op_summaries(
    ops: list[CamOp], feed_rate_mmpm: float | None = None,
) -> list[dict]:
    """Setup-sheet rows for the op-summary dialog (BUILDPLAN M4.6).

    Each row: name, strategy, paths, floor_z_mm, cut_length_mm, and
    est_minutes when a feed rate is given (cutting only — rapids excluded,
    so it is a lower bound).
    """
    rows: list[dict] = []
    for op in ops:
        floor_z, _ = op.z_range()
        length = op.path_length_mm()
        row = {
            "name": op.name,
            "strategy": _OP_STRATEGIES.get(op.name, "—"),
            "paths": len(op.paths),
            "floor_z_mm": floor_z,
            "cut_length_mm": length,
        }
        if feed_rate_mmpm:
            row["est_minutes"] = length / feed_rate_mmpm
        rows.append(row)
    return rows


def count_tool_changes(ops: list[CamOp]) -> int:
    """Number of tool-change blocks the program will emit (op-order transitions)."""
    changes = 0
    current: str | None = None
    for op in ops:
        nm = op.tool_name
        if nm is None:
            continue
        if current is not None and nm != current:
            changes += 1
        current = nm
    return changes


def build_tool_settings(
    ops: list[CamOp],
    tools_cfg: dict,
    *,
    default_feed: float,
    default_plunge: float,
    default_spindle: float,
    machine=None,
) -> tuple[dict, list[str]]:
    """Assemble a name → ToolSetting map for a multi-tool program (M6.1).

    Each distinct tool (in machining order) gets a Tn number; its feeds come from
    the tool's own tools.yaml override when present, else the supplied defaults
    (material/CAM), clamped to the machine profile. Returns (settings, warnings).
    """
    from ..post.grbl import ToolSetting

    settings: dict[str, ToolSetting] = {}
    warnings: list[str] = []
    number = 0
    used: set[int] = set()
    for op in ops:
        nm = op.tool_name
        if nm is None or nm in settings:
            continue
        t = op.tool or tools_cfg.get(nm, {})
        # Stable T-number from the tool spec when set (M7.8); else the next free
        # number by machining order — shipped tools carry none, so unchanged.
        n = int(t.get("number") or 0)
        if n <= 0 or n in used:
            number += 1
            while number in used:
                number += 1
            n = number
        used.add(n)
        feed = t.get("feed_rate_mmpm") or default_feed
        plunge = t.get("plunge_rate_mmpm") or default_plunge
        spindle = t.get("spindle_rpm") or default_spindle
        if machine is not None:
            if feed > machine.max_feed_mmpm:
                warnings.append(f"{nm}: feed {feed:.0f} > machine max "
                                f"{machine.max_feed_mmpm:.0f} mm/min — clamped")
                feed = machine.max_feed_mmpm
            if plunge > machine.max_plunge_mmpm:
                warnings.append(f"{nm}: plunge {plunge:.0f} > machine max "
                                f"{machine.max_plunge_mmpm:.0f} mm/min — clamped")
                plunge = machine.max_plunge_mmpm
            if spindle > machine.max_spindle_rpm:
                warnings.append(f"{nm}: spindle {spindle:.0f} > machine max "
                                f"{machine.max_spindle_rpm:.0f} RPM — clamped")
                spindle = machine.max_spindle_rpm
            elif machine.min_spindle_rpm and spindle < machine.min_spindle_rpm:
                spindle = machine.min_spindle_rpm
        diameter = float(t.get("diameter_mm", 2.0 * t.get("radius_mm", 1.0)))
        settings[nm] = ToolSetting(
            number=n, name=nm, diameter_mm=diameter,
            feed_rate_mmpm=float(feed), plunge_rate_mmpm=float(plunge),
            spindle_rpm=int(round(spindle)),
        )
    return settings, warnings


def write_castle_program(
    ops: list[CamOp],
    post: "GRBLPost",  # noqa: F821
    side: str = "Posterior Cut",
    arc_tol_mm: float = 0.01,
    contour_stepdown_mm: float = _DEFAULT_CAM.contour_stepdown_mm,
    contour_ramp_angle_deg: float = _DEFAULT_CAM.contour_ramp_angle_deg,
    tool_settings: dict | None = None,
    tool_change_mode: str = "m0",
    contour_op_names: set | None = None,
    drill_op_names: set | None = None,
    peck_depth_mm: float = 1.5,
    contour_lead_in: str = _DEFAULT_CAM.contour_lead_in,
) -> None:
    """Emit the ops into a single GRBL program (the castle's five ops, or any
    op list — e.g. a temple's engrave + profile, BUILDPLAN M6.3).

    `contour_op_names` are the through-cut ops that get the partial-lap ramped
    lead-in (default the castle's Eyewires / Perimeter); every other op is emitted
    as plain plunge-and-feed polylines (relief rasters, engraving strokes).

    arc_tol_mm > 0 fits G2/G3 arcs to the curved passes (smooth motion, smaller
    files). The through-cut contours (Eyewires / Perimeter) get a partial-lap
    ramped lead-in over the stepdown instead of a straight slot-plunge.

    Multi-tool jobs (BUILDPLAN M6.1): when `tool_settings` (a name → ToolSetting
    map) is given, the program announces the first op's tool and emits a
    tool-change block whenever a following op's tool differs — so a change costs
    one block, and the fixed machining order (pockets → relief → contours) keeps
    same-tool ops naturally grouped. When `tool_settings` is None the program is
    single-tool, exactly as before.
    """
    # "Holes" (decorative OUTLINE openings) is an inside through-cut exactly like
    # Eyewires — it needs the same ramped lead-in, not a full-depth plunge.
    contour_ops = contour_op_names if contour_op_names is not None else {"Eyewires", "Holes", "Perimeter"}
    drill_ops = drill_op_names or set()
    # On an auto-tool-change machine the M6 that follows the header raises Z itself, so
    # the header's safe-Z retract is a wasted bob before the tool change — skip it there
    # (the first cutting pass still takes its own full retract after the M6).
    post.header(side, initial_retract=(tool_change_mode != "m6"))
    current: str | None = None
    first = ops[0].tool_name if ops else None
    if tool_settings and first in tool_settings:
        post.apply_tool(tool_settings[first])
        current = first
    # Auto-tool-change machines (Carbide Motion + probe) want the first tool loaded
    # and measured up front — emit M6 so it probes before cutting (BUILDPLAN M8).
    if tool_change_mode == "m6":
        n = tool_settings[first].number if (tool_settings and first in tool_settings) else 1
        post.initial_tool_load(n)
    post.spindle_on()
    for op in ops:
        nm = op.tool_name
        if tool_settings and nm is not None and nm != current and nm in tool_settings:
            post.tool_change(tool_settings[nm], mode=tool_change_mode)
            current = nm
        post.comment(f"--- {op.name} ---")
        if op.name in drill_ops:
            # each path is a hole, stored as [(x, y, z_top), (x, y, z_bottom)]
            for path in op.paths:
                (x, y, z_top), (_, _, z_bottom) = path[0], path[-1]
                post.peck_drill(x, y, z_top, z_bottom, peck_depth_mm)
            post.safe_retract()
            continue
        # ramp_height 0 makes the post plunge-and-lap instead of taking the
        # partial-lap ramped lead-in — which is exactly `contour_lead_in="plunge"`.
        # A zero ramp ANGLE would not do this: the post reads that as "ramp the
        # whole lap" (see `_emit_ramped_loop`), which is the opposite request.
        ramp = (contour_stepdown_mm
                if op.name in contour_ops and contour_lead_in != "plunge" else 0.0)
        for path in op.paths:
            post.emit_polyline(path, arc_tol=arc_tol_mm, ramp_height=ramp,
                               ramp_angle_deg=contour_ramp_angle_deg)
        post.safe_retract()
    post.end_program()
