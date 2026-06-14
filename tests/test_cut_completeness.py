"""Cut-simulation core + completeness gate (BUILDPLAN M5).

The simulator sweeps the tool along cutting moves and records the achieved floor;
the verifier flags uncut/gouged regions vs the target relief. The gate asserts
our generated program reaches essentially the whole posterior surface — within a
margin of the Fusion control — catching the pad-block/nosepad incompleteness
that the M2/M3 envelope gates could not see.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildcam.core.sim import (
    ToolProfile, achieved_floor, densify,
    cutting_paths_from_ops, cutting_paths_from_program, verify,
)

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildcam" / "config"


# ------------------------------------------------------------------ tool model

def test_flat_tool_stamps_cylinder():
    tp = ToolProfile("flat", 1.0)
    floor = achieved_floor([[(0.0, 0.0, 2.0)]], tp, (-3, -3), (61, 61), 0.1, init_z=9.0)
    # cell at the tip is cut to 2.0; a cell ~2 mm away (> radius) is untouched
    assert floor[30, 30] == pytest.approx(2.0, abs=1e-6)
    assert floor[30, 50] == pytest.approx(9.0, abs=1e-6)


def test_ball_tool_rises_off_axis():
    tp = ToolProfile("ball", 2.0)
    floor = achieved_floor([[(0.0, 0.0, 0.0)]], tp, (-3, -3), (61, 61), 0.1, init_z=9.0)
    centre = floor[30, 30]
    off = floor[30, 40]                       # 1 mm off-axis
    assert centre == pytest.approx(0.0, abs=1e-6)
    assert off == pytest.approx(2.0 - np.sqrt(4 - 1), abs=0.02)   # R - sqrt(R²-d²)
    assert off > centre


def test_densify_spacing():
    pts = densify([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)], 1.0)
    assert len(pts) == 11


def test_program_parse_flattens_arc_and_drops_rapids():
    prog = "G21\nG0 X10 Y0\nG3 X0 Y10 I-10 J0 F600\nG0 Z5\n"
    paths = cutting_paths_from_program(prog)
    assert len(paths) == 1                    # the rapid split off the arc
    arc = np.asarray(paths[0])
    # endpoints of the quarter circle
    assert arc[0][0] == pytest.approx(10.0, abs=1e-6)
    assert arc[-1][1] == pytest.approx(10.0, abs=0.05)
    assert len(arc) > 5                        # flattened to chords


# ------------------------------------------------------------------ completeness gate

@pytest.fixture(scope="module")
def demo():
    from guildcam.core.geometry.regions import partition_zones
    from guildcam.core.io_import.dxf import import_dxf
    from guildcam.core.io_import.normalize import points_to_polygon
    from guildcam.core.project.schema import CastleParams
    from guildcam.core.relief.castle import build_castle_relief
    from guildcam.core.cam.castle_ops import generate_castle_program

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle = CastleParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    tool = yaml.safe_load((CONFIG / "tools.yaml").read_text())["flat_3175"]
    ops = generate_castle_program(relief, castle, hinges, tool)
    return part, castle, relief, tool, ops


def _report(relief, part, tool, paths):
    f = relief.field
    target = np.where(relief.inside, f.z, np.nan)
    init_z = 12.0
    floor = achieved_floor(paths, ToolProfile.from_tool(tool),
                           f.origin, f.z.shape, f.resolution, init_z)
    return verify(floor, target, relief.inside, f.origin, f.resolution, partition=part)


def test_our_program_reaches_the_surface_like_fusion(demo):
    part, castle, relief, tool, ops = demo
    ours = _report(relief, part, tool, cutting_paths_from_ops(ops))

    # Fusion control, aligned to the body centroid
    fpaths = cutting_paths_from_program(
        (DEMO / "Demo Program.nc").read_text(encoding="utf-8", errors="replace"))
    fa = np.vstack([np.asarray(p) for p in fpaths])
    cen = part.body.centroid
    sx, sy = cen.x - fa[:, 0].mean(), cen.y - fa[:, 1].mean()
    fpaths = [[(x + sx, y + sy, z) for x, y, z in p] for p in fpaths]
    fusion = _report(relief, part, tool, fpaths)

    msg = (f"\nours uncut {100*ours.completeness.uncut_fraction:.1f}% "
           f"(worst {ours.completeness.max_excess_mm:.2f} mm) | "
           f"fusion {100*fusion.completeness.uncut_fraction:.1f}%\n"
           + "\n".join(ours.summary_lines()))
    # We must reach the surface about as completely as the control.
    assert ours.completeness.uncut_fraction <= fusion.completeness.uncut_fraction + 0.03, msg
    assert ours.completeness.max_excess_mm <= 2.5, msg
