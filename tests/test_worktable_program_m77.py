"""Combined worktable program from the nested bed (BUILDPLAN M7.7).

The output half of the reorientation: a role-matched `BedNest` (M7.6) on the
user-tagged `Worktable` (M7.4) is combined into ONE scheduled `worktable.nc`
(`build_nest_program`) — op names prefixed per placement, the through-cut / drill
name sets collected, and the M6.5 precedence-aware tool-change minimiser run over
the whole bed — then posted, linted, keep-out-cleared and cut-timed exactly like
the M6.5 fixture bed. Per-component programs are unchanged (covered by M6.1–M6.4).
These tests run headless (numpy + shapely); the GUI post is offscreen-smoked.
"""
from pathlib import Path

import pytest
import yaml

from guildmodel.core.project.schema import (
    BaseCurveBlockParams, BedRole, CastleCamParams, CastleParams,
    MachineProfile, Worktable, WorktableZone,
)
from guildmodel.core.cam.castle_ops import (
    CamOp, build_tool_settings, write_castle_program,
)
from guildmodel.core.cam.block_ops import BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS
from guildmodel.core.cam.cuttime import MachineDynamics, estimate_program
from guildmodel.core.cam.layout import (
    build_nest_program, nest_components_on_worktable, worktable_clearance_violations,
)
from guildmodel.core.post.grbl import GRBLPost
from guildmodel.core.post.machine import lint_program

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())
FIXTURE = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text())


def _op(name, tool, pts):
    return CamOp(name, paths=[[(x, y, 0.0) for x, y in pts]],
                 tool={**TOOLS[tool], "name": tool})


def _rect_zone(zid, role, x0, y0, x1, y1):
    return WorktableZone(id=zid, role=role,
                         polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


# ------------------------------------------------------------------ build_nest_program

def _two_part_nest():
    """A frame (one flat op) + a base-curve block (drill then flat) on a 2-zone bed."""
    from guildmodel.core.cam.layout import BedPart
    bed = Worktable(zones=[
        _rect_zone("front", BedRole.FRAME_FRONT, 0, 0, 100, 80),
        _rect_zone("bc", BedRole.BASE_CURVE_RIGHT, 120, 0, 200, 80),
    ])
    frame = BedPart("frame_front", "Frame", "",
                    [_op("Perimeter", "flat_3175", [(-5, -5), (5, 5)])],
                    {"Perimeter"}, set())
    block = BedPart("base_curve_right", "Block", "",
                    [_op("Drill Holes", "drill_m4_clear", [(0, 0)]),
                     _op("Block Profile", "flat_3175", [(-4, -4), (4, 4)])],
                    {"Block Profile"}, {"Drill Holes"})
    return bed, nest_components_on_worktable([frame, block], bed)


def test_nest_program_prefixes_and_classifies_names():
    _bed, nest = _two_part_nest()
    prog = build_nest_program(nest)
    assert {op.name for op in prog.ops} == {
        "Frame · Perimeter", "Block · Drill Holes", "Block · Block Profile"}
    assert prog.contour_op_names == {"Frame · Perimeter", "Block · Block Profile"}
    assert prog.drill_op_names == {"Block · Drill Holes"}


def test_nest_program_preserves_each_parts_internal_order():
    _bed, nest = _two_part_nest()
    prog = build_nest_program(nest)
    names = [op.name for op in prog.ops]
    assert names.index("Block · Drill Holes") < names.index("Block · Block Profile")


def test_nest_program_minimises_tool_changes():
    # frame (flat) + block (drill + flat) -> 2 distinct tools -> exactly one change
    _bed, nest = _two_part_nest()
    prog = build_nest_program(nest)
    assert prog.n_tool_changes == 1


def test_nest_program_does_not_mutate_the_nest_ops():
    """The bed render reads the nest's own ops by base name — the combined post must
    rename copies, not the nest in place."""
    _bed, nest = _two_part_nest()
    build_nest_program(nest)
    base_names = {op.name for pl in nest.placements for op in pl.ops}
    assert base_names == {"Perimeter", "Drill Holes", "Block Profile"}


# ------------------------------------------------------------------ demo bed: post + gate

@pytest.fixture(scope="module")
def demo_nest():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.cam.block_ops import generate_block_program
    from guildmodel.core.cam.layout import BedPart

    raw = import_dxf(DEMO / "GuildDraw DXF Export.dxf")
    outline = points_to_polygon(raw["OUTLINE"][0])
    lenses = [points_to_polygon(c) for c in raw["LENS"]]
    hinges = [points_to_polygon(c) for c in raw["HINGE"]]
    part = partition_zones(outline, lenses, raw["SCULPT"])
    castle, cam = CastleParams(), CastleCamParams()
    relief = build_castle_relief(part, castle, hinges, resolution=0.3)
    frame_ops = generate_castle_program(relief, castle, hinges, TOOLS["flat_3175"],
                                        params=cam, tools_cfg=TOOLS)
    od = sorted(lenses, key=lambda p: p.centroid.x)[-1]
    block_ops = generate_block_program(od, BaseCurveBlockParams(), TOOLS, cam)
    parts = [
        BedPart("frame_front", "Frame", "", frame_ops, {"Eyewires", "Perimeter"}, set()),
        BedPart("base_curve_right", "Block", "", block_ops,
                BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS),
    ]
    bed = Worktable.from_fixture_dict(FIXTURE)
    return bed, nest_components_on_worktable(parts, bed)


def test_demo_worktable_program_posts_lints_and_clears(demo_nest):
    bed, nest = demo_nest
    prog = build_nest_program(nest)
    assert prog.n_tool_changes == 2     # fine hinge tool + bulk flat + block drill → 2 changes
    machine = MachineProfile()
    acetate = MATS["acetate"]
    ts, _ = build_tool_settings(prog.ops, TOOLS, default_feed=acetate["feed_rate_mmpm"],
                                default_plunge=acetate["plunge_rate_mmpm"],
                                default_spindle=acetate["spindle_rpm"], machine=machine)
    first = ts[prog.ops[0].tool_name]
    post = GRBLPost("worktable", "acetate", first.diameter_mm, first.spindle_rpm,
                    first.feed_rate_mmpm, first.plunge_rate_mmpm, safe_z_mm=20.0)
    write_castle_program(prog.ops, post, side="Worktable", tool_settings=ts,
                         tool_change_mode=machine.tool_change_mode,
                         contour_op_names=prog.contour_op_names,
                         drill_op_names=prog.drill_op_names, peck_depth_mm=1.5)
    text = post.to_string()
    assert text.count("Tool Change") == 2                       # 3 tools → 2 changes
    assert lint_program(text, machine) == []
    # drilling at the mounting screws is intended -> drill ops exempt; cutting clears
    assert worktable_clearance_violations(
        prog.ops, bed, skip_op_names=prog.drill_op_names) == []
    # ...and the exemption does real work: without it the drill IS flagged
    assert any("Drill Holes" in v for v in worktable_clearance_violations(prog.ops, bed))
    rep = estimate_program(text, MachineDynamics.from_profile(machine),
                           tool_change_seconds=machine.tool_change_seconds)
    assert rep.n_tool_changes == 2
    assert rep.total_seconds > rep.cycle_seconds                # change dwell counted


# ------------------------------------------------------------------ GUI post (offscreen)

def test_gui_generate_worktable_program(tmp_path, monkeypatch):
    """The Worktable tab's Generate Worktable Program posts the nest into
    `_last_programs['worktable.nc']` + a worktable setup sheet (BUILDPLAN M7.7)."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication, QMessageBox
    from shapely.geometry import Polygon

    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import MainWindow, NestWorker
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)

    bed = Worktable.from_fixture_dict(FIXTURE)
    lens = Polygon([(0, 0), (40, 0), (40, 26), (0, 26)])         # a cheap stand-in lens
    spec = {"mode": "block", "kind": "base_curve_right", "label": "BC R",
            "lens": lens, "block": BaseCurveBlockParams()}
    worker = NestWorker([spec], bed, cam_params=CastleCamParams(), resolution=0.6)
    done = []
    worker.finished.connect(lambda nest: done.append(nest))
    worker.run()
    assert len(done) == 1 and done[0].placements

    try:
        win = MainWindow()
    except Exception as exc:                                     # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    win._worktable = bed
    win._nest = done[0]
    win._on_generate_worktable_nest()

    assert "worktable.nc" in (win._last_programs or {})
    assert win._last_programs["worktable.nc"].strip()
    assert win._last_setup["component"] == "worktable"
    assert win._last_setup["parts"] and win._last_setup["parts"][0]["label"] == "BC R"
    assert win._act_export_nc.isEnabled()
