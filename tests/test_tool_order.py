"""The briefest tool first, within what the cut allows (2026-09-27):
`core.cam.sequence.order_by_tool_work` and its wiring into the temple and
castle generators.

The maker's example: a temple whose hinge pockets and profile share a 2 mm end
mill and whose engraving takes the engraving bit. The bit has the least work,
so it runs first; the operator loads it, starts, and swaps once to the end
mill. The profile still releases the part last, holes still precede it, and a
front — whose relief is a chain — posts exactly as before.
"""
import pytest
from shapely.geometry import Polygon

from guildmodel.core.cam.castle_ops import CamOp, CASTLE_OP_TIERS
from guildmodel.core.cam.layout import count_tool_changes, schedule_bed_ops
from guildmodel.core.cam.sequence import order_by_tool_work
from guildmodel.core.cam.temple_ops import TEMPLE_OP_TIERS, generate_temple_program
from guildmodel.core.project.schema import CastleCamParams, TempleParams

TOOLS = {
    "flat_3175": {"name": "flat_3175", "diameter_mm": 3.175, "radius_mm": 1.5875,
                  "type": "flat"},
    "flat_2mm": {"name": "flat_2mm", "diameter_mm": 2.0, "radius_mm": 1.0, "type": "flat"},
    "engrave_vbit": {"name": "engrave_vbit", "diameter_mm": 0.5, "radius_mm": 0.25,
                     "type": "vbit"},
}

OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])
HINGE = [Polygon([(55, -3), (65, -3), (65, 3), (55, 3)])]
SHORT_ENGRAVING = [[(-30.0, 0.0), (0.0, 0.0), (30.0, 0.0)]]


def _op(name, tool, length):
    """An op of one straight cut `length` mm long, on `tool` (a library entry, or
    a stand-in dict for a name the small library here does not carry)."""
    t = (TOOLS.get(tool) or {"name": tool, "radius_mm": 0.5}) if tool else None
    return CamOp(name, paths=[[(0.0, 0.0, 0.0), (float(length), 0.0, 0.0)]], tool=t)


def _names(ops):
    return [op.name for op in ops]


# ------------------------------------------------------------------ the rule

def test_the_least_work_tool_runs_first_within_a_tier():
    ops = [_op("Hinge Pockets", "flat_2mm", 800),
           _op("Engraving", "engrave_vbit", 120),
           _op("Temple Profile", "flat_2mm", 600)]
    out = order_by_tool_work(ops, TEMPLE_OP_TIERS)
    assert _names(out) == ["Engraving", "Hinge Pockets", "Temple Profile"]
    assert count_tool_changes(out) == 1                      # bit → end mill, once
    assert count_tool_changes(ops) == 2                      # what it was


def test_work_is_the_tool_total_over_the_whole_program():
    # The engraving alone is longer than the pockets alone, but the end mill also
    # cuts the profile, so the bit is still the lesser tool and goes first.
    ops = [_op("Hinge Pockets", "flat_2mm", 100),
           _op("Engraving", "engrave_vbit", 300),
           _op("Temple Profile", "flat_2mm", 600)]
    assert _names(order_by_tool_work(ops, TEMPLE_OP_TIERS)) == [
        "Engraving", "Hinge Pockets", "Temple Profile"]
    # ...and with the profile on a third tool the pockets are the lesser tool.
    ops[2] = _op("Temple Profile", "flat_3175", 600)
    assert _names(order_by_tool_work(ops, TEMPLE_OP_TIERS)) == [
        "Hinge Pockets", "Engraving", "Temple Profile"]


def test_the_tiers_hold_the_release_last_and_holes_before_it():
    ops = [_op("Hinge Pockets", "flat_2mm", 800),
           _op("Engraving", "engrave_vbit", 10),
           _op("Holes", "engrave_vbit", 10),        # bit work is tiny, but a hole is a through-cut
           _op("Temple Profile", "flat_2mm", 5)]     # and the profile is last however short
    out = order_by_tool_work(ops, TEMPLE_OP_TIERS)
    assert _names(out) == ["Engraving", "Hinge Pockets", "Holes", "Temple Profile"]


def test_a_single_tool_program_keeps_its_order():
    ops = [_op("Hinge Pockets", "flat_2mm", 10), _op("Engraving", "flat_2mm", 900),
           _op("Temple Profile", "flat_2mm", 100)]
    assert order_by_tool_work(ops, TEMPLE_OP_TIERS) == ops
    untooled = [_op("Hinge Pockets", None, 10), _op("Engraving", None, 900),
                _op("Temple Profile", None, 100)]
    assert order_by_tool_work(untooled, TEMPLE_OP_TIERS) == untooled


def test_an_op_the_tiers_do_not_name_is_a_barrier():
    ops = [_op("Hinge Pockets", "flat_2mm", 800),
           _op("Something New", "flat_3175", 5),
           _op("Engraving", "engrave_vbit", 10),
           _op("Temple Profile", "flat_2mm", 600)]
    out = order_by_tool_work(ops, TEMPLE_OP_TIERS)
    assert _names(out) == _names(ops)                        # nothing crosses it


def test_the_same_objects_come_back():
    ops = [_op("Hinge Pockets", "flat_2mm", 800), _op("Engraving", "engrave_vbit", 10),
           _op("Temple Profile", "flat_2mm", 600)]
    out = order_by_tool_work(ops, TEMPLE_OP_TIERS)
    assert {id(o) for o in out} == {id(o) for o in ops} and len(out) == 3


# ------------------------------------------------------------------ the temple

def test_the_makers_temple_posts_the_bit_first_and_one_change():
    t = TempleParams(hinge_tool="flat_2mm", profile_tool="flat_2mm",
                     engrave_tool="engrave_vbit")
    ops = generate_temple_program(OUTLINE, SHORT_ENGRAVING, t, TOOLS, hinge_polys=HINGE)
    assert _names(ops) == ["Engraving", "Hinge Pockets", "Temple Profile"]
    assert [op.tool_name for op in ops] == ["engrave_vbit", "flat_2mm", "flat_2mm"]
    assert count_tool_changes(ops) == 1


def test_the_default_temple_still_pockets_before_it_engraves_when_that_is_less_work():
    # Enough engraving that the bit outworks the 2 mm pockets: the pockets go first.
    long_engraving = [[(-60.0, y), (60.0, y)] for y in (-4.0, -2.0, 0.0, 2.0, 4.0)] * 8
    ops = generate_temple_program(OUTLINE, long_engraving, TempleParams(), TOOLS,
                                  hinge_polys=HINGE)
    by = {op.name: op for op in ops}
    assert by["Engraving"].path_length_mm() > by["Hinge Pockets"].path_length_mm()
    assert _names(ops) == ["Hinge Pockets", "Engraving", "Temple Profile"]


def test_a_disabled_op_does_not_count_toward_its_tool():
    # With the profile disabled the 2 mm tool's work is the pockets alone, which
    # is less than a long engraving: the pockets go first.
    long_engraving = [[(-60.0, y), (60.0, y)] for y in (-4.0, -2.0, 0.0, 2.0, 4.0)] * 8
    t = TempleParams(hinge_tool="flat_2mm", profile_tool="flat_2mm")
    params = CastleCamParams(op_enabled={"Temple Profile": False})
    ops = generate_temple_program(OUTLINE, long_engraving, t, TOOLS, params=params,
                                  hinge_polys=HINGE)
    assert _names(ops) == ["Hinge Pockets", "Engraving"]


def test_the_bed_inherits_a_components_order():
    temple = [_op("Engraving", "engrave_vbit", 120), _op("Hinge Pockets", "flat_2mm", 800),
              _op("Temple Profile", "flat_2mm", 600)]
    block = [_op("Drill Holes", "flat_2mm", 30), _op("Block Profile", "flat_3175", 400)]
    bed = schedule_bed_ops([temple, block])
    assert _names(bed)[0] == "Engraving"                     # the bit, first on the bed
    assert _names(bed).index("Temple Profile") > _names(bed).index("Hinge Pockets")


# ------------------------------------------------------------------ the front

def test_the_fronts_program_is_a_chain_and_does_not_move():
    ops = [_op("Hinge Pockets", "flat_2mm", 200), _op("Rough Relief", "flat_3175", 9000),
           _op("Fine Relief", "flat_3175", 12000), _op("Features", "ball_1mm", 50),
           _op("Eyewires", "flat_3175", 700), _op("Holes", "flat_3175", 40),
           _op("Lens Groove", "groove_drageoir", 300), _op("Perimeter", "flat_3175", 900)]
    assert _names(order_by_tool_work(ops, CASTLE_OP_TIERS)) == _names(ops)
    # ...with the hinge tool also on the fine relief, so that it outweighs the
    # rough tool: the pockets still go first, into the flat blank
    ops[2].tool = TOOLS["flat_2mm"]
    assert _names(order_by_tool_work(ops, CASTLE_OP_TIERS)) == _names(ops)
    # ...even with the bulk tool pinned onto the pockets (a single-tool relief)
    for op in ops:
        op.tool = TOOLS["flat_3175"]
    assert _names(order_by_tool_work(ops, CASTLE_OP_TIERS)) == _names(ops)


def test_an_untooled_op_is_not_the_tool_already_loaded():
    # Before the first op nothing is in the spindle: an op with no tool must be
    # ranked by its work like any other, not taken for the current tool.
    ops = [_op("Hinge Pockets", "flat_2mm", 100), _op("Engraving", None, 900),
           _op("Temple Profile", "flat_2mm", 600)]
    assert _names(order_by_tool_work(ops, TEMPLE_OP_TIERS)) == [
        "Hinge Pockets", "Engraving", "Temple Profile"]
