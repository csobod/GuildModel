"""Cut-time model + budget gate (BUILDPLAN M4.8 task 1).

The model (`core/cam/cuttime.py`) estimates how long a posted GRBL program runs,
op-by-op, with an assumption-free cutting-only figure and an accel-aware cycle
estimate (GRBL trapezoidal + junction-deviation planner). The budget gate asserts
our generated posterior program stays within a multiple of the Fusion control
`Demo Program.nc` (~10 min) — the regression that the cut-time-efficiency work is
driven against.
"""
import math
from pathlib import Path

import pytest
import yaml

from guildmodel.core.cam.cuttime import (
    MachineDynamics, estimate_program, format_report,
)

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "tests" / "fixtures" / "demo"
CONFIG = ROOT / "src" / "guildmodel" / "config"

# The cutting-only budget the generated program must stay within, relative to
# the Fusion control. Cutting-only (length / programmed feed) is the gate figure
# because it makes no machine-dynamics assumption.
CUT_BUDGET = 1.30


# ------------------------------------------------------------------ model units

def test_straight_feed_cutting_only():
    """A single 100 mm cut at 600 mm/min is exactly 10 s of cutting."""
    rep = estimate_program("G21\nG1 X100 Y0 F600\n")
    assert rep.cut_mm == pytest.approx(100.0, abs=1e-6)
    assert rep.cutting_only_seconds == pytest.approx(10.0, abs=1e-6)


def test_arc_length_recovered():
    """A ccw quarter circle of R=10 has arc length R·π/2."""
    prog = "G21\nG0 X10 Y0\nG3 X0 Y10 I-10 J0 F600\n"
    rep = estimate_program(prog)
    assert rep.cut_mm == pytest.approx(10.0 * math.pi / 2, abs=0.02)
    assert rep.rapid_mm == pytest.approx(10.0, abs=1e-6)


def test_accel_penalises_many_short_segments():
    """The cycle estimate must exceed cutting-only when the path is chopped into
    short zig-zag segments (cornering forces decel), but track it closely for one
    long straight move."""
    dyn = MachineDynamics(max_accel_mmps2=300.0, junction_deviation_mm=0.01)

    one_long = estimate_program("G21\nG1 X200 F1000\n", dyn)
    assert one_long.cycle_seconds == pytest.approx(
        one_long.cutting_only_seconds, rel=0.10)

    zig = ["G21"]
    for k in range(1, 81):
        zig.append(f"G1 X{k * 0.5} Y{(k % 2) * 0.5} F1000")
    zig_rep = estimate_program("\n".join(zig) + "\n", dyn)
    assert zig_rep.cycle_seconds > 1.4 * zig_rep.cutting_only_seconds


def test_reference_program_is_sane():
    """The Fusion control parses to ~10-11 min, matching its setup sheet."""
    text = (DEMO / "Demo Program.nc").read_text(encoding="utf-8", errors="replace")
    rep = estimate_program(text)
    assert 9.0 < rep.cutting_only_seconds / 60 < 12.0
    assert 9.5 < rep.cycle_seconds / 60 < 13.0
    # all five ops recognised
    names = {o.name for o in rep.ops}
    assert {"Hinge Pockets", "Rough Relief", "Fine Relief",
            "Eyewires", "Perimeter"} <= names


# ------------------------------------------------------------------ budget gate

@pytest.fixture(scope="module")
def generated_program() -> str:
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.project.schema import CastleParams
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.core.cam.castle_ops import (
        generate_castle_program, write_castle_program,
    )
    from guildmodel.core.post.grbl import GRBLPost

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle = CastleParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    tool = yaml.safe_load((CONFIG / "tools.yaml").read_text())["flat_3175"]
    ops = generate_castle_program(relief, castle, hinges, tool)
    post = GRBLPost(
        job_name="budget", material="acetate", tool_diameter_mm=3.175,
        spindle_rpm=10000, feed_rate_mmpm=750, plunge_rate_mmpm=333,
        safe_z_mm=castle.stock.total_pad_height_mm + 5.0,
    )
    write_castle_program(ops, post)
    return post.to_string()


def test_generated_program_within_cut_budget(generated_program):
    control = estimate_program(
        (DEMO / "Demo Program.nc").read_text(encoding="utf-8", errors="replace"))
    ours = estimate_program(generated_program)

    ratio = ours.cutting_only_seconds / control.cutting_only_seconds
    msg = (
        f"\ncut-time ratio {ratio:.2f}x (budget {CUT_BUDGET}x)\n"
        + format_report(control, "CONTROL (Demo Program.nc)")
        + "\n\n" + format_report(ours, "GENERATED")
    )
    assert ratio <= CUT_BUDGET, msg
