"""Whole-bed cut simulation (BUILDPLAN M7.7).

Simulate the machined result of a whole nested worktable: build each placed
component's single-part cut sim (relief target + achieved floor, reusing the M5/M7
per-component machinery), then **composite** them onto one machine-coordinate bed
grid at their placement offsets and `verify` completeness / gouge across the bed.

Why compositing per-component sims equals simulating the combined ``worktable.nc``:
the nested components are spatially **disjoint**, and the combined program is the
per-component ops **reordered** (M7.7 `build_nest_program`) — and the achieved floor
is order-independent (a per-cell *min* over swept points). So the bed's achieved
floor is exactly the union of each component's floor in its own region, and this
reuses the proven per-component sim verbatim. Rapids between parts are excluded
from the sim, as everywhere.

A placement is the affine ``p ↦ R(θ)·p + (dx, dy)`` from the part's design frame
(`cam.layout.BedPlacement`), and the composite applies the same map to the
heightfields (`placed_fields`, BUILDPLAN M19): the exact `np.rot90` for a quarter
turn, a resampling for any other angle. Until M19 only the translation was
applied, while the steps came from the rotated ops, so a left temple nested at
its 180° default was verified against a floor that faced the other way; the
comment here that "rotation defaults to 0 in the nest" had been false since
that default was seeded.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .report import CutReport, verify
from .toolsim import ToolProfile, achieved_floor_grouped
from .paths import cutting_paths_from_program_grouped
from .playback import (
    RemovalPlan, RemovalPlayback, build_removal_plan, simulate_removal, tool_radius_below,
)


@dataclass
class ComponentSim:
    """One nested component's cut sim in its own design frame, plus the rigid
    placement — a rotation about the design origin, then (dx, dy) — that puts
    it on the bed (machine coordinates)."""
    floor: np.ndarray            # achieved floor (design grid)
    target: np.ndarray           # intended surface; NaN outside the body / openings
    inside: np.ndarray           # body mask
    origin: tuple[float, float]  # design-frame XY of cell [0, 0]
    resolution: float
    dx: float = 0.0              # placement translation onto the bed
    dy: float = 0.0
    label: str = ""
    kind: str = ""
    rotation_deg: float = 0.0    # placement rotation, applied before the translation


# ------------------------------------------------------------------ M19 placement

def placed_fields(
    fields: list, origin: tuple[float, float], resolution: float,
    dx: float, dy: float, rotation_deg: float, *, kinds: tuple,
) -> tuple[list, tuple[float, float]]:
    """Design-frame grids under the placement ``p ↦ R(θ)·p + (dx, dy)``.

    Returns ``(fields', (mx, my))``: the same grids seen from the machine frame,
    and the machine XY of their cell ``[0, 0]``, so a caller stamps them onto the
    bed by translation alone, as it always did. ``kinds`` names each field:

    * ``"height"`` — a surface (the floor): bilinear, edge-clamped;
    * ``"target"`` — a surface that is NaN off the body: filled from its nearest
      valid cell before sampling, then NaN again wherever the ``"mask"`` is off;
    * ``"mask"`` — the body (bool): nearest neighbor, off outside the grid;
    * ``"stock"`` — a stock top: bilinear, zero (no stock) outside the grid.

    A grid cell owns the half cell around its sample, so the mask and the stock
    extend half a cell past the last sample (`scipy`'s ``grid-constant``; its
    ``constant`` stops at the sample and loses a half cell all round, measured
    2026-10-14 as 39 × 11 of a 40 × 12 blank).

    θ = 0 returns the grids themselves and ``origin + (dx, dy)``, bit for bit the
    translation this was before M19. A quarter turn is `np.rot90`, exact. Any
    other angle is resampled with `scipy.ndimage.map_coordinates` onto a lattice
    of the same pitch aligned with the machine grid, so the result is within a
    cell of a direct stamp of the rotated ops (`tests/test_bed_sim_rotation_m19`).
    """
    th = float(rotation_deg) % 360.0
    if th < 1e-9 or 360.0 - th < 1e-9:
        return list(fields), (origin[0] + dx, origin[1] + dy)
    quarter = th / 90.0
    if abs(quarter - round(quarter)) < 1e-9:
        return _rot90_fields(fields, origin, resolution, dx, dy, int(round(quarter)) % 4)
    return _resample_fields(fields, origin, resolution, dx, dy, th, kinds=kinds)


def _placed_center(origin, shape, resolution, dx, dy, th_deg):
    """The design lattice's center (its cell centers' mean) and that point under
    the placement — the point the rotated grid is laid out about."""
    rows, cols = shape
    cx = origin[0] + (cols - 1) / 2.0 * resolution
    cy = origin[1] + (rows - 1) / 2.0 * resolution
    c, s = math.cos(math.radians(th_deg)), math.sin(math.radians(th_deg))
    return (cx, cy), (c * cx - s * cy + dx, s * cx + c * cy + dy), (c, s)


def _rot90_fields(fields, origin, resolution, dx, dy, k):
    """A quarter turn, exact. Row index runs with +y here, so a counter-clockwise
    turn of the part is `np.rot90` with a negative ``k``."""
    _, (mcx, mcy), _ = _placed_center(origin, fields[0].shape, resolution, dx, dy, 90.0 * k)
    out = [np.rot90(f, -k) for f in fields]
    orows, ocols = out[0].shape
    return out, (mcx - (ocols - 1) / 2.0 * resolution,
                 mcy - (orows - 1) / 2.0 * resolution)


def _resample_fields(fields, origin, resolution, dx, dy, th_deg, *, kinds):
    """Any angle: a machine-aligned lattice over the rotated footprint, each cell
    sampled back in the design grid through the inverse placement."""
    from scipy.ndimage import distance_transform_edt, map_coordinates

    rows, cols = fields[0].shape
    _, (mcx, mcy), (c, s) = _placed_center(origin, (rows, cols), resolution, dx, dy, th_deg)
    hw, hh = (cols - 1) / 2.0 * resolution, (rows - 1) / 2.0 * resolution
    corners = np.array([[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]])
    rot = corners @ np.array([[c, -s], [s, c]]).T
    x0 = math.floor((mcx + rot[:, 0].min()) / resolution) * resolution
    y0 = math.floor((mcy + rot[:, 1].min()) / resolution) * resolution
    x1 = math.ceil((mcx + rot[:, 0].max()) / resolution) * resolution
    y1 = math.ceil((mcy + rot[:, 1].max()) / resolution) * resolution
    ocols = int(round((x1 - x0) / resolution)) + 1
    orows = int(round((y1 - y0) / resolution)) + 1
    jj, ii = np.meshgrid(np.arange(ocols), np.arange(orows))
    qx = x0 + jj * resolution - mcx          # machine cell centers, about the placed center
    qy = y0 + ii * resolution - mcy
    px = c * qx + s * qy                     # inverse rotation → design offsets
    py = -s * qx + c * qy
    coords = [(py + hh) / resolution, (px + hw) / resolution]   # [row, col]

    out: list = [None] * len(fields)
    mask = None
    for i, (f, kind) in enumerate(zip(fields, kinds)):
        if kind == "mask":
            mask = map_coordinates(np.asarray(f, dtype=np.uint8), coords, order=0,
                                   mode="grid-constant", cval=0).astype(bool)
            out[i] = mask
    for i, (f, kind) in enumerate(zip(fields, kinds)):
        f = np.asarray(f, dtype=np.float64)
        if kind == "mask":
            continue
        if kind == "height":
            out[i] = map_coordinates(f, coords, order=1, mode="nearest")
        elif kind == "stock":
            out[i] = map_coordinates(f, coords, order=1, mode="grid-constant", cval=0.0)
        elif kind == "target":
            valid = np.isfinite(f)
            if valid.all():
                filled = f
            elif not valid.any():
                filled = np.zeros_like(f)
            else:
                _, (ri, ci) = distance_transform_edt(~valid, return_indices=True)
                filled = f[ri, ci]
            t = map_coordinates(filled, coords, order=1, mode="nearest")
            out[i] = np.where(mask, t, np.nan) if mask is not None else t
        else:
            raise ValueError(f"unknown field kind {kind!r}")
    return out, (x0, y0)


def flat_blank_heightfield(length_mm: float, width_mm: float, top_mm: float,
                           resolution: float) -> tuple[np.ndarray, tuple[float, float]]:
    """A single-level blank (a temple's, a block's) centered on the design
    origin: the heightfield and the XY of its cell ``[0, 0]``. The stock a
    simulation carves is the blank as listed, not the relief grid cropped to
    the cut (session two of M20)."""
    cols = max(1, int(round(length_mm / resolution)))
    rows = max(1, int(round(width_mm / resolution)))
    return (np.full((rows, cols), float(top_mm), dtype=np.float64),
            (-length_mm / 2.0, -width_mm / 2.0))


def relief_for_spec(spec: dict, *, resolution: float, kernel: str = "raster", progress=None):
    """The part's relief in its design frame — the target the bed verdict
    compares the posted program against (M20 session two). The castle relief
    is what `PartsWorker` builds to generate the front's ops, so a caller with
    that in hand passes it instead of calling this."""
    mode = spec["mode"]
    if mode == "castle":
        from ..zmap import castle_relief
        return castle_relief(spec["partition"], spec["castle"], spec["hinge"],
                             kernel=kernel, resolution=resolution, progress=progress)
    if mode == "temple":
        from ..relief.flat import (
            build_temple_relief, place_temple_curves, place_temple_on_blank)
        t = spec["temple"]
        outline, hinge, engraving = place_temple_on_blank(
            spec["outline"], spec["hinge"], spec["engraving"], t.blank_length_mm,
            stock_side=t.stock_side, snap=t.snap_to_blank_end,
            origin_from_drawing=t.origin_from_drawing)
        graphics = place_temple_curves(
            spec.get("graphics", ()), spec["outline"], spec["hinge"],
            t.blank_length_mm, stock_side=t.stock_side, snap=t.snap_to_blank_end,
            origin_from_drawing=t.origin_from_drawing)
        return build_temple_relief(outline, t, hinge, engraving,
                                   graphic_curves=graphics,
                                   resolution=resolution, progress=progress)
    from ..relief.flat import build_block_relief
    return build_block_relief(spec["lens"], spec["block"], resolution=resolution,
                              progress=progress)


def stock_for_spec(spec: dict, resolution: float) -> tuple[np.ndarray, tuple[float, float]]:
    """The part's blank as listed — its full size, the front's pad block on it —
    centered on the design origin, at `resolution`: ``(heightfield, origin)``."""
    mode = spec["mode"]
    if mode == "castle":
        from ..relief.castle import stock_top_heightfield
        hf = stock_top_heightfield(spec["castle"].stock, resolution=resolution)
        return hf.z, hf.origin
    if mode == "temple":
        t = spec["temple"]
        return flat_blank_heightfield(t.blank_length_mm, t.blank_width_mm,
                                      t.blank_thickness_mm, resolution)
    b = spec["block"]
    return flat_blank_heightfield(b.blank_length_mm, b.blank_width_mm,
                                  b.blank_thickness_mm, resolution)


def simulate_component(
    spec: dict,
    *,
    cam,
    tools_cfg: dict,
    mats_cfg: dict,
    material_name: str = "acetate",
    resolution: float = 0.4,
    kernel: str = "raster",
    progress=None,
):
    """Build one component's relief + posted program and sweep the tools → its
    achieved floor and target surface (BUILDPLAN M5/M7).

    `spec` is a build description (the same shape the GUI nests from): a ``mode``
    of ``castle`` / ``temple`` / ``block`` plus that mode's geometry + params.
    Returns ``(floor, target, inside, origin, resolution)`` — the target carries
    NaN outside the body / openings, like the per-component sims.
    """
    from ..cam.castle_ops import (
        build_tool_settings, generate_castle_program, resolve_tool, write_castle_program,
    )
    from ..post.grbl import GRBLPost

    key = (material_name.split() or ["acetate"])[0].lower()
    mat = mats_cfg.get(key, mats_cfg["acetate"])
    mode = spec["mode"]
    if mode == "castle":
        from ..cam.component import CASTLE_CONTOUR_OPS
        from ..zmap import castle_relief
        castle, hinge = spec["castle"], spec["hinge"]
        tool = resolve_tool(cam.tool_name, tools_cfg, tools_cfg.get("flat_3175"))
        relief = castle_relief(spec["partition"], castle, hinge, kernel=kernel,
                               resolution=resolution, progress=progress)
        ops = generate_castle_program(relief, castle, hinge, tool,
                                      params=cam, tools_cfg=tools_cfg)
        contour_names, drill_names = set(CASTLE_CONTOUR_OPS), set()
        top_z, peck, fallback = castle.stock.total_pad_height_mm, 1.5, tool
        init_z = top_z + 1.0
    elif mode == "temple":
        from ..relief.flat import (
            build_temple_relief, place_temple_curves, place_temple_on_blank)
        from ..cam.temple_ops import TEMPLE_CONTOUR_OPS, generate_temple_program
        t = spec["temple"]
        # Snap onto the blank FIRST (M11 stock-side), matching the generators the
        # nest placed — otherwise a snapped temple's floor stamps onto the bed at
        # its un-snapped design position and misses its placement.
        outline, hinge, engraving = place_temple_on_blank(
            spec["outline"], spec["hinge"], spec["engraving"], t.blank_length_mm,
            stock_side=t.stock_side, snap=t.snap_to_blank_end,
            origin_from_drawing=t.origin_from_drawing)
        graphics = place_temple_curves(
            spec.get("graphics", ()), spec["outline"], spec["hinge"],
            t.blank_length_mm, stock_side=t.stock_side, snap=t.snap_to_blank_end,
            origin_from_drawing=t.origin_from_drawing)
        relief = build_temple_relief(outline, t, hinge, engraving,
                                     graphic_curves=graphics,
                                     resolution=resolution, progress=progress)
        ops = generate_temple_program(outline, engraving, t, tools_cfg, cam,
                                      hinge_polys=hinge, graphic_curves=graphics)
        contour_names, drill_names = set(TEMPLE_CONTOUR_OPS), set()
        top_z, peck = t.blank_thickness_mm, 1.5
        fallback, init_z = resolve_tool(t.profile_tool, tools_cfg), t.blank_thickness_mm
    else:  # block
        from ..relief.flat import build_block_relief
        from ..cam.block_ops import (
            BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
        )
        b = spec["block"]
        relief = build_block_relief(spec["lens"], b, resolution=resolution, progress=progress)
        ops = generate_block_program(spec["lens"], b, tools_cfg, cam)
        contour_names, drill_names = set(BLOCK_CONTOUR_OPS), set(BLOCK_DRILL_OPS)
        top_z, peck = b.blank_thickness_mm, b.peck_depth_mm
        fallback, init_z = resolve_tool(b.profile_tool, tools_cfg), b.blank_thickness_mm

    # The component's own feeds (its clamp: the Cut tab's material row, else the
    # preset) and its per-tool settings, as the posting paths resolve them.
    tool_settings, _ = build_tool_settings(
        ops, tools_cfg,
        default_feed=cam.feed_rate_mmpm or mat["feed_rate_mmpm"],
        default_plunge=cam.plunge_rate_mmpm or mat["plunge_rate_mmpm"],
        default_spindle=cam.spindle_rpm or mat["spindle_rpm"],
        tool_feeds=getattr(cam, "tool_feeds", None))
    first = tool_settings[ops[0].tool_name]
    post = GRBLPost(
        job_name="sim", material=material_name,
        tool_diameter_mm=first.diameter_mm, spindle_rpm=first.spindle_rpm,
        feed_rate_mmpm=first.feed_rate_mmpm, plunge_rate_mmpm=first.plunge_rate_mmpm,
        safe_z_mm=top_z + cam.safe_z_clearance_mm)
    write_castle_program(
        ops, post, arc_tol_mm=cam.arc_tolerance_mm,
        contour_stepdown_mm=cam.contour_stepdown_mm,
        contour_ramp_angle_deg=cam.contour_ramp_angle_deg,
        contour_lead_in=cam.contour_lead_in,
        tool_settings=tool_settings, contour_op_names=contour_names,
        drill_op_names=drill_names, peck_depth_mm=peck)

    f = relief.field
    groups = cutting_paths_from_program_grouped(post.to_string())
    profiles = {n: ToolProfile.from_tool(tools_cfg[n])
                for n in {t for _, t in groups if t and t in tools_cfg}}
    floor = achieved_floor_grouped(
        groups, profiles, ToolProfile.from_tool(fallback),
        f.origin, f.z.shape, f.resolution, init_z)
    target = np.where(relief.inside, f.z, np.nan)
    return floor, target, relief.inside, f.origin, f.resolution


def composite_bed_report(
    comps: list[ComponentSim],
    work_area: tuple[float, float],
    *,
    resolution: float,
    bed_origin: tuple[float, float] = (0.0, 0.0),
    complete_tol_mm: float = 0.5,
) -> CutReport:
    """Stamp each component's (floor, target, inside) onto one bed grid at its
    placement offset and `verify` the whole worktable.

    All components must share the bed `resolution` (the caller builds them at it);
    each is rotated and translated by its placement (`placed_fields`, M19). On the
    rare overlap the first component wins. Returns a `CutReport` the GUI renders
    via `show_report`.
    """
    ox, oy = bed_origin
    width, height = work_area
    cols = max(1, int(round(width / resolution)))
    rows = max(1, int(round(height / resolution)))
    bed_target = np.full((rows, cols), np.nan)
    bed_inside = np.zeros((rows, cols), dtype=bool)
    bed_floor = np.full((rows, cols), np.nan)

    for c in comps:
        (floor_c, target_c, inside_c), (mx, my) = placed_fields(
            [c.floor, c.target, c.inside], c.origin, resolution, c.dx, c.dy,
            c.rotation_deg, kinds=("height", "target", "mask"))
        crows, ccols = inside_c.shape
        coff = int(round((mx - ox) / resolution))
        roff = int(round((my - oy) / resolution))
        r0, c0 = max(0, roff), max(0, coff)
        r1, c1 = min(rows, roff + crows), min(cols, coff + ccols)
        if r0 >= r1 or c0 >= c1:
            continue
        sr0, sc0 = r0 - roff, c0 - coff
        src = (slice(sr0, sr0 + (r1 - r0)), slice(sc0, sc0 + (c1 - c0)))
        dst = (slice(r0, r1), slice(c0, c1))
        place = inside_c[src] & ~bed_inside[dst]      # first component wins on overlap
        bed_inside[dst] |= inside_c[src]
        bt, bf = bed_target[dst], bed_floor[dst]
        bt[place] = target_c[src][place]
        bf[place] = floor_c[src][place]
        bed_target[dst], bed_floor[dst] = bt, bf

    # verify needs a finite floor where valid; cells outside the body are excluded.
    floor = np.where(np.isfinite(bed_floor), bed_floor, 0.0)
    return verify(floor, bed_target, bed_inside, bed_origin, resolution,
                  partition=None, complete_tol_mm=complete_tol_mm)


def composite_bed_targets(comps: list, bed_origin: tuple[float, float],
                          shape: tuple[int, int], resolution: float):
    """Every component's (target, inside) under its placement onto one bed
    grid: ``(bed_target, bed_inside)``. The first component wins an overlap."""
    rows, cols = shape
    ox, oy = bed_origin
    bed_target = np.full((rows, cols), np.nan)
    bed_inside = np.zeros((rows, cols), dtype=bool)
    for c in comps:
        (target_c, inside_c), (mx, my) = placed_fields(
            [c.target, c.inside], c.origin, resolution, c.dx, c.dy,
            c.rotation_deg, kinds=("target", "mask"))
        crows, ccols = inside_c.shape
        coff = int(round((mx - ox) / resolution))
        roff = int(round((my - oy) / resolution))
        r0, c0 = max(0, roff), max(0, coff)
        r1, c1 = min(rows, roff + crows), min(cols, coff + ccols)
        if r0 >= r1 or c0 >= c1:
            continue
        sr0, sc0 = r0 - roff, c0 - coff
        src = (slice(sr0, sr0 + (r1 - r0)), slice(sc0, sc0 + (c1 - c0)))
        dst = (slice(r0, r1), slice(c0, c1))
        place = inside_c[src] & ~bed_inside[dst]
        bed_inside[dst] |= inside_c[src]
        bt = bed_target[dst]
        bt[place] = target_c[src][place]
        bed_target[dst] = bt
    return bed_target, bed_inside


def bed_report_from_program(
    program_text: str,
    comps: list,
    stock_parts: list,
    *,
    resolution: float,
    tools_cfg: dict,
    fallback: ToolProfile,
    margin_mm: float = 8.0,
    complete_tol_mm: float = 0.5,
    progress=None,
) -> CutReport:
    """The whole-bed verdict read from the POSTED program (M20 session two).

    The program is the contract and the simulator its reader: ``worktable.nc``'s
    cutting moves, grouped by tool, are stamped onto one machine-coordinate grid
    — cropped to the placed blanks plus a margin, each cell starting at its own
    blank's top — and compared with the targets composited from every part's
    relief under its placement. Nothing is regenerated: the reliefs come from
    Generate's cache (the front) or a flat build (temples, blocks), and the
    paths from the file the machine will run.
    """
    bed_stock, bed_origin = _bed_stock(stock_parts, resolution, margin_mm)
    groups = cutting_paths_from_program_grouped(program_text)
    profiles = {n: ToolProfile.from_tool(tools_cfg[n])
                for n in {t for _, t in groups if t and t in tools_cfg}}
    floor = achieved_floor_grouped(groups, profiles, fallback, bed_origin,
                                   bed_stock.shape, resolution, bed_stock,
                                   progress=progress)
    bed_target, bed_inside = composite_bed_targets(comps, bed_origin, bed_stock.shape,
                                                   resolution)
    return verify(floor, bed_target, bed_inside, bed_origin, resolution,
                  partition=None, complete_tol_mm=complete_tol_mm)


# ------------------------------------------------------------------ M7.12.3 bed removal

@dataclass
class BedRemovalPart:
    """One placed part for the volumetric bed sim (BUILDPLAN M7.12.3): its
    **machine-coordinate** cut steps (from the nest placement's ops) plus its stock
    heightfield in the **design** grid and the placement that puts it on the bed
    (a rotation about the design origin, then the offset)."""
    steps: list                  # [(label, ToolProfile, paths in machine coords)]
    stock_top: np.ndarray        # design-frame stock heightfield
    origin: tuple                # design-frame origin of stock_top
    dx: float = 0.0
    dy: float = 0.0
    rotation_deg: float = 0.0


def simulate_bed_removal(
    parts: list,
    *,
    resolution: float,
    margin_mm: float = 8.0,
    frames: int = 60,
) -> RemovalPlayback:
    """Volumetric removal for a whole nested bed (BUILDPLAN M7.12.3).

    Stamps every part's stock onto ONE machine-coordinate grid — auto-cropped to
    the parts' footprint + a margin, so an empty 300×200 bed costs no memory — then
    carves the combined machine-coordinate steps part by part with
    :func:`simulate_removal`. Parts are spatially disjoint, so the order-independent
    per-cell min holds (the same argument as :func:`composite_bed_report`). The
    returned playback's ``origin`` is the cropped bed corner, so the GUI renders the
    block at the right machine position.
    """
    if not parts:
        return simulate_removal([], np.zeros((1, 1)), (0.0, 0.0), resolution, frames=1)
    bed_stock, bed_origin = _bed_stock(parts, resolution, margin_mm)
    return simulate_removal(_schedule_step_order(parts), bed_stock, bed_origin,
                            resolution, frames=frames)


def _bed_stock(parts: list, resolution: float, margin_mm: float):
    """The cropped bed stock heightfield + its machine-coord origin (shared by the
    frame-based bed sim and the position-based plan)."""
    placed = []                       # (stock as seen from the machine, its origin)
    x0s, y0s, x1s, y1s = [], [], [], []
    for p in parts:
        (stock,), (mx, my) = placed_fields(
            [p.stock_top], p.origin, resolution, p.dx, p.dy,
            getattr(p, "rotation_deg", 0.0), kinds=("stock",))
        placed.append((stock, mx, my))
        srows, scols = stock.shape
        x0s.append(mx); y0s.append(my)
        x1s.append(mx + scols * resolution); y1s.append(my + srows * resolution)
    bed_ox, bed_oy = min(x0s) - margin_mm, min(y0s) - margin_mm
    cols = max(1, int(round((max(x1s) + margin_mm - bed_ox) / resolution)))
    rows = max(1, int(round((max(y1s) + margin_mm - bed_oy) / resolution)))

    bed_stock = np.zeros((rows, cols), dtype=np.float64)
    for stock, mx, my in placed:
        srows, scols = stock.shape
        coff = int(round((mx - bed_ox) / resolution))
        roff = int(round((my - bed_oy) / resolution))
        r0, c0 = max(0, roff), max(0, coff)
        r1, c1 = min(rows, roff + srows), min(cols, coff + scols)
        if r0 >= r1 or c0 >= c1:
            continue
        sr0, sc0 = r0 - roff, c0 - coff
        bed_stock[r0:r1, c0:c1] = np.maximum(
            bed_stock[r0:r1, c0:c1],
            stock[sr0:sr0 + (r1 - r0), sc0:sc0 + (c1 - c0)])
    return bed_stock, (bed_ox, bed_oy)


def build_bed_removal_plan(
    parts: list, *, resolution: float, margin_mm: float = 8.0, keyframes: int = 16,
) -> RemovalPlan:
    """Position-based whole-bed removal (BUILDPLAN M7.12): the cropped bed stock +
    the scheduled (tool-grouped) steps as a `RemovalPlan`, so the GUI drives the tool
    along its exact path in sync with the material removal."""
    if not parts:
        return build_removal_plan([], np.zeros((1, 1)), (0.0, 0.0), resolution)
    bed_stock, bed_origin = _bed_stock(parts, resolution, margin_mm)
    return build_removal_plan(_schedule_step_order(parts), bed_stock, bed_origin,
                              resolution, keyframes=keyframes)


def _schedule_step_order(parts: list) -> list:
    """Order every part's steps to minimize tool changes AND front-load the briefest
    tools — the sim mirror of `cam.layout.schedule_bed_ops` (BUILDPLAN M6.5 + operator-
    time optimization), keyed by the tool **profile**: stay on the current tool while any
    ready step needs it, else switch to the ready tool with the least TOTAL cutting length
    (so the longest-running tool finishes last, unattended), keeping each part's internal
    order. So the bed SIM plays in the exact tool-grouped order the worktable.nc runs —
    all same-tool ops at once, longest tool last — not part by part.
    """
    def key(step):                      # step = (label, ToolProfile, paths)
        p = step[1]
        return (p.kind, round(p.radius_mm, 4), round(p.corner_radius_mm, 4),
                round(p.included_angle_deg, 4))

    def step_len(step) -> float:        # 3-D cutting length of a step's paths
        total = 0.0
        for path in step[2]:
            if len(path) > 1:
                a = np.asarray(path, dtype=float)
                total += float(np.linalg.norm(np.diff(a, axis=0), axis=1).sum())
        return total

    seqs = [list(p.steps) for p in parts]
    pointers = [0] * len(seqs)
    tool_cost: dict = {}
    tool_n: dict = {}
    for s in seqs:
        for st in s:
            k = key(st)
            tool_cost[k] = tool_cost.get(k, 0.0) + step_len(st)
            tool_n[k] = tool_n.get(k, 0) + 1

    def rank(k):                        # ascending work → longest tool last
        return (tool_cost.get(k, 0.0), tool_n.get(k, 0), str(k))

    out: list = []
    current = None
    while any(pointers[i] < len(seqs[i]) for i in range(len(seqs))):
        rdy = [(i, seqs[i][pointers[i]])
               for i in range(len(seqs)) if pointers[i] < len(seqs[i])]
        same = [(i, st) for i, st in rdy if key(st) == current]
        if same:
            i, st = same[0]
        else:
            current = min({key(st) for _, st in rdy}, key=rank)
            i, st = next((i, st) for i, st in rdy if key(st) == current)
        out.append(st)
        pointers[i] += 1
    return out


def bed_collision_frames(
    cursors: list,
    frame_labels: list,
    op_tool_geom: dict,
    keep_outs: list,
    hold_down_height_mm: float = 8.0,
) -> list[bool]:
    """Per-frame hold-down collision flags for the bed sim (BUILDPLAN M7.12.3).

    `keep_outs` = ``[(cx, cy, radius)]`` in machine coordinates, each a post rising
    from the bed to `hold_down_height_mm`. A frame is flagged when the part of the
    **tool** low enough to reach that post (the widest radius within
    ``[tip_z, hold_down_height]``) overlaps the post in XY. So a tall holder won't
    flag a low screw it passes well above, and a tip cutting down beside a screw
    does — Z-aware, far less trigger-happy than a flat XY footprint.
    """
    flags: list[bool] = []
    for i in range(len(cursors)):
        cur = cursors[i]
        hit = False
        if cur is not None and cur[0] == cur[0] and cur[1] == cur[1]:   # finite (not NaN)
            label = frame_labels[i] if i < len(frame_labels) else None
            r = tool_radius_below(op_tool_geom.get(label), float(cur[2]),
                                  hold_down_height_mm)
            if r > 0.0:
                x, y = float(cur[0]), float(cur[1])
                for cx, cy, kr in keep_outs:
                    if (x - cx) ** 2 + (y - cy) ** 2 < (kr + r) ** 2:
                        hit = True
                        break
        flags.append(hit)
    return flags
