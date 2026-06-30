"""The five-operation posterior CAM recipe (BUILDPLAN M3).

Reproduces the maker's proven Fusion 360 program (DEMO_PROJECT_TEARDOWN.md §6)
from the castle relief, in order:

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

from ..project.schema import CastleCamParams, CastleParams, StockDefinition
from ..relief.castle import CastleRelief, stock_top_heightfield
from ..relief.heightfield import Heightfield
from .dropcutter import cutter_location_surface
from .pocketing import _inward_offsets, _SCALE

Point3 = tuple[float, float, float]


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
) -> list[tuple[float, float, float]]:
    """Keep-out circles ``(cx, cy, radius)`` the tool CENTRE must stay outside when
    a pass-link retract is lowered below safe Z (BUILDPLAN M8). They mark the
    work-holding screws standing proud of the stock — the standard Guild fixture:
    one at each stock-blank corner and one at each lens centre (the body's interior
    holes). ``radius`` = screw radius + tool radius + margin, so the tool *edge*
    keeps ``margin`` clear of the head. Design coordinates (blank centred on origin)."""
    keep_r = screw_head_diameter_mm / 2.0 + tool_radius_mm + margin_mm
    hl, hw = stock.blank_length_mm / 2.0, stock.blank_width_mm / 2.0
    centers = [(hl, hw), (-hl, hw), (hl, -hw), (-hl, -hw)]      # blank corners
    for ring in body.interiors:                                 # lens centres
        c = Polygon(ring).centroid
        centers.append((c.x, c.y))
    return [(x, y, keep_r) for x, y in centers]


# ------------------------------------------------------------------ op 1: hinge pockets

def hinge_pocket_op(
    hinge_polys: list[Polygon],
    floor_z: float,
    start_z: float,
    tool_radius_mm: float,
    params: CastleCamParams,
) -> CamOp:
    """Pocket each hinge outline to floor_z with a ramped lap entry.

    The outermost tool ring is lapped repeatedly, descending ramp_step_mm per
    lap from start_z (just above local stock) to the floor — no straight
    plunge into material. The full inward cascade then clears the floor.
    """
    op = CamOp("Hinge Pockets")
    for poly in hinge_polys:
        rings = _poly_rings(poly, tool_radius_mm, params.pocket_stepover_mm)
        if not rings:
            continue
        outer = rings[0]
        path: list[Point3] = []

        # ramp laps on the outer ring
        ring_xy = [(p[0] / _SCALE, p[1] / _SCALE) for p in outer]
        ring_xy.append(ring_xy[0])
        n = len(ring_xy)
        z = start_z
        path.append((*ring_xy[0], z))
        while z > floor_z + 1e-9:
            z_next = max(floor_z, z - params.ramp_step_mm)
            for i in range(1, n):
                t = i / (n - 1)
                path.append((*ring_xy[i], z + (z_next - z) * t))
            z = z_next

        # floor laps: outer ring once more flat, then the inward cascade
        path += [(*p, floor_z) for p in ring_xy]
        for ring in rings[1:]:
            path += _ring_to_points(ring, floor_z)
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
                           max_rings: int = 4000) -> list[list]:
    """Concentric boundary-offset rings tiling `body` (Fusion 'Scallop' style).

    Successive inward erosions of the material polygon: the exterior shrinks and
    the lens holes grow, so the rings wrap the outline *and* every eyewire. The
    relief finish then follows the frame instead of raster-sweeping it.
    """
    rings: list[list] = []
    d = 0.0
    for _ in range(max_rings):
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

    def _emit(op: CamOp, zgrid: np.ndarray, mask: np.ndarray) -> None:
        for ring in contour_parallel_rings(machining,
                                           params.relief_stepover_mm):
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
    _emit(fine, z_fine, band & (z_fine < stock_cls.z - eps))
    _emit(rough, z_rough, cut_rough)
    return rough, fine


# ------------------------------------------------------------------ ops 4+5: contours

def contour_passes(top_z: float, skin_z: float, stepdown_mm: float) -> list[float]:
    """Depth passes from the stock's top level down to the onion skin."""
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
) -> CamOp:
    op = CamOp(name)
    offset = tool_radius_mm + allowance_mm
    rings: list[list[tuple[float, float]]] = []
    for poly in polys:
        buffered = poly.buffer(offset if side == "outside" else -offset, join_style="round")
        geoms = buffered.geoms if buffered.geom_type == "MultiPolygon" else [buffered]
        for g in geoms:
            if g.is_empty:
                continue
            coords = list(g.exterior.coords)
            rings.append(coords)

    # Ring-major ordering: finish one ring through its full depth stack before
    # moving to the next (Fusion's order). Depth-major (the old order)
    # alternated lenses at each level, adding a long OD<->OS traverse per pass
    # — the back-and-forth that dramatically inflates eyewire cut time.
    passes = contour_passes(top_z, skin_z, params.contour_stepdown_mm)
    for ring in rings:
        for z in passes:
            pts = [(x, y, z) for x, y in ring]
            op.paths.append(_rdp(pts, params.simplify_tol_mm))
    return op


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
    body = relief.partition.body
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

    # 4 — eyewires (lens holes are the body's interior rings)
    _p("Eyewires", 4)
    eyewire_tool = _tool_for("Eyewires")
    lenses = [Polygon(ring) for ring in body.interiors]
    op4 = contour_op(
        "Eyewires", lenses, "inside", eyewire_tool["radius_mm"],
        allowance, top_z, skin, params,
    )
    op4.tool = eyewire_tool
    ops.append(op4)

    # 5 — perimeter
    _p("Perimeter", 5)
    perimeter_tool = _tool_for("Perimeter")
    op5 = contour_op(
        "Perimeter", [Polygon(body.exterior)], "outside",
        perimeter_tool["radius_mm"], allowance, top_z, skin, params,
    )
    op5.tool = perimeter_tool
    ops.append(op5)
    return ops


# Strategy descriptions for the in-app setup sheet, keyed by op name.
_OP_STRATEGIES = {
    "Hinge Pockets": "Pocket 2D · ramped lap entry",
    "Rough Relief": "Raster drop-cutter · stock-aware, +axial stock",
    "Fine Relief": "Raster drop-cutter",
    "Eyewires": "Contour 2D (inside) · onion skin",
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
    contour_ops = contour_op_names if contour_op_names is not None else {"Eyewires", "Perimeter"}
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
        ramp = contour_stepdown_mm if op.name in contour_ops else 0.0
        for path in op.paths:
            post.emit_polyline(path, arc_tol=arc_tol_mm, ramp_height=ramp,
                               ramp_angle_deg=contour_ramp_angle_deg)
        post.safe_retract()
    post.end_program()
