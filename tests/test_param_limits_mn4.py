"""Bounds on what a parameter is allowed to be (BUILDPLAN-NEW M-N4, sliders).

Sweeping the panel's own spin-box ranges on all three fixtures (2026-08-10)
turned up three ways to ask for something the maker cannot have, none of which
anything in the toolchain caught:

  * **Stock is invisible to the model.** A 15 mm nosepad out of a 6 + 4 mm stack
    builds a clean, watertight, verified solid. Nothing between the drawing and
    the G-code ever compares a zone height to the material it is cut from.
  * **A hinge pocket can come out of the front of the frame.** On the demo at a
    5.5 mm endpiece the removed volume stops changing at 5.5 mm of depth
    (7362.9 mm3 at 5.5, 6.0 and 8.0) — by then the pocket is a through hole.
  * **A lens groove can dissolve the castle**, at 1.55 mm on the gabriel and
    1.90 mm on the aviator, both inside the 0.2–2.0 mm the panel offered. The
    guard that fires there was itself raising `NameError` rather than the
    sentence it meant to; that is the last test in this file.

`core.project.limits` derives the safe range for each. These are its gates.
"""
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

#: The groove depth the panel offers. `max_groove_depth` returning less than
#: this is the whole point on two of the three drawings.
GROOVE_PANEL_MAX_MM = 2.0


def _from_gdraw(name, tmp_path_factory):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

    path = tmp_path_factory.mktemp(name) / f"{name}.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / name).iterdir()):
            zf.write(f, f.name)
    return build_workspaces_from_gdraw(path)[0][0]


@pytest.fixture(scope="module")
def fronts(tmp_path_factory):
    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)

    layers, curves = import_curves(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    demo = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="",
                              layers=layers, curves=curves)
    derive_workspace(demo)
    return {"demo": demo,
            "gabriel": _from_gdraw("gabriel", tmp_path_factory),
            "aviator": _from_gdraw("aviator", tmp_path_factory)}


# ------------------------------------------------------------------ stock

def test_a_nosepad_cannot_be_taller_than_the_stack_it_is_cut_from():
    """The case that started this: 10 mm of nosepad out of 6 + 4 mm of material.

    Exactly at the ceiling, which is why the shipped default is 10.0 — the pad
    block is sized for the towers it exists to carry.
    """
    from guildmodel.core.project.limits import castle_limits
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    assert castle.stock.blank_thickness_mm == 6.0
    assert castle.stock.pad_block_thickness_mm == 4.0

    limit = castle_limits(castle)["zones.nosepad_mm"]
    assert limit.high == pytest.approx(10.0)
    assert limit.holds(castle.zones.nosepad_mm)
    assert not limit.holds(10.5)


@pytest.mark.parametrize("blank,pad,use_pad,expected", [
    (6.0, 4.0, True, 10.0),
    (6.0, 2.0, True, 8.0),
    (4.0, 4.0, True, 8.0),
    (6.0, 4.0, False, 6.0),     # no pad block: the blank is all there is
])
def test_the_nosepad_ceiling_follows_the_entered_stock(blank, pad, use_pad, expected):
    from guildmodel.core.project.limits import castle_limits
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    castle.stock.blank_thickness_mm = blank
    castle.stock.pad_block_thickness_mm = pad
    castle.stock.use_pad_block = use_pad
    assert castle_limits(castle)["zones.nosepad_mm"].high == pytest.approx(expected)


def test_a_zone_lapping_over_the_pad_block_only_gets_the_blank(fronts):
    """Overlap is worth nothing: the part hanging off the block has blank under it.

    Measured with the default 45x45 pad — bridge and both nosepads sit wholly on
    it, the eyewires lap over (18–44% of their area on the pad, on all three
    drawings) and the endpieces are entirely off. So the eyewires answer to the
    6 mm blank however much of them is over the block.
    """
    from guildmodel.core.project.limits import zone_ceilings
    from guildmodel.core.project.schema import StockDefinition

    stock = StockDefinition()
    for name, front in fronts.items():
        ceilings = zone_ceilings(stock, front.partition)
        assert ceilings["nosepad"] == pytest.approx(10.0), name
        assert ceilings["bridge"] == pytest.approx(10.0), name
        assert ceilings["endpiece"] == pytest.approx(6.0), name
        assert ceilings["eyewire_inferior"] == pytest.approx(6.0), name
        assert ceilings["eyewire_superior"] == pytest.approx(6.0), name


def test_moving_the_pad_block_off_the_nose_takes_the_ceiling_with_it(fronts):
    """The ceiling is measured, not assumed from the zone's name."""
    from guildmodel.core.project.limits import zone_ceilings
    from guildmodel.core.project.schema import StockDefinition

    stock = StockDefinition(pad_block_dy_mm=60.0)     # shoved off the nose
    ceilings = zone_ceilings(stock, fronts["demo"].partition)
    assert ceilings["nosepad"] == pytest.approx(6.0)


def test_the_pad_block_has_to_sit_on_the_blank():
    from guildmodel.core.project.limits import stock_limits
    from guildmodel.core.project.schema import StockDefinition

    limits = stock_limits(StockDefinition(blank_length_mm=60.0, blank_width_mm=40.0))
    assert limits["stock.pad_block_length_mm"].high == pytest.approx(60.0)
    assert limits["stock.pad_block_width_mm"].high == pytest.approx(40.0)


# ------------------------------------------------------------ hinge pocket

def test_a_hinge_pocket_stops_short_of_the_front_face():
    """Measured: at a depth equal to the endpiece height the pocket is a hole,
    and cutting deeper removes nothing more."""
    from guildmodel.core.project.limits import MIN_POCKET_FLOOR_MM, castle_limits
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    castle.zones.endpiece_mm = 5.5
    limit = castle_limits(castle)["hinge_pocket_depth_mm"]
    assert limit.high == pytest.approx(5.5 - MIN_POCKET_FLOOR_MM)
    assert not limit.holds(5.5)

    castle.zones.endpiece_mm = 2.0
    assert castle_limits(castle)["hinge_pocket_depth_mm"].high == pytest.approx(1.5)


# ----------------------------------------------------------------- groove

@pytest.mark.parametrize("name,bites", [("demo", False),
                                        ("gabriel", True),
                                        ("aviator", True)])
def test_the_groove_depth_ceiling_is_a_depth_that_actually_works(fronts, name, bites):
    """The ceiling has to be measured per drawing, and it has to be *reachable*.

    Two claims. The depth handed back re-partitions the castle — a ceiling that
    is itself broken is worse than none. And on the gabriel and the aviator it
    lands below 2.0 mm, which is where the panel's own range ended: those two
    drawings could be broken from the GUI before this existed.
    """
    from guildmodel.core.geometry.rings import lip_partition
    from guildmodel.core.project.limits import max_groove_depth

    partition = fronts[name].partition
    ceiling = max_groove_depth(partition, high=GROOVE_PANEL_MAX_MM)
    assert ceiling > 0.0

    lip = lip_partition(partition, ceiling)          # must not raise
    assert lip.classified
    assert len(lip.zones) == len(partition.zones)

    assert (ceiling < GROOVE_PANEL_MAX_MM) is bites


def test_the_v_has_to_fit_between_the_front_face_and_the_wall_top():
    """`cam.castle_ops.groove_warnings`' two conditions, as a range instead of a
    sentence printed after the toolpath was posted."""
    from guildmodel.core.project.limits import castle_limits
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    wall = min(castle.zones.eyewire_superior_mm, castle.zones.eyewire_inferior_mm)
    castle.lens_groove.width_mm = 2.0

    offset = castle_limits(castle)["lens_groove.anterior_offset_mm"]
    assert offset.low == pytest.approx(1.0)              # half the V clears Z = 0
    assert offset.high == pytest.approx(wall - 1.0)      # and the wall top
    assert offset.holds(castle.lens_groove.anterior_offset_mm)

    width = castle_limits(castle)["lens_groove.width_mm"]
    assert width.high == pytest.approx(2.0 * min(1.5, wall - 1.5))


# ----------------------------------------------------------- edge features

def test_a_chamfer_is_bounded_by_the_wall_it_runs_along():
    """A chamfer of width w at angle a drops w*tan(a). Measured on the demo: a
    12 mm posterior chamfer at 45 degrees on the 4.8 mm brow builds a solid that
    overlaps itself along 3 edges and will not export as valid STL."""
    from guildmodel.core.project.limits import edge_feature_limits
    from guildmodel.core.project.schema import CastleParams, EdgeFeature

    castle = CastleParams()
    wall = castle.zones.eyewire_superior_mm
    brow = EdgeFeature(id="brow", label="Brow", face="posterior", edge="outline",
                       zones=["eyewire_superior_od"], profile="chamfer",
                       width_mm=6.0, angle_deg=45.0, min_thickness_mm=0.0)

    limits = edge_feature_limits(castle, brow)
    assert limits["width_mm"].high == pytest.approx(wall)     # tan(45) == 1
    assert not limits["width_mm"].holds(12.0)
    assert limits["radius_mm"].high == pytest.approx(wall)
    assert limits["min_thickness_mm"].high == pytest.approx(wall)


def test_reserving_thickness_spends_the_same_budget():
    """`min_thickness_mm` is material the feature may not touch, so it comes
    straight off what the width is allowed to be."""
    from guildmodel.core.project.limits import edge_feature_limits
    from guildmodel.core.project.schema import CastleParams, EdgeFeature

    castle = CastleParams()
    brow = EdgeFeature(id="brow", label="Brow", face="posterior", edge="outline",
                       zones=["eyewire_superior_od"], profile="chamfer",
                       width_mm=2.0, angle_deg=45.0, min_thickness_mm=2.5)
    assert edge_feature_limits(castle, brow)["width_mm"].high == pytest.approx(2.3)


def test_a_steeper_chamfer_narrows_the_width_it_allows():
    """The three are one budget seen from three sides, which is why each is
    re-derived from the others' current values after every change."""
    from guildmodel.core.project.limits import edge_feature_limits
    from guildmodel.core.project.schema import CastleParams, EdgeFeature

    castle = CastleParams()
    shallow = EdgeFeature(id="a", label="a", face="posterior", edge="outline",
                          zones=["eyewire_superior_od"], profile="chamfer",
                          width_mm=2.0, angle_deg=20.0, min_thickness_mm=0.0)
    steep = shallow.model_copy(update={"angle_deg": 70.0})
    assert (edge_feature_limits(castle, steep)["width_mm"].high
            < edge_feature_limits(castle, shallow)["width_mm"].high)


# --------------------------------------------------------------- invariant

def test_no_shipped_default_starts_out_of_range():
    """A fresh project must not open covered in warnings.

    The invariant that keeps this module honest as the schema moves: every
    default `CastleParams` value sits inside the range this module derives for
    it. It is also the reason the nosepad ceiling reads 10.0 and not 9.9 — the
    default *is* the ceiling, deliberately.
    """
    from guildmodel.core.project.limits import castle_limits
    from guildmodel.core.project.schema import CastleParams

    castle = CastleParams()
    values = {
        "zones.endpiece_mm": castle.zones.endpiece_mm,
        "zones.bridge_mm": castle.zones.bridge_mm,
        "zones.nosepad_mm": castle.zones.nosepad_mm,
        "zones.eyewire_superior_mm": castle.zones.eyewire_superior_mm,
        "zones.eyewire_inferior_mm": castle.zones.eyewire_inferior_mm,
        "hinge_pocket_depth_mm": castle.hinge_pocket_depth_mm,
        "pad_splay.anterior_clamp_mm": castle.pad_splay.anterior_clamp_mm,
        "eyewire_bezel.anterior_clamp_mm": castle.eyewire_bezel.anterior_clamp_mm,
        "bridge_relief.anterior_clamp_mm": castle.bridge_relief.anterior_clamp_mm,
        "bridge_relief.depth_mm": castle.bridge_relief.depth_mm,
        "lens_groove.anterior_offset_mm": castle.lens_groove.anterior_offset_mm,
        "lens_groove.width_mm": castle.lens_groove.width_mm,
        "stock.pad_block_length_mm": castle.stock.pad_block_length_mm,
        "stock.pad_block_width_mm": castle.stock.pad_block_width_mm,
    }
    limits = castle_limits(castle)
    outside = [(path, value, limits[path])
               for path, value in values.items() if not limits[path].holds(value)]
    assert outside == []


# ---------------------------------------------------------------- the bug

def test_the_groove_guard_raises_its_own_sentence(fronts):
    """`lip_partition`'s guard raised `NameError: name 'BooleanError' is not
    defined` — the class lives in `solid/occ.py`, which this module cannot import
    without pulling in the 264 MB it exists to avoid, and nothing swallowed it.

    Reachable from the panel on two of the three fixtures. The class moved to
    `geometry/rings.py`; `occ` re-exports it, so `core/solid` catches the same
    object it always did.
    """
    from guildmodel.core.geometry.rings import BooleanError, lip_partition
    from guildmodel.core.project.limits import max_groove_depth

    partition = fronts["gabriel"].partition
    past_it = max_groove_depth(partition, high=GROOVE_PANEL_MAX_MM) + 0.5

    with pytest.raises(BooleanError) as caught:
        lip_partition(partition, past_it)
    assert "rim lip" in str(caught.value)


def test_the_two_kernels_still_catch_the_same_class():
    """`core/solid` is full of `except BooleanError`. Moving the class must not
    have left it catching a different one from the one now raised."""
    pytest.importorskip("OCP", reason="cadquery-ocp not installed")
    from guildmodel.core.geometry.rings import BooleanError as shared
    from guildmodel.core.solid import BooleanError as from_package
    from guildmodel.core.solid.occ import BooleanError as from_occ

    assert shared is from_package is from_occ


def test_deriving_a_limit_does_not_load_a_kernel():
    """`core.project.limits` is read by the GUI on every keystroke. It may not
    drag in Manifold, OCCT, or the CAM to answer a question about millimetres."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c",
         "import sys\n"
         "from guildmodel.core.project import limits\n"
         "from guildmodel.core.project.schema import CastleParams\n"
         "limits.castle_limits(CastleParams())\n"
         "bad = [m for m in sys.modules if m.split('.')[0] in ('OCP', 'manifold3d')]\n"
         "print(','.join(sorted(bad)))"],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "", out.stdout
