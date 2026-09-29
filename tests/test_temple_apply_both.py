"""Temple tab ▸ Apply to both temples (2026-09-27): the tab's settings copied onto
the other temple, so both cut with the same tools and depths; each temple keeps
its own fixture zone, program zero and cut settings; the copied-to temple's
model and program are marked stale; the button is off when there is no other
temple.
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
def test_the_temple_tab_is_applied_to_the_other_temple(tmp_path, monkeypatch):
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "two.gdraw"))
    ws = {w.kind: w for w in win._workspaces}
    right, left = ws[ComponentKind.TEMPLE_RIGHT], ws[ComponentKind.TEMPLE_LEFT]
    assert win.params.temple_apply_both_btn.isEnabled()

    win._activate_workspace(win._workspaces.index(right))
    left.program_zero = ProgramZero(x_ref="left", y_ref="bottom", z_ref="top")
    left.mesh_built = True
    left.stage_cache = {"flat": object()}
    left.program_stored = True
    win._clear_dirty()

    # edit the right temple's tab the way a maker would
    win.params.temple_engrave_depth.setValue(0.8)
    win.params.temple_blank_length.setValue(175.0)
    win.params.temple_hinge_depth.setValue(1.4)
    win.params.temple_engrave_tool.setCurrentText("flat_2mm")
    win.params.temple_stock_side.setCurrentText("left")
    win.params.temple_apply_both_btn.click()

    assert left.temple_params.engrave_depth_mm == pytest.approx(0.8)
    assert left.temple_params.blank_length_mm == pytest.approx(175.0)
    assert left.temple_params.hinge_pocket_depth_mm == pytest.approx(1.4)
    assert left.temple_params.engrave_tool == "flat_2mm"
    assert left.temple_params.stock_side == "left"
    assert left.temple_params.fixture_zone == "temple_left"      # kept per temple
    assert right.temple_params.fixture_zone == "temple_right"
    assert left.program_zero == ProgramZero(x_ref="left", y_ref="bottom", z_ref="top")
    assert left.mesh_built is False and left.stage_cache == {}   # stale model dropped
    assert left.program_stored is False                          # stale program flagged
    assert win._dirty is True

    # the left temple's tab now shows the copied settings
    win._activate_workspace(win._workspaces.index(left))
    t = win.params.temple_params()
    assert t.engrave_depth_mm == pytest.approx(0.8) and t.engrave_tool == "flat_2mm"
    assert t.fixture_zone == "temple_left"

    # nothing to copy: the same click again reports a match and marks nothing
    win._clear_dirty()
    win.params.temple_apply_both_btn.click()
    assert win._dirty is False
    assert "already match" in win.status_lbl.text()

    # one temple only: the button is off
    win._load_model(_make_gdraw(tmp_path / "one.gdraw", both_temples=False))
    assert win.params.temple_apply_both_btn.isEnabled() is False
