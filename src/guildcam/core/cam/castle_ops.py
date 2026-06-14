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
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
from shapely.geometry import Polygon

# Optional stage-boundary progress hook (BUILDPLAN M4.6 Part B); see
# relief.castle.ProgressFn. Default None — core never imports the GUI.
ProgressFn = Callable[[str, float], None]

from ..project.schema import CastleParams, StockDefinition
from ..relief.castle import CastleRelief, stock_top_heightfield
from ..relief.heightfield import Heightfield
from .dropcutter import cutter_location_surface
from .pocketing import _inward_offsets, _SCALE

Point3 = tuple[float, float, float]


@dataclass
class CamOp:
    name: str
    paths: list[list[Point3]] = field(default_factory=list)

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


@dataclass
class CastleCamParams:
    """Operation parameters; defaults are the Demo Project reference values."""
    tool_name: str = "flat_3175"
    pocket_stepover_mm: float = 1.2
    relief_stepover_mm: float = 0.8
    rough_axial_stock_mm: float = 2.0
    contour_stepdown_mm: float = 2.5
    ramp_step_mm: float = 0.6        # pocket ramp descent per lap
    skim_epsilon_mm: float = 0.05    # "nothing to cut" threshold for roughing
    simplify_tol_mm: float = 0.01


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
    tool_type: str,
    tool_radius_mm: float,
    params: CastleCamParams,
) -> tuple[CamOp, CamOp]:
    """Rough (surface + axial stock, stock-aware) and fine (final surface).

    Both passes are **contour-parallel** (BUILDPLAN M5 CAM-quality work): the
    toolpath is a set of boundary-offset rings that follow the outline and the
    eyewires, riding the drop-cutter surface — not an axis-aligned raster. The
    cutter-location surface, the two-level stock surface, the tool-reach mask
    and the stock-aware rough mask are unchanged, so the cut envelopes match the
    reference NC; only the path *pattern* differs.

    Outside the body the CAM field is held at local stock height, so the rim
    band stays untouched until the perimeter op.
    """
    f = relief.field
    res = f.resolution
    ox, oy = f.origin
    stock_hf = stock_top_heightfield(
        stock, resolution=res, origin=f.origin, shape=f.z.shape
    )
    cam_z = np.where(relief.inside, f.z, stock_hf.z)
    cls_fine = cutter_location_surface(
        Heightfield(z=cam_z, origin=f.origin, resolution=res),
        tool_type, tool_radius_mm,
    )
    stock_cls = cutter_location_surface(stock_hf, tool_type, tool_radius_mm)

    eps = params.skim_epsilon_mm
    fine = CamOp("Fine Relief")
    rough = CamOp("Rough Relief")

    # tool centers may roam anywhere within tool reach of the body
    from scipy.ndimage import binary_dilation
    r_px = max(1, int(round(tool_radius_mm / res)))
    yy, xx = np.ogrid[-r_px:r_px + 1, -r_px:r_px + 1]
    reach = binary_dilation(relief.inside, structure=(xx**2 + yy**2) <= r_px**2)

    rows, cols = cls_fine.z.shape
    z_fine = cls_fine.z
    z_rough = np.minimum(z_fine + params.rough_axial_stock_mm, stock_cls.z)
    # rough only where stock actually sits above the rough target
    cut_rough = reach & ((z_fine + params.rough_axial_stock_mm) < stock_cls.z - eps)

    def _emit(op: CamOp, zgrid: np.ndarray, mask: np.ndarray) -> None:
        for ring in contour_parallel_rings(relief.partition.body,
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
            zline = zgrid[ri, ci]
            for run in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
                if run.size < 2:
                    continue
                pts = [(float(dp[k, 0]), float(dp[k, 1]), float(zline[k]))
                       for k in run]
                op.paths.append(_rdp(pts, params.simplify_tol_mm))

    _emit(fine, z_fine, reach)
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
    keep_r = fixture["hold_down_screw_radius_mm"] + tool_radius_mm
    screws = np.array([[s["x"], s["y"]] for s in fixture["hold_down_screws"]])

    violations: list[str] = []
    for op in ops:
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


# ------------------------------------------------------------------ program assembly

def generate_castle_program(
    relief: CastleRelief,
    castle: CastleParams,
    hinge_polys: list[Polygon],
    tool: dict,
    params: CastleCamParams | None = None,
    progress: Optional[ProgressFn] = None,
) -> list[CamOp]:
    """The five ops, in machining order, from the castle relief.

    progress: optional per-op stage hook (BUILDPLAN M4.6 Part B).
    """
    params = params or CastleCamParams()
    tool_r = tool["radius_mm"]
    stock = castle.stock
    body = relief.partition.body
    skin = castle.onion_skin_mm
    allowance = castle.hand_finishing_allowance_mm
    top_z = stock.total_pad_height_mm

    ops: list[CamOp] = []

    def _p(label: str, k: int) -> None:
        if progress is not None:
            progress(f"Op {k}/5 · {label}", k / 5.0)

    # 1 — hinge pockets (cut first, stock rigid). Hinges sit on the blank
    # outside the pad block, so the local stock top is the blank thickness.
    _p("Hinge pockets", 1)
    floor_z = castle.zones.endpiece_mm - castle.hinge_pocket_depth_mm
    ops.append(hinge_pocket_op(
        hinge_polys, floor_z,
        start_z=stock.blank_thickness_mm + 0.5,
        tool_radius_mm=tool_r, params=params,
    ))

    # 2 + 3 — rough then fine relief
    _p("Rough + fine relief", 3)
    rough, fine = relief_ops(relief, stock, tool["type"], tool_r, params)
    ops += [rough, fine]

    # 4 — eyewires (lens holes are the body's interior rings)
    _p("Eyewires", 4)
    lenses = [Polygon(ring) for ring in body.interiors]
    ops.append(contour_op(
        "Eyewires", lenses, "inside", tool_r, allowance, top_z, skin, params
    ))

    # 5 — perimeter
    _p("Perimeter", 5)
    ops.append(contour_op(
        "Perimeter", [Polygon(body.exterior)], "outside",
        tool_r, allowance, top_z, skin, params,
    ))
    return ops


# Strategy descriptions for the in-app setup sheet, keyed by op name.
_OP_STRATEGIES = {
    "Hinge Pockets": "Pocket 2D · ramped lap entry",
    "Rough Relief": "Raster drop-cutter · stock-aware, +axial stock",
    "Fine Relief": "Raster drop-cutter",
    "Eyewires": "Contour 2D (inside) · onion skin",
    "Perimeter": "Contour 2D (outside) · onion skin",
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


def write_castle_program(
    ops: list[CamOp],
    post: "GRBLPost",  # noqa: F821
    side: str = "Posterior Cut",
    arc_tol_mm: float = 0.01,
    contour_stepdown_mm: float = CastleCamParams.contour_stepdown_mm,
) -> None:
    """Emit the five ops into a single GRBL program.

    arc_tol_mm > 0 fits G2/G3 arcs to the curved passes (smooth motion, smaller
    files). The through-cut contours (Eyewires / Perimeter) get a ramped
    lead-in over the stepdown instead of a straight slot-plunge.
    """
    contour_ops = {"Eyewires", "Perimeter"}
    post.header(side)
    post.spindle_on()
    for op in ops:
        post.comment(f"--- {op.name} ---")
        ramp = contour_stepdown_mm if op.name in contour_ops else 0.0
        for path in op.paths:
            post.emit_polyline(path, arc_tol=arc_tol_mm, ramp_height=ramp)
        post.safe_retract()
    post.end_program()
