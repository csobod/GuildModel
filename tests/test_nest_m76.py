"""Role-matched auto-nesting onto the tagged worktable (BUILDPLAN M7.6).

Generalises the M6.5 fixture-name nesting onto the user-tagged `Worktable` (M7.4):
each built component lands on a zone whose ROLE matches its kind, several of one
kind fill several same-role zones, and clearance is checked against arbitrary
**keep-out polygons** (a screw circle is a special case), keeping the base-curve
drill-at-screw exemption. These tests run headless (shapely + numpy).
"""
from pathlib import Path

import pytest
import yaml

from guildmodel.core.project.schema import (
    BaseCurveBlockParams, BedRole, CastleCamParams, CastleParams,
    Worktable, WorktableZone,
)
from guildmodel.core.cam.castle_ops import CamOp
from guildmodel.core.cam.block_ops import BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS
from guildmodel.core.cam.layout import (
    BedPart, nest_components_on_worktable, ops_bbox_center,
    worktable_clearance_violations,
)

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
FIXTURE = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text())


def _op(name, tool, pts):
    return CamOp(name, paths=[[(x, y, 0.0) for x, y in pts]],
                 tool={**TOOLS[tool], "name": tool})


def _part(kind, label, op):
    return BedPart(kind, label, "", [op], set(), set())


def _rect_zone(zid, role, x0, y0, x1, y1):
    return WorktableZone(id=zid, role=role,
                         polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


# ------------------------------------------------------------------ role matching

def test_each_kind_lands_on_its_role_zone():
    bed = Worktable.from_fixture_dict(FIXTURE)         # the default Guild bed
    parts = [
        _part("frame_front", "Frame", _op("Perimeter", "flat_3175", [(0, 0)])),
        _part("temple_right", "Temple R", _op("Temple Profile", "flat_3175", [(0, 0)])),
        _part("temple_left", "Temple L", _op("Temple Profile", "flat_3175", [(0, 0)])),
        _part("base_curve_right", "BC R", _op("Block Profile", "flat_3175", [(0, 0)])),
        _part("base_curve_left", "BC L", _op("Block Profile", "flat_3175", [(0, 0)])),
    ]
    nest = nest_components_on_worktable(parts, bed)
    assert nest.unplaced == []
    by_label = {pl.label: pl for pl in nest.placements}
    assert by_label["Frame"].zone_id == "front"
    assert by_label["Temple R"].zone_id == "temple_right"
    assert by_label["BC L"].zone_id == "bc_template_left"
    # role recorded == kind for every placement
    assert all(pl.role == pl.kind for pl in nest.placements)


def test_part_centres_on_its_zone():
    bed = Worktable(zones=[_rect_zone("z", BedRole.FRAME_FRONT, 100, 50, 300, 150)])
    op = _op("Perimeter", "flat_3175", [(-10, -5), (10, 5)])     # bbox centre (0, 0)
    nest = nest_components_on_worktable([_part("frame_front", "F", op)], bed)
    pl = nest.placements[0]
    assert pl.zone_id == "z"
    bx, by = ops_bbox_center(pl.ops)
    assert (bx, by) == pytest.approx((200.0, 100.0))            # zone bbox centre
    assert (pl.dx, pl.dy) == pytest.approx((200.0, 100.0))


def test_unmatched_kind_is_left_unplaced():
    bed = Worktable(zones=[_rect_zone("z", BedRole.TEMPLE_RIGHT, 0, 0, 100, 50)])
    parts = [_part("frame_front", "Frame", _op("Perimeter", "flat_3175", [(0, 0)]))]
    nest = nest_components_on_worktable(parts, bed)
    assert nest.placements == []
    assert [p.label for p in nest.unplaced] == ["Frame"]


# ------------------------------------------------------------------ multi-part batching

def test_several_of_one_kind_fill_several_same_role_zones():
    bed = Worktable(zones=[
        _rect_zone("front_a", BedRole.FRAME_FRONT, 0, 0, 100, 80),
        _rect_zone("front_b", BedRole.FRAME_FRONT, 120, 0, 220, 80),
    ])
    parts = [
        _part("frame_front", "F1", _op("Perimeter", "flat_3175", [(0, 0)])),
        _part("frame_front", "F2", _op("Perimeter", "flat_3175", [(0, 0)])),
        _part("frame_front", "F3", _op("Perimeter", "flat_3175", [(0, 0)])),
    ]
    nest = nest_components_on_worktable(parts, bed)
    placed_zones = {pl.label: pl.zone_id for pl in nest.placements}
    # F1/F2 take the two zones (bottom-left first); F3 has no free zone
    assert set(placed_zones.values()) == {"front_a", "front_b"}
    assert placed_zones["F1"] == "front_a"                      # lowest-left zone first
    assert [p.label for p in nest.unplaced] == ["F3"]


# ------------------------------------------------------------------ polygon keep-outs

def test_polygon_keepout_catches_a_collision():
    # a placement zone 0..100 with a rectangular clamp bar keep-out across its middle
    bed = Worktable(zones=[
        _rect_zone("z", BedRole.FRAME_FRONT, 0, 0, 100, 100),
        _rect_zone("clamp", BedRole.KEEP_OUT, 40, 40, 60, 60),
    ])
    # part bbox centre (0,0) → lands at the zone centre (50,50), inside the clamp
    foul = _op("Perimeter", "flat_3175", [(0, 0)])
    nest = nest_components_on_worktable([_part("frame_front", "F", foul)], bed)
    viol = worktable_clearance_violations(nest.all_ops(), bed)
    assert viol and "Perimeter" in viol[0]


def test_polygon_keepout_clears_when_outside():
    bed = Worktable(zones=[
        _rect_zone("z", BedRole.FRAME_FRONT, 0, 0, 100, 100),
        _rect_zone("clamp", BedRole.KEEP_OUT, 0, 0, 10, 10),   # a corner, away from centre
    ])
    op = _op("Perimeter", "flat_3175", [(0, 0)])               # lands at (50,50)
    nest = nest_components_on_worktable([_part("frame_front", "F", op)], bed)
    assert worktable_clearance_violations(nest.all_ops(), bed) == []


def test_circle_keepout_and_drill_exemption():
    # a screw circle keep-out (radius_mm set, exact circle) centred in the zone
    screw = WorktableZone(id="screw", role=BedRole.KEEP_OUT, radius_mm=5.0,
                          polygon=[(45, 45), (55, 45), (55, 55), (45, 55)])  # centre (50,50)
    bed = Worktable(zones=[_rect_zone("z", BedRole.BASE_CURVE_RIGHT, 0, 0, 100, 100), screw])
    drill = CamOp("Drill Holes", paths=[[(0.0, 0.0, 0.0)]],   # bbox → zone centre (50,50)
                  tool={**TOOLS["drill_m4_clear"], "name": "drill_m4_clear"})
    part = BedPart("base_curve_right", "BC", "", [drill], set(), {"Drill Holes"})
    nest = nest_components_on_worktable([part], bed)
    placed = nest.all_ops()
    # the hole lands on the screw centre → without the exemption it's flagged, with it
    # exempt (the screw IS its mounting bolt)
    assert worktable_clearance_violations(placed, bed) != []
    assert worktable_clearance_violations(
        placed, bed, skip_op_names=nest.drill_op_names()) == []


# ------------------------------------------------------------------ demo bed integration

@pytest.fixture(scope="module")
def demo_parts():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.cam.block_ops import generate_block_program

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
    return [
        BedPart("frame_front", "Frame", "", frame_ops, {"Eyewires", "Perimeter"}, set()),
        BedPart("base_curve_right", "Block", "", block_ops,
                BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS),
    ]


def test_nest_worker_and_gui_render_and_nudge(tmp_path, monkeypatch):
    """The GUI NestWorker generates a component program and nests it; the bed canvas
    renders the footprint and a drag nudges the placement (BUILDPLAN M7.6)."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    from shapely.geometry import Polygon

    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import MainWindow, NestWorker

    bed = Worktable.from_fixture_dict(FIXTURE)
    lens = Polygon([(0, 0), (40, 0), (40, 26), (0, 26)])      # a cheap stand-in lens
    spec = {"mode": "block", "kind": "base_curve_right", "label": "BC R",
            "lens": lens, "block": BaseCurveBlockParams()}
    worker = NestWorker([spec], bed, cam_params=CastleCamParams(), resolution=0.6)
    done, errs = [], []
    worker.finished.connect(lambda nest: done.append(nest))
    worker.error.connect(lambda tb: errs.append(tb))
    worker.run()
    assert errs == [], errs[0] if errs else ""
    assert len(done) == 1
    nest = done[0]
    assert [pl.zone_id for pl in nest.placements] == ["bc_template_right"]

    try:
        win = MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    win._worktable = bed
    win._nest = nest
    win._refresh_nest_render()                                # builds the canvas footprints
    assert len(win.bed_canvas._placements) == 1

    pl = nest.placements[0]
    before = (pl.dx, pl.dy)
    win._on_component_nudged("bc_template_right", 7.0, -3.0)   # simulate a drag
    assert (pl.dx, pl.dy) == pytest.approx((before[0] + 7.0, before[1] - 3.0))


def test_demo_nests_on_default_bed_clear(demo_parts):
    bed = Worktable.from_fixture_dict(FIXTURE)
    nest = nest_components_on_worktable(demo_parts, bed)
    assert nest.unplaced == []
    zones = {pl.label: pl.zone_id for pl in nest.placements}
    assert zones["Frame"] == "front"
    assert zones["Block"] == "bc_template_right"
    # the block's M4 holes land on the bc-template screws (their mounting bolts) →
    # the drill ops are exempt; everything else must clear the keep-outs
    assert worktable_clearance_violations(
        nest.all_ops(), bed, skip_op_names=nest.drill_op_names()) == []
    # sanity: without the exemption the drill IS flagged (the exemption does real work)
    flagged = worktable_clearance_violations(nest.all_ops(), bed)
    assert any("Drill Holes" in v for v in flagged)
