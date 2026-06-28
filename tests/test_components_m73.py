"""Per-component notebook intake (BUILDPLAN M7.3).

The Qt-free heart of the component notebook — `build_workspaces_from_gdraw` +
`derive_workspace` — turns a `.gdraw` into one derived workspace per component
(frame front + both temples + a base-curve template per lens). These tests run
without a Qt platform; a final, guarded MainWindow smoke test exercises the
File ▸ Open Model wiring (the tab bar + activation) where Qt is available.
"""
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from guildmodel.core.project.schema import ComponentKind
from guildmodel.gui.component_workspace import (
    build_workspaces_from_gdraw,
    derive_workspace,
    ComponentWorkspace,
)

_SVG_NS = "http://www.w3.org/2000/svg"


# ------------------------------------------------------------------ builders

def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _svg_bytes(state):
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _front_state():
    return {
        "forming": {"apical_radius_mm": 88.0, "bridge_angle_deg": 5.0},
        "curves": [
            _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
            _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
            _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
            _line("SCULPT", [(0, -20), (0, 20)]),
            _line("SCULPT", [(30, -20), (30, 20)]),
            _line("HINGE", [(50, -5), (58, -5), (58, 5), (50, 5)], closed=True),
        ],
    }


def _temple_r_state():
    return {"curves": [
        _line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True),
        _line("ENGRAVING", [(-40, 0), (0, 0), (40, 0)]),
    ]}


def _make_gdraw(path):
    states = {"front": _front_state(), "temple_r": _temple_r_state(),
              "temple_l": {"curves": []},
              "hinge": {"curves": [_line("HINGE", [(0, 0), (8, 0), (8, 8), (0, 8)], closed=True)]}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))
    return path


# ------------------------------------------------------------------ derive_workspace

def test_derive_frame_front_geometry():
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="Frame Front",
                            layers={})
    ws.layers = {k: [] for k in ("OUTLINE", "LENS", "SCULPT", "HINGE", "ENGRAVING")}
    ws.layers["OUTLINE"] = [[(-60, -20), (60, -20), (60, 20), (-60, 20)]]
    ws.layers["LENS"] = [[(20, -12), (45, -12), (45, 12), (20, 12)],
                         [(-45, -12), (-20, -12), (-20, 12), (-45, 12)]]
    ws.layers["SCULPT"] = [[(0, -20), (0, 20)], [(30, -20), (30, 20)]]
    derive_workspace(ws)
    assert ws.outline_poly is not None
    assert ws.lens_od is not None and ws.lens_os is not None
    assert ws.lens_od.centroid.x > ws.lens_os.centroid.x      # OD on +x
    assert ws.partition is not None                           # SCULPT cuts → a partition
    assert ws.is_temple is False


def test_derive_temple_is_temple():
    ws = ComponentWorkspace(kind=ComponentKind.TEMPLE_RIGHT, label="Temple Right",
                            layers={"OUTLINE": [[(-70, -6), (70, -6), (70, 6), (-70, 6)]],
                                    "ENGRAVING": [[(-40, 0), (40, 0)]]})
    derive_workspace(ws)
    assert ws.is_temple is True
    assert ws.outline_poly is not None
    assert ws.lens_od is None
    assert len(ws.engraving_curves) == 1


# ------------------------------------------------------------------ build_workspaces_from_gdraw

def test_build_workspaces_is_five_components(tmp_path):
    path = _make_gdraw(tmp_path / "model.gdraw")
    workspaces, active = build_workspaces_from_gdraw(path)
    kinds = [w.kind for w in workspaces]
    assert kinds[:3] == [ComponentKind.FRAME_FRONT,
                         ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT]
    assert {kinds[3], kinds[4]} == {ComponentKind.BASE_CURVE_RIGHT,
                                    ComponentKind.BASE_CURVE_LEFT}
    assert active == "front"


def test_build_workspaces_geometry_and_enabled(tmp_path):
    path = _make_gdraw(tmp_path / "model.gdraw")
    workspaces, _ = build_workspaces_from_gdraw(path)
    by_kind = {w.kind: w for w in workspaces}

    front = by_kind[ComponentKind.FRAME_FRONT]
    assert front.outline_poly is not None and front.lens_od is not None
    assert front.partition is not None
    assert front.label == "Frame Front"

    assert by_kind[ComponentKind.TEMPLE_RIGHT].enabled is True
    assert by_kind[ComponentKind.TEMPLE_RIGHT].is_temple is True
    assert by_kind[ComponentKind.TEMPLE_LEFT].enabled is False    # empty workspace

    # each base-curve template carries its single lens (drives the block generator)
    for kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
        assert by_kind[kind].lens_od is not None
        assert by_kind[kind].outline_poly is None


# ------------------------------------------------------------------ MainWindow smoke (guarded)

def test_open_model_populates_tabs(tmp_path, monkeypatch):
    """File ▸ Open Model builds the tab bar and activation swaps the active
    component. Skipped where no Qt platform / VTK is available."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    try:
        QApplication.instance() or QApplication([])
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    path = _make_gdraw(tmp_path / "model.gdraw")
    win._load_model(path)

    # 5 component tabs + a trailing Worktable tab (BUILDPLAN M7.4)
    assert win.component_tabs.count() == 6
    assert win._worktable_tab_index == 5
    assert not win.component_tabs.isHidden()                     # shown when components exist
    assert win.component_tabs.isTabEnabled(0) is True            # frame front
    assert win.component_tabs.isTabEnabled(2) is False           # empty temple_l

    win._activate_workspace(1)                                    # a temple
    assert win._is_temple is True
    win._activate_workspace(3)                                    # a base-curve template
    assert win._lens_od is not None
    win._activate_workspace(0)                                    # back to the front
    assert win._is_temple is False and win._partition is not None


def test_kind_aware_param_dock_and_persistence(tmp_path, monkeypatch):
    """Each tab shows its kind's params, and per-component edits persist across
    tab switches. Skipped where no Qt platform / VTK is available."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    try:
        QApplication.instance() or QApplication([])
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                      # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")

    win._load_model(_make_gdraw(tmp_path / "model.gdraw"))
    p = win.params

    # frame front shows Castle/Stock, not Temple/Base Curve
    win._activate_workspace(0)
    assert p.isTabVisible(p._tab_castle) and p.isTabVisible(p._tab_stock)
    assert not p.isTabVisible(p._tab_temple) and not p.isTabVisible(p._tab_block)

    # a temple shows the Temple tab (and hides Castle/Stock)
    win._activate_workspace(1)
    assert p.isTabVisible(p._tab_temple)
    assert not p.isTabVisible(p._tab_castle) and not p.isTabVisible(p._tab_block)

    # edit the temple's engrave depth, switch away + back → it persists
    p.temple_engrave_depth.setValue(0.7)
    win._activate_workspace(0)
    win._activate_workspace(1)
    assert p.temple_engrave_depth.value() == pytest.approx(0.7)

    # a base-curve template shows the Base Curve tab
    win._activate_workspace(3)
    assert p.isTabVisible(p._tab_block)
    assert not p.isTabVisible(p._tab_temple)
