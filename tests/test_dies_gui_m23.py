"""The press dies on the Forming panel (BUILDPLAN M23), without a window:
the fold's controls round-trip `PressDieParams`, ride on the forming the
panel hands back, and say when they moved."""
import pytest

from guildmodel.core.project.schema import FormingMetadata, PressDieParams

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def panel(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.forming_panel import FormingPanel
    return FormingPanel()


def test_the_dies_fold_round_trips_its_parameters(panel):
    assert panel.dies() == PressDieParams()
    heard = []
    panel.dies_changed.connect(lambda: heard.append(1))
    d = PressDieParams(mode="pre_cut", mat_thickness_mm=4.5, clearance_mm=0.12, over_bend=0.98,
                       face_form_in_die=False, bridge_in_die=True, cutaways=False,
                       relief_depth_mm=1.5, relief_rim_mm=6.0, trim_mm=8.0, margin_mm=12.0,
                       flange_mm=15.0, flange_thickness_mm=10.0, draft_deg=3.0, dowel_mm=8.0,
                       dowel_fit_mm=0.2, vent_mm=1.5, mounting_pattern=True,
                       punch_radius_mm=12.0, v_angle_deg=30.0, export_with_all=True)
    panel.set_dies(d)
    assert heard == []                                   # a restore says nothing
    assert panel.dies() == d
    panel.die_mat.setValue(2.0)
    assert heard == [1] and panel.dies().mat_thickness_mm == 2.0
    panel.die_cutaways.setChecked(True)
    assert heard == [1, 1] and panel.dies().cutaways


def test_the_dies_ride_with_the_forming(panel):
    base = FormingMetadata()
    panel.set_forming(base.with_base_curve(4.0, 172.0, dies=PressDieParams(mat_thickness_mm=5.0).model_dump()))
    assert panel.die_mat.value() == 5.0
    panel.die_over_bend.setValue(0.97)
    forming = panel.forming(base)
    assert forming.dies.mat_thickness_mm == 5.0 and forming.dies.over_bend == 0.97
    assert forming.base_curve == 4.0
    # a forming from before M23 reads as the default dies
    old = FormingMetadata.model_validate({"base_curve": 6.0})
    panel.set_forming(old)
    assert panel.dies() == PressDieParams()
    panel.set_die_readout("Closed gap 7.88 mm")
    assert panel.die_readout.text() == "Closed gap 7.88 mm"
