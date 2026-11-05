"""The temples' link (2026-11-02; the Apply-to-both button until then): linked,
the open temple's Temple, Cut and Machine settings are copied onto the other
temple whenever the dock is read back, each keeping its own fixture zone and
seats, the changed temple's model and program marked stale; unlinked, each
temple keeps its own; linking again asks, and the other temple takes the open
one's settings; the switch is on the dock's corner only while a temple is open
and there is another temple; the state rides in the project file, and a file
from before the link opens linked when its temples match.
"""
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from guildmodel.core.project.schema import ComponentKind, ProgramZero

_SVG_NS = "http://www.w3.org/2000/svg"


def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _svg_bytes(state):
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _make_gdraw(path, *, both_temples=True):
    front = {"curves": [
        _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
        _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
        _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
        _line("SCULPT", [(0, -20), (0, 20)]),
        _line("SCULPT", [(30, -20), (30, 20)]),
    ]}
    temple = {"curves": [
        _line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True),
        _line("ENGRAVING", [(-40, 0), (40, 0)]),
    ]}
    states = {"front": front, "temple_r": temple,
              "temple_l": temple if both_temples else {"curves": []},
              "hinge": {"curves": []}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))
    return path


def _window(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    try:
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    win.view3d.show_mesh = lambda *a, **k: None
    win.view3d.show_flat = lambda *a, **k: None
    return win


@pytest.mark.gui
def test_linked_temples_take_the_open_temples_settings(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentCamOverrides
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "two.gdraw"))
    ws = {w.kind: w for w in win._workspaces}
    right, left = ws[ComponentKind.TEMPLE_RIGHT], ws[ComponentKind.TEMPLE_LEFT]
    assert win._temples_linked is True                  # a new drawing's temples are alike

    # the switch: on the dock's corner for a temple, not for the front
    win._activate_workspace(win._workspaces.index(right))
    assert win.params.temple_link_btn.isVisibleTo(win.params)
    assert win.params.temples_linked()
    win._activate_workspace(0)
    assert not win.params.temple_link_btn.isVisibleTo(win.params)

    win._activate_workspace(win._workspaces.index(right))
    left.mesh_built = True
    left.stage_cache = {"flat": object()}
    left.program_stored = left.program_fresh = True
    win._clear_dirty()

    # edit the right temple on all three tabs, as a maker would
    win.params.temple_engrave_depth.setValue(0.8)
    win.params.temple_blank_length.setValue(175.0)
    win.params.temple_hinge_depth.setValue(1.4)
    win.params.temple_engrave_tool.setCurrentText("flat_2mm")
    win.params.temple_stock_side.setCurrentText("left")
    win.params._set_program_zero(ProgramZero(x_ref="left", y_ref="bottom", z_ref="top",
                                             shift_x_mm=2.0))
    win.params.ov_stepdown.setValue(0.7)
    # the link copies when the dock is read back: a tab switch, a save, a Generate
    win._activate_workspace(win._workspaces.index(left))

    assert left.temple_params.engrave_depth_mm == pytest.approx(0.8)
    assert left.temple_params.blank_length_mm == pytest.approx(175.0)
    assert left.temple_params.hinge_pocket_depth_mm == pytest.approx(1.4)
    assert left.temple_params.engrave_tool == "flat_2mm"
    assert left.temple_params.stock_side == "left"
    assert left.temple_params.fixture_zone == "temple_left"      # kept per temple
    assert right.temple_params.fixture_zone == "temple_right"
    assert left.program_zero == ProgramZero(x_ref="left", y_ref="bottom", z_ref="top",
                                            shift_x_mm=2.0)
    assert left.cam_overrides.contour_stepdown_mm == pytest.approx(0.7)
    assert left.mesh_built is False and left.stage_cache == {}   # stale model dropped
    assert left.program_stored is False                          # stale program flagged
    assert win._dirty is True

    # the left temple's tabs show the copied settings
    t = win.params.temple_params()
    assert t.engrave_depth_mm == pytest.approx(0.8) and t.engrave_tool == "flat_2mm"
    assert t.fixture_zone == "temple_left"
    assert win.params._program_zero().shift_x_mm == pytest.approx(2.0)
    assert win.params.ov_stepdown.value() == pytest.approx(0.7)
    assert win._temples_match()

    # one temple only: no switch
    win._load_model(_make_gdraw(tmp_path / "one.gdraw", both_temples=False))
    temples = win._temple_workspaces()
    assert len(temples) == 1
    win._activate_workspace(win._workspaces.index(temples[0]))
    assert not win.params.temple_link_btn.isVisibleTo(win.params)


@pytest.mark.gui
def test_unlinked_temples_keep_their_own_and_relinking_asks(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "two.gdraw"))
    ws = {w.kind: w for w in win._workspaces}
    right, left = ws[ComponentKind.TEMPLE_RIGHT], ws[ComponentKind.TEMPLE_LEFT]
    win._activate_workspace(win._workspaces.index(right))
    win._clear_dirty()

    # unlink: a click on the switch, no question asked
    win.params.temple_link_btn.click()
    assert win._temples_linked is False and not win.params.temples_linked()
    assert win._dirty is True
    win.params.temple_engrave_depth.setValue(0.9)
    win._activate_workspace(win._workspaces.index(left))
    assert left.temple_params.engrave_depth_mm != pytest.approx(0.9)   # its own
    assert not win._temples_match()

    # link again from the left temple: asked, Cancel keeps them apart
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Cancel)
    win.params.temple_link_btn.click()
    assert asked and "Temple R" in asked[0] and "Temple L" in asked[0]
    assert win._temples_linked is False and not win.params.temples_linked()
    assert right.temple_params.engrave_depth_mm == pytest.approx(0.9)

    # Yes: the right temple takes the left one's settings
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    win.params.temple_link_btn.click()
    assert win._temples_linked is True and win.params.temples_linked()
    assert right.temple_params.engrave_depth_mm == left.temple_params.engrave_depth_mm
    assert right.temple_params.fixture_zone == "temple_right"
    assert win._temples_match()

    # temples that already match link without a question
    win.params.temple_link_btn.click()           # off
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: pytest.fail("asked with nothing to change"))
    win.params.temple_link_btn.click()           # on
    assert win._temples_linked is True


@pytest.mark.gui
def test_the_link_rides_in_the_project_file(tmp_path, monkeypatch):
    from guildmodel.core.project.gmodel import load_gmodel
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "two.gdraw"))
    ws = {w.kind: w for w in win._workspaces}
    right = ws[ComponentKind.TEMPLE_RIGHT]
    win._activate_workspace(win._workspaces.index(right))
    win.params.temple_link_btn.click()                  # unlinked
    win.params.temple_engrave_depth.setValue(0.9)
    path = tmp_path / "apart.gmodel"
    win._write_gmodel(path)
    assert load_gmodel(path).project.temples_linked is False

    win._open_project(path, remember=False)
    assert win._temples_linked is False
    assert not win._temples_match()

    # a file from before the link: linked when the temples match, apart when not
    import json, zipfile
    from guildmodel.core.project import gmodel as gmodel_mod
    real_load = gmodel_mod.load_gmodel
    for name, expect in (("apart", False), ("alike", True)):
        src = path if name == "apart" else None
        if src is None:
            win._load_model(_make_gdraw(tmp_path / "two.gdraw"))
            src = tmp_path / "alike.gmodel"
            win._write_gmodel(src)
        old = tmp_path / f"old_{name}.gmodel"
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(old, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "project.json":
                    d = json.loads(data)
                    d.pop("temples_linked", None)
                    data = json.dumps(d).encode()
                zout.writestr(item, data)
        monkeypatch.setattr(gmodel_mod, "load_gmodel",
                            lambda p, *a, **k: real_load(p, verify=False))
        win._open_project(old, remember=False)
        assert win._temples_linked is expect, name
