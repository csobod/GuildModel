"""Custom worktable layout & multi-part nesting (BUILDPLAN M6.5).

Cut several components in one program on the bed (the fixture): each part is
generated in its own design frame, placed on its bed zone, and the whole set is
scheduled to minimise tool changes across the bed while respecting each part's
internal op order. These tests cover the transform, the scheduler, clearance over
the layout, the combined post, cut-time over the bed, and the `.gmodel` round-trip.
"""
from pathlib import Path

import pytest
import yaml
from shapely.geometry import Polygon

from guildmodel.core.project.schema import (
    BaseCurveBlockParams, BedLayout, CastleCamParams, CastleParams,
    ComponentPlacement, MachineProfile, ProjectSchema,
)
from guildmodel.core.cam.castle_ops import (
    CamOp, build_tool_settings, write_castle_program,
)
from guildmodel.core.cam.block_ops import (
    BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS, generate_block_program,
)
from guildmodel.core.cam.layout import (
    BedPart, bed_clearance_violations, build_bed_program, ops_bbox_center,
    place_ops_at_zone, schedule_bed_ops, transform_ops, zone_center,
)
from guildmodel.core.post.grbl import GRBLPost
from guildmodel.core.post.machine import lint_program
from guildmodel.core.cam.cuttime import estimate_program, MachineDynamics

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "Demo Project"
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())
FIXTURE = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text())


def _op(name, tool, pts):
    return CamOp(name, paths=[[(x, y, 0.0) for x, y in pts]],
                 tool={**TOOLS[tool], "name": tool})


# ------------------------------------------------------------------ geometry

def test_transform_translates_and_rotates():
    op = _op("P", "flat_3175", [(0, 0), (10, 0)])
    moved = transform_ops([op], 5.0, 3.0)[0]
    assert moved.paths[0][0] == pytest.approx((5.0, 3.0, 0.0))
    assert moved.paths[0][1] == pytest.approx((15.0, 3.0, 0.0))
    # 90° rotation about origin then translate
    rot = transform_ops([op], 0.0, 0.0, 90.0)[0]
    assert rot.paths[0][1][0] == pytest.approx(0.0, abs=1e-9)
    assert rot.paths[0][1][1] == pytest.approx(10.0, abs=1e-9)


def test_zone_center_matches_fixture():
    z = FIXTURE["blank_zones"]["bc_template_right"]
    assert zone_center(FIXTURE, "bc_template_right") == pytest.approx(
        (z["x_mm"] + z["width_mm"] / 2.0, z["y_mm"] + z["height_mm"] / 2.0))


def test_place_centers_bbox_on_zone():
    op = _op("P", "flat_3175", [(0, 0), (20, 10)])           # bbox centre (10, 5)
    placed, (dx, dy) = place_ops_at_zone([op], FIXTURE, "bc_template_right")
    cx, cy = zone_center(FIXTURE, "bc_template_right")
    bx, by = ops_bbox_center(placed)
    assert (bx, by) == pytest.approx((cx, cy))               # part centred in zone


# ------------------------------------------------------------------ scheduler

def test_schedule_minimises_tool_changes_respecting_order():
    # frame-like (all bulk) + block-like (drill, bulk, bulk)
    A = [_op("A relief", "flat_3175", [(0, 0)]),
         _op("A perim", "flat_3175", [(1, 1)])]
    B = [_op("B drill", "drill_m4_clear", [(2, 2)]),
         _op("B forming", "flat_3175", [(3, 3)]),
         _op("B profile", "flat_3175", [(4, 4)])]
    sched = schedule_bed_ops([A, B])
    names = [op.name for op in sched]
    # drill is front-loaded (fewest remaining), then all bulk -> ONE change
    changes = sum(1 for i in range(1, len(sched))
                  if sched[i].tool_name != sched[i - 1].tool_name)
    assert changes == 1
    assert names[0] == "B drill"
    # each part keeps its internal order
    assert names.index("B forming") > names.index("B drill")
    assert names.index("B profile") > names.index("B forming")
    assert names.index("A perim") > names.index("A relief")


def test_schedule_preserves_precedence_across_conflicting_tool_orders():
    # part using bulk THEN special must not be reordered to special-then-bulk
    A = [_op("A0", "flat_3175", [(0, 0)]), _op("A1", "drill_m4_clear", [(1, 1)])]
    sched = schedule_bed_ops([A])
    assert [op.name for op in sched] == ["A0", "A1"]


# ------------------------------------------------------------------ assembly + clearance

@pytest.fixture(scope="module")
def demo_bed():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon
    from guildmodel.core.relief.castle import build_castle_relief
    from guildmodel.core.cam.castle_ops import generate_castle_program

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
        BedPart("frame_front", "Frame", "front", frame_ops, {"Eyewires", "Perimeter"}, set()),
        BedPart("base_curve_block", "Block", "bc_template_right", block_ops,
                BLOCK_CONTOUR_OPS, BLOCK_DRILL_OPS),
    ]
    return build_bed_program(parts, FIXTURE)


def test_bed_places_each_part_on_its_zone(demo_bed):
    labels = {p.label: p for p in demo_bed.placements}
    assert labels["Frame"].fixture_zone == "front"
    assert labels["Block"].fixture_zone == "bc_template_right"
    # offsets land the parts in the positive machine quadrant (on the bed)
    assert labels["Frame"].x_mm > 100 and labels["Block"].x_mm > 0


def test_bed_op_names_are_prefixed_and_classified(demo_bed):
    assert all(" · " in op.name for op in demo_bed.ops)
    assert any(n.endswith("Perimeter") for n in demo_bed.contour_op_names)
    assert any(n.endswith("Drill Holes") for n in demo_bed.drill_op_names)


def test_bed_minimises_changes_minimal_for_three_tools(demo_bed):
    # M11: the frame's hinge pockets now default to a fine tool (flat_2mm), so the bed
    # carries 3 tools — flat_2mm, the bulk flat_3175, and the block's drill — and the
    # scheduler minimises the changes between them to exactly 2.
    assert demo_bed.n_tool_changes == 2


def test_one_program_posts_lints_and_clears(demo_bed):
    machine = MachineProfile()
    acetal = MATS["acetal"]
    ts, _ = build_tool_settings(demo_bed.ops, TOOLS, default_feed=acetal["feed_rate_mmpm"],
                                default_plunge=acetal["plunge_rate_mmpm"],
                                default_spindle=acetal["spindle_rpm"], machine=machine)
    first = ts[demo_bed.ops[0].tool_name]
    post = GRBLPost("worktable", "acetate", first.diameter_mm, first.spindle_rpm,
                    first.feed_rate_mmpm, first.plunge_rate_mmpm, safe_z_mm=20.0)
    write_castle_program(demo_bed.ops, post, side="Worktable", tool_settings=ts,
                         tool_change_mode=machine.tool_change_mode,
                         contour_op_names=demo_bed.contour_op_names,
                         drill_op_names=demo_bed.drill_op_names, peck_depth_mm=1.5)
    text = post.to_string()
    assert text.count("Tool Change") == 2     # 3 tools (fine hinge + bulk + drill) → 2 changes
    assert lint_program(text, machine) == []
    # drilling at the mounting screws is intended -> exempt; cutting must clear
    assert bed_clearance_violations(demo_bed.ops, FIXTURE,
                                    skip_op_names=demo_bed.drill_op_names) == []
    # cut-time over the whole bed includes the change dwell
    rep = estimate_program(text, MachineDynamics.from_profile(machine),
                           tool_change_seconds=machine.tool_change_seconds)
    assert rep.n_tool_changes == 2
    assert rep.total_seconds > rep.cycle_seconds


def test_block_holes_land_on_the_fixture_mounting_screws(demo_bed):
    """The bc-template screws are the block's mounting bolts — so without the
    drill exemption, the clearance check *would* flag the holes (a sanity check
    that the exemption is doing real work)."""
    flagged = bed_clearance_violations(demo_bed.ops, FIXTURE)   # no skip
    assert any("Drill Holes" in v for v in flagged)


# ------------------------------------------------------------------ round-trip

def test_bed_layout_round_trips_through_gmodel(tmp_path):
    from guildmodel.core.project.gmodel import save_gmodel, load_gmodel
    proj = ProjectSchema(job_name="Bed")
    proj.bed_layout = BedLayout(placements=[
        ComponentPlacement(kind="frame_front", label="Frame", fixture_zone="front",
                           x_mm=201.1, y_mm=144.3),
        ComponentPlacement(kind="base_curve_block", label="Block",
                           fixture_zone="bc_template_right", x_mm=54.8, y_mm=147.3),
    ])
    path = tmp_path / "bed.gmodel"
    save_gmodel(path, project=proj, dxf_bytes=b"dxf")
    bl = load_gmodel(path).project.bed_layout
    assert [p.kind for p in bl.placements] == ["frame_front", "base_curve_block"]
    assert bl.placements[0].x_mm == pytest.approx(201.1)
