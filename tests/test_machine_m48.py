"""Machine profiles + user CAM params (BUILDPLAN M4.8 tasks 2 & 3).

Covers: the persisted CAM-params / machine schema round-trip, the shipped
machine profiles, output clamping + arc linearization, program linting, and the
acceptance criterion that a non-Guild profile produces a compliant program.
"""
from pathlib import Path

import pytest
import yaml

from guildcam.core.project.schema import (
    CastleCamParams, MachineProfile, ProjectSchema,
)
from guildcam.core.post.machine import (
    apply_machine_limits, available_machines, lint_program, load_machine_profile,
)
from guildcam.core.cam.cuttime import MachineDynamics

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildcam" / "config"


# ------------------------------------------------------------------ schema persistence

def test_project_round_trips_cam_params_and_machine():
    proj = ProjectSchema()
    proj.cam_params.relief_stepover_mm = 1.1
    proj.cam_params.machine_name = "carbide_nomad3"
    proj.cam_params.feed_rate_mmpm = 600.0
    proj.machine.name = "carbide_nomad3"
    restored = ProjectSchema.model_validate_json(proj.model_dump_json())
    assert restored.cam_params.relief_stepover_mm == 1.1
    assert restored.cam_params.machine_name == "carbide_nomad3"
    assert restored.cam_params.feed_rate_mmpm == 600.0
    assert restored.machine.name == "carbide_nomad3"


def test_cam_params_dump_load_is_stable():
    cp = CastleCamParams(tool_name="flat_3mm", contour_ramp_angle_deg=12.0,
                         spindle_rpm=18000)
    assert CastleCamParams(**cp.model_dump()) == cp


# ------------------------------------------------------------------ profiles

def test_shipped_profiles_load_and_guild_is_first():
    names = [n for n, _ in available_machines(CONFIG)]
    assert names[0] == "guild_cnc"
    assert "carbide_nomad3" in names and "grbl_no_arc" in names
    for name in names:
        prof = load_machine_profile(name, CONFIG)
        assert prof.work_area_x_mm > 0 and prof.max_feed_mmpm > 0


def test_missing_profile_falls_back_or_raises():
    assert load_machine_profile("guild_cnc", CONFIG).name == "guild_cnc"
    with pytest.raises(FileNotFoundError):
        load_machine_profile("no_such_machine", CONFIG)


# ------------------------------------------------------------------ clamping

def test_apply_machine_limits_clamps_and_warns():
    prof = MachineProfile(max_feed_mmpm=1000, max_plunge_mmpm=300,
                          max_spindle_rpm=12000, max_doc_mm=1.5)
    out = apply_machine_limits(
        prof, feed_rate_mmpm=2000, plunge_rate_mmpm=500, spindle_rpm=20000,
        contour_stepdown_mm=2.5, requested_arc_tol_mm=0.01, material_max_doc_mm=2.0)
    assert out.feed_rate_mmpm == 1000
    assert out.plunge_rate_mmpm == 300
    assert out.spindle_rpm == 12000
    assert out.contour_stepdown_mm == 1.5      # min(machine 1.5, material 2.0)
    assert out.arc_tol_mm == 0.01              # arcs supported
    assert len(out.warnings) >= 4


def test_no_arc_profile_linearizes():
    prof = MachineProfile(supports_arcs=False)
    out = apply_machine_limits(
        prof, feed_rate_mmpm=750, plunge_rate_mmpm=333, spindle_rpm=10000,
        contour_stepdown_mm=2.0, requested_arc_tol_mm=0.01)
    assert out.arc_tol_mm == 0.0
    assert any("arc" in w.lower() for w in out.warnings)


def test_min_spindle_raised():
    prof = MachineProfile(min_spindle_rpm=10000)
    out = apply_machine_limits(
        prof, feed_rate_mmpm=750, plunge_rate_mmpm=333, spindle_rpm=8000,
        contour_stepdown_mm=2.0, requested_arc_tol_mm=0.0)
    assert out.spindle_rpm == 10000


# ------------------------------------------------------------------ dynamics

def test_dynamics_from_profile():
    prof = load_machine_profile("carbide_shapeoko", CONFIG)
    dyn = MachineDynamics.from_profile(prof)
    assert dyn.rapid_rate_mmpm == prof.rapid_rate_mmpm
    assert dyn.max_accel_mmps2 == prof.max_accel_mmps2


# ------------------------------------------------------------------ linting

def test_lint_flags_oversize_part():
    prof = MachineProfile(work_area_x_mm=50, work_area_y_mm=50)
    prog = "G21\nG1 X0 Y0 F600\nG1 X120 Y10\n"     # 120 mm span > 50
    warns = lint_program(prog, prof)
    assert any("work area" in w for w in warns)


def test_lint_flags_arcs_on_no_arc_machine():
    prof = MachineProfile(supports_arcs=False, work_area_x_mm=500, work_area_y_mm=500)
    prog = "G21\nG1 X0 Y0 F600\nG3 X10 Y10 I10 J0 F600\n"
    assert any("arc" in w.lower() for w in lint_program(prog, prof))


# ------------------------------------------------------------------ acceptance

@pytest.fixture(scope="module")
def demo_relief():
    from guildcam.core.geometry.regions import partition_zones
    from guildcam.core.io_import.dxf import import_dxf
    from guildcam.core.io_import.normalize import points_to_polygon
    from guildcam.core.project.schema import CastleParams
    from guildcam.core.relief.castle import build_castle_relief

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle = CastleParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    return relief, castle, hinges


def _post_for(machine_name, demo_relief):
    from guildcam.core.cam.castle_ops import generate_castle_program, write_castle_program
    from guildcam.core.post.grbl import GRBLPost

    relief, castle, hinges = demo_relief
    tool = yaml.safe_load((CONFIG / "tools.yaml").read_text())["flat_3175"]
    mat = yaml.safe_load((CONFIG / "materials.yaml").read_text())["acetate"]
    prof = load_machine_profile(machine_name, CONFIG)
    clamp = apply_machine_limits(
        prof, feed_rate_mmpm=mat["feed_rate_mmpm"], plunge_rate_mmpm=mat["plunge_rate_mmpm"],
        spindle_rpm=mat["spindle_rpm"], contour_stepdown_mm=2.5,
        requested_arc_tol_mm=0.01, material_max_doc_mm=mat.get("max_doc_mm"))
    cam = CastleCamParams(machine_name=machine_name).model_copy(
        update={"contour_stepdown_mm": clamp.contour_stepdown_mm})
    ops = generate_castle_program(relief, castle, hinges, tool, params=cam)
    post = GRBLPost(
        job_name="m", material="acetate", tool_diameter_mm=3.175,
        spindle_rpm=clamp.spindle_rpm, feed_rate_mmpm=clamp.feed_rate_mmpm,
        plunge_rate_mmpm=clamp.plunge_rate_mmpm,
        safe_z_mm=castle.stock.total_pad_height_mm + 5.0)
    write_castle_program(
        ops, post, arc_tol_mm=clamp.arc_tol_mm,
        contour_stepdown_mm=cam.contour_stepdown_mm,
        contour_ramp_angle_deg=cam.contour_ramp_angle_deg)
    return post.to_string(), prof


def test_non_guild_profile_produces_compliant_program(demo_relief):
    """A non-Guild machine (no arc support, tighter DOC) yields a program with
    no G2/G3 and no lint violations — the M4.8 acceptance criterion."""
    text, prof = _post_for("grbl_no_arc", demo_relief)
    assert "G2 " not in text and "G3 " not in text   # linearized
    assert lint_program(text, prof) == []


def test_carbide_nomad_program_fits_and_keeps_arcs(demo_relief):
    text, prof = _post_for("carbide_nomad3", demo_relief)
    assert "G2 " in text or "G3 " in text            # arcs kept
    assert lint_program(text, prof) == []            # ~110 mm part fits 203 mm bed
