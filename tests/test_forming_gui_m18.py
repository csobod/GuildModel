"""Forming preview and formed STL (BUILDPLAN M18) — the window and the panel.

The core half is `test_forming_m18`. This half drives the wiring: the action
and its key, the panel's round trip, what a settled value does to the
component and the project, what a drag does not do, and the three things
that must stay untouched — the readiness dot, the stored program, and the
castle the CAM reads.

No triangle is rendered here: the viewer's `show_formed` / `show_flat` are
recorded rather than run, because an offscreen VTK has no GL context. The
warp itself runs for real on the gabriel fixture, so the badge and the
readout are the real ones.
"""
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
    """The fixture's front, built once through the choke point."""
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
    """Stands in for the viewer's two formed-scene calls."""

    def __init__(self):
        self.calls = []
        self.formed_active = False

    def show_formed(self, mesh, edges=None, badge="", ghost=False, normals=None):
        self.calls.append(("formed", mesh, edges, badge, ghost, normals))
        self.formed_active = True

    def show_flat(self):
        self.calls.append(("flat",))
        self.formed_active = False

    @property
    def badges(self):
        return [c[3] for c in self.calls if c[0] == "formed"]


def _record_viewer(monkeypatch, win) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr(win.view3d, "show_formed", rec.show_formed)
    monkeypatch.setattr(win.view3d, "show_flat", rec.show_flat)
    monkeypatch.setattr(win.view3d, "show_mesh", lambda *a, **k: None)
    monkeypatch.setattr(type(win.view3d), "formed_active",
                        property(lambda self: rec.formed_active))
    return rec


# ------------------------------------------------------------------ the action

@pytest.mark.gui
def test_forming_is_a_registered_view_action_on_f(tmp_path, monkeypatch):
    win = _window(monkeypatch, tmp_path)
    specs = {s.key: s for s in win._action_specs}
    assert specs["forming"].default_shortcut == "F"
    assert specs["forming"].group == "view"
    assert specs["forming"].toolbar_default is True
    assert specs["export_formed"].group == "build"
    assert specs["export_formed"].default_shortcut == ""
    # in the window, so the key fires; with its icon, in the house style
    assert win._act_forming in win.actions()
    names = {name for _act, name in win._icon_actions}
    assert "view-forming" in names
    icon = Path(__file__).parents[1] / "src" / "guildmodel" / "gui" / "resources" / "icons" / "view-forming.svg"
    text = icon.read_text(encoding="utf-8")
    assert 'viewBox="0 0 20 20"' in text and 'stroke="currentColor"' in text
    # nothing loaded: inert
    assert not win._act_forming.isEnabled()
    assert not win._act_export_formed.isEnabled()
    assert win._forming_panel.isHidden()


# ------------------------------------------------------------------ the flow

@pytest.mark.gui
def test_pressing_f_forms_the_front_and_touches_nothing_a_machine_reads(
        tmp_path, monkeypatch, gabriel_built):
    """§0.6's exit criteria, headless: F, the preset, the drag, off — and
    the readiness dot, the stored-program flag and the castle's own groove
    setting are exactly what they were."""
    from PySide6.QtWidgets import QApplication

    win = _window(monkeypatch, tmp_path)
    app = QApplication.instance()
    win._load_model(_gabriel(tmp_path))
    assert win._act_forming.isEnabled()
    assert win._act_export_formed.isEnabled()
    rec = _record_viewer(monkeypatch, win)

    mesh, edges = gabriel_built
    win._switch_view(1)
    win._on_mesh_finished(mesh, "pockets", edges)
    dot, stored = win.readiness._state, win._program_stored
    castle_before = win.params.castle_params()
    assert castle_before.lens_groove.enabled is False
    win._clear_dirty()

    # F
    win._act_forming.setChecked(True)
    assert rec.badges[-1] == "FORMED · Flat"
    assert not win._forming_panel.isHidden()
    assert win._workspaces[0].forming.is_flat
    assert not win._dirty, "looking is not editing"

    # the press
    panel = win._forming_panel
    panel.press.setCurrentIndex(panel.press.findText(PRESET))
    assert rec.badges[-1] == "FORMED · SBT base 4 · 4.00 D · 164° · +0 mm"
    f = win._workspaces[0].forming
    assert f.press_preset == PRESET and f.base_curve == 4.0
    assert f.base_radius_mm == 144.0, "on a press row the die's own radius"
    assert f.face_form_deg == pytest.approx(163.97)
    assert f.crease_gap_mm == pytest.approx(19.5, abs=0.1), "seeded from the drawing"
    assert win._dirty

    # the groove override: the Model tab's groove is off and the panel's is
    # on, so a base with the groove is built once, off-thread
    assert _pump(app, lambda: win._formed_source is not None), "override never landed"
    assert win.params.castle_params().lens_groove.enabled is False

    # the drag: every tick re-forms, nothing is written until release
    slider = panel.projection.slider
    n = len(rec.badges)
    slider.sliderPressed.emit()
    for v in range(1, 41):
        slider.setValue(v)
        app.processEvents()
        assert win._workspaces[0].forming.bridge_projection_mm == 0.0
    assert len(rec.badges) - n >= 40
    slider.sliderReleased.emit()
    app.processEvents()
    assert win._workspaces[0].forming.bridge_projection_mm == 4.0
    assert rec.badges[-1] == "FORMED · SBT base 4 · 4.00 D · 164° · +4 mm"
    readout = panel.readout.text()
    assert "mm deep" in readout and "bridge" in readout and "forward" in readout
    # §0.4's gabriel row on the crease map: ~131 x 47 mm, a bowed front
    formed = [c[1] for c in rec.calls if c[0] == "formed"][-1]
    lo, hi = formed.bounds
    assert 130.0 < hi[0] - lo[0] < 133.0
    assert 17.0 < hi[2] - lo[2] < 22.0
    assert rec.calls[-1][2] is not None, "the creases ride the warp"

    # untouched
    assert win.readiness._state == dot
    assert win._program_stored == stored
    assert win.params.castle_params() == castle_before

    # off: from cache, and the panel goes with it
    win._act_forming.setChecked(False)
    assert rec.calls[-1] == ("flat",)
    assert win._forming_panel.isHidden()
    # ...but the forming stays with the component for the export and the save
    assert win._workspaces[0].forming.bridge_projection_mm == 4.0
    _pump(app, lambda: not win._formed_build_busy(), 30)


@pytest.mark.gui
def test_a_temple_tab_is_never_formed(tmp_path, monkeypatch, gabriel_built):
    from PySide6.QtWidgets import QApplication

    win = _window(monkeypatch, tmp_path)
    win._load_model(_gabriel(tmp_path))
    rec = _record_viewer(monkeypatch, win)
    mesh, edges = gabriel_built
    win._switch_view(1)
    win._on_mesh_finished(mesh, "pockets", edges)
    win._act_forming.setChecked(True)
    assert rec.formed_active

    kinds = [ws.kind.value for ws in win._workspaces]
    win._activate_workspace(kinds.index("temple_right"))
    assert not win._act_forming.isEnabled()
    assert win._forming_panel.isHidden()
    assert not win._forming_applies()
    assert win._act_forming.isChecked(), "the view state survives the tab, like the turntable"
    _pump(QApplication.instance(), lambda: not win._formed_build_busy(), 30)


# ------------------------------------------------------------------ the files

@pytest.mark.gui
def test_the_formed_file_rides_export_all_only_when_formed(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import FormingMetadata

    win = _window(monkeypatch, tmp_path)
    win._load_model(_gabriel(tmp_path))
    assert win._formed_filename(0) == "frame_front_formed.stl"
    assert win._formed_export_spec(0, only_if_formed=True) is None
    always = win._formed_export_spec(0)
    assert always["mode"] == "formed" and always["forming"].is_flat

    win._workspaces[0].forming = FormingMetadata().with_base_curve(
        4.0, 163.97, radius_mm=144.0, bridge_projection_mm=4.0,
        press_preset=PRESET)
    spec = win._formed_export_spec(0, only_if_formed=True)
    assert spec["mode"] == "formed"
    assert spec["label"].endswith("(formed)")
    assert spec["castle"].lens_groove.enabled is True, "the groove override"
    assert win._workspaces[0].castle_params.lens_groove.enabled is False
    kinds = [ws.kind.value for ws in win._workspaces]
    assert win._formed_export_spec(kinds.index("temple_right")) is None


@pytest.mark.gui
def test_forming_round_trips_through_the_project(tmp_path, monkeypatch):
    """Saved with the component; restored over the drawing's own fields."""
    from guildmodel.core.project.schema import FormingMetadata

    win = _window(monkeypatch, tmp_path)
    win._load_model(_gabriel(tmp_path))
    ws = win._workspaces[0]
    drawing = ws.forming
    ws.forming = drawing.with_base_curve(3.0, 169.24, radius_mm=181.0,
                                         bridge_projection_mm=2.5,
                                         crease_angle_deg=50.0,
                                         bridge_offset_mm=-1.5,
                                         formed_groove=False,
                                         press_preset="SBT base 3 / lens 4")
    proj = win._build_project_schema()
    front = next(c for c in proj.components if c.kind.value == "frame_front")
    assert front.forming == ws.forming
    assert front.forming.apical_radius_mm == drawing.apical_radius_mm
    assert front.forming.crease_angle_deg == 50.0
    assert front.forming.bridge_offset_mm == -1.5

    # a v1.7.0 file: the drawing's two fields were never written, so the
    # drawing's values stand and the maker's forming (flat) comes through
    old = FormingMetadata()
    merged = win._merge_saved_forming(drawing, old)
    assert merged.is_flat
    assert merged.apical_radius_mm == drawing.apical_radius_mm
    assert merged.bridge_angle_deg == drawing.bridge_angle_deg
    # a v1.8.0 file carries them itself
    merged = win._merge_saved_forming(drawing, front.forming)
    assert merged == front.forming
    assert win._merge_saved_forming(None, front.forming) == front.forming
    assert win._merge_saved_forming(drawing, None) == drawing


# ------------------------------------------------------------------ the panel

def test_the_panel_round_trips_a_components_forming(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.core.project.schema import FormingMetadata
    from guildmodel.gui.widgets.forming_panel import FormingPanel

    panel = FormingPanel()
    f = FormingMetadata(apical_radius_mm=12.0).with_base_curve(
        4.0, 163.97, radius_mm=144.0, bridge_projection_mm=4.0,
        crease_gap_mm=18.5, crease_angle_deg=50.0, bridge_offset_mm=1.5,
        die_radius_mm=6.5, crease_blend_mm=0.75,
        formed_groove=False, press_preset=PRESET)
    changed = []
    panel.changed.connect(lambda: changed.append(1))
    panel.set_forming(f)
    assert not changed, "a restore never emits"
    assert panel.press.currentText() == PRESET
    assert panel.base_curve.value() == 4.0
    assert panel.face_form.value() == pytest.approx(163.97)
    assert panel.projection.value() == 4.0
    assert panel.crease_gap.value() == 18.5
    assert panel.crease_angle.value() == 50.0
    assert panel.offset.value() == 1.5
    assert panel.die_radius.value() == 6.5
    assert panel.crease_blend.value() == 0.75
    assert panel.groove.isChecked() is False
    assert panel.forming(FormingMetadata(apical_radius_mm=12.0)) == f
    assert panel.radius_readout.text() == "R 144 mm"
    assert "16° wrap" in panel.face_form_readout.text()
    assert panel.die_readout.text() == "", "a named die needs no readout"
    # Auto names the die it uses: the arc through both creases
    panel.die_radius.setValue(0.0)
    assert panel.die_readout.text() == "R 12.7 mm"     # (9.25^2 + 16) / 8
    assert panel.forming(FormingMetadata()).die_radius_mm == 0.0

    panel.set_forming(FormingMetadata())
    assert panel.press.currentText() == "Flat"
    assert panel.radius_readout.text() == "flat"
    assert panel.forming(FormingMetadata()).is_flat


def test_touching_a_slider_makes_the_press_custom(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.core.project.schema import FormingMetadata
    from guildmodel.gui.widgets.forming_panel import FormingPanel

    panel = FormingPanel()
    changed, sliding = [], []
    panel.changed.connect(lambda: changed.append(1))
    panel.sliding.connect(lambda: sliding.append(1))

    panel.press.setCurrentIndex(panel.press.findText(PRESET))
    assert changed == [1]
    assert panel.base_curve.value() == 4.0 and panel.face_form.value() == pytest.approx(163.97)
    assert panel.radius_readout.text() == "R 144 mm"

    panel.base_curve.setValue(4.25)            # typed: settled, custom, 530 / D
    assert panel.press.currentText() == "Custom"
    assert panel.radius_readout.text() == "R 125 mm"
    assert len(changed) == 2 and not sliding
    assert panel.forming(FormingMetadata()).base_radius_mm == pytest.approx(530.0 / 4.25)
    panel.base_curve.setValue(4.0)             # back on the row: named again
    assert panel.press.currentText() == PRESET
    assert panel.forming(FormingMetadata()).base_radius_mm == 144.0

    s = panel.projection.slider
    s.sliderPressed.emit()
    for v in (5, 10, 15):
        s.setValue(v)
    assert len(sliding) == 3 and len(changed) == 3
    s.sliderReleased.emit()
    assert len(changed) == 4
    assert panel.projection.value() == 1.5
    panel.projection.setValue(-2.0)                # the die only presses forward
    assert panel.projection.value() == 0.0

    panel.press.setCurrentIndex(panel.press.findText("Flat"))
    assert panel.base_curve.value() == 0.0 and panel.face_form.value() == 180.0
    assert panel.forming(FormingMetadata()).press_preset == ""
    assert panel.radius_readout.text() == "flat"


def test_the_base_curve_moves_in_quarter_steps(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.gui.widgets.forming_panel import FormingPanel

    panel = FormingPanel()
    assert panel.base_curve.spin.singleStep() == 0.25
    assert panel.base_curve.hard_range() == (0.0, 16.0)
    s = panel.base_curve.slider
    s.setValue(s.value() + s.singleStep())
    assert panel.base_curve.value() == 0.25


def test_the_makers_presses_reach_the_combo(tmp_path, monkeypatch):
    import yaml

    import guildmodel.core.forming.presses as store
    _qt(monkeypatch, tmp_path)
    from guildmodel.gui.widgets.forming_panel import FormingPanel

    user = tmp_path / "presses.yaml"
    monkeypatch.setattr(store, "_USER", user)
    user.write_text(yaml.safe_dump({"Bench die 6": {"base_curve": 6.0,
                                                   "face_form_deg": 158.0}}),
                    encoding="utf-8")
    panel = FormingPanel()
    labels = [panel.press.itemText(i) for i in range(panel.press.count())]
    assert labels[0] == "Flat" and labels[-1] == "Custom"
    assert "Bench die 6" in labels and PRESET in labels
    panel.press.setCurrentIndex(panel.press.findText("Bench die 6"))
    assert panel.base_curve.value() == 6.0
    assert panel.radius_readout.text() == "R 88 mm", "no die radius given: 530 / D"
