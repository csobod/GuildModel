"""Multi-tool jobs & per-operation tool assignment (BUILDPLAN M6.1).

Covers the five M6.1 deliverables:
  * per-op tool binding (schema + generation) and round-trip through `.gmodel`;
  * tool-change posting (M0/M6 blocks) that parses and lints clean;
  * tool-reach gating (warn + suggest a fitting tool);
  * the sim + cut-time model are tool-aware (a 2 mm tool reaches a pocket the
    3.175 mm bulk tool cannot; change dwell lands in the cut-time total).
"""
from pathlib import Path

import numpy as np
import pytest
import yaml
from shapely.geometry import Polygon

from guildmodel.core.project.schema import (
    CastleParams, CastleCamParams, MachineProfile, ProjectSchema, POSTERIOR_OPS,
)
from guildmodel.core.cam.castle_ops import (
    build_tool_settings, count_tool_changes, generate_castle_program,
    hinge_pocket_op, reach_warnings, resolve_tool, write_castle_program,
)
from guildmodel.core.post.grbl import GRBLPost, ToolSetting
from guildmodel.core.post.machine import lint_program
from guildmodel.core.cam.cuttime import estimate_program, MachineDynamics

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MAT = yaml.safe_load((CONFIG / "materials.yaml").read_text())["acetate"]


# ------------------------------------------------------------------ schema / config

def test_tools_yaml_has_a_small_pocket_tool():
    assert "flat_2mm" in TOOLS and TOOLS["flat_2mm"]["radius_mm"] == 1.0


def test_tool_for_op_falls_back_to_global():
    cam = CastleCamParams(tool_name="flat_3175", op_tools={"Hinge Pockets": "flat_2mm"})
    assert cam.tool_for_op("Hinge Pockets") == "flat_2mm"
    assert cam.tool_for_op("Perimeter") == "flat_3175"
    assert cam.tools_in_use() == ["flat_2mm", "flat_3175"]
    assert cam.is_multi_tool()
    assert not CastleCamParams().is_multi_tool()


def test_resolve_tool_normalizes_name_and_default():
    t = resolve_tool("flat_2mm", TOOLS)
    assert t["name"] == "flat_2mm" and t["radius_mm"] == 1.0
    # unknown name -> default
    d = resolve_tool("does_not_exist", TOOLS, default=TOOLS["flat_3175"])
    assert d is TOOLS["flat_3175"]


def test_op_tools_round_trip_through_gmodel(tmp_path):
    from guildmodel.core.project.gmodel import save_gmodel, load_gmodel
    proj = ProjectSchema(job_name="MT")
    proj.cam_params = CastleCamParams(op_tools={"Hinge Pockets": "flat_2mm"})
    path = tmp_path / "mt.gmodel"
    save_gmodel(path, project=proj, dxf_bytes=b"dxf")
    b = load_gmodel(path)
    assert b.project.cam_params.op_tools == {"Hinge Pockets": "flat_2mm"}
    assert b.project.cam_params.is_multi_tool()


# ------------------------------------------------------------------ demo fixture

@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.relief.castle import build_castle_relief

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle = CastleParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    return part, castle, relief, hinges


# ------------------------------------------------------------------ per-op binding

def test_generate_binds_per_op_tools(demo):
    part, castle, relief, hinges = demo
    cam = CastleCamParams(op_tools={"Hinge Pockets": "flat_2mm"})
    ops = generate_castle_program(
        relief, castle, hinges, TOOLS["flat_3175"], params=cam, tools_cfg=TOOLS)
    by = {op.name: op for op in ops}
    assert by["Hinge Pockets"].tool_name == "flat_2mm"
    assert by["Perimeter"].tool_name == "flat_3175"
    assert by["Fine Relief"].tool_name == "flat_3175"
    # the small pocket tool has its own (smaller) radius driving its offsets
    assert by["Hinge Pockets"].tool["radius_mm"] == 1.0
    assert count_tool_changes(ops) == 1   # small -> bulk, once


def test_single_tool_path_unchanged(demo):
    """No tools_cfg -> the legacy global tool drives every op; no per-op tool
    names, so the post emits no tool-change blocks."""
    part, castle, relief, hinges = demo
    ops = generate_castle_program(relief, castle, hinges, TOOLS["flat_3175"])
    assert all(op.tool_name is None for op in ops)   # raw dict carries no "name"
    assert count_tool_changes(ops) == 0


# ------------------------------------------------------------------ tool-change posting

def _post_multitool(ops, machine, mode="m0"):
    ts, warns = build_tool_settings(
        ops, TOOLS, default_feed=MAT["feed_rate_mmpm"],
        default_plunge=MAT["plunge_rate_mmpm"], default_spindle=MAT["spindle_rpm"],
        machine=machine)
    first = ts[ops[0].tool_name]
    post = GRBLPost("mt", "acetate", first.diameter_mm, first.spindle_rpm,
                    first.feed_rate_mmpm, first.plunge_rate_mmpm, safe_z_mm=15.0)
    write_castle_program(ops, post, tool_settings=ts, tool_change_mode=mode)
    return ts, post.to_string()


def test_tool_change_block_m0_parses_and_lints(demo):
    part, castle, relief, hinges = demo
    cam = CastleCamParams(op_tools={"Hinge Pockets": "flat_2mm"})
    ops = generate_castle_program(
        relief, castle, hinges, TOOLS["flat_3175"], params=cam, tools_cfg=TOOLS)
    machine = MachineProfile()       # guild_cnc defaults, tool_change_mode m0
    ts, text = _post_multitool(ops, machine, mode="m0")

    # exactly one change block; manual mode -> an M0 pause; spindle restarts (M3)
    assert text.count("Tool Change") == 1
    assert sum(1 for ln in text.splitlines() if ln.strip() == "M0") == 1
    assert text.count("M3 S") >= 2   # initial + after the change
    # tool numbers assigned by first appearance
    assert ts["flat_2mm"].number == 1 and ts["flat_3175"].number == 2
    # the program is ASCII below the (legacy em-dash) header banner
    assert all(ln.isascii() for ln in text.splitlines() if "GuildModel" not in ln)
    # lint clean against the machine
    assert lint_program(text, machine) == []


def test_tool_change_block_m6_emits_toolword(demo):
    part, castle, relief, hinges = demo
    cam = CastleCamParams(op_tools={"Hinge Pockets": "flat_2mm"})
    ops = generate_castle_program(
        relief, castle, hinges, TOOLS["flat_3175"], params=cam, tools_cfg=TOOLS)
    machine = MachineProfile(tool_change_mode="m6")
    _, text = _post_multitool(ops, machine, mode="m6")
    assert "M6 T2" in text
    assert all(ln.strip() != "M0" for ln in text.splitlines())  # no manual pause


def test_per_tool_feeds_applied_and_grouped(demo):
    part, castle, relief, hinges = demo
    cam = CastleCamParams(op_tools={"Hinge Pockets": "flat_2mm"})
    ops = generate_castle_program(
        relief, castle, hinges, TOOLS["flat_3175"], params=cam, tools_cfg=TOOLS)
    ts, _ = _post_multitool(ops, MachineProfile())
    # flat_2mm carries its own gentler feed override from tools.yaml
    assert ts["flat_2mm"].feed_rate_mmpm == 500.0
    assert ts["flat_2mm"].spindle_rpm == 12000
    # flat_3175 has no override -> the material feed
    assert ts["flat_3175"].feed_rate_mmpm == MAT["feed_rate_mmpm"]


def test_single_tool_posts_without_change_blocks(demo):
    part, castle, relief, hinges = demo
    ops = generate_castle_program(relief, castle, hinges, TOOLS["flat_3175"])
    post = GRBLPost("st", "acetate", 3.175, 10000, 750, 333, safe_z_mm=15.0)
    write_castle_program(ops, post)              # no tool_settings
    text = post.to_string()
    assert "Tool Change" not in text


# ------------------------------------------------------------------ cut-time dwell

def test_cuttime_charges_tool_change_dwell(demo):
    part, castle, relief, hinges = demo
    cam = CastleCamParams(op_tools={"Hinge Pockets": "flat_2mm"})
    ops = generate_castle_program(
        relief, castle, hinges, TOOLS["flat_3175"], params=cam, tools_cfg=TOOLS)
    machine = MachineProfile()
    _, text = _post_multitool(ops, machine)
    rep = estimate_program(text, MachineDynamics.from_profile(machine),
                           tool_change_seconds=machine.tool_change_seconds)
    assert rep.n_tool_changes == 1
    assert rep.tool_change_seconds == pytest.approx(machine.tool_change_seconds)
    # total = motion cycle + change dwell, and dwell is NOT folded into cycle
    assert rep.total_seconds == pytest.approx(rep.cycle_seconds + machine.tool_change_seconds)
    assert rep.total_seconds > rep.cycle_seconds


# ------------------------------------------------------------------ tool-reach gating

def _square(cx, cy, w):
    h = w / 2.0
    return Polygon([(cx - h, cy - h), (cx + h, cy - h),
                    (cx + h, cy + h), (cx - h, cy + h)])


def test_reach_warns_when_tool_too_large_and_suggests_fit():
    pocket = _square(0, 0, 2.4)               # ~2.4 mm wide pocket, inradius ~1.2
    feats = [("Hinge Pockets", "hinge pocket", [pocket], resolve_tool("flat_3175", TOOLS))]
    warns = reach_warnings(feats, TOOLS)
    assert len(warns) == 1
    w = warns[0]
    assert w.op_name == "Hinge Pockets" and w.tool_name == "flat_3175"
    assert w.fits_radius_mm == pytest.approx(1.2, abs=0.05)
    # suggests a tool that actually fits the pocket
    assert w.suggested_tool is not None
    assert TOOLS[w.suggested_tool]["radius_mm"] <= w.fits_radius_mm + 1e-6
    assert w.message()


def test_reach_no_warning_when_tool_fits():
    pocket = _square(0, 0, 2.4)
    feats = [("Hinge Pockets", "hinge pocket", [pocket], resolve_tool("flat_2mm", TOOLS))]
    assert reach_warnings(feats, TOOLS) == []   # r=1.0 <= inradius ~1.2


# ------------------------------------------------------------------ tool-aware sim

def test_small_tool_reaches_narrow_pocket_bulk_tool_cannot():
    """The headline multi-tool win: a 2 mm tool clears a narrow pocket floor the
    3.175 mm bulk tool can't even enter (BUILDPLAN M6.1 task 5)."""
    from guildmodel.core.sim import ToolProfile, achieved_floor, cutting_paths_from_ops

    pocket = _square(0.0, 0.0, 2.4)
    floor_z, start_z = 2.0, 8.0
    cam = CastleCamParams()
    res, init_z = 0.1, 9.0
    origin = (-4.0, -4.0)
    shape = (81, 81)
    centre = (40, 40)

    def sim(tool):
        op = hinge_pocket_op([pocket], floor_z, start_z, tool["radius_mm"], cam)
        op.tool = tool
        paths = cutting_paths_from_ops([op])
        if not paths:                         # tool produced no toolpath at all
            return np.full(shape, init_z)
        return achieved_floor(paths, ToolProfile.from_tool(tool),
                              origin, shape, res, init_z)

    big = sim(TOOLS["flat_3175"])             # r=1.5875 > pocket inradius ~1.2
    small = sim(TOOLS["flat_2mm"])            # r=1.0 fits

    # the small tool drives the pocket centre down to the floor…
    assert small[centre] == pytest.approx(floor_z, abs=0.2)
    # …the bulk tool leaves it well proud of the floor (uncut)
    assert big[centre] >= floor_z + 1.5
