"""The guide sizes a drawing carries (GuildDraw 2.0, its Road to 2.0 item 3).

GuildDraw writes, per workspace, the stock guide the design is drawn against,
``guides: {"stock": {"width_mm", "height_mm"}}``, with the pad block's guide
(``"pad"``) beside it on the front, in scene mm with the width along x.
GuildModel seeds a new project's blanks from them: the front's blank and pad
block, each temple's blank. A file without the key keeps the shop's defaults,
and a reopened or reloaded project keeps its own.
"""
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from guildmodel.core.io_import.gdraw import TABS, read_gdraw
from guildmodel.core.project.schema import ComponentKind
from guildmodel.gui.component_workspace import (build_workspaces_from_gdraw,
                                                seed_blank_from_guides)

_SVG_NS = "http://www.w3.org/2000/svg"


def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _front(guides=None):
    state = {"mirror": {"x": 0.0, "enabled": False}, "curves": [
        _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
        _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
        _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
    ]}
    if guides is not None:
        state["guides"] = guides
    return state


def _temple(guides=None):
    state = {"mirror": {"enabled": False}, "curves": [
        _line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True)]}
    if guides is not None:
        state["guides"] = guides
    return state


def _gdraw(path, states):
    ET.register_namespace("", _SVG_NS)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab in TABS:
            root = ET.Element(f"{{{_SVG_NS}}}svg")
            ET.SubElement(root, f"{{{_SVG_NS}}}metadata").text = json.dumps(
                states.get(tab, {"curves": []}))
            zf.writestr(f"{tab}.svg", ET.tostring(root, xml_declaration=True,
                                                  encoding="utf-8"))
    return path


FRONT_GUIDES = {"stock": {"width_mm": 180.0, "height_mm": 90.0},
                "pad": {"width_mm": 50.0, "height_mm": 40.0}}
TEMPLE_GUIDES = {"stock": {"width_mm": 160.0, "height_mm": 28.0}}


def test_the_reader_carries_each_workspaces_guides(tmp_path):
    path = _gdraw(tmp_path / "g.gdraw", {"front": _front(FRONT_GUIDES),
                                         "temple_r": _temple(TEMPLE_GUIDES),
                                         "temple_l": _temple()})
    doc = read_gdraw(path)
    assert doc.workspaces["front"].guides == {"stock": (180.0, 90.0), "pad": (50.0, 40.0)}
    assert doc.workspaces["temple_r"].guides == {"stock": (160.0, 28.0)}
    assert doc.workspaces["temple_l"].guides == {}


@pytest.mark.parametrize("bad", [
    "170 x 85", {"stock": "big"}, {"stock": {"width_mm": "wide", "height_mm": 85}},
    {"stock": {"width_mm": -170.0, "height_mm": 85.0}},
    {"stock": {"width_mm": float("nan"), "height_mm": 85.0}}, {"stock": {}},
])
def test_a_guide_that_is_not_a_size_is_ignored(tmp_path, bad):
    path = _gdraw(tmp_path / "g.gdraw", {"front": _front(bad)})
    assert read_gdraw(path).workspaces["front"].guides == {}


def test_a_new_projects_blanks_come_from_the_guides(tmp_path):
    path = _gdraw(tmp_path / "g.gdraw", {"front": _front(FRONT_GUIDES),
                                         "temple_r": _temple(TEMPLE_GUIDES),
                                         "temple_l": _temple()})
    workspaces, _ = build_workspaces_from_gdraw(path)
    by_kind = {ws.kind: ws for ws in workspaces}
    front = by_kind[ComponentKind.FRAME_FRONT]
    thickness = front.castle_params.stock.blank_thickness_mm

    assert seed_blank_from_guides(front) == "blank 180 x 90 mm and pad block 50 x 40 mm"
    stock = front.castle_params.stock
    assert (stock.blank_length_mm, stock.blank_width_mm) == (180.0, 90.0)
    assert (stock.pad_block_length_mm, stock.pad_block_width_mm) == (50.0, 40.0)
    assert stock.blank_thickness_mm == thickness           # not in the guides

    right = by_kind[ComponentKind.TEMPLE_RIGHT]
    assert seed_blank_from_guides(right) == "blank 160 x 28 mm"
    assert (right.temple_params.blank_length_mm, right.temple_params.blank_width_mm) \
        == (160.0, 28.0)

    left = by_kind[ComponentKind.TEMPLE_LEFT]
    before = left.temple_params.model_dump()
    assert seed_blank_from_guides(left) is None             # no key: the defaults
    assert left.temple_params.model_dump() == before
    for ws in workspaces:
        if ws.kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
            assert seed_blank_from_guides(ws) is None


@pytest.mark.gui
def test_the_window_seeds_a_new_drawing_and_a_reload_keeps_the_makers_blank(
        tmp_path, monkeypatch):
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

    path = _gdraw(tmp_path / "g.gdraw", {"front": _front(FRONT_GUIDES)})
    win._load_model(path)
    stock = win._workspaces[0].castle_params.stock
    assert (stock.blank_length_mm, stock.blank_width_mm) == (180.0, 90.0)

    # The maker changes the blank; reloading the drawing keeps it.
    win._activate_workspace(0)
    win.params.blank_length.setValue(200.0)
    win._activate_workspace(1)
    win._on_reload_drawing()
    assert win._workspaces[0].castle_params.stock.blank_length_mm == pytest.approx(200.0)
