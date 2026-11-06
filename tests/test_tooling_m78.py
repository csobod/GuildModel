"""Typed tool model + the editable tool library (BUILDPLAN M7.8).

`ToolSpec` promotes the loose ``tools.yaml`` entries to a validated model whose
`to_tool_dict()` is a drop-in for every existing consumer; `gui.tool_store` merges
the shipped baseline with a user library (``~/.guildmodel/tools.yaml``) so the maker
adds/edits/removes tools in Preferences instead of hand-editing YAML. Headless
except the PrefsDialog Tools-tab smoke (offscreen Qt).
"""
from pathlib import Path

import pytest
import yaml

from guildmodel.core.cam.tooling import ToolSpec
from guildmodel.core.cam.castle_ops import CamOp, build_tool_settings
from guildmodel.gui import tool_store

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildmodel" / "config"
SHIPPED_TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())


@pytest.fixture
def tmp_user(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    return tmp_path / "tools.yaml"


# ------------------------------------------------------------------ ToolSpec

def test_spec_reads_shipped_entry_and_derives_radius():
    s = ToolSpec.from_dict(SHIPPED_TOOLS["flat_3175"])
    assert s.type == "flat" and s.diameter_mm == 3.175
    assert s.radius_mm == pytest.approx(3.175 / 2)
    d = s.to_tool_dict()
    assert d["radius_mm"] == pytest.approx(3.175 / 2)
    assert d["type"] == "flat" and "diameter_mm" in d


def test_spec_reads_every_shipped_tool():
    for vals in SHIPPED_TOOLS.values():
        s = ToolSpec.from_dict(vals)
        assert s.diameter_mm > 0
        assert s.to_tool_dict()["radius_mm"] == pytest.approx(s.diameter_mm / 2)


def test_spec_omits_unset_feeds_keeps_set():
    bare = ToolSpec(display_name="X", diameter_mm=2.0)
    assert "feed_rate_mmpm" not in bare.to_tool_dict()          # unset → use material
    fed = ToolSpec(display_name="Y", diameter_mm=2.0, feed_rate_mmpm=500, spindle_rpm=12000)
    d = fed.to_tool_dict()
    assert d["feed_rate_mmpm"] == 500 and d["spindle_rpm"] == 12000


def test_spec_roundtrips_through_yaml():
    s = ToolSpec(display_name="V60", type="vbit", diameter_mm=6.0,
                 included_angle_deg=60.0, flutes=2, number=7, notes="engrave")
    back = ToolSpec.from_dict(s.to_yaml())
    assert back.type == "vbit" and back.included_angle_deg == 60.0
    assert back.number == 7 and back.notes == "engrave"
    assert back.to_tool_dict()["included_angle_deg"] == 60.0


# ------------------------------------------------------------------ store

def test_effective_equals_shipped_without_user(tmp_user):
    eff = tool_store.effective()
    assert set(eff) == set(SHIPPED_TOOLS)
    assert eff["flat_3175"]["diameter_mm"] == 3.175


def test_add_user_tool_appears(tmp_user):
    tool_store.save_tool("vbit_60", ToolSpec(display_name="60° V-bit", type="vbit",
                                             diameter_mm=6.0, included_angle_deg=60.0))
    eff = tool_store.effective()
    assert "vbit_60" in eff and eff["vbit_60"]["radius_mm"] == 3.0
    assert "vbit_60" in tool_store.names()
    assert not tool_store.is_shipped("vbit_60")


def test_override_and_reset_shipped(tmp_user):
    tool_store.save_tool("flat_3175",
                         tool_store.spec("flat_3175").model_copy(update={"flutes": 3}))
    assert tool_store.effective()["flat_3175"]["flutes"] == 3
    assert SHIPPED_TOOLS["flat_3175"]["flutes"] == 1            # shipped untouched
    tool_store.reset_tool("flat_3175")
    assert tool_store.effective()["flat_3175"]["flutes"] == 1


def test_delete_shipped_tombstones_then_resets(tmp_user):
    tool_store.delete_tool("flat_6mm")
    assert "flat_6mm" not in tool_store.effective()
    tool_store.reset_tool("flat_6mm")
    assert "flat_6mm" in tool_store.effective()


def test_delete_user_added_removes(tmp_user):
    tool_store.save_tool("temp", ToolSpec(display_name="t", diameter_mm=1.0))
    assert "temp" in tool_store.effective()
    tool_store.delete_tool("temp")
    assert "temp" not in tool_store.effective()


def test_import_export_roundtrip(tmp_user, tmp_path):
    tool_store.save_tool("custom", ToolSpec(display_name="c", diameter_mm=4.0))
    lib = tmp_path / "lib.tools"
    tool_store.export_library(lib)
    tool_store.reset_all()
    assert "custom" not in tool_store.effective()
    n = tool_store.import_library(lib)
    assert n >= 1 and "custom" in tool_store.effective()


# ------------------------------------------------------------------ stable T-numbers

def _op(name, tname, dia, *, number=None):
    tool = {"name": tname, "type": "flat", "radius_mm": dia / 2, "diameter_mm": dia}
    if number is not None:
        tool["number"] = number
    return CamOp(name, paths=[[(0.0, 0.0, 0.0)]], tool=tool)


def test_explicit_tool_number_is_honored():
    ops = [_op("A", "a", 2.0, number=5), _op("B", "b", 3.0)]
    ts, _ = build_tool_settings(ops, {}, default_feed=500, default_plunge=200,
                                default_spindle=10000)
    assert ts["a"].number == 5
    assert ts["b"].number != 5 and ts["b"].number >= 1


def test_a_made_up_number_never_takes_a_later_tools_own():
    """2.3.1: a tool without a number, cutting first, took T1 from a later
    tool whose pocket is 1, which was then made up too; on a tool changer
    that fetches the wrong pocket. Own numbers are reserved first; of two
    tools claiming one, the first in machining order keeps it."""
    ops = [_op("A", "a", 2.0), _op("B", "b", 3.0, number=1), _op("C", "c", 1.0, number=1)]
    ts, _ = build_tool_settings(ops, {}, default_feed=500, default_plunge=200,
                                default_spindle=10000)
    assert (ts["b"].number, ts["b"].numbered) == (1, True)
    assert ts["a"].number not in (1,) and not ts["a"].numbered
    assert ts["c"].number not in (1, ts["a"].number) and not ts["c"].numbered


def test_auto_numbering_is_back_compatible():
    ops = [_op("A", "a", 2.0), _op("B", "b", 3.0)]
    ts, _ = build_tool_settings(ops, {}, default_feed=500, default_plunge=200,
                                default_spindle=10000)
    assert ts["a"].number == 1 and ts["b"].number == 2


# ------------------------------------------------------------------ Preferences Tools tab

def test_an_edit_on_the_tools_tab_keeps_what_the_form_does_not_show(tmp_path, monkeypatch):
    """2.3.1, a maker's report: typing a Tool number on the lens-groove cutter
    warped its drawing and saved it with no V and no neck. The form rebuilt
    the tool from its own fields; the groove's form has none there."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import PrefsDialog

    dlg = PrefsDialog({"dark_mode": False, "show_log_on_start": False,
                       "preview_resolution_mm": 0.3, "export_resolution_mm": 0.15,
                       "last_output_dir": ""}, None)
    shipped = tool_store.spec("groove_drageoir")
    assert shipped.groove_depth_mm > 0 and shipped.neck_length_mm > 0
    row = [dlg._tool_list.item(i).data(0x0100) for i in range(dlg._tool_list.count())]
    dlg._tool_list.setCurrentRow(row.index("groove_drageoir"))
    dlg._tw["number"].setValue(3)                 # the edit the maker made
    spec = dlg._tool_working["groove_drageoir"]
    assert spec.number == 3
    for f in ("groove_depth_mm", "groove_width_mm", "neck_diameter_mm", "neck_length_mm"):
        assert getattr(spec, f) == getattr(shipped, f), f
    assert dlg._tool_view._spec == spec               # and drawn as kept
    dlg._save_tools()
    saved = tool_store.effective()["groove_drageoir"]
    assert saved["number"] == 3 and saved["groove_depth_mm"] == shipped.groove_depth_mm
    assert saved["neck_length_mm"] == shipped.neck_length_mm


def test_prefs_tools_tab_add_commits_to_library(tmp_path, monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(tool_store, "_USER", tmp_path / "tools.yaml")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import PrefsDialog

    prefs = {"dark_mode": False, "show_log_on_start": False,
             "preview_resolution_mm": 0.3, "export_resolution_mm": 0.15,
             "last_output_dir": ""}
    dlg = PrefsDialog(prefs, None)
    before = set(tool_store.names())
    dlg._on_tool_add()                          # stages a "New Tool"
    dlg._save_tools()                           # commit to the user library
    after = tool_store.effective()
    assert len(after) == len(before) + 1
    added = [n for n in after if n not in before]
    assert added and after[added[0]]["radius_mm"] > 0
    # shipped tools are still present and unchanged
    assert tool_store.effective()["flat_3175"]["diameter_mm"] == 3.175
