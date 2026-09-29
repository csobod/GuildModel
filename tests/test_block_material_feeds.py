"""A part cut from another material than the project's takes that material's
feeds, not the Cut tab's row (2026-09-29).

The Cut tab's feed, plunge and spindle are filled from the project material.
The per-tool feeds (2026-09-27) made that row the default of the temple and
block paths too, and posting against v1.7.0 found the lone base-curve block, in
acetal, cut at the acetate front's feeds: twice acetal's, with the header still
saying acetal. The bed had always done so, since it read a block's material
only from a Cut-tab override the block does not carry. Pinned here: the rule
(`feeds.for_material`), both bed seams, the panel, and the window's block path.
"""
import time
import zipfile
from pathlib import Path

import pytest
import yaml

from guildmodel.core.cam.feeds import ROW_FEED_FIELDS, for_material, material_key
from guildmodel.core.project.schema import (
    BaseCurveBlockParams, CastleCamParams, ComponentCamOverrides, ComponentKind,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "src" / "guildmodel" / "config"
FIXTURES = Path(__file__).parent / "fixtures"
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text(encoding="utf-8"))

#: A Cut tab row nobody would mistake for a preset.
ROW = CastleCamParams(feed_rate_mmpm=1100.0, plunge_rate_mmpm=400.0, spindle_rpm=9000)


def test_the_row_belongs_to_the_project_material():
    assert material_key("Acetate (cellulose)") == "acetate" and material_key("") == "acetate"
    assert for_material(ROW, "acetate", "acetate") is ROW
    bare = for_material(ROW, "acetal", "acetate")
    assert all(getattr(bare, f) is None for f in ROW_FEED_FIELDS)
    assert bare.contour_stepdown_mm == ROW.contour_stepdown_mm      # nothing else moves


def test_a_block_on_the_bed_cuts_as_acetal_without_an_override():
    from guildmodel.core.post.machine import load_machine_profile
    from guildmodel.gui.app import _spec_cam
    machine = load_machine_profile("guild_cnc", CONFIG)
    acetal = MATS["acetal"]

    block = {"mode": "block", "block": BaseCurveBlockParams(), "cam_overrides": None}
    cam, clamp, name = _spec_cam(block, ROW, machine, MATS, "acetate")
    assert name == "acetal"
    assert (clamp.feed_rate_mmpm, clamp.plunge_rate_mmpm, clamp.spindle_rpm) == (
        acetal["feed_rate_mmpm"], acetal["plunge_rate_mmpm"], acetal["spindle_rpm"])

    # its own override still wins
    block["cam_overrides"] = ComponentCamOverrides(feed_rate_mmpm=500.0)
    assert _spec_cam(block, ROW, machine, MATS, "acetate")[1].feed_rate_mmpm == 500.0

    # a part in the project material keeps the row
    front = {"mode": "castle", "cam_overrides": None}
    _cam, clamp, name = _spec_cam(front, ROW, machine, MATS, "acetate")
    assert name == "acetate" and clamp.feed_rate_mmpm == 1100.0 and clamp.spindle_rpm == 9000


def test_the_core_seam_reads_the_blocks_own_material():
    from guildmodel.core.cam.component import resolve_component_cam
    from guildmodel.core.post.machine import load_machine_profile
    from guildmodel.core.project.schema import Component
    machine = load_machine_profile("guild_cnc", CONFIG)
    block = Component.for_kind(ComponentKind.BASE_CURVE_RIGHT)
    _cam, clamp, _mat, name = resolve_component_cam(
        ROW, block, machine=machine, mats_cfg=MATS, material_name="acetate")
    assert name == "acetal" and clamp.feed_rate_mmpm == MATS["acetal"]["feed_rate_mmpm"]


# ------------------------------------------------------------------ the panel

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


def test_the_panel_hands_a_block_its_own_materials_feeds(tmp_path, monkeypatch):
    p = _panel(monkeypatch, tmp_path)
    p.feed_override.setValue(1100.0)
    p.spindle_override.setValue(9000)
    assert p.cam_params_for("acetate").feed_rate_mmpm == 1100.0
    bare = p.cam_params_for("acetal")
    assert bare.feed_rate_mmpm is None and bare.spindle_rpm is None
    ov = ComponentCamOverrides(material="acetal", feed_rate_mmpm=500.0)
    assert p.cam_params_for("acetal", ov).feed_rate_mmpm == 500.0

    # the Feeds & Speeds rows say what the block will post
    p.set_component_kind(ComponentKind.BASE_CURVE_RIGHT)
    assert p.posting_material_name() == "acetal"
    row = p.tool_feed_rows()["flat_3175"]
    assert row.feed.value() == MATS["acetal"]["feed_rate_mmpm"]
    assert row.spindle.value() == MATS["acetal"]["spindle_rpm"]
    assert p._material_caption.text().endswith("acetal")
    # a temple in the project material still inherits the row
    p.set_component_kind(ComponentKind.TEMPLE_RIGHT)
    assert p.tool_feed_rows()["flat_3175"].feed.value() == 1100.0


# ------------------------------------------------------------------ the window

def _pump(app, until, timeout=120.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.02)
    return False


@pytest.mark.gui
def test_the_block_posted_from_the_front_tab_cuts_at_acetals_feeds(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, lambda *a, **k: None)
    try:
        from guildmodel.gui.app import MainWindow, OpSummaryDialog
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    monkeypatch.setattr(OpSummaryDialog, "exec", lambda self: 0)   # the setup sheet is modal
    win.view3d.show_mesh = lambda *a, **k: None
    win.view3d.show_flat = lambda *a, **k: None

    gdraw = tmp_path / "gabriel.gdraw"
    with zipfile.ZipFile(gdraw, "w") as zf:
        for f in sorted((FIXTURES / "gabriel").iterdir()):
            zf.write(f, f.name)
    win._load_model(gdraw)
    assert _pump(app, lambda: win._act_block.isEnabled())
    win.params.feed_override.setValue(1100.0)                 # the front's acetate row
    win.params.plunge_override.setValue(400.0)
    win.params.spindle_override.setValue(9000)

    win._last_programs = {}
    win._on_generate_block()
    th = lambda: win._gcode_thread
    assert _pump(app, lambda: win._last_programs and not th().isRunning())
    text = win._last_programs["base_curve_block.nc"]
    profile = text.split("--- Block Profile ---")[1]
    acetal = MATS["acetal"]
    assert f"M3 S{acetal['spindle_rpm']}" in text and "S9000" not in text
    assert f"F{acetal['feed_rate_mmpm']:.0f}" in profile
    assert "F1100" not in profile and "F400" not in profile
