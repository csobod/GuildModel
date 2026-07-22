"""Base-curve forming blocks (BUILDPLAN M6.4).

Auto-generate the heat-forming holding block from the frame DXF: the lens-interior
footprint scribed on an acetal blank, the blank profile-cut to release it, and
three M4 mounting holes peck-drilled (in-line, 10 mm, ~4.5 mm clearance —
confirmed with the user). Built on the M6.1 multi-tool post (drill → bulk change).
"""
from pathlib import Path

import pytest
import yaml
from shapely.geometry import Polygon

from guildmodel.core.project.schema import (
    BaseCurveBlockParams, CastleCamParams, MachineProfile, ProjectSchema,
)
from guildmodel.core.cam.block_ops import (
    BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, center_on_origin, generate_block_program,
)
from guildmodel.core.cam.castle_ops import (
    build_tool_settings, count_tool_changes, write_castle_program,
)
from guildmodel.core.post.grbl import GRBLPost
from guildmodel.core.post.machine import lint_program

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "tests" / "fixtures" / "demo"
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())

# A synthetic lens interior (an ellipse-ish blob) off-origin, to prove centering.
LENS = Polygon([(40, 10), (60, 18), (66, 30), (58, 42), (42, 40), (36, 26)])


# ------------------------------------------------------------------ config / schema

def test_drill_tool_and_acetal_shipped():
    assert "drill_m4_clear" in TOOLS and TOOLS["drill_m4_clear"]["diameter_mm"] == 4.5
    assert "acetal" in MATS and MATS["acetal"]["display_name"].startswith("Acetal")


def test_block_defaults_match_confirmed_spec():
    b = BaseCurveBlockParams()
    assert (b.blank_length_mm, b.blank_width_mm) == (70.0, 70.0)
    assert b.blank_thickness_mm == pytest.approx(4.7625)      # 3/16" acetal
    assert b.material == "acetal"
    assert b.hole_arrangement == "inline"
    assert b.hole_spacing_mm == 10.0 and b.hole_diameter_mm == 4.5
    assert b.stock().total_pad_height_mm == pytest.approx(4.7625)


def test_hole_centers_inline_and_triangle():
    b = BaseCurveBlockParams()                                   # inline, 3 @ 10 mm
    xs = sorted(x for x, _ in b.hole_centers())
    assert xs == pytest.approx([-10.0, 0.0, 10.0])
    assert all(y == 0.0 for _, y in b.hole_centers())
    tri = BaseCurveBlockParams(hole_arrangement="triangle").hole_centers()
    assert len(tri) == 3
    # centroid at the origin; side length == spacing
    cx = sum(x for x, _ in tri) / 3.0
    cy = sum(y for _, y in tri) / 3.0
    assert cx == pytest.approx(0.0, abs=1e-9) and cy == pytest.approx(0.0, abs=1e-6)
    import math
    d01 = math.dist(tri[0], tri[1])
    assert d01 == pytest.approx(10.0, abs=1e-6)


def test_center_on_origin():
    x0, y0, x1, y1 = center_on_origin(LENS).bounds
    assert (x0 + x1) == pytest.approx(0.0, abs=1e-9)             # bbox centred
    assert (y0 + y1) == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------------------ generation

def test_generate_block_two_ops_drill_then_lens_profile():
    ops = generate_block_program(LENS, BaseCurveBlockParams(), TOOLS)
    assert [op.name for op in ops] == ["Drill Holes", "Block Profile"]   # nothing else
    assert ops[0].tool_name == "drill_m4_clear"
    assert ops[1].tool_name == "flat_3175"
    assert count_tool_changes(ops) == 1                          # drill -> bulk


def test_block_profile_cuts_the_lens_shape():
    """The block outline is the LENS shape (cut free like a frame outline), not a
    surrounding box — one tool-offset beyond the lens, centred on the blank."""
    b = BaseCurveBlockParams()
    prof = generate_block_program(LENS, b, TOOLS)[1]
    x0, y0, x1, y1 = prof.xy_bounds()
    lx0, ly0, lx1, ly1 = LENS.bounds
    offset = TOOLS["flat_3175"]["radius_mm"] + b.hand_finishing_allowance_mm
    assert (x1 - x0) == pytest.approx((lx1 - lx0) + 2 * offset, abs=0.3)
    assert (y1 - y0) == pytest.approx((ly1 - ly0) + 2 * offset, abs=0.3)
    assert (x0 + x1) == pytest.approx(0.0, abs=0.3)              # centred on the blank
    # the profile reaches down to the onion skin (a through-cut, not a scribe)
    assert prof.z_range()[0] == pytest.approx(b.onion_skin_mm)


def test_three_holes_at_spec_and_through_depth():
    b = BaseCurveBlockParams()
    drill = generate_block_program(LENS, b, TOOLS)[0]
    assert len(drill.paths) == 3
    xs = sorted(p[0][0] for p in drill.paths)
    assert xs == pytest.approx([-10.0, 0.0, 10.0])
    for path in drill.paths:
        (x, y, z_top), (_, _, z_bottom) = path[0], path[-1]
        assert z_top == pytest.approx(4.7625)                   # top face
        assert z_bottom == pytest.approx(-b.drill_breakthrough_mm)  # through
    assert b.hole_diameter_mm == TOOLS[b.drill_tool]["diameter_mm"]


# ------------------------------------------------------------------ posting

def _post_block(ops, machine):
    mat = MATS["acetal"]
    ts, _ = build_tool_settings(
        ops, TOOLS, default_feed=mat["feed_rate_mmpm"],
        default_plunge=mat["plunge_rate_mmpm"], default_spindle=mat["spindle_rpm"],
        machine=machine)
    first = ts[ops[0].tool_name]
    post = GRBLPost("bc", "acetal", first.diameter_mm, first.spindle_rpm,
                    first.feed_rate_mmpm, first.plunge_rate_mmpm, safe_z_mm=11.35)
    write_castle_program(ops, post, side="Base-Curve Block", tool_settings=ts,
                         tool_change_mode=machine.tool_change_mode,
                         contour_op_names=BLOCK_CONTOUR_OPS, drill_op_names=BLOCK_DRILL_OPS,
                         peck_depth_mm=1.5)
    return ts, post.to_string()


def test_block_program_pecks_drills_changes_tool_and_lints():
    ops = generate_block_program(LENS, BaseCurveBlockParams(), TOOLS)
    machine = MachineProfile()
    ts, text = _post_block(ops, machine)
    assert text.count("Tool Change") == 1
    assert ts["drill_m4_clear"].number == 1 and ts["flat_3175"].number == 2
    # the drill section has multiple peck plunges (G1 Z) and rapid retracts (G0 Z)
    head = text.split("Block Profile")[0]
    drill = head.split("Drill Holes")[1]
    assert drill.count("G1 Z") >= 6          # >= 2 pecks per hole x 3 holes
    assert drill.count("G0 Z") >= 6          # full-retract pecking
    assert lint_program(text, machine) == []


def test_peck_drill_emits_g83_cycle():
    post = GRBLPost("d", "acetal", 4.5, 6000, 150, 80, safe_z_mm=10.0)
    post.peck_drill(0.0, 0.0, 6.0, -1.0, peck_depth=2.0)
    zs = [ln for ln in post.to_string().splitlines() if "Z" in ln]
    # deepest plunge reaches the bottom, retracts stay above the top face
    plunges = [float(ln.split("Z")[1].split()[0]) for ln in zs if ln.startswith("G1")]
    assert min(plunges) == pytest.approx(-1.0)


# ------------------------------------------------------------------ round-trip

def test_block_params_round_trip_through_gmodel(tmp_path):
    from guildmodel.core.project.gmodel import save_gmodel, load_gmodel
    proj = ProjectSchema(job_name="BC")
    proj.base_curve_block = BaseCurveBlockParams(
        hole_arrangement="triangle", hole_diameter_mm=3.3, blank_thickness_mm=8.0)
    path = tmp_path / "bc.gmodel"
    save_gmodel(path, project=proj, dxf_bytes=b"dxf")
    b = load_gmodel(path).project.base_curve_block
    assert b.hole_arrangement == "triangle" and b.hole_diameter_mm == 3.3
    assert b.blank_thickness_mm == 8.0
