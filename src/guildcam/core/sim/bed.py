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
