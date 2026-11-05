"""The draft view in the window (2.3): View ▸ Draft on D, the panel under
the viewer, the assembly in the viewer's formed slot, the targets written
to the project, the Temple tab's Forming section, the blueprint written,
Preferences ▸ Forming and ▸ Blueprint, and the project's round trip."""
import os
import time
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

FIXTURES = Path(__file__).parent / "fixtures"
PRESET = "SBT base 4 / lens 4"


def _qt(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _gabriel(tmp_path) -> Path:
    path = tmp_path / "gabriel.gdraw"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted((FIXTURES / "gabriel").iterdir()):
            zf.write(f, f.name)
    return path


def _pump(app, until, timeout=60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(scope="module")
def gabriel_built(tmp_path_factory):
    from guildmodel.gui.component_workspace import build_workspaces_from_gdraw
    from guildmodel.gui.mesh_build import build_component_mesh

    path = _gabriel(tmp_path_factory.mktemp("gabriel"))
    ws = build_workspaces_from_gdraw(path)[0][0]
    spec = {"mode": "castle", "kind": "frame_front", "label": "Frame Front",
            "partition": ws.partition, "castle": ws.castle_params,
            "hinge": list(ws.hinge_polys), "stage": "pockets"}
    mesh, edges, _ = build_component_mesh(spec, resolution=0.3, kernel="mesh")
    return mesh, edges


def _window(monkeypatch, tmp_path):
    _qt(monkeypatch, tmp_path)
    try:
        from guildmodel.gui.app import MainWindow
        return MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")


class _Recorder:
    def __init__(self):
        self.calls = []
        self.formed_active = False

    def show_formed(self, mesh, edges=None, badge="", ghost=False, normals=None):
        self.calls.append(("formed", mesh, badge))
        self.formed_active = True

    def show_flat(self):
        self.calls.append(("flat",))
        self.formed_active = False

    @property
    def badges(self):
        return [c[2] for c in self.calls if c[0] == "formed"]


def _record_viewer(monkeypatch, win) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(win.view3d, "show_formed", rec.show_formed)
    monkeypatch.setattr(win.view3d, "show_flat", rec.show_flat)
    monkeypatch.setattr(win.view3d, "show_mesh", lambda *a, **k: None)
    monkeypatch.setattr(type(win.view3d), "formed_active",
                        property(lambda self: rec.formed_active))
    return rec


@pytest.mark.gui
def test_draft_is_a_registered_view_action_on_d(tmp_path, monkeypatch):
    win = _window(monkeypatch, tmp_path)
    assert win._actions_by_key["draft"] is win._act_draft
    assert win._act_draft.shortcut().toString() == "D"
    assert win._act_draft.isCheckable() and not win._act_draft.isEnabled()
    assert win._actions_by_key["blueprint"] is win._act_blueprint
    assert win._draft_panel.isHidden()


@pytest.mark.gui
def test_pressing_d_assembles_the_frame_and_the_targets_reach_the_project(
        tmp_path, monkeypatch, gabriel_built):
    from PySide6.QtWidgets import QApplication
    win = _window(monkeypatch, tmp_path)
    app = QApplication.instance()
    win._load_model(_gabriel(tmp_path))
    assert win._act_draft.isEnabled() and win._act_blueprint.isEnabled()
    # a new project's targets come from Preferences ▸ Blueprint
    assert win._workspaces[0].forming.pantoscopic_tilt_deg == 8.0
    assert win._draft.splay_deg == 0.0
    rec = _record_viewer(monkeypatch, win)
    mesh, edges = gabriel_built
    win._switch_view(1)
    win._on_mesh_finished(mesh, "pockets", edges)
    win._clear_dirty()

    win._act_draft.setChecked(True)
    assert rec.badges[-1].startswith("DRAFT · side 8.0° · splay 0.0° · Rivet")
    assert not win._draft_panel.isHidden() and win._forming_panel.isHidden()
    assert not win._dirty, "looking is not editing"
    scene = [c[1] for c in rec.calls if c[0] == "formed"][-1]
    lo, hi = scene.bounds
    assert hi[2] - lo[2] > 100.0, "the temples run back from the front"
    assert "hinge" in win._draft_panel.side_readout.text()
    assert "checks pass" in win._draft_panel.checks.text()

    # the splay and the angle of side, into the project and the front
    panel = win._draft_panel
    panel.splay.setValue(3.0)
    app.processEvents()
    assert win._draft.splay_deg == 3.0 and win._dirty
    panel.side.setValue(10.0)
    app.processEvents()
    assert win._workspaces[0].forming.pantoscopic_tilt_deg == 10.0
    assert rec.badges[-1].startswith("DRAFT · side 10.0° · splay 3.0°")
    panel.kind.setCurrentIndex(panel.kind.findData("spring"))
    app.processEvents()
    assert win._draft.hinge.kind.value == "spring" and "Spring" in rec.badges[-1]
    # the panel's tip bend reaches both temples
    panel.bend_angle.setValue(40.0)
    app.processEvents()
    for ws in win._temple_workspaces():
        assert ws.temple_params.tip_bend.drop_angle_deg == 40.0

    # Forming and Draft are one slot
    win._act_forming.setChecked(True)
    assert not win._act_draft.isChecked() and win._draft_panel.isHidden()
    assert rec.badges[-1].startswith("FORMED")
    win._act_draft.setChecked(True)
    assert not win._act_forming.isChecked() and rec.badges[-1].startswith("DRAFT")

    # off: the flat model from cache
    win._act_draft.setChecked(False)
    assert rec.calls[-1] == ("flat",) and win._draft_panel.isHidden()

    # the round trip
    proj = win._build_project_schema()
    assert proj.draft.splay_deg == 3.0 and proj.draft.hinge.kind.value == "spring"
    assert proj.components[0].forming.pantoscopic_tilt_deg == 10.0
    assert proj.components[1].temple.tip_bend.drop_angle_deg == 40.0
    gm = tmp_path / "draft.gmodel"
    win._write_gmodel(gm)
    win2 = _window(monkeypatch, tmp_path)
    monkeypatch.setattr(win2.view3d, "show_mesh", lambda *a, **k: None)
    win2._open_project(gm)
    assert win2._draft.splay_deg == 3.0 and win2._draft.hinge.kind.value == "spring"
    assert win2._workspaces[0].forming.pantoscopic_tilt_deg == 10.0
    assert win2._workspaces[1].temple_params.tip_bend.drop_angle_deg == 40.0
    _pump(app, lambda: not win._formed_build_busy(), 30)


@pytest.mark.gui
def test_the_temple_tab_carries_the_tip_bend(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    win = _window(monkeypatch, tmp_path)
    app = QApplication.instance()
    win._load_model(_gabriel(tmp_path))
    win._activate_workspace(1)
    readout = win.params.temple_bend_readout.text()
    assert "Ear point" in readout and "(auto)" in readout and "drop 37.0 mm" in readout
    win._clear_dirty()
    win.params.temple_bend_angle.setValue(0.0)
    app.processEvents()
    assert win._dirty and win.params.temple_bend_readout.text().startswith("Straight")
    assert win.params.temple_params().tip_bend.drop_angle_deg == 0.0
    win.params.temple_bend_length.setValue(200.0)
    app.processEvents()
    win.params.temple_bend_angle.setValue(50.0)
    app.processEvents()
    assert win.params.temple_bend_readout.text().startswith("Out of range")
    assert "Forming" in win.params._folds or "Tip Bend" in win.params._folds


@pytest.mark.gui
def test_the_blueprint_is_written_from_the_dialog(tmp_path, monkeypatch, gabriel_built):
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog
    from guildmodel.gui import blueprint_dialog
    win = _window(monkeypatch, tmp_path)
    app = QApplication.instance()
    win._load_model(_gabriel(tmp_path))
    _record_viewer(monkeypatch, win)
    mesh, edges = gabriel_built
    win._switch_view(1)
    win._on_mesh_finished(mesh, "pockets", edges)
    out = tmp_path / "gabriel_blueprint.pdf"

    class _Dlg(blueprint_dialog.BlueprintDialog):
        def exec(self):
            self.editor.owner.setText("Guild")
            self.editor.paper.setCurrentIndex(self.editor.paper.findData("a3"))
            self.defaults_check.setChecked(True)
            self.action = "pdf"
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(blueprint_dialog, "BlueprintDialog", _Dlg)
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "PDF files (*.pdf)")))
    win._on_export_blueprint()
    # composed on a worker under the progress dialog; the file follows
    assert win._progress_dialog is not None and win._progress_owner == "blueprint"
    assert _pump(app, lambda: out.exists(), 120), "the blueprint never landed"
    assert out.read_bytes().startswith(b"%PDF")
    _pump(app, lambda: win._blueprint_thread is None or not win._blueprint_thread.isRunning(), 30)
    assert win._progress_dialog is None
    assert win._draft.blueprint.owner == "Guild" and win._draft.blueprint.paper == "a3"
    # the defaults were adopted, the design's cells left out
    from guildmodel.gui import prefs as prefs_mod
    saved = prefs_mod.load()["draft"]["blueprint"]
    assert saved["owner"] == "Guild" and saved["paper"] == "a3"
    assert "design_name" not in saved and "issue_date" not in saved
    assert "Blueprint written" in win.status_lbl.text()
    _pump(app, lambda: not win._formed_build_busy(), 30)


@pytest.mark.gui
def test_preferences_carry_forming_and_blueprint(tmp_path, monkeypatch):
    from guildmodel.gui import prefs as prefs_mod
    from guildmodel.gui.app import PrefsDialog
    # a fresh prefs file: the blueprint test above adopted defaults into
    # the run's shared one
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    win = _window(monkeypatch, tmp_path)
    dlg = PrefsDialog(win._prefs, win)
    dlg._neutral_fraction.setValue(0.5)
    dlg._tooling_index.setValue(1.6)
    dlg._draft_defaults.side.setValue(10.0)
    dlg._blueprint_defaults.projection.setCurrentIndex(
        dlg._blueprint_defaults.projection.findData("first"))
    p = dlg.to_prefs()
    assert p["forming"] == {"tooling_index": 1.6, "sheet_thickness_mm": 6.0,
                            "neutral_fraction": 0.5}
    assert p["draft"]["angle_of_side_deg"] == 10.0
    assert p["draft"]["blueprint"] == {"projection": "first"}
    assert p["draft"]["hinge"] == {}
    # the forming panel's custom radius follows the index
    win._prefs.update(p)
    win._forming_panel.set_tooling_index(1.6)
    win._forming_panel.base_curve.setValue(4.0)
    assert win._forming_panel.radius_readout.text() == "R 150 mm"
    # and the active forming carries the neutral surface
    win._load_model(_gabriel(tmp_path))
    assert win._active_forming().neutral_fraction == 0.5
