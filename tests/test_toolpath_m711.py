"""Toolpath overlay & per-op inspector (BUILDPLAN M7.11).

After a per-component Generate, the program's cutting paths draw over the 2D design
(color-coded, per-op visibility + highlight) and a dockable inspector lists each op
(tool / Z-floor / length / time) with visibility checkboxes that drive the overlay.
Offscreen Qt throughout.
"""
import pytest

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_dxf_canvas_toolpath_overlay(qapp):
    from guildmodel.gui.widgets.dxf_canvas import DxfCanvas
    c = DxfCanvas()
    c.resize(320, 220)
    c.set_layers({"OUTLINE": [[(0, 0), (50, 0), (50, 30), (0, 30), (0, 0)]]})
    c.set_toolpaths([
        {"name": "Perimeter", "color": "#e0563b",
         "paths": [[(0, 0), (50, 0), (50, 30), (0, 30), (0, 0)]]},
        {"name": "Eyewires", "color": "#3b86e0", "paths": [[(10, 10), (20, 10)]]},
    ])
    assert not c.grab().isNull()
    c.set_toolpath_visible("Eyewires", False)
    c.set_toolpath_highlight("Perimeter")
    assert c._tp_visible["Eyewires"] is False
    assert not c.grab().isNull()                    # still renders with one hidden
    c.clear_toolpaths()
    assert c._toolpaths == [] and c._tp_highlight is None


def test_op_overlay_from_ops_drops_z(qapp):
    from guildmodel.gui.app import _op_overlay
    from guildmodel.core.cam.castle_ops import CamOp
    ops = [
        CamOp("Perimeter", paths=[[(0.0, 0.0, 1.0), (5.0, 0.0, 1.0)]],
              tool={"name": "flat_3175"}),
        CamOp("Hinge Pockets", paths=[[(1.0, 1.0, 0.5)]], tool={"name": "flat_2mm"}),
    ]
    ov = _op_overlay(ops)
    assert [o["name"] for o in ov] == ["Perimeter", "Hinge Pockets"]
    assert ov[0]["tool"] == "flat_3175"
    assert ov[0]["paths"] == [[(0.0, 0.0), (5.0, 0.0)]]   # (x, y) only, z dropped


@pytest.mark.gui
def test_inspector_populates_toggles_and_highlights(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtCore import Qt
    from guildmodel.gui.app import MainWindow
    try:
        win = MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    overlay = [
        {"name": "Perimeter", "tool": "flat_3175", "paths": [[(0, 0), (5, 0)]]},
        {"name": "Eyewires", "tool": "flat_3175", "paths": [[(1, 1), (2, 1)]]},
    ]
    rows = [
        {"name": "Perimeter", "strategy": "Contour", "floor_z_mm": 0.4,
         "cut_length_mm": 1000.0, "est_minutes": 1.2},
        {"name": "Eyewires", "strategy": "Contour", "floor_z_mm": 0.4,
         "cut_length_mm": 500.0, "est_minutes": 0.6},
    ]
    win._show_toolpath_overlay(overlay, rows)
    assert win._toolpath_table.rowCount() == 2
    assert len(win.canvas._toolpaths) == 2
    # offscreen: a child is not isVisible() until the top-level is shown — use isHidden
    assert not win._toolpath_dock.isHidden()
    # the dock title carries the totals (1.5 m, 1.8 min)
    assert "1.50 m" in win._toolpath_dock.windowTitle()
    assert "1.8 min" in win._toolpath_dock.windowTitle()

    # unchecking an op hides its overlay
    item = win._toolpath_table.item(0, 0)
    item.setCheckState(Qt.CheckState.Unchecked)
    assert win.canvas._tp_visible["Perimeter"] is False
    # selecting a row highlights that op
    win._toolpath_table.selectRow(1)
    assert win.canvas._tp_highlight == "Eyewires"

    win.close()
