"""The 2.0 bug hunt, in the window (2026-10-16).

Each test here pins a defect a review found by driving the window offscreen,
fixed the same day. The core findings are in `test_bug_hunt_v200.py`.
"""
import json
import os
import xml.etree.ElementTree as ET
import zipfile

import pytest

_SVG_NS = "http://www.w3.org/2000/svg"


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _new_window():
    """A window, built where the gui marker's scan can see it."""
    from guildmodel.gui.app import MainWindow
    try:
        return MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    """The environment the windows are built in: a home of their own, and
    message boxes that answer at once."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QMessageBox
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: None)
    return _new_window


def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _gdraw(path, *, left_temple=False):
    front = {"mirror": {"enabled": False}, "curves": [
        _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
        _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
        _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
        _line("SCULPT", [(0, -20), (0, 20)]),
        _line("SCULPT", [(30, -20), (30, 20)]),
    ]}
    temple = {"mirror": {"enabled": False}, "curves": [
        _line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True)]}
    states = {"front": front, "temple_r": temple,
              "temple_l": temple if left_temple else {"curves": []},
              "hinge": {"curves": []}}
    ET.register_namespace("", _SVG_NS)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            root = ET.Element(f"{{{_SVG_NS}}}svg")
            ET.SubElement(root, f"{{{_SVG_NS}}}metadata").text = json.dumps(st)
            zf.writestr(f"{tab}.svg", ET.tostring(root, xml_declaration=True,
                                                  encoding="utf-8"))
    return path


def _by_kind(win, kind):
    return [w for w in win._workspaces if w.kind == kind]


@pytest.mark.gui
def test_export_gcode_writes_the_active_components_program(window, tmp_path, monkeypatch):
    """File ▸ Export G-code read a name before it was assigned (05b84bc) and
    raised on every component tab; only the Worktable's export worked."""
    from PySide6.QtWidgets import QFileDialog
    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    win._activate_workspace(0)
    win._last_programs = {"posterior_cut.nc": "G21\nM30\n"}
    win._program_fresh = True
    out = tmp_path / "out.nc"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(win, "_z_profile_hold", lambda *a, **k: False)
    win._on_export_nc()
    assert out.read_text(encoding="utf-8") == "G21\nM30\n"


@pytest.mark.gui
def test_each_part_keeps_its_own_program_through_save_and_reopen(window, tmp_path):
    """The front and both base-curve blocks were all saved as component
    "front": the last one's programs took the slot, and a reopen handed them
    to all three, the front's posted as a block."""
    from guildmodel.core.project.schema import ComponentKind as K
    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    # The active tab's programs live on the window; work from the temple's.
    win._activate_workspace(1)
    parts = {K.FRAME_FRONT: "(front)", K.BASE_CURVE_RIGHT: "(block r)",
             K.BASE_CURVE_LEFT: "(block l)"}
    for kind, text in parts.items():
        (ws,) = _by_kind(win, kind)
        ws.last_programs = {f"{kind.value}.nc": text}
        ws.program_stored = ws.program_fresh = True
    path = tmp_path / "m.gmodel"
    assert win._save_gmodel_to(path) is True
    project = json.loads(zipfile.ZipFile(path).read("project.json"))
    ids = [c["id"] for c in project["components"]]
    assert len(ids) == len(set(ids))

    win2 = _new_window()
    win2._open_project(path)
    for kind, text in parts.items():
        (ws,) = _by_kind(win2, kind)
        assert ws.last_programs == {f"{kind.value}.nc": text}, kind


@pytest.mark.gui
def test_an_older_project_seeds_its_shared_slot_only_to_its_owner(window, tmp_path):
    """A file from before the ids were unique kept one slot for the front and
    both blocks. When only the front had a program, the slot is the front's;
    the blocks are not given it."""
    from guildmodel.core.project.gmodel import save_gmodel
    from guildmodel.core.project.schema import ComponentKind as K
    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    project = win._build_project_schema()
    for comp in project.components:
        if comp.kind in (K.FRAME_FRONT, K.BASE_CURVE_RIGHT, K.BASE_CURVE_LEFT):
            comp.id = "front"
        comp.has_program = comp.kind == K.FRAME_FRONT
    path = tmp_path / "old.gmodel"
    save_gmodel(path, project=project, gdraw_bytes=win._source_gdraw_bytes,
                component_artifacts={"front": {"programs": {"posterior_cut.nc": "(front)"}}})

    win2 = _new_window()
    win2._open_project(path)
    (front,) = _by_kind(win2, K.FRAME_FRONT)
    assert front.last_programs == {"posterior_cut.nc": "(front)"}
    for kind in (K.BASE_CURVE_RIGHT, K.BASE_CURVE_LEFT):
        (block,) = _by_kind(win2, kind)
        assert not block.last_programs, kind


class _Started(Exception):
    """Raised by a stand-in simulation worker: the simulation would start."""


@pytest.mark.gui
def test_simulate_in_an_unsaved_session_generates_once(window, tmp_path, monkeypatch):
    """The simulation wants a fresh program, and only a save marked one
    fresh: in an unsaved session Simulate generated the program, came back,
    found none, and generated it again, forever."""
    from types import SimpleNamespace
    import guildmodel.gui.app as app_mod
    from guildmodel.core.project.schema import ComponentKind as K

    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    win._activate_workspace(win._workspaces.index(_by_kind(win, K.FRAME_FRONT)[0]))
    monkeypatch.setattr(win, "_castle_ready", lambda: True)
    posted = "G21\nG0 Z11\nM30\n"
    generated = []

    def generate(_checked=False, *, then=None):
        generated.append(then)
        # what the worker hands `_on_gcode_finished`, unsaved: no project path
        win._gcode_worker = SimpleNamespace(
            programs={"posterior_cut.nc": posted}, setup_dict=None, machine_dump=None)
        win._gcode_then = then
        win._on_gcode_finished("", [])

    started = []

    class Worker:
        def __init__(self, *a, program_text=None, **k):
            started.append(program_text)
            raise _Started

    monkeypatch.setattr(win, "_on_generate", generate)
    monkeypatch.setattr(app_mod, "SimWorker", Worker)
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda _ms, fn: fn())
    assert win._project_path is None
    with pytest.raises(_Started):
        win._start_component_sim()
    assert len(generated) == 1 and started == [posted]
    # the program is fresh now: a second Simulate does not generate again
    with pytest.raises(_Started):
        win._start_component_sim()
    assert len(generated) == 1 and started == [posted, posted]
    # a program generated for the simulation that lacks the part's file stops
    win._last_programs = {}
    win._start_component_sim(generated=True)
    assert len(generated) == 1


@pytest.mark.gui
def test_a_stale_program_comes_back_stale(window, tmp_path, monkeypatch):
    """A save after a change kept the older program and marked it stored, and
    a reopen offered it as current: the dot green, the simulation and Export
    G-code reading a program the design had left behind."""
    from PySide6.QtWidgets import QMessageBox, QFileDialog
    from guildmodel.core.project.schema import ComponentKind as K

    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    win._activate_workspace(win._workspaces.index(_by_kind(win, K.FRAME_FRONT)[0]))
    win._last_programs = {"posterior_cut.nc": "(old)"}
    win._program_fresh = True
    win._invalidate_program()                     # a CAM setting moved
    path = tmp_path / "m.gmodel"
    assert win._save_gmodel_to(path) is True
    assert win._program_stored is False           # the dot stays yellow

    win2 = _new_window()
    win2._open_project(path)
    (front,) = _by_kind(win2, K.FRAME_FRONT)
    assert front.last_programs == {"posterior_cut.nc": "(old)"}
    assert front.program_fresh is False and front.program_stored is False
    # Export G-code asks first, and Cancel writes nothing
    win2._activate_workspace(win2._workspaces.index(front))
    out = tmp_path / "out.nc"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(win2, "_z_profile_hold", lambda *a, **k: False)
    asked = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: (
        asked.append(a[1]), QMessageBox.StandardButton.Cancel)[1])
    win2._on_export_nc()
    assert asked and not out.exists()


@pytest.mark.gui
def test_a_quiet_build_leaves_generates_dialog_open(window, tmp_path):
    """Every job shared one progress dialog, and any job's end closed it: a
    quiet rebuild landing under Generate's let the window take input, a tab
    switch included, while the program was still being made."""
    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    win._open_progress("Generating G-code", "gcode")
    win._close_progress("mesh")                   # a quiet build lands
    assert win._progress_dialog is not None
    win._close_progress("gcode")
    assert win._progress_dialog is None


@pytest.mark.gui
def test_a_program_lands_on_the_part_it_was_made_for(window, tmp_path, monkeypatch):
    """A program that landed after the maker changed tabs became the new
    tab's: a temple's program held by the front, posted as the front's. It is
    filed on its own part now, and one for a closed design is dropped."""
    from types import SimpleNamespace
    from guildmodel.core.project.schema import ComponentKind as K

    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    front = _by_kind(win, K.FRAME_FRONT)[0]
    temple = _by_kind(win, K.TEMPLE_RIGHT)[0]
    win._activate_workspace(win._workspaces.index(front))

    def job(text):
        w = SimpleNamespace(programs={"posterior_cut.nc": text}, setup_dict=None,
                            machine_dump=None)
        win._stamp_job(w)
        return w

    win._gcode_worker = job("(front)")
    win._activate_workspace(win._workspaces.index(temple))
    before = dict(win._last_programs)
    win._on_gcode_finished("", [])
    assert win._last_programs == before           # the temple's set is untouched
    assert front.last_programs == {"posterior_cut.nc": "(front)"}
    assert front.program_fresh is True and front.program_stored is False

    win._gcode_worker = job("(gone)")
    win._design_token += 1                        # another drawing opened
    win._on_gcode_finished("", [])
    assert front.last_programs == {"posterior_cut.nc": "(front)"}
    assert win._last_programs == before


def _pump(until, timeout=60.0):
    import time
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if until():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.gui
def test_a_dxf_project_keeps_its_parts_settings_through_a_reopen(window, tmp_path):
    """A project made from a DXF restored the project-level castle and CAM and
    nothing of its one component: the program zero, the CAM overrides and the
    forming went back to the defaults on every reopen."""
    from pathlib import Path
    from guildmodel.core.project.schema import ComponentCamOverrides, ProgramZero

    dxf = Path(__file__).parent / "fixtures" / "demo" / "GuildDraw DXF Export.dxf"
    win = _new_window()
    win._load_dxf(dxf)
    assert _pump(lambda: bool(win._workspaces) and win._active_ws == 0)
    corner = ProgramZero(x_ref="left", y_ref="bottom", z_ref="top")
    win.params._set_program_zero(corner)
    win.params.set_cam_overrides(ComponentCamOverrides(material="acetal"))
    path = tmp_path / "dxf.gmodel"
    assert win._save_gmodel_to(path) is True

    win2 = _new_window()
    win2._open_project(path)
    assert _pump(lambda: bool(win2._workspaces) and win2._active_ws == 0)
    (ws2,) = win2._workspaces
    assert ws2.program_zero == corner
    assert ws2.cam_overrides.material == "acetal"


@pytest.mark.gui
def test_reload_drawing_keeps_the_sculpts_and_takes_a_new_parts_switch(window, tmp_path):
    """Reload Drawing dropped every sculpt's mesh, which lives on the part and
    not in the drawing, and gave each part its old switch: a temple drawn
    since the last open stayed off."""
    from guildmodel.core.project.schema import ComponentKind as K
    path = _gdraw(tmp_path / "m.gdraw")
    win = _new_window()
    win._load_model(path)
    assert not _by_kind(win, K.TEMPLE_LEFT)[0].enabled           # not drawn yet
    _by_kind(win, K.FRAME_FRONT)[0].sculpt_sources["sha"] = b"mesh bytes"
    _gdraw(path, left_temple=True)                               # drawn on disk
    win._on_reload_drawing()
    assert _by_kind(win, K.TEMPLE_LEFT)[0].enabled
    left = win._workspaces.index(_by_kind(win, K.TEMPLE_LEFT)[0])
    assert win.component_tabs.isTabEnabled(left)
    assert _by_kind(win, K.FRAME_FRONT)[0].sculpt_sources.get("sha") == b"mesh bytes"
    # a part the maker switched off stays off
    _by_kind(win, K.TEMPLE_RIGHT)[0].enabled = False
    win._on_reload_drawing()
    assert not _by_kind(win, K.TEMPLE_RIGHT)[0].enabled


@pytest.mark.gui
def test_opening_a_project_leaves_the_cam_preferences_alone(window, tmp_path):
    """The CAM tab is remembered for the next drawing. Opening a project
    restored its settings through the same signals an edit sends, and they
    became the next new drawing's: a staged job with Perimeter off left the
    next drawing posting without its releasing cut."""
    from guildmodel.core.project.schema import CastleCamParams
    win = _new_window()
    win._load_model(_gdraw(tmp_path / "m.gdraw"))
    win.params.set_cam_params(CastleCamParams(op_enabled={"Perimeter": False}))
    path = tmp_path / "staged.gmodel"
    assert win._save_gmodel_to(path) is True

    win2 = _new_window()
    before = dict(win2._prefs.get("cam_params") or {})
    win2._open_project(path)
    assert not win2._cam_prefs_timer.isActive()
    assert (win2._prefs.get("cam_params") or {}) == before
    # an edit the maker makes is still remembered
    win2.params.pocket_stepdown.setValue(win2.params.pocket_stepdown.value() + 0.1)
    assert win2._cam_prefs_timer.isActive()
