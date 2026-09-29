"""Feeds and speeds per tool (2026-09-27).

The chain, field by field: the project's setting for the tool (the Cut tab's
per-tool rows, `CastleCamParams.tool_feeds`), else the tool's own library feeds
(`tools.yaml`), else the program's feeds (the Cut tab's material row). One
resolver, `core.cam.feeds.resolve_tool_feeds`, serves the post and the panel,
so what the maker reads on the tab is what the machine gets — an engraving bit
that ships at 300 mm/min no longer runs there silently while the tab says 1200.
"""
import re

import pytest
from shapely.geometry import Polygon

from guildmodel.core.cam.castle_ops import (
    CamOp, build_tool_settings, op_summaries, stamp_cut_settings, write_castle_program,
)
from guildmodel.core.cam.feeds import resolve_tool_feeds
from guildmodel.core.cam.temple_ops import generate_temple_program
from guildmodel.core.post.grbl import GRBLPost
from guildmodel.core.post.machine import MachineProfile, clamp_cam_to_machine
from guildmodel.core.project.schema import CastleCamParams, TempleParams, ToolFeeds

TOOLS = {
    "flat_3175": {"name": "flat_3175", "diameter_mm": 3.175, "radius_mm": 1.5875,
                  "type": "flat", "flutes": 1},
    "flat_2mm": {"name": "flat_2mm", "diameter_mm": 2.0, "radius_mm": 1.0, "type": "flat",
                 "flutes": 2, "feed_rate_mmpm": 500.0, "plunge_rate_mmpm": 200.0,
                 "spindle_rpm": 12000},
    "engrave_vbit": {"name": "engrave_vbit", "diameter_mm": 0.5, "radius_mm": 0.25,
                     "type": "vbit", "flutes": 2, "feed_rate_mmpm": 300.0,
                     "plunge_rate_mmpm": 100.0, "spindle_rpm": 14000},
}
MAT = {"feed_rate_mmpm": 1200.0, "plunge_rate_mmpm": 450.0, "spindle_rpm": 10000,
       "max_doc_mm": 2.0}
OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])
HINGE = [Polygon([(55, -3), (65, -3), (65, 3), (55, 3)])]
ENGRAVING = [[(-30.0, 0.0), (30.0, 0.0)]]


def _op(name, tool, length=100.0):
    return CamOp(name, paths=[[(0.0, 0.0, 0.0), (length, 0.0, 0.0)]], tool=TOOLS[tool])


# ------------------------------------------------------------------ the resolver

def test_the_project_wins_then_the_tool_then_the_material_field_by_field():
    r = resolve_tool_feeds(TOOLS["engrave_vbit"], default_feed=1200, default_plunge=450,
                           default_spindle=10000, override=ToolFeeds(feed_rate_mmpm=250))
    assert (r.feed_rate_mmpm, r.plunge_rate_mmpm, r.spindle_rpm) == (250.0, 100.0, 14000)
    assert r.sources == ("project", "tool", "tool")
    assert r.source_label() == "this project"
    r = resolve_tool_feeds(TOOLS["flat_3175"], default_feed=1200, default_plunge=450,
                           default_spindle=10000)
    assert (r.feed_rate_mmpm, r.plunge_rate_mmpm, r.spindle_rpm) == (1200.0, 450.0, 10000)
    assert r.source_label() == "material"
    r = resolve_tool_feeds(TOOLS["flat_2mm"], default_feed=1200, default_plunge=450,
                           default_spindle=10000, override={"spindle_rpm": 16000})
    assert r.spindle_rpm == 16000 and r.feed_rate_mmpm == 500.0
    assert r.source_label() == "this project"
    assert resolve_tool_feeds(None, default_feed=1, default_plunge=2, default_spindle=3).sources == (
        "material", "material", "material")


def test_tool_feeds_round_trip_and_an_old_project_loads():
    cam = CastleCamParams(tool_feeds={"engrave_vbit": ToolFeeds(feed_rate_mmpm=250)})
    again = CastleCamParams(**cam.model_dump())
    assert again.tool_feeds["engrave_vbit"].feed_rate_mmpm == 250
    assert again.tool_feeds["engrave_vbit"].plunge_rate_mmpm is None
    assert CastleCamParams(**{"tool_name": "flat_3175"}).tool_feeds == {}   # v1.7 file
    assert ToolFeeds().is_empty() and not ToolFeeds(spindle_rpm=1).is_empty()
    with pytest.raises(Exception):
        ToolFeeds(feed_rate_mmpm=0)


# ------------------------------------------------------------------ the post

def test_build_tool_settings_takes_the_projects_feeds_and_still_clamps():
    ops = [_op("Engraving", "engrave_vbit"), _op("Hinge Pockets", "flat_2mm"),
           _op("Temple Profile", "flat_3175")]
    machine = MachineProfile(max_feed_mmpm=2000.0, max_spindle_rpm=15000.0)
    ts, warns = build_tool_settings(
        ops, TOOLS, default_feed=1200, default_plunge=450, default_spindle=10000,
        machine=machine,
        tool_feeds={"engrave_vbit": ToolFeeds(feed_rate_mmpm=250, spindle_rpm=18000),
                    "flat_3175": {"feed_rate_mmpm": 900}})
    assert ts["engrave_vbit"].feed_rate_mmpm == 250.0
    assert ts["engrave_vbit"].plunge_rate_mmpm == 100.0           # the library's
    assert ts["engrave_vbit"].spindle_rpm == 15000                 # clamped
    assert any("engrave_vbit" in w and "spindle" in w for w in warns)
    assert ts["flat_2mm"].feed_rate_mmpm == 500.0                 # untouched: the library's
    assert ts["flat_3175"].feed_rate_mmpm == 900.0                # the project's, as a dict
    assert ts["flat_3175"].spindle_rpm == 10000                    # the material's


def test_stamp_cut_settings_carries_the_projects_tool_feeds():
    ops = [_op("Engraving", "engrave_vbit"), _op("Temple Profile", "flat_3175")]
    cam = CastleCamParams(tool_feeds={"engrave_vbit": ToolFeeds(feed_rate_mmpm=250)})
    cam, clamp = clamp_cam_to_machine(cam, MachineProfile(), MAT)
    stamp_cut_settings(ops, TOOLS, cam, clamp)
    assert ops[0].cut.feed_rate_mmpm == 250.0
    assert ops[1].cut.feed_rate_mmpm == 1200.0


def test_op_summaries_time_each_op_at_its_own_tools_feed():
    ops = [_op("Engraving", "engrave_vbit", 300.0), _op("Temple Profile", "flat_3175", 1200.0)]
    ts, _ = build_tool_settings(ops, TOOLS, default_feed=1200, default_plunge=450,
                                default_spindle=10000)
    rows = op_summaries(ops, feed_rate_mmpm=1200.0, tool_settings=ts)
    assert rows[0]["est_minutes"] == pytest.approx(1.0)      # 300 mm at the bit's 300
    assert rows[1]["est_minutes"] == pytest.approx(1.0)      # 1200 mm at the material's 1200
    assert op_summaries(ops, feed_rate_mmpm=1200.0)[0]["est_minutes"] == pytest.approx(0.25)


def test_the_posted_temple_runs_the_bit_at_the_projects_feed():
    cam = CastleCamParams(tool_feeds={"engrave_vbit": ToolFeeds(feed_rate_mmpm=250)})
    cam, clamp = clamp_cam_to_machine(cam, MachineProfile(), MAT)
    ops = generate_temple_program(OUTLINE, ENGRAVING, TempleParams(), TOOLS, params=cam,
                                  hinge_polys=HINGE)
    ts, _ = build_tool_settings(
        ops, TOOLS, default_feed=clamp.feed_rate_mmpm, default_plunge=clamp.plunge_rate_mmpm,
        default_spindle=clamp.spindle_rpm, tool_feeds=cam.tool_feeds)
    first = ts[ops[0].tool_name]
    post = GRBLPost("t", "acetate", first.diameter_mm, first.spindle_rpm,
                    first.feed_rate_mmpm, first.plunge_rate_mmpm, safe_z_mm=15.0)
    write_castle_program(ops, post, tool_settings=ts)
    text = post.to_string()
    sections = re.split(r"--- Tool(?: Change ->)? T\d+: ", text)
    vbit = next(s for s in sections if s.startswith("engrave_vbit"))
    profile = next(s for s in sections if s.startswith("flat_3175"))
    assert re.search(r"\bF250(\.0+)?\b", vbit)
    assert not re.search(r"\bF300(\.0+)?\b", vbit)                 # the library's, overridden
    assert re.search(r"\bF1200(\.0+)?\b", profile)


# ------------------------------------------------------------------ the Cut tab

def _panel(monkeypatch, tmp_path):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from guildmodel.gui import material_store, tool_store
    monkeypatch.setattr(material_store, "_USER", tmp_path / "materials.yaml")
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.widgets.params_panel import ParamsPanel
    return ParamsPanel()


def test_the_rows_follow_the_component_and_its_tools(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(monkeypatch, tmp_path)
    rows = p.tool_feed_rows()
    assert "flat_3175" in rows and "flat_2mm" in rows            # the bulk tool + the hinge default
    assert "Hinge Pockets" in rows["flat_2mm"].ops
    assert rows["flat_3175"].source.text() == "material"
    assert rows["flat_2mm"].source.text() == "tool library"

    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    rows = p.tool_feed_rows()
    assert list(rows) == ["engrave_vbit", "flat_2mm", "flat_3175"]
    assert rows["engrave_vbit"].feed.value() == 300.0             # the library's, shown at last
    assert rows["engrave_vbit"].spindle.value() == 14000
    assert rows["flat_3175"].feed.value() == 1200.0               # acetate
    assert "0.120" in rows["flat_3175"].chip.text()               # 1200 / 10000 / 1 flute
    assert "within" in rows["flat_3175"].chip.text().lower()

    p.temple_profile_tool.setCurrentText("flat_2mm")             # one tool for two ops
    rows = p.tool_feed_rows()
    assert list(rows) == ["engrave_vbit", "flat_2mm"]
    assert rows["flat_2mm"].ops == ["Hinge Pockets", "Temple Profile"]

    p.set_component_kind(ComponentKind.BASE_CURVE_RIGHT)
    assert list(p.tool_feed_rows()) == ["drill_m4_clear", "flat_3175"]


def test_editing_a_row_is_the_projects_word_and_reset_takes_it_back(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(monkeypatch, tmp_path)
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    seen = []
    p.cam_changed.connect(lambda: seen.append(1))
    row = p.tool_feed_rows()["engrave_vbit"]
    row.feed.setValue(250.0)
    assert seen
    tf = p.cam_params().tool_feeds
    assert tf == {"engrave_vbit": ToolFeeds(feed_rate_mmpm=250.0)}
    row = p.tool_feed_rows()["engrave_vbit"]                      # the same row, refreshed
    assert row.source.text() == "this project" and row.reset_btn.isEnabled()
    assert row.spindle.value() == 14000                           # still the library's
    row.reset_btn.click()
    assert p.cam_params().tool_feeds == {}
    row = p.tool_feed_rows()["engrave_vbit"]
    assert row.feed.value() == 300.0 and row.source.text() == "tool library"
    assert not row.reset_btn.isEnabled()
    # a zero clears one field only
    row.spindle.setValue(16000)
    row.feed.setValue(250.0)
    row.feed.setValue(0)
    assert p.cam_params().tool_feeds == {"engrave_vbit": ToolFeeds(spindle_rpm=16000)}


def test_a_restored_project_shows_its_tool_feeds(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(monkeypatch, tmp_path)
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.set_cam_params(CastleCamParams(tool_feeds={"engrave_vbit": ToolFeeds(spindle_rpm=16000)}))
    row = p.tool_feed_rows()["engrave_vbit"]
    assert row.spindle.value() == 16000 and row.source.text() == "this project"
    assert p.cam_params().tool_feeds["engrave_vbit"].spindle_rpm == 16000


def test_the_material_row_flows_to_the_tools_that_inherit_it(tmp_path, monkeypatch):
    from guildmodel.core.project.schema import ComponentKind
    p = _panel(monkeypatch, tmp_path)
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.feed_override.setValue(900.0)
    rows = p.tool_feed_rows()
    assert rows["flat_3175"].feed.value() == 900.0                # inherits the material row
    assert rows["engrave_vbit"].feed.value() == 300.0             # has its own
    assert p.cam_params().tool_feeds == {}                        # nothing per tool was set


def test_the_rows_follow_the_components_overrides_and_its_groove(tmp_path, monkeypatch):
    # Activating a component restores its overrides and the groove under
    # blockSignals; the rows must be recomputed from them all the same, or they
    # show the previous component's feeds against this one's material row.
    from guildmodel.core.project.schema import CastleParams, ComponentCamOverrides, ComponentKind
    p = _panel(monkeypatch, tmp_path)
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    p.set_cam_overrides(ComponentCamOverrides(feed_rate_mmpm=600.0, spindle_rpm=9000))
    rows = p.tool_feed_rows()
    assert rows["flat_3175"].feed.value() == 600.0 and rows["flat_3175"].spindle.value() == 9000
    p.set_cam_overrides(None)                                     # the next temple: none
    rows = p.tool_feed_rows()
    assert rows["flat_3175"].feed.value() == 1200.0 and rows["flat_3175"].spindle.value() == 10000
    assert p.cam_params().tool_feeds == {}

    p.set_component_kind(ComponentKind.FRAME_FRONT)
    c = CastleParams()
    p.set_castle_params(c.model_copy(update={
        "lens_groove": c.lens_groove.model_copy(update={"enabled": True})}))
    assert any("Lens Groove" in row.ops for row in p.tool_feed_rows().values())
    p.set_castle_params(CastleParams())
    assert not any("Lens Groove" in row.ops for row in p.tool_feed_rows().values())

