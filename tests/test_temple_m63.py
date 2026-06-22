"""Temples with engraving (BUILDPLAN M6.3).

A temple is a flat outline cut plus ENGRAVING passes, with a tool change between
the small engraving bit and the bulk profile tool (built on the M6.1 multi-tool
machinery). These tests cover the engrave depth/tool, the profile envelope, the
posted tool change, intake of the ENGRAVING layer, and the `.gcam` round-trip.
"""
from pathlib import Path

import pytest
import yaml
from shapely.geometry import Polygon

from guildcam.core.project.schema import (
    CastleCamParams, MachineProfile, ProjectSchema, TempleParams,
)
from guildcam.core.cam.temple_ops import (
    TEMPLE_CONTOUR_OPS, engrave_op, generate_temple_program,
)
from guildcam.core.cam.castle_ops import (
    build_tool_settings, count_tool_changes, write_castle_program,
)
from guildcam.core.post.grbl import GRBLPost
from guildcam.core.post.machine import lint_program

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildcam" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MAT = yaml.safe_load((CONFIG / "materials.yaml").read_text())["acetate"]

# a synthetic temple: a flat bar outline + two engraving strokes
OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])
ENGRAVING = [
    [(-40, 0), (-30, 3), (-20, 0), (-10, 3), (0, 0)],   # zigzag logo
    [(10, -2), (40, -2)],                                # underline
]


# ------------------------------------------------------------------ config / schema

def test_engrave_tool_shipped():
    assert "engrave_vbit" in TOOLS
    assert TOOLS["engrave_vbit"]["diameter_mm"] == 0.5
    assert TOOLS["engrave_vbit"]["feed_rate_mmpm"] == 300.0   # gentle per-tool feed


def test_temple_fixture_zone_exists():
    fixture = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text())
    assert "temple_right" in fixture["blank_zones"]


def test_temple_params_defaults_and_stock():
    t = TempleParams()
    assert t.engrave_tool == "engrave_vbit" and t.profile_tool == "flat_3175"
    s = t.stock()
    assert s.blank_thickness_mm == t.blank_thickness_mm
    assert s.total_pad_height_mm == t.blank_thickness_mm    # no pad block


# ------------------------------------------------------------------ generation

def test_generate_temple_two_ops_engrave_then_profile():
    ops = generate_temple_program(OUTLINE, ENGRAVING, TempleParams(), TOOLS)
    assert [op.name for op in ops] == ["Engraving", "Temple Profile"]
    assert ops[0].tool_name == "engrave_vbit"
    assert ops[1].tool_name == "flat_3175"
    assert count_tool_changes(ops) == 1


def test_engrave_is_at_depth_below_top():
    t = TempleParams(blank_thickness_mm=4.0, engrave_depth_mm=0.3)
    ops = generate_temple_program(OUTLINE, ENGRAVING, t, TOOLS)
    eng = ops[0]
    zmin, zmax = eng.z_range()
    assert zmin == pytest.approx(3.7) and zmax == pytest.approx(3.7)   # 4.0 - 0.3
    assert len(eng.paths) == 2


def test_no_engraving_yields_profile_only():
    ops = generate_temple_program(OUTLINE, [], TempleParams(), TOOLS)
    assert [op.name for op in ops] == ["Temple Profile"]
    assert count_tool_changes(ops) == 0


# a hinge recess near the +x end of the bar, well clear of the engraving strokes
HINGE = [Polygon([(55, -3), (65, -3), (65, 3), (55, 3)])]


def test_temple_hinge_pockets_emitted_when_present():
    ops = generate_temple_program(OUTLINE, ENGRAVING, TempleParams(), TOOLS, hinge_polys=HINGE)
    assert [op.name for op in ops] == ["Hinge Pockets", "Engraving", "Temple Profile"]
    hp = ops[0]
    assert hp.tool_name == "flat_2mm"            # the temple's hinge tool
    zmin, zmax = hp.z_range()
    assert zmin == pytest.approx(3.0)            # 4.0 thickness − 1.0 pocket depth
    assert zmax == pytest.approx(4.5)            # ramp entry begins above the blank top
    assert count_tool_changes(ops) == 2          # flat_2mm → engrave_vbit → flat_3175


def test_temple_without_hinge_is_unchanged():
    ops = generate_temple_program(OUTLINE, ENGRAVING, TempleParams(), TOOLS, hinge_polys=[])
    assert [op.name for op in ops] == ["Engraving", "Temple Profile"]


def test_temple_hinge_pocket_posts_and_lints():
    ops = generate_temple_program(OUTLINE, ENGRAVING, TempleParams(), TOOLS, hinge_polys=HINGE)
    machine = MachineProfile()
    _, text = _post_temple(ops, machine)
    assert text.count("Tool Change") == 2
    # the pocket is milled first (Z3.0000 floor) — before the first tool change
    head = text.split("Tool Change")[0]
    assert "Z3.0000" in head
    assert lint_program(text, machine) == []


def test_profile_envelope_top_to_onion_skin():
    t = TempleParams(blank_thickness_mm=4.0, onion_skin_mm=0.4)
    ops = generate_temple_program(OUTLINE, ENGRAVING, t, TOOLS)
    prof = ops[1]
    zmin, zmax = prof.z_range()
    assert zmin == pytest.approx(0.4)            # ends on the onion skin (no tabs)
    assert zmax <= 4.0 + 1e-9                    # starts at/below the blank top
    # the profile is OUTSIDE the outline (offset by tool radius + allowance)
    rprof = TOOLS["flat_3175"]["radius_mm"]
    xs = [x for path in prof.paths for x, _, _ in path]
    assert max(xs) > 70.0 + rprof - 0.2          # ring sits outside the 70 mm edge


def test_engrave_op_skips_degenerate_curves():
    op = engrave_op([[(0, 0)], [(0, 0), (5, 0)]], depth_z=3.0, tool=TOOLS["engrave_vbit"])
    assert len(op.paths) == 1                    # the single-point curve dropped


# ------------------------------------------------------------------ posting

def _post_temple(ops, machine, mode="m0"):
    ts, _ = build_tool_settings(
        ops, TOOLS, default_feed=MAT["feed_rate_mmpm"],
        default_plunge=MAT["plunge_rate_mmpm"], default_spindle=MAT["spindle_rpm"],
        machine=machine)
    first = ts[ops[0].tool_name]
    post = GRBLPost("temple", "acetate", first.diameter_mm, first.spindle_rpm,
                    first.feed_rate_mmpm, first.plunge_rate_mmpm, safe_z_mm=9.0)
    write_castle_program(ops, post, side="Temple", tool_settings=ts,
                         tool_change_mode=mode, contour_op_names=TEMPLE_CONTOUR_OPS)
    return ts, post.to_string()


def test_temple_posts_one_tool_change_and_lints():
    ops = generate_temple_program(OUTLINE, ENGRAVING, TempleParams(), TOOLS)
    machine = MachineProfile()
    ts, text = _post_temple(ops, machine)
    assert text.count("Tool Change") == 1
    assert sum(1 for ln in text.splitlines() if ln.strip() == "M0") == 1
    # engraving runs first on T1, profile on T2
    assert ts["engrave_vbit"].number == 1 and ts["flat_3175"].number == 2
    # the engraving bit carries its own gentle feed
    assert ts["engrave_vbit"].feed_rate_mmpm == 300.0
    assert lint_program(text, machine) == []


def test_engraving_emitted_at_constant_depth_in_program():
    ops = generate_temple_program(OUTLINE, ENGRAVING, TempleParams(), TOOLS)
    _, text = _post_temple(ops, MachineProfile())
    # the engraving section feeds at Z 3.7 (4.0 - 0.3) before the tool change
    head = text.split("Tool Change")[0]
    assert "Z3.7000" in head


# ------------------------------------------------------------------ DXF intake

def test_engraving_layer_imported(tmp_path):
    import ezdxf
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()
    msp.add_lwpolyline([(-70, -6), (70, -6), (70, 6), (-70, 6), (-70, -6)],
                       dxfattribs={"layer": "OUTLINE"})
    msp.add_lwpolyline([(-40, 0), (-20, 0), (0, 0)], dxfattribs={"layer": "ENGRAVING"})
    path = tmp_path / "temple.dxf"
    doc.saveas(path)

    from guildcam.core.io_import.dxf import import_dxf
    raw = import_dxf(path)
    assert raw["ENGRAVING"] and len(raw["ENGRAVING"][0]) >= 3
    assert not raw["LENS"]                       # a temple has no lenses
    assert raw["OUTLINE"]


# ------------------------------------------------------------------ round-trip

def test_temple_params_round_trip_through_gcam(tmp_path):
    from guildcam.core.project.gcam import save_gcam, load_gcam
    proj = ProjectSchema(job_name="Temple")
    proj.temple = TempleParams(engrave_depth_mm=0.5, profile_tool="flat_2mm",
                               blank_thickness_mm=5.0)
    path = tmp_path / "temple.gcam"
    save_gcam(path, project=proj, dxf_bytes=b"dxf")
    t = load_gcam(path).project.temple
    assert t.engrave_depth_mm == 0.5 and t.profile_tool == "flat_2mm"
    assert t.blank_thickness_mm == 5.0
