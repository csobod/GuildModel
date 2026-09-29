"""The tool-library write-back offer (2026-09-27): Generate a program whose
per-tool feeds differ from the tool library and GuildModel offers, once, to
save them to the library, with Don't ask again and a switch under
Preferences ▸ General ▸ Prompts. The project keeps its own values either way.
"""
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from guildmodel.core.project.schema import ComponentKind, ToolFeeds

_SVG_NS = "http://www.w3.org/2000/svg"


# ------------------------------------------------------------------ the store

def _store(monkeypatch, tmp_path):
    from guildmodel.gui import tool_store
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    return tool_store


def test_departures_are_the_fields_that_differ_from_the_library(tmp_path, monkeypatch):
    ts = _store(monkeypatch, tmp_path)
    # the shipped V-bit: 300 / 100 / 14000
    assert ts.feed_departures("engrave_vbit", ToolFeeds(feed_rate_mmpm=300)) == {}
    assert ts.feed_departures("engrave_vbit", ToolFeeds(feed_rate_mmpm=250)) == {
        "feed_rate_mmpm": 250.0}
    assert ts.feed_departures("engrave_vbit", {"spindle_rpm": 16000, "plunge_rate_mmpm": 100}) == {
        "spindle_rpm": 16000.0}
    # the shipped bulk tool carries no feeds: anything set is a departure
    assert ts.feed_departures("flat_3175", ToolFeeds(feed_rate_mmpm=900)) == {
        "feed_rate_mmpm": 900.0}
    assert ts.feed_departures("no_such_tool", ToolFeeds(feed_rate_mmpm=900)) == {}
    assert ts.feed_departures("engrave_vbit", ToolFeeds()) == {}


def test_save_feeds_writes_the_library_and_keeps_the_rest(tmp_path, monkeypatch):
    ts = _store(monkeypatch, tmp_path)
    before = ts.spec("engrave_vbit")
    ts.save_feeds("engrave_vbit", {"feed_rate_mmpm": 250.0})
    after = ts.spec("engrave_vbit")
    assert after.feed_rate_mmpm == 250.0
    assert after.plunge_rate_mmpm == before.plunge_rate_mmpm == 100.0
    assert after.spindle_rpm == before.spindle_rpm
    assert after.included_angle_deg == before.included_angle_deg == 30.0
    assert (tmp_path / "tools.yaml").exists()
    assert ts.feed_departures("engrave_vbit", ToolFeeds(feed_rate_mmpm=250)) == {}
    ts.reset_tool("engrave_vbit")
    assert ts.spec("engrave_vbit").feed_rate_mmpm == 300.0


# ------------------------------------------------------------------ the window

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
    states = {"front": front, "temple_r": temple, "temple_l": {"curves": []},
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
    from guildmodel.gui import prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
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
def test_generate_offers_the_library_once_and_saves_on_yes(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    ts = _store(monkeypatch, tmp_path)
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    temple = next(i for i, w in enumerate(win._workspaces)
                  if w.kind == ComponentKind.TEMPLE_RIGHT)
    win._activate_workspace(temple)
    shown = []
    answer = {"btn": QMessageBox.StandardButton.No, "tick": False}

    def fake_exec(box):
        shown.append(box.informativeText())
        if answer["tick"]:
            box.checkBox().setChecked(True)
        return answer["btn"]
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    win._maybe_write_back_tool_feeds()
    assert shown == []                                        # nothing set per tool

    win.params.tool_feed_rows()["engrave_vbit"].feed.setValue(250.0)
    win._maybe_write_back_tool_feeds()
    assert len(shown) == 1 and "engrave_vbit: feed 250" in shown[0]
    assert ts.spec("engrave_vbit").feed_rate_mmpm == 300.0    # No: the library is untouched
    win._maybe_write_back_tool_feeds()
    assert len(shown) == 1                                    # the same departure, once

    win.params.tool_feed_rows()["engrave_vbit"].spindle.setValue(16000)
    answer["btn"] = QMessageBox.StandardButton.Yes
    win._maybe_write_back_tool_feeds()
    assert len(shown) == 2 and "spindle 16000" in shown[1]
    spec = ts.spec("engrave_vbit")
    assert spec.feed_rate_mmpm == 250.0 and spec.spindle_rpm == 16000.0
    assert spec.plunge_rate_mmpm == 100.0                     # the rest of the tool kept
    # the project keeps its own values, and nothing departs any more
    assert win.params.cam_params().tool_feeds["engrave_vbit"].feed_rate_mmpm == 250.0
    win._maybe_write_back_tool_feeds()
    assert len(shown) == 2

    # Don't ask again silences the offer and lands in the prefs file
    win.params.tool_feed_rows()["engrave_vbit"].plunge.setValue(80.0)
    answer.update(btn=QMessageBox.StandardButton.No, tick=True)
    win._maybe_write_back_tool_feeds()
    assert len(shown) == 3
    assert win._prefs["prompt_tool_feeds_writeback"] is False
    assert json.loads((tmp_path / "prefs.json").read_text(
        encoding="utf-8"))["prompt_tool_feeds_writeback"] is False
    win.params.tool_feed_rows()["engrave_vbit"].plunge.setValue(90.0)
    win._maybe_write_back_tool_feeds()
    assert len(shown) == 3                                    # silenced
