"""Playback from the full posted motion — animate the retracts (BUILDPLAN M8 Part B).

The cut-path playback used to drop rapids (cutting moves only), so it never showed
the tool retracting and its duration under-represented the real cycle. Now it is
built from the posted program's FULL motion: rapids are kept (the tool animates the
lift / traverse / descend) but flagged so they remove no material, and each run is
densified by time so rapids play back fast.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "tests" / "fixtures" / "demo"
CONFIG = ROOT / "src" / "guildmodel" / "config"


@pytest.fixture(scope="module")
def posted():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.relief.castle import build_castle_relief, stock_top_heightfield
    from guildmodel.core.cam.castle_ops import (
        generate_castle_program, write_castle_program, work_holding_keepouts)
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import CastleParams, CastleCamParams

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle, cam = CastleParams(), CastleCamParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.4)
    f = relief.field
    tools = yaml.safe_load((CONFIG / "tools.yaml").read_text(encoding="utf-8"))
    ops = generate_castle_program(relief, castle, hinges, tools["flat_3175"])
    top = castle.stock.total_pad_height_mm
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=3.175,
                    spindle_rpm=10000, feed_rate_mmpm=750, plunge_rate_mmpm=333,
                    safe_z_mm=top + 5, feed_plane_mm=top + 1)
    post.link_clearance_z_mm = top + cam.link_clearance_mm
    post.link_keepouts = tuple(work_holding_keepouts(relief.partition.body, castle.stock, 3.175 / 2))
    write_castle_program(ops, post)
    stock = stock_top_heightfield(castle.stock, resolution=f.resolution,
                                  origin=f.origin, shape=f.z.shape)
    return post.to_string(), tools, f, stock, top


def test_motion_runs_keep_rapids():
    from guildmodel.core.sim.paths import motion_runs_from_program
    gcode = ("; --- Rough Relief ---\nG0 Z11.5\nG0 X10 Y0\nG1 Z1 F750\n"
             "G1 X20 Y0 F750\nG0 Z11.5\nG0 X30 Y0\nG1 Z1 F750\nG1 X40 Y0 F750\n")
    runs = motion_runs_from_program(gcode)
    assert any(is_cut for *_, is_cut in runs)          # feeds kept
    assert any(not is_cut for *_, is_cut in runs)      # rapids kept (were dropped before)
    assert all(r[0] == "Rough Relief" for r in runs)   # op label tracked from the comment


def test_rapids_animate_but_carve_nothing(posted):
    from guildmodel.core.sim import (
        ToolProfile, build_removal_plan, motion_steps_from_program)
    from guildmodel.core.sim.playback import plan_floor_to
    gcode, tools, f, stock, top = posted
    prof = ToolProfile.from_tool(tools["flat_3175"])
    profs = {n: ToolProfile.from_tool(c) for n, c in tools.items()}
    steps = motion_steps_from_program(gcode, prof, profiles=profs,
                                      rapid_mmpm=3000, feed_mmpm=750, base_spacing=f.resolution)
    plan = build_removal_plan(steps, stock.z, f.origin, f.resolution)

    # the playback includes rapid segments and the tool rises to the retract heights
    assert any(not c for c in plan.seg_cut), "no rapid segments in the playback"
    rapid_idx = [i for i, c in enumerate(plan.seg_cut) if not c]
    rapid_z = np.concatenate(
        [plan.positions[plan.seg_bounds[i]:plan.seg_bounds[i + 1], 2] for i in rapid_idx])
    assert rapid_z.max() >= top + 1.0                  # retracts are animated

    # rapids remove NO material: the final floor equals the cuts-only floor
    cuts_only = build_removal_plan([s for s in steps if s[3]], stock.z, f.origin, f.resolution)
    assert np.array_equal(plan_floor_to(plan, plan.n_positions),
                          plan_floor_to(cuts_only, cuts_only.n_positions))


def test_rapids_are_time_weighted_fast(posted):
    """A rapid covers more distance per frame than a cut (it plays back faster)."""
    from guildmodel.core.sim import ToolProfile, motion_steps_from_program
    gcode, tools, f, stock, top = posted
    prof = ToolProfile.from_tool(tools["flat_3175"])
    steps = motion_steps_from_program(gcode, prof, rapid_mmpm=3000, feed_mmpm=750,
                                      base_spacing=0.4)
    cut_sp = next(s[4] for s in steps if s[3])
    rapid_sp = next(s[4] for s in steps if not s[3])
    assert rapid_sp == pytest.approx(0.4 * 3000 / 750)   # 4x coarser
    assert rapid_sp > cut_sp
