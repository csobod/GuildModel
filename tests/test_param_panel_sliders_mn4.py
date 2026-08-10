"""The Model and Stock tabs, once every measurement became draggable (M-N4).

`core.project.limits` derives the ranges and `ParamSlider` presents them; this
is the part in between — which control each rule lands on, and when the panel
asks again. The rules move constantly: the nosepad's ceiling follows the stock,
the hinge pocket's follows the endpiece above it, and an edge feature's follows
whichever wall the *selected* feature runs along.

The exclusions are pinned too. Cut and Machine keep plain spin boxes on purpose
— a feed rate is a decision, not a shape, and there is nothing to scrub for —
and a test says so, because "some of them are sliders" is otherwise indis-
tinguishable from "the conversion was left half done".
"""
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def demo_partition():
    from guildmodel.core.io_import.dxf import import_curves
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import (ComponentWorkspace,
                                                    derive_workspace)

    layers, curves = import_curves(FIXTURES / "demo" / "GuildDraw DXF Export.dxf")
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="",
                            layers=layers, curves=curves)
    derive_workspace(ws)
    return ws.partition


@pytest.fixture
def panel(qt_app):
    from guildmodel.gui.widgets.params_panel import ParamsPanel

    return ParamsPanel()


@pytest.fixture
def drawn(panel, demo_partition):
    """A panel with a drawing in it — the only state in which an edge feature's
    span means anything, since the zone picker lists this drawing's zones."""
    panel.set_zones(demo_partition)
    return panel


def _slider_paths(panel):
    from guildmodel.gui.widgets.param_slider import ParamSlider

    return {path: w for path, w in panel._limit_targets().items()
            if isinstance(w, ParamSlider)}


def test_every_limited_control_is_a_slider(panel):
    """A rule with no slider to land on is a rule that does nothing."""
    assert set(_slider_paths(panel)) == set(panel._limit_targets())


def test_a_fresh_panel_opens_with_nothing_out_of_range(panel):
    assert panel.out_of_range_paths() == []


def test_the_cut_and_machine_tabs_keep_their_spin_boxes(panel):
    """Deliberate, not missed. Sliding a spindle speed buys nothing and makes an
    exact number harder to hit."""
    from PySide6.QtWidgets import QDoubleSpinBox

    for name in ("onion_skin", "hand_allowance", "feed_override",
                 "contour_stepdown", "relief_stepover", "hold_tab_height"):
        assert isinstance(getattr(panel, name), QDoubleSpinBox), name


def test_the_footing_pairs_keep_theirs_too(panel):
    """Two radii share one row — no width for a handle worth dragging, and
    neither has a derived limit to show."""
    from PySide6.QtWidgets import QDoubleSpinBox

    for ext, inner in panel.footing_spins.values():
        assert isinstance(ext, QDoubleSpinBox)
        assert isinstance(inner, QDoubleSpinBox)


# --------------------------------------------------------------- live rules

def test_the_nosepad_ceiling_follows_the_stock_the_maker_entered(panel):
    """The case this work started from: 10 mm of tower needs 6 + 4 mm of stack."""
    assert panel.zone_nosepad.safe_range()[1] == pytest.approx(10.0)

    panel.pad_thickness.setValue(2.0)
    assert panel.zone_nosepad.safe_range()[1] == pytest.approx(8.0)

    panel.use_pad_block.setChecked(False)
    assert panel.zone_nosepad.safe_range()[1] == pytest.approx(6.0)


def test_shrinking_the_stock_marks_the_tower_instead_of_shortening_it(panel):
    """The whole reason the spin box keeps the hard range."""
    panel.blank_thickness.setValue(4.0)
    panel.pad_thickness.setValue(2.0)

    assert panel.zone_nosepad.value() == pytest.approx(10.0)
    assert panel.zone_nosepad.out_of_range()
    assert "zones.nosepad_mm" in dict(panel.out_of_range_paths())


def test_the_handle_stops_exactly_at_the_material(panel):
    panel.blank_thickness.setValue(5.0)
    panel.pad_thickness.setValue(3.0)
    panel.zone_nosepad.setValue(4.0)         # start inside, then drag up
    panel.zone_nosepad.slider.setValue(panel.zone_nosepad.slider.maximum())
    assert panel.zone_nosepad.value() == pytest.approx(8.0)


def test_the_hinge_pocket_follows_the_endpiece_above_it(panel):
    from guildmodel.core.project.limits import MIN_POCKET_FLOOR_MM

    panel.zone_endpiece.setValue(2.0)
    assert panel.hinge_pocket_depth.safe_range()[1] == pytest.approx(
        2.0 - MIN_POCKET_FLOOR_MM)

    panel.hinge_pocket_depth.slider.setValue(panel.hinge_pocket_depth.slider.maximum())
    assert panel.hinge_pocket_depth.value() < panel.zone_endpiece.value()


def test_the_pad_block_cannot_be_dragged_off_the_blank(panel):
    panel.blank_length.setValue(60.0)
    panel.pad_length.slider.setValue(panel.pad_length.slider.maximum())
    assert panel.pad_length.value() <= 60.0


def test_the_groove_v_follows_the_wall_it_is_cut_into(panel):
    panel.zone_eyewire_inferior.setValue(3.0)
    panel.zone_eyewire_superior.setValue(3.0)
    panel.groove_width.setValue(2.0)
    low, high = panel.groove_offset.safe_range()
    assert low == pytest.approx(1.0)
    assert high == pytest.approx(2.0)


def test_the_edge_editor_answers_to_the_selected_feature(drawn):
    """Two features on two different walls get two different ceilings, and
    switching rows has to re-ask."""
    from guildmodel.core.project.schema import EdgeFeature

    def feature(fid, zone):
        return EdgeFeature(id=fid, label=fid, face="posterior", edge="outline",
                           zones=[zone], profile="chamfer", width_mm=1.0,
                           angle_deg=45.0, min_thickness_mm=0.0)

    drawn.zone_eyewire_superior.setValue(6.0)
    drawn.zone_eyewire_inferior.setValue(2.0)
    drawn.set_edge_features([feature("brow", "eyewire_superior_od"),
                             feature("lower", "eyewire_inferior_od")])

    drawn.edge_list.setCurrentRow(0)
    tall = drawn.ef_width.safe_range()[1]
    drawn.edge_list.setCurrentRow(1)
    short = drawn.ef_width.safe_range()[1]

    assert tall == pytest.approx(6.0)
    assert short == pytest.approx(2.0)


def test_reserving_thickness_immediately_narrows_the_width(drawn):
    """The three numbers are one budget, re-derived after every change."""
    from guildmodel.core.project.schema import EdgeFeature

    drawn.zone_eyewire_superior.setValue(5.0)
    drawn.set_edge_features([EdgeFeature(
        id="brow", label="brow", face="posterior", edge="outline",
        zones=["eyewire_superior_od"], profile="chamfer", width_mm=1.0,
        angle_deg=45.0, min_thickness_mm=0.0)])
    drawn.edge_list.setCurrentRow(0)
    assert drawn.ef_width.safe_range()[1] == pytest.approx(5.0)

    drawn.ef_min_thickness.setValue(2.0)
    assert drawn.ef_width.safe_range()[1] == pytest.approx(3.0)


# -------------------------------------------------------------------- load

def test_opening_a_project_that_no_longer_fits_says_so(panel):
    """A stock change between sessions must not edit the frame on the way in."""
    from guildmodel.core.project.schema import CastleParams

    saved = CastleParams()
    saved.zones.nosepad_mm = 10.0
    saved.stock.blank_thickness_mm = 4.0
    saved.stock.pad_block_thickness_mm = 2.0

    panel.set_castle_params(saved)

    assert panel.zone_nosepad.value() == pytest.approx(10.0)
    assert panel.castle_params().zones.nosepad_mm == pytest.approx(10.0)
    assert panel.zone_nosepad.out_of_range()


def test_a_round_trip_through_the_panel_changes_nothing(panel):
    """`castle_params` must still be the exact snapshot it was before any of the
    controls grew a handle."""
    from guildmodel.core.project.schema import CastleParams

    before = CastleParams()
    panel.set_castle_params(before)
    assert panel.castle_params() == before
