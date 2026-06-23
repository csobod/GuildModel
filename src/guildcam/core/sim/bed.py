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
reuses the proven per-component sim verbatim. (Rapids between parts are excluded
from the sim, as everywhere; rotation defaults to 0 in the nest, so placement is a
pure translation.)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .report import CutReport, verify
from .toolsim import ToolProfile, achieved_floor_grouped
from .paths import cutting_paths_from_program_grouped
from .playback import RemovalPlayback, simulate_removal, tool_radius_below


@dataclass
class ComponentSim:
    """One nested component's cut sim in its own design frame, plus the rigid
    placement (dx, dy) that puts it on the bed (machine coordinates)."""
    floor: np.ndarray            # achieved floor (design grid)
    target: np.ndarray           # intended surface; NaN outside the body / openings
    inside: np.ndarray           # body mask
    origin: tuple[float, float]  # design-frame XY of cell [0, 0]
    resolution: float
    dx: float = 0.0              # placement translation onto the bed
    dy: float = 0.0
    label: str = ""
    kind: str = ""


def simulate_component(
    spec: dict,
    *,
    cam,
    tools_cfg: dict,
    mats_cfg: dict,
    material_name: str = "acetate",
    resolution: float = 0.4,
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

    mat = mats_cfg.get(material_name.split()[0].lower(), mats_cfg["acetate"])
    mode = spec["mode"]
    if mode == "castle":
        from ..relief.castle import build_castle_relief
        castle, hinge = spec["castle"], spec["hinge"]
        tool = resolve_tool(cam.tool_name, tools_cfg, tools_cfg.get("flat_3175"))
        relief = build_castle_relief(spec["partition"], castle, hinge,
                                     resolution=resolution, progress=progress)
        ops = generate_castle_program(relief, castle, hinge, tool,
                                      params=cam, tools_cfg=tools_cfg)
        contour_names, drill_names = {"Eyewires", "Perimeter"}, set()
        top_z, peck, fallback = castle.stock.total_pad_height_mm, 1.5, tool
        init_z = top_z + 1.0
    elif mode == "temple":
        from ..relief.flat import build_temple_relief
        from ..cam.temple_ops import TEMPLE_CONTOUR_OPS, generate_temple_program
        t = spec["temple"]
        relief = build_temple_relief(spec["outline"], t, spec["hinge"], spec["engraving"],
                                     resolution=resolution, progress=progress)
        ops = generate_temple_program(spec["outline"], spec["engraving"], t, tools_cfg, cam,
                                      hinge_polys=spec["hinge"])
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

    tool_settings, _ = build_tool_settings(
        ops, tools_cfg, default_feed=mat["feed_rate_mmpm"],
        default_plunge=mat["plunge_rate_mmpm"], default_spindle=mat["spindle_rpm"])
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
    placement is a pure translation by (dx, dy). On the rare overlap the first
    component wins. Returns a `CutReport` the GUI renders via `show_report`.
    """
    ox, oy = bed_origin
    width, height = work_area
    cols = max(1, int(round(width / resolution)))
    rows = max(1, int(round(height / resolution)))
    bed_target = np.full((rows, cols), np.nan)
    bed_inside = np.zeros((rows, cols), dtype=bool)
    bed_floor = np.full((rows, cols), np.nan)

    for c in comps:
        crows, ccols = c.inside.shape
        coff = int(round((c.origin[0] + c.dx - ox) / resolution))
        roff = int(round((c.origin[1] + c.dy - oy) / resolution))
        r0, c0 = max(0, roff), max(0, coff)
        r1, c1 = min(rows, roff + crows), min(cols, coff + ccols)
        if r0 >= r1 or c0 >= c1:
            continue
        sr0, sc0 = r0 - roff, c0 - coff
        src = (slice(sr0, sr0 + (r1 - r0)), slice(sc0, sc0 + (c1 - c0)))
        dst = (slice(r0, r1), slice(c0, c1))
        place = c.inside[src] & ~bed_inside[dst]      # first component wins on overlap
        bed_inside[dst] |= c.inside[src]
        bt, bf = bed_target[dst], bed_floor[dst]
        bt[place] = c.target[src][place]
        bf[place] = c.floor[src][place]
        bed_target[dst], bed_floor[dst] = bt, bf

    # verify needs a finite floor where valid; cells outside the body are excluded.
    floor = np.where(np.isfinite(bed_floor), bed_floor, 0.0)
    return verify(floor, bed_target, bed_inside, bed_origin, resolution,
                  partition=None, complete_tol_mm=complete_tol_mm)


# ------------------------------------------------------------------ M7.12.3 bed removal

@dataclass
class BedRemovalPart:
    """One placed part for the volumetric bed sim (BUILDPLAN M7.12.3): its
    **machine-coordinate** cut steps (from the nest placement's ops) plus its stock
    heightfield in the **design** grid and the placement offset onto the bed."""
    steps: list                  # [(label, ToolProfile, paths in machine coords)]
    stock_top: np.ndarray        # design-frame stock heightfield
    origin: tuple                # design-frame origin of stock_top
    dx: float = 0.0
    dy: float = 0.0


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

    x0s, y0s, x1s, y1s = [], [], [], []
    for p in parts:
        srows, scols = p.stock_top.shape
        mx, my = p.origin[0] + p.dx, p.origin[1] + p.dy
        x0s.append(mx); y0s.append(my)
        x1s.append(mx + scols * resolution); y1s.append(my + srows * resolution)
    bed_ox, bed_oy = min(x0s) - margin_mm, min(y0s) - margin_mm
    cols = max(1, int(round((max(x1s) + margin_mm - bed_ox) / resolution)))
    rows = max(1, int(round((max(y1s) + margin_mm - bed_oy) / resolution)))

    bed_stock = np.zeros((rows, cols), dtype=np.float64)
    for p in parts:
        srows, scols = p.stock_top.shape
        coff = int(round((p.origin[0] + p.dx - bed_ox) / resolution))
        roff = int(round((p.origin[1] + p.dy - bed_oy) / resolution))
        r0, c0 = max(0, roff), max(0, coff)
        r1, c1 = min(rows, roff + srows), min(cols, coff + scols)
        if r0 >= r1 or c0 >= c1:
            continue
        sr0, sc0 = r0 - roff, c0 - coff
        bed_stock[r0:r1, c0:c1] = np.maximum(
            bed_stock[r0:r1, c0:c1],
            p.stock_top[sr0:sr0 + (r1 - r0), sc0:sc0 + (c1 - c0)])

    all_steps = _schedule_step_order(parts)
    return simulate_removal(all_steps, bed_stock, (bed_ox, bed_oy), resolution,
                            frames=frames)


def _schedule_step_order(parts: list) -> list:
    """Order every part's steps to minimise tool changes — the same greedy strategy
    as `cam.layout.schedule_bed_ops` (BUILDPLAN M6.5), keyed by the tool **profile**:
    stay on the current tool while any ready step needs it, else switch to the ready
    tool with the fewest remaining steps (front-loading the rare tools), keeping each
    part's internal order. So the bed SIM plays in the tool-grouped order the
    worktable.nc actually runs — all same-tool ops at once — not part by part.
    """
    def key(step):                      # step = (label, ToolProfile, paths)
        p = step[1]
        return (p.kind, round(p.radius_mm, 4), round(p.corner_radius_mm, 4),
                round(p.included_angle_deg, 4))

    seqs = [list(p.steps) for p in parts]
    pointers = [0] * len(seqs)
    remaining: dict = {}
    for s in seqs:
        for st in s:
            remaining[key(st)] = remaining.get(key(st), 0) + 1

    out: list = []
    current = None
    while any(pointers[i] < len(seqs[i]) for i in range(len(seqs))):
        rdy = [(i, seqs[i][pointers[i]])
               for i in range(len(seqs)) if pointers[i] < len(seqs[i])]
        same = [(i, st) for i, st in rdy if key(st) == current]
        if same:
            i, st = same[0]
        else:
            current = min({key(st) for _, st in rdy}, key=lambda t: remaining.get(t, 0))
            i, st = next((i, st) for i, st in rdy if key(st) == current)
        out.append(st)
        remaining[key(st)] -= 1
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
