"""Shop defaults per kind of part — Preferences ▸ Parts — and the offers that can
be silenced (2026-09-27).

The Qt-free half pins `gui/part_defaults.py`: what a fresh workspace is seeded
with, what a saved project offers to adopt and when, sparse storage, and the
prefs keys. The window half (marked `gui`) pins the wiring: a fresh drawing
starts from the defaults, Save offers a departure once and adopts it on Yes,
"Don't ask again" silences the offer, and the material write-back honors its
switch. The Parts page and the Preferences dialog are exercised on their own,
unmarked, since neither needs a window.
"""
import json
import zipfile
from xml.etree import ElementTree as ET

import pytest

from guildmodel.core.project.schema import (
    BaseCurveBlockParams, CastleParams, ComponentKind, ProgramZero, StockDefinition,
    TempleParams,
)
from guildmodel.gui import part_defaults as pd
from guildmodel.gui import prefs as prefs_mod
from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

_SVG_NS = "http://www.w3.org/2000/svg"


# ------------------------------------------------------------------ a drawing

def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _svg_bytes(state):
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _make_gdraw(path, *, both_temples=False):
    front = {"curves": [
        _line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
        _line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
        _line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
        _line("SCULPT", [(0, -20), (0, 20)]),
        _line("SCULPT", [(30, -20), (30, 20)]),
        _line("HINGE", [(50, -5), (58, -5), (58, 5), (50, 5)], closed=True),
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


def _by_kind(workspaces):
    return {w.kind: w for w in workspaces}


LOWER_LEFT_TOP = ProgramZero(x_ref="left", y_ref="bottom", z_ref="top")

SHOP = {
    **prefs_mod.DEFAULTS,
    "part_defaults": {
        "frame_front": {"program_zero": LOWER_LEFT_TOP.model_dump(),
                        "params": {"stock": {"blank_thickness_mm": 8.0}}},
        "temple": {"program_zero": ProgramZero(x_ref="right", y_ref="top").model_dump(),
                   "params": {"snap_to_blank_end": False, "stock_side": "left",
                              "blank_length_mm": 180.0, "profile_tool": "flat_2mm"}},
        "base_curve": {"program_zero": LOWER_LEFT_TOP.model_dump(),
                       "params": {"hole_spacing_mm": 12.0, "hole_count": 2}},
    },
}


# ------------------------------------------------------------------ prefs keys

def test_shipped_prefs_carry_the_new_keys():
    assert prefs_mod.DEFAULTS["part_defaults"] == pd.empty()
    assert prefs_mod.DEFAULTS["part_defaults"] == {
        "frame_front": {}, "temple": {}, "base_curve": {}}
    for key in ("prompt_set_default_bed", "prompt_set_part_defaults",
                "prompt_material_writeback", "prompt_tool_feeds_writeback"):
        assert prefs_mod.DEFAULTS[key] is True


def test_an_old_prefs_file_gains_the_groups_and_keeps_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text(json.dumps({"dark_mode": True}), encoding="utf-8")
    p = prefs_mod.load()
    assert p["part_defaults"] == pd.empty()
    assert p["prompt_set_part_defaults"] is True and p["prompt_material_writeback"] is True
    # a file with one group set keeps it and still has the other two
    (tmp_path / "prefs.json").write_text(json.dumps(
        {"part_defaults": {"temple": {"params": {"stock_side": "left"}}}}), encoding="utf-8")
    p = prefs_mod.load()
    assert p["part_defaults"]["temple"] == {"params": {"stock_side": "left"}}
    assert p["part_defaults"]["frame_front"] == {} and p["part_defaults"]["base_curve"] == {}


# ------------------------------------------------------------------ seeding

def test_nothing_set_means_the_schema_defaults(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    pd.seed_workspaces(workspaces, prefs_mod.DEFAULTS)
    ws = _by_kind(workspaces)
    for w in workspaces:
        assert w.program_zero == ProgramZero()
    t = ws[ComponentKind.TEMPLE_RIGHT].temple_params
    assert t.snap_to_blank_end is True and t.stock_side == "right"
    assert t.fixture_zone == "temple_right"
    assert ws[ComponentKind.BASE_CURVE_LEFT].block_params.hole_count == 3
    assert ws[ComponentKind.FRAME_FRONT].castle_params.stock.blank_thickness_mm == 6.0


def test_seed_applies_the_shop_defaults_per_kind(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    pd.seed_workspaces(workspaces, SHOP)
    ws = _by_kind(workspaces)
    assert ws[ComponentKind.FRAME_FRONT].program_zero == LOWER_LEFT_TOP
    assert ws[ComponentKind.FRAME_FRONT].castle_params.stock.blank_thickness_mm == 8.0
    assert ws[ComponentKind.FRAME_FRONT].castle_params.stock.blank_length_mm == 170.0
    for kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
        t = ws[kind].temple_params
        assert ws[kind].program_zero == ProgramZero(x_ref="right", y_ref="top")
        assert t.snap_to_blank_end is False and t.stock_side == "left"
        assert t.blank_length_mm == 180.0 and t.profile_tool == "flat_2mm"
        assert t.blank_width_mm == 30.0                        # untouched field
    assert ws[ComponentKind.TEMPLE_LEFT].temple_params.fixture_zone == "temple_left"
    for kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
        b = ws[kind].block_params
        assert ws[kind].program_zero == LOWER_LEFT_TOP
        assert b.hole_spacing_mm == 12.0 and b.hole_count == 2
    assert ws[ComponentKind.BASE_CURVE_LEFT].block_params.fixture_zone == "bc_template_left"


def test_a_stored_value_that_no_longer_validates_is_dropped_alone():
    prefs = {"part_defaults": {"temple": {
        "program_zero": {"mode": "sideways"},
        "params": {"stock_side": "middle", "blank_length_mm": 180.0,
                   "engrave_depth_mm": 9.0}}}}          # last one: not a page field
    assert pd.default_program_zero(prefs, "temple_right") == ProgramZero()
    t = pd.default_params(prefs, "temple_right")
    assert t.stock_side == "right" and t.blank_length_mm == 180.0
    assert t.engrave_depth_mm == TempleParams().engrave_depth_mm


def test_seed_lays_overrides_over_what_the_workspace_came_with(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    front = _by_kind(workspaces)[ComponentKind.FRAME_FRONT]
    front.castle_params = CastleParams(onion_skin_mm=0.7)     # a value the drawing set
    pd.seed_workspace(front, SHOP)
    assert front.castle_params.onion_skin_mm == 0.7
    assert front.castle_params.stock.blank_thickness_mm == 8.0


# ------------------------------------------------------------------ the offer

def test_departures_need_every_enabled_part_of_a_kind_to_agree(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    pd.seed_workspaces(workspaces, prefs_mod.DEFAULTS)
    ws = _by_kind(workspaces)
    assert pd.departures(workspaces, prefs_mod.DEFAULTS) == []

    # the right temple re-zeroed; the left is disabled (empty), so it does not vote
    ws[ComponentKind.TEMPLE_RIGHT].program_zero = LOWER_LEFT_TOP
    deps = pd.departures(workspaces, prefs_mod.DEFAULTS)
    assert [(d.group, d.field) for d in deps] == [("temple", "program_zero")]
    assert deps[0].value == LOWER_LEFT_TOP.model_dump()

    # enable the left with a different zero: the temples disagree, nothing is offered
    ws[ComponentKind.TEMPLE_LEFT].enabled = True
    ws[ComponentKind.TEMPLE_LEFT].program_zero = ProgramZero(x_ref="right", y_ref="top")
    assert pd.departures(workspaces, prefs_mod.DEFAULTS) == []
    ws[ComponentKind.TEMPLE_LEFT].program_zero = LOWER_LEFT_TOP
    assert len(pd.departures(workspaces, prefs_mod.DEFAULTS)) == 1

    # the temples' alignment is offered, and their blank as one line
    for kind in (ComponentKind.TEMPLE_RIGHT, ComponentKind.TEMPLE_LEFT):
        ws[kind].temple_params = ws[kind].temple_params.model_copy(
            update={"snap_to_blank_end": False, "stock_side": "left",
                    "blank_length_mm": 200.0})
    fields = {(d.group, d.field) for d in pd.departures(workspaces, prefs_mod.DEFAULTS)}
    assert fields == {("temple", "program_zero"), ("temple", "snap_to_blank_end"),
                      ("temple", "stock_side"), ("temple", "stock")}

    # the front and the blocks offer their zero, not their onion skin or holes
    ws[ComponentKind.FRAME_FRONT].program_zero = LOWER_LEFT_TOP
    ws[ComponentKind.FRAME_FRONT].castle_params = CastleParams(onion_skin_mm=0.9)
    for kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT):
        ws[kind].program_zero = LOWER_LEFT_TOP
        ws[kind].block_params = BaseCurveBlockParams(hole_spacing_mm=14.0)
    fields = {(d.group, d.field) for d in pd.departures(workspaces, prefs_mod.DEFAULTS)}
    assert ("frame_front", "program_zero") in fields
    assert ("base_curve", "program_zero") in fields
    assert not any(f in ("onion_skin_mm", "hole_spacing_mm", "blank_length_mm")
                   for _, f in fields)
    assert ("frame_front", "stock") not in fields and ("base_curve", "stock") not in fields


def test_each_part_offers_its_stock_as_one_line(tmp_path):
    # A maker standardizes their own blanks as surely as their zeros: a stock
    # that departs is offered, one line per group, where every enabled part of
    # the group agrees, and is adopted whole and sparsely.
    workspaces, _ = build_workspaces_from_gdraw(
        _make_gdraw(tmp_path / "m.gdraw", both_temples=True))
    prefs = json.loads(json.dumps(prefs_mod.DEFAULTS))
    pd.seed_workspaces(workspaces, prefs)
    ws = _by_kind(workspaces)
    assert pd.departures(workspaces, prefs) == []

    front = ws[ComponentKind.FRAME_FRONT]
    front.castle_params = front.castle_params.model_copy(update={
        "stock": StockDefinition(blank_thickness_mm=8.0, use_pad_block=False)})
    right, left = ws[ComponentKind.TEMPLE_RIGHT], ws[ComponentKind.TEMPLE_LEFT]
    right.temple_params = right.temple_params.model_copy(update={"blank_width_mm": 32.0})
    deps = pd.departures(workspaces, prefs)
    assert [(d.group, d.field) for d in deps] == [("frame_front", "stock")]  # temples differ
    left.temple_params = left.temple_params.model_copy(update={"blank_width_mm": 32.0})
    deps = pd.departures(workspaces, prefs)
    assert [d.text() for d in deps] == [
        "Frame Front: blank 170 × 85 × 8 mm, no pad block",
        "Temples: blank 170 × 32 × 4 mm"]

    pd.adopt(prefs, deps)
    assert prefs["part_defaults"]["frame_front"] == {
        "params": {"stock": {"blank_thickness_mm": 8.0, "use_pad_block": False}}}
    assert prefs["part_defaults"]["temple"] == {"params": {"blank_width_mm": 32.0}}
    assert pd.departures(workspaces, prefs) == []
    json.dumps(prefs)                                    # what prefs.save writes

    # the next drawing starts on that stock
    fresh, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "n.gdraw"))
    pd.seed_workspaces(fresh, prefs)
    f = _by_kind(fresh)
    stock = f[ComponentKind.FRAME_FRONT].castle_params.stock
    assert stock.blank_thickness_mm == 8.0 and stock.use_pad_block is False
    assert f[ComponentKind.TEMPLE_RIGHT].temple_params.blank_width_mm == 32.0

    # back to the shipped stock: adopted, that is the entry's absence
    front.castle_params = front.castle_params.model_copy(update={"stock": StockDefinition()})
    deps = pd.departures(workspaces, prefs)
    assert [(d.group, d.field) for d in deps] == [("frame_front", "stock")]
    pd.adopt(prefs, deps)
    assert prefs["part_defaults"]["frame_front"] == {}


def test_departures_are_measured_against_the_shop_not_the_schema(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    pd.seed_workspaces(workspaces, SHOP)
    assert pd.departures(workspaces, SHOP) == []          # the shop's own values
    # back to the schema default is a departure from this shop's default
    _by_kind(workspaces)[ComponentKind.TEMPLE_RIGHT].program_zero = ProgramZero()
    deps = pd.departures(workspaces, SHOP)
    assert [(d.group, d.field) for d in deps] == [("temple", "program_zero")]


def test_adopt_ends_the_departure_and_stores_it_sparsely(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    prefs = json.loads(json.dumps(prefs_mod.DEFAULTS))
    pd.seed_workspaces(workspaces, prefs)
    ws = _by_kind(workspaces)
    ws[ComponentKind.TEMPLE_RIGHT].program_zero = LOWER_LEFT_TOP
    ws[ComponentKind.TEMPLE_RIGHT].temple_params = (
        ws[ComponentKind.TEMPLE_RIGHT].temple_params.model_copy(
            update={"snap_to_blank_end": False}))
    deps = pd.departures(workspaces, prefs)
    assert len(deps) == 2
    keys = [d.key() for d in deps]
    assert keys == [d.key() for d in pd.departures(workspaces, prefs)]   # stable identity
    pd.adopt(prefs, deps)
    assert prefs["part_defaults"]["temple"] == {
        "program_zero": LOWER_LEFT_TOP.model_dump(),
        "params": {"snap_to_blank_end": False}}
    assert prefs["part_defaults"]["frame_front"] == {}
    assert pd.departures(workspaces, prefs) == []
    json.dumps(prefs)                                    # what prefs.save writes


def test_a_departure_reads_like_the_maker():
    assert pd.Departure("temple", "program_zero", LOWER_LEFT_TOP.model_dump()).text() == (
        "Temples: program zero — Stock blank lower-left, top face")
    assert pd.Departure("temple", "snap_to_blank_end", False).text() == (
        "Temples: snap to blank end off")
    assert pd.Departure("temple", "stock_side", "left").text() == "Temples: stock side left"
    assert pd.Departure("frame_front", "stock",
                        pd.stock_of("frame_front", CastleParams())).text() == (
        "Frame Front: blank 170 × 85 × 6 mm, pad block 45 × 45 × 4 mm")
    assert pd.Departure("base_curve", "stock",
                        pd.stock_of("base_curve", BaseCurveBlockParams())).text() == (
        "Base-curve blocks: blank 70 × 70 × 4.7625 mm")
    assert pd.Departure("frame_front", "program_zero",
                        ProgramZero(mode="fixture").model_dump()).text().startswith(
        "Frame Front: program zero — Fixture")


# ------------------------------------------------------------------ sparse storage

def test_adopting_the_schema_value_is_the_entrys_absence(tmp_path):
    # The shop says lower-left and snap off; the project went back to the
    # schema's center and snap on. Adopted, that is no entry at all — not the
    # schema value written out, which a moved shipped default would then miss.
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    prefs = json.loads(json.dumps(SHOP))
    pd.seed_workspaces(workspaces, prefs)
    ws = _by_kind(workspaces)[ComponentKind.TEMPLE_RIGHT]
    ws.program_zero = ProgramZero()
    ws.temple_params = ws.temple_params.model_copy(update={"snap_to_blank_end": True})
    deps = pd.departures(workspaces, prefs)
    assert {d.field for d in deps} == {"program_zero", "snap_to_blank_end"}
    pd.adopt(prefs, deps)
    temple = prefs["part_defaults"]["temple"]
    assert "program_zero" not in temple
    assert "snap_to_blank_end" not in temple["params"]
    assert temple["params"]["stock_side"] == "left"           # the rest of the shop's, kept
    assert pd.departures(workspaces, prefs) == []


def test_a_default_naming_a_tool_the_library_lost_is_dropped(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    t = pd.with_overrides(TempleParams(), "temple",
                          {"profile_tool": "no_such_tool", "blank_length_mm": 180.0})
    assert t.profile_tool == TempleParams().profile_tool     # the schema's, and shown as such
    assert t.blank_length_mm == 180.0                        # the rest applies
    assert pd.with_overrides(TempleParams(), "temple", {"profile_tool": "flat_2mm"}
                             ).profile_tool == "flat_2mm"


def test_sparse_storage_drops_schema_values():
    assert pd.sparse_zero(ProgramZero()) is None
    assert pd.sparse_zero(LOWER_LEFT_TOP) == LOWER_LEFT_TOP.model_dump()
    assert pd.sparse_params("temple", TempleParams()) == {}
    assert pd.sparse_params("temple", TempleParams(blank_length_mm=180.0,
                                                    engrave_depth_mm=1.0)) == {
        "blank_length_mm": 180.0}                        # engrave depth is not a page field
    front = CastleParams()
    front.stock.blank_thickness_mm = 8.0
    assert pd.sparse_params("frame_front", front) == {"stock": {"blank_thickness_mm": 8.0}}
    assert pd.sparse_params("frame_front", CastleParams()) == {}
    # what the page stores is what the seed reads back
    t = pd.with_overrides(pd.schema_default("temple_left"), "temple",
                          pd.sparse_params("temple", TempleParams(stock_side="left")))
    assert t.stock_side == "left" and t.fixture_zone == "temple_left"


# ------------------------------------------------------------------ the window

def _qt(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # a clean prefs file per test — the session-wide isolation in conftest is
    # shared, and these tests write part defaults
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(monkeypatch, tmp_path):
    _qt(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QMessageBox
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


def test_the_parts_page_round_trips_sparsely(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsPage

    assert PartDefaultsPage(dict(prefs_mod.DEFAULTS)).to_prefs() == pd.empty()
    page = PartDefaultsPage(SHOP)
    assert page.to_prefs() == SHOP["part_defaults"]
    # the stock-side combo follows the snap, as on the dock
    assert page.temple_side.isEnabled() is False
    page.temple_snap.setChecked(True)
    assert page.temple_side.isEnabled() is True
    # reset puts the schema back for that group only
    page._set_temple(pd.schema_default("temple_right"), ProgramZero())
    out = page.to_prefs()
    assert out["temple"] == {}
    assert out["frame_front"] == SHOP["part_defaults"]["frame_front"]


@pytest.mark.gui
def test_a_fresh_drawing_starts_from_the_shop_defaults(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    prefs_mod.save(SHOP)                                  # the shop's file, before the window
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    ws = _by_kind(win._workspaces)
    assert win.params._program_zero() == LOWER_LEFT_TOP    # the front is active
    assert win.params.castle_params().stock.blank_thickness_mm == 8.0
    idx = win._workspaces.index(ws[ComponentKind.TEMPLE_RIGHT])
    win._activate_workspace(idx)
    assert win.params._program_zero() == ProgramZero(x_ref="right", y_ref="top")
    t = win.params.temple_params()
    assert t.snap_to_blank_end is False and t.stock_side == "left"
    assert t.blank_length_mm == 180.0
    assert win.params.temple_stock_side.isEnabled() is False


def _lines(dlg):
    return "\n".join(cb.text() for cb in dlg.line_checks)


def test_the_offer_is_a_checkbox_per_line(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QDialogButtonBox
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsOffer

    deps = [pd.Departure("frame_front", "program_zero", LOWER_LEFT_TOP.model_dump()),
            pd.Departure("temple", "stock", pd.stock_of("temple", TempleParams()))]
    dlg = PartDefaultsOffer(deps)
    assert [cb.text() for cb in dlg.line_checks] == [d.text() for d in deps]
    assert dlg.chosen() == deps                           # every line checked to start
    no = dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.No)
    assert no.isDefault() and not dlg.yes_button.isDefault()
    assert dlg.yes_button.isEnabled() and not dlg.dont_ask.isChecked()
    dlg.line_checks[1].setChecked(False)                  # a one-off job's blank
    assert dlg.chosen() == [deps[0]]
    dlg.line_checks[0].setChecked(False)
    assert dlg.chosen() == [] and not dlg.yes_button.isEnabled()
    dlg.line_checks[1].setChecked(True)
    assert dlg.yes_button.isEnabled()


@pytest.mark.gui
def test_save_offers_a_departure_once_and_adopts_it_on_yes(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsOffer
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    shown = []
    answer = {"code": QDialog.DialogCode.Rejected}

    def fake_exec(dlg):
        shown.append(_lines(dlg))
        return answer["code"]
    monkeypatch.setattr(PartDefaultsOffer, "exec", fake_exec)

    gmodel = tmp_path / "m.gmodel"
    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert shown == []                                    # nothing departs yet

    win.params._set_program_zero(LOWER_LEFT_TOP)          # the front's zero
    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert len(shown) == 1 and "Frame Front: program zero" in shown[0]
    assert win._prefs["part_defaults"]["frame_front"] == {}   # No: nothing adopted

    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert len(shown) == 1                                # the same departure, once

    answer["code"] = QDialog.DialogCode.Accepted
    win.params._set_program_zero(ProgramZero(x_ref="right", y_ref="top", z_ref="top"))
    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert len(shown) == 2                                # a further change asks again
    assert win._prefs["part_defaults"]["frame_front"]["program_zero"] == (
        ProgramZero(x_ref="right", y_ref="top", z_ref="top").model_dump())
    on_disk = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))
    assert on_disk["part_defaults"]["frame_front"]["program_zero"]["x_ref"] == "right"
    assert pd.departures(win._workspaces, win._prefs) == []

    # the stock on the Stock tab too
    win.params.blank_thickness.setValue(8.0)
    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert len(shown) == 3
    assert "Frame Front: blank 170 × 85 × 8 mm, pad block 45 × 45 × 4 mm" in shown[2]
    assert win._prefs["part_defaults"]["frame_front"]["params"] == {
        "stock": {"blank_thickness_mm": 8.0}}
    # the next drawing starts there
    win2 = _window(monkeypatch, tmp_path)
    win2._load_model(_make_gdraw(tmp_path / "n.gdraw"))
    assert win2.params._program_zero() == ProgramZero(x_ref="right", y_ref="top", z_ref="top")
    assert win2.params.castle_params().stock.blank_thickness_mm == 8.0


@pytest.mark.gui
def test_the_offer_adopts_only_the_checked_lines_and_asks_once_each(tmp_path, monkeypatch):
    # A new zero as the shop's standard, on a job cut from an oversized blank:
    # the maker takes the zero and leaves the blank, and the blank is not asked
    # about again while a further change to the zero is.
    from PySide6.QtWidgets import QDialog
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsOffer
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    seen = []

    def take_the_zero(dlg):
        seen.append([cb.text() for cb in dlg.line_checks])
        for cb in dlg.line_checks:
            cb.setChecked("program zero" in cb.text())
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(PartDefaultsOffer, "exec", take_the_zero)

    gmodel = tmp_path / "m.gmodel"
    win.params._set_program_zero(LOWER_LEFT_TOP)
    win.params.blank_thickness.setValue(8.0)
    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert len(seen) == 1 and len(seen[0]) == 2
    assert win._prefs["part_defaults"]["frame_front"] == {
        "program_zero": LOWER_LEFT_TOP.model_dump()}      # the blank is left alone

    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert len(seen) == 1                                 # the blank still departs, asked once

    win.params._set_program_zero(ProgramZero(x_ref="right", y_ref="top"))
    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert len(seen) == 2 and len(seen[1]) == 1           # that change alone
    assert seen[1][0].startswith("Frame Front: program zero")
    assert win._prefs["part_defaults"]["frame_front"]["program_zero"]["x_ref"] == "right"
    assert "params" not in win._prefs["part_defaults"]["frame_front"]


@pytest.mark.gui
def test_save_itself_commits_the_typed_number_and_makes_the_offer(tmp_path, monkeypatch):
    # Ctrl+S, not `_maybe_prompt_part_defaults` by hand: the Save action reads
    # the panel, so a number typed and not yet committed with Enter or Tab must
    # be applied first, and the offer must follow the save.
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsOffer
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    win._project_path = tmp_path / "m.gmodel"
    shown = []

    def decline(dlg):
        shown.append(_lines(dlg))
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(PartDefaultsOffer, "exec", decline)
    win.params._set_program_zero(LOWER_LEFT_TOP)

    win.show()
    QApplication.setActiveWindow(win)
    box = win.params.feed_override
    box.setFocus()
    QApplication.processEvents()
    assert QApplication.focusWidget() is box
    box.selectAll()
    QTest.keyClicks(box, "777")
    assert box.value() != 777.0                               # typed, not yet applied

    win._on_save_project()
    assert box.value() == 777.0
    assert win.params.cam_params().feed_rate_mmpm == 777.0
    assert (tmp_path / "m.gmodel").exists()
    assert len(shown) == 1 and "Frame Front: program zero" in shown[0]


@pytest.mark.gui
def test_dont_ask_again_silences_the_part_defaults_offer(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsOffer
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    shown = []

    def decline_forever(dlg):
        shown.append(1)
        dlg.dont_ask.setChecked(True)
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(PartDefaultsOffer, "exec", decline_forever)

    gmodel = tmp_path / "m.gmodel"
    win.params._set_program_zero(LOWER_LEFT_TOP)
    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert shown == [1]
    assert win._prefs["prompt_set_part_defaults"] is False
    assert json.loads((tmp_path / "prefs.json").read_text(
        encoding="utf-8"))["prompt_set_part_defaults"] is False
    win.params._set_program_zero(ProgramZero(x_ref="right", y_ref="top"))
    assert win._save_gmodel_to(gmodel)
    win._maybe_prompt_part_defaults()
    assert shown == [1]                                   # silenced


@pytest.mark.gui
def test_material_writeback_honors_its_switch(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from guildmodel.gui import material_store
    win = _window(monkeypatch, tmp_path)
    monkeypatch.setattr(material_store, "changed_keys", lambda *a, **k: ["feed_rate_mmpm"])
    saved = []
    monkeypatch.setattr(material_store, "save_override", lambda *a, **k: saved.append(a))

    def boom(box):                                        # pragma: no cover
        raise AssertionError("asked while silenced")
    win._prefs["prompt_material_writeback"] = False
    monkeypatch.setattr(QMessageBox, "exec", boom)
    win._maybe_write_back_material()                      # no box, no write
    assert saved == []

    win._prefs["prompt_material_writeback"] = True

    def decline_forever(box):
        box.checkBox().setChecked(True)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "exec", decline_forever)
    win._maybe_write_back_material()
    assert win._prefs["prompt_material_writeback"] is False and saved == []

    win._prefs["prompt_material_writeback"] = True
    monkeypatch.setattr(QMessageBox, "exec", lambda box: QMessageBox.StandardButton.Yes)
    win._maybe_write_back_material()
    assert len(saved) == 1 and win._prefs["prompt_material_writeback"] is True


def test_preferences_general_tab_lists_the_four_prompts(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.gui.app import PrefsDialog
    prefs = dict(prefs_mod.DEFAULTS)
    prefs["prompt_set_part_defaults"] = False
    dlg = PrefsDialog(prefs)
    out = dlg.to_prefs()
    assert out["prompt_set_default_bed"] is True
    assert out["prompt_set_part_defaults"] is False
    assert out["prompt_material_writeback"] is True
    assert out["prompt_tool_feeds_writeback"] is True
    assert out["part_defaults"] == pd.empty()
    dlg._prompt_checks["prompt_set_part_defaults"].setChecked(True)
    assert dlg.to_prefs()["prompt_set_part_defaults"] is True
