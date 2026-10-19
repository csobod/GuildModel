"""The stock engine reads the posted program once (BUILDPLAN M21 §6.8 task 5).

`core.sim.paths` has two parsers over the same program; `core.stock.program`
has one. It must give each of them back: the cutting paths tagged by tool, and
the full motion with its op labels and rapids. Pinned on a real front's
program and on the forms the post emits, and on an external control's dialect
(an arc, inches, incremental moves, an A word).
"""
import zipfile
from pathlib import Path

import numpy as np
import pytest
import yaml

from guildmodel.core.sim.paths import (cutting_paths_from_program_grouped,
                                       motion_runs_from_program)
from guildmodel.core.stock import (Run, ToolShape, cutting_paths, machine_seconds,
                                   parse_program, poses_for_run, spacing_for)
from guildmodel.core.stock.cutting import poses_from_path

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def gabriel_program():
    """The gabriel front's posted program, as the Simulate view posts it."""
    from guildmodel.core.cam.castle_ops import (build_tool_settings, generate_castle_program,
                                                write_castle_program)
    from guildmodel.core.post.grbl import GRBLPost
    from guildmodel.core.project.schema import CastleCamParams
    from guildmodel.core.zmap import castle_relief
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = FIXTURES.parent / "_gabriel_program.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / "gabriel").iterdir()):
            zf.write(f, f.name)
    try:
        ws = build_workspaces_from_gdraw(path)[0][0]
    finally:
        path.unlink()
    tools = yaml.safe_load((ROOT / "src/guildmodel/config/tools.yaml").read_text())
    cam = CastleCamParams()
    relief = castle_relief(ws.partition, ws.castle_params, ws.hinge_polys, kernel="mesh",
                           resolution=0.3)
    ops = generate_castle_program(relief, ws.castle_params, ws.hinge_polys,
                                  tools[cam.tool_name], params=cam, tools_cfg=tools)
    resolved, _ = build_tool_settings(ops, tools, default_feed=600, default_plunge=200,
                                      default_spindle=12000)
    first = resolved[ops[0].tool_name]
    post = GRBLPost(job_name="t", material="acetate", tool_diameter_mm=first.diameter_mm,
                    spindle_rpm=first.spindle_rpm, feed_rate_mmpm=first.feed_rate_mmpm,
                    plunge_rate_mmpm=first.plunge_rate_mmpm, safe_z_mm=15.0)
    write_castle_program(ops, post, tool_settings=resolved)
    return post.to_string(), tools


def test_the_cutting_paths_are_the_grouped_parsers(gabriel_program):
    program, _tools = gabriel_program
    want = cutting_paths_from_program_grouped(program)
    got = cutting_paths(parse_program(program))
    assert len(got) == len(want)
    for (gp, gt), (wp, wt) in zip(got, want):
        assert gt == wt
        assert np.array_equal(np.asarray(gp), np.asarray(wp))


def test_the_motion_is_the_run_parsers(gabriel_program):
    program, _tools = gabriel_program
    want = motion_runs_from_program(program)
    runs = parse_program(program)
    # the run parser does not split on a feed change; join ours the same way
    joined = []
    for r in runs:
        key = (r.label, r.tool, r.is_cut)
        if joined and joined[-1][0] == key and joined[-1][1][-1] == tuple(r.points[0][:3]):
            joined[-1][1].extend(tuple(p[:3]) for p in r.points[1:])
        else:
            joined.append((key, [tuple(p[:3]) for p in r.points]))
    assert len(joined) == len(want)
    for (key, pts), (label, tool, poly, is_cut) in zip(joined, want):
        assert key == (label, tool, is_cut)
        assert np.array_equal(np.asarray(pts), np.asarray(poly))


def test_every_run_carries_its_feed_and_rapids_carry_none(gabriel_program):
    program, _tools = gabriel_program
    runs = parse_program(program)
    assert any(r.is_cut for r in runs) and any(not r.is_cut for r in runs)
    assert all(r.feed_mmpm > 0 for r in runs if r.is_cut)
    assert all(r.feed_mmpm == 0 for r in runs if not r.is_cut)
    labels = {r.label for r in runs}
    assert "Component Pockets" in labels and "Perimeter" in labels
    assert all(r.tool for r in runs if r.label)


def test_an_external_dialect_parses():
    prog = ("G20 G90\nG0 X1 Y0\nG1 Z-0.1 F10\nG3 X0 Y1 I-1 J0\nG91\nG1 X0.5 A15\n"
            "G1 A15\nG28\nG90 G21\nG0 X0 Y0\n")
    runs = parse_program(prog, chord_mm=0.3)
    cut = [r for r in runs if r.is_cut]
    assert cut, "a cut after the first rapid"
    first = cut[0]
    assert first.feed_mmpm == pytest.approx(10 * 25.4)
    pts = np.asarray(first.points)
    assert pts[0, 0] == pytest.approx(25.4) and pts[-1, 3] == pytest.approx(30.0)
    assert len(pts) > 5                                   # the arc was flattened
    assert pts[-1, 0] == pytest.approx(0.5 * 25.4 + 0.0, abs=1e-6)   # incremental X
    # G28 breaks the motion; the program then goes metric again
    assert runs[-1].points[-1][0] == pytest.approx(0.0)


def test_poses_land_where_the_floor_was_stamped():
    run = Run("Fine Relief", "flat_3175", True, 600.0,
              [(0, 0, 1, 0), (3.3, 0, 1, 0), (3.3, 2.2, 0.5, 0), (0, 0, 0.5, 0)])
    want = poses_from_path([p[:3] for p in run.points], 0.15)
    got = poses_for_run(run, 0.15)
    assert np.array_equal(got, want)
    # the machine moves in three axes: the length is the 3D one
    assert run.length_mm() == pytest.approx(3.3 + np.hypot(2.2, 0.5) + np.hypot(3.3, 2.2))


def test_the_spacing_follows_the_grid_and_a_small_tool():
    assert spacing_for(ToolShape(radius_mm=1.5875), 0.15) == 0.15
    assert spacing_for(ToolShape(radius_mm=0.25), 0.15) == pytest.approx(0.125)
    assert spacing_for(ToolShape(radius_mm=0.01), 0.15) == pytest.approx(0.0375)


def test_machine_seconds_weight_a_run_by_its_rate():
    cut = Run("Perimeter", "flat_3175", True, 600.0, [(0, 0, 0, 0), (60, 0, 0, 0)])
    rapid = Run("Perimeter", "flat_3175", False, 0.0, [(0, 0, 0, 0), (60, 0, 0, 0)])
    assert machine_seconds(cut, 3000.0, 750.0) == pytest.approx(6.0)
    assert machine_seconds(rapid, 3000.0, 750.0) == pytest.approx(1.2)
    unknown = Run("", None, True, 0.0, [(0, 0, 0, 0), (75, 0, 0, 0)])
    assert machine_seconds(unknown, 3000.0, 750.0) == pytest.approx(6.0)
