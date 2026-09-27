"""The 2026-09-26 bug hunt before v1.8.0: the window half.

See ``test_bug_hunt_v180`` for the core. Pinned here:

- a saved forming keeps its die radius when its press row is not installed
  (the preview and the export bent to different radii, and the first
  slider touch rewrote the project);
- a base-curve drag off a press row leaves the row's die at once, not at
  release;
- a layout handle says when it is let go, moved or not (the uncut base of
  a drag that ended where it began stayed on screen);
- a cleared viewer is a flat viewer;
- prefs are written atomically;
- a reopened project keeps every component's program (every reopen used to
  drop the stored program, and the next save dropped it from the file);
- Cancel reaches a running build, the rebuild owed from during a build
  runs once the thread has stopped, and a build for a design that has
  since been closed is dropped rather than filed under the new one.
"""
import json
import time
import zipfile
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _qt(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _gabriel(tmp_path, name="gabriel.gdraw") -> Path:
    path = tmp_path / name
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


def _window(monkeypatch, tmp_path):
    _qt(monkeypatch, tmp_path)
    try:
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    # no GL offscreen: the scene calls are not what these tests are about
    win.view3d.show_mesh = lambda *a, **k: None
    win.view3d.show_formed = lambda *a, **k: None
    win.view3d.show_flat = lambda *a, **k: None
    return win


# ------------------------------------------------------------- the panel

def test_a_saved_forming_keeps_its_die_when_its_press_is_gone(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.core.project.schema import FormingMetadata
    from guildmodel.gui.widgets.forming_panel import FormingPanel

    panel = FormingPanel()
    # 4 D at 150° names no shipped row; the die is a press that is not installed here
    saved = FormingMetadata().with_base_curve(4.0, 150.0, radius_mm=144.0,
                                              bridge_projection_mm=4.0,
                                              press_preset="A press from another shop")
    panel.set_forming(saved)
    assert panel.press.currentText() == "Custom"
    out = panel.forming(saved)
    assert out.base_radius_mm == 144.0 and out.press_preset == ""
    for name in ("base_curve", "face_form_wrap_deg", "bridge_projection_mm"):
        assert getattr(out, name) == getattr(saved, name), name
    assert panel._radius_in_use() == 144.0
    # once the curve moves, the convention is the only radius there is
    panel.base_curve.setValue(6.0)
    assert panel.forming(saved).base_radius_mm == pytest.approx(530.0 / 6.0)


def test_dragging_the_curve_off_a_row_leaves_its_die_at_once(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.core.forming import press_rows
    from guildmodel.gui.widgets.forming_panel import FormingPanel

    panel = FormingPanel()
    row = press_rows()[0]
    panel.press.setCurrentIndex(panel.press.findText(row.label))
    assert panel._radius_in_use() == row.radius_mm
    # mid-drag: the slider has moved, nothing has settled, the combo still names the row
    panel.base_curve.blockSignals(True)
    panel.base_curve.setValue(row.base_curve + 4.0)
    panel.base_curve.blockSignals(False)
    assert panel.press.currentText() == row.label
    assert panel._radius_in_use() == pytest.approx(530.0 / (row.base_curve + 4.0))


def test_a_released_handle_says_so_even_unmoved(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.gui.widgets.param_slider import ParamSlider

    handle = ParamSlider(1.0, 0.0, 10.0)
    seen = []
    handle.released.connect(lambda: seen.append("released"))
    handle.valueChanged.connect(lambda v: seen.append("changed"))
    handle.slider.sliderPressed.emit()
    handle.slider.sliderReleased.emit()          # let go where it was picked up
    assert seen == ["released"]


def test_a_cleared_viewer_is_flat(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.gui.widgets.viewer_3d import Viewer3D

    viewer = Viewer3D()
    viewer._formed_on = True
    viewer._formed_ghost = True
    viewer.clear()
    assert viewer.formed_active is False and viewer._formed_ghost is False


def test_prefs_are_written_atomically(tmp_path, monkeypatch):
    from guildmodel.gui import prefs

    monkeypatch.setattr(prefs, "_DIR", tmp_path)
    monkeypatch.setattr(prefs, "_FILE", tmp_path / "prefs.json")
    prefs.save({"recent_files": ["a"]})
    assert json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8")) == {"recent_files": ["a"]}
    assert not list(tmp_path.glob("*.tmp"))


# ------------------------------------------------------------ the window

@pytest.mark.gui
def test_a_reopened_project_keeps_every_components_program(tmp_path, monkeypatch):
    win = _window(monkeypatch, tmp_path)
    win._load_model(_gabriel(tmp_path))
    labels = [w.label for w in win._workspaces]
    assert labels[0] == "Frame Front" and labels[1].startswith("Temple")

    # a program on the front and another on a temple, as the workers leave them
    win._last_programs = {"frame_front.nc": "; front"}
    win._last_setup = {"tool": "flat_3175"}
    win._program_stored = True
    win._activate_workspace(1)
    win._last_programs = {"temple_right.nc": "; temple"}
    win._program_stored = True
    win._activate_workspace(0)

    path = tmp_path / "p.gmodel"
    assert win._save_gmodel_to(path, announce=False)
    names = zipfile.ZipFile(path).namelist()
    assert "program/frame_front.nc" in names                    # the hand-off job
    assert any(n.startswith("components/") and n.endswith("/temple_right.nc") for n in names)
    assert any(n.startswith("components/") and n.endswith("/frame_front.nc") for n in names)

    again = _window(monkeypatch, tmp_path)
    again._open_project(path, remember=False)
    assert again._last_programs == {"frame_front.nc": "; front"}
    assert again._last_setup == {"tool": "flat_3175"}
    assert again._program_stored and again._act_export_nc.isEnabled()
    assert again._workspaces[1].last_programs == {"temple_right.nc": "; temple"}
    assert again._workspaces[1].program_stored
    # and a plain re-save keeps both
    path2 = tmp_path / "p2.gmodel"
    assert again._save_gmodel_to(path2, announce=False)
    names2 = zipfile.ZipFile(path2).namelist()
    assert "program/frame_front.nc" in names2
    assert any(n.endswith("/temple_right.nc") for n in names2)


@pytest.mark.gui
def test_cancel_reaches_a_running_build_and_nothing_stale_lands(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    app = _qt(monkeypatch, tmp_path)
    win = _window(monkeypatch, tmp_path)
    win._load_model(_gabriel(tmp_path))
    log = []
    win.append_log = lambda m: log.append(m)

    # Cancel: the button on the progress dialog reaches the worker while it runs.
    # The raster kernel at a fine resolution is slow enough to be caught.
    win._prefs["model_kernel"] = "raster"
    win._prefs["preview_resolution_mm"] = 0.1
    t0 = time.monotonic()
    win._on_build_3d()
    worker = win._mesh_worker
    assert win._progress_dialog is not None
    _pump(app, lambda: time.monotonic() - t0 > 0.5, 2)
    win._progress_dialog.findChild(QPushButton).click()
    assert worker._cancel is True                 # set at once, not when run() returns
    assert _pump(app, lambda: not win._mesh_thread.isRunning(), 120)
    assert any("canceled" in m.lower() for m in log)
    assert not any("All component models built" in m for m in log)

    # The owed rebuild: a change during a build is remembered, and it runs
    # once the thread has actually stopped (the handler runs before it has).
    win._prefs["model_kernel"] = "mesh"
    win._prefs["preview_resolution_mm"] = 0.5
    workers = []
    win._start_mesh_build(show_progress=False)
    workers.append(id(win._mesh_worker))
    win._start_mesh_build(show_progress=False)
    assert win._rebuild_pending
    def track():
        if id(win._mesh_worker) not in workers:
            workers.append(id(win._mesh_worker))
        return len(workers) >= 2
    assert _pump(app, track, 120), "the owed rebuild never started"
    assert _pump(app, lambda: not win._mesh_thread.isRunning() and not win._rebuild_pending, 120)

    # A build for a design that has since been closed is dropped.
    win._start_mesh_build(show_progress=False)
    assert win._mesh_thread.isRunning()
    win._load_model(_gabriel(tmp_path, "other.gdraw"))
    assert _pump(app, lambda: not win._mesh_thread.isRunning(), 120)
    _pump(app, lambda: False, 0.3)               # let the queued result land
    assert win._stage_cache == {} and not win._mesh_built
    assert any("no longer open" in m for m in log)

    # A failure is said to the maker: the dialog names it, carries the
    # exception's own line, and its button opens the log.
    win._on_gcode_error("Traceback (most recent call last):\n  ...\nValueError: no feed for acetal")
    box = win._failure_box
    assert box.isVisible() and "G-code generation" in box.windowTitle()
    assert "no feed for acetal" in box.informativeText()
    win._on_failure_box_clicked(win._failure_show_log)
    _pump(app, lambda: False, 0.2)                 # the dock arranges on a zero timer
    assert win._log_dock.isVisible() or win._log_want
    win._on_sim_error("boom")                      # one dialog, updated, not a second
    assert win._failure_box is box and "Simulation" in box.windowTitle()
    box.hide()
    win._wind_down_threads()


def test_a_cut_tab_spin_box_settles_on_enter_not_per_keystroke(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.gui.widgets.params_panel import _spinbox

    assert _spinbox(1500.0, 0.0, 5000.0).keyboardTracking() is False
