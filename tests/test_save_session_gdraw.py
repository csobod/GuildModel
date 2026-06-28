"""A whole-model (.gdraw) session must be saveable to a .gcam and reopen intact.

Pre-rc1 fix: loading a .gdraw, editing, and saving used to fail with "Import a
DXF before saving" because the container only embedded a single source.dxf. Now
the .gdraw is embedded and the per-component params round-trip (BUILDPLAN M7.1).
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


def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _svg_bytes(state):
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _make_gdraw(path):
    front = {
        "forming": {"apical_radius_mm": 88.0},
        "curves": [
            _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
            _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
            _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
            _line("SCULPT", [(0, -20), (0, 20)]),
            _line("SCULPT", [(30, -20), (30, 20)]),
            _line("HINGE", [(50, -5), (58, -5), (58, 5), (50, 5)], closed=True),
        ],
    }
    temple_r = {"curves": [
        _line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True),
        _line("ENGRAVING", [(-40, 0), (40, 0)]),
    ]}
    states = {"front": front, "temple_r": temple_r, "temple_l": {"curves": []},
              "hinge": {"curves": []}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))
    return path


def test_gdraw_session_saves_and_reopens(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QMessageBox
    from guildcam.gui.app import MainWindow
    # No blocking dialogs in a headless run.
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)

    try:
        win = MainWindow()
    except Exception as exc:                                   # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    gdraw = _make_gdraw(tmp_path / "model.gdraw")
    win._load_model(gdraw)
    assert len(win._workspaces) >= 2          # frame front + at least one temple
    assert win._source_gdraw_bytes is not None
    assert win._source_dxf_bytes is None      # a model has no single DXF

    # Edit a per-component param on a (non-active) temple workspace.
    from guildcam.core.project.schema import TempleParams, ComponentKind
    temple = next(w for w in win._workspaces if w.kind == ComponentKind.TEMPLE_RIGHT)
    temple.temple_params = TempleParams(blank_length_mm=173.5)

    # The old blocker: saving a .gdraw session. It must now succeed.
    gcam = tmp_path / "model.gcam"
    assert win._save_gcam_to(gcam) is True
    with zipfile.ZipFile(gcam) as zf:
        assert "source.gdraw" in zf.namelist()
        assert "source.dxf" not in zf.namelist()

    # Reopen into a fresh window: geometry rebuilt from the embedded .gdraw and the
    # edited temple param restored.
    win2 = MainWindow()
    win2._open_project(gcam)
    assert win2._source_gdraw_bytes is not None
    assert len(win2._workspaces) == len(win._workspaces)
    temple2 = next(w for w in win2._workspaces if w.kind == ComponentKind.TEMPLE_RIGHT)
    assert temple2.temple_params is not None
    assert temple2.temple_params.blank_length_mm == pytest.approx(173.5)
