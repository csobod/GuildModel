"""Parts on the bed, on and off (BUILDPLAN M19 §4).

Batch production cuts the base-curve templates once. Until M19 every populated
component went onto the worktable, with no way to leave one off short of
removing it from the drawing, and the Worktable panel had no list of parts.
`Component.on_bed` is the switch: distinct from `enabled` ("in this model"), a
part off the bed keeps its tab, builds, exports and posts on its own, and is
left out of the nest's program, its setup sheet and the bed simulation.

The Qt-free half pins the schema (a v1.8.x file opens with every part on the
bed; the switch round-trips), the shop default per kind of part and its sparse
storage, the nest restricted to the parts on the bed, and that nothing in the
core reads the switch, so no program can depend on it. The Parts page is
exercised on its own, unmarked. The window half (marked `gui`) pins the wiring:
the Parts rows and the canvas follow each other, Delete on a footprint
unchecks, Generate leaves the part out and says so on the sheet, and a part off
the bed is saved and reopens off while a fresh drawing is seeded from the shop.
"""
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml

from guildmodel.core.cam.castle_ops import CamOp
from guildmodel.core.cam.layout import (
    BedPart, build_nest_program, nest_components_on_worktable,
)
from guildmodel.core.project.schema import (
    Component, ComponentKind, ProjectSchema, Worktable,
)
from guildmodel.gui import part_defaults as pd
from guildmodel.gui import prefs as prefs_mod
from guildmodel.gui.component_workspace import build_workspaces_from_gdraw

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "src" / "guildmodel" / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
FIXTURE = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text())

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


def _make_gdraw(path):
    """A front, both temples and so both base-curve blocks: five parts."""
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
    states = {"front": front, "temple_r": temple, "temple_l": temple,
              "hinge": {"curves": []}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))
    return path


def _by_kind(workspaces):
    return {w.kind: w for w in workspaces}


BLOCKS_OFF = {**prefs_mod.DEFAULTS, "part_defaults": {
    "frame_front": {}, "temple": {}, "base_curve": {"on_bed": False}}}


# ------------------------------------------------------------------ the schema

def test_on_bed_defaults_on_and_a_file_from_before_opens_that_way():
    assert Component.for_kind(ComponentKind.TEMPLE_LEFT).on_bed is True
    # a v1.8.x project.json has no such key
    before = {"id": "temple_l", "kind": "temple_left", "enabled": True}
    assert Component.model_validate(before).on_bed is True
    proj = ProjectSchema(components=[Component.model_validate(before)])
    dump = json.loads(proj.model_dump_json())
    for c in dump["components"]:
        c.pop("on_bed", None)
    assert all(c.on_bed for c in ProjectSchema.model_validate(dump).components)


def test_on_bed_round_trips_through_a_gmodel(tmp_path):
    from guildmodel.core.project.gmodel import load_gmodel, save_gmodel
    p = ProjectSchema(job_name="Batch")
    p.add_component(Component.for_kind(ComponentKind.FRAME_FRONT))
    p.add_component(Component.for_kind(ComponentKind.BASE_CURVE_RIGHT, on_bed=False))
    path = tmp_path / "batch.gmodel"
    save_gmodel(path, project=p, dxf_bytes=b"dxf")
    comps = {c.kind: c for c in load_gmodel(path).project.components}
    assert comps[ComponentKind.FRAME_FRONT].on_bed is True
    assert comps[ComponentKind.BASE_CURVE_RIGHT].on_bed is False
    assert comps[ComponentKind.BASE_CURVE_RIGHT].enabled is True   # off the bed, in the model


def test_nothing_in_the_core_reads_the_switch():
    """A part's own program cannot depend on the box: the only core file that
    knows the field is the schema that declares it."""
    core = ROOT / "src" / "guildmodel" / "core"
    readers = sorted(str(p.relative_to(core)) for p in core.rglob("*.py")
                     if "on_bed" in p.read_text(encoding="utf-8"))
    assert readers == ["project/schema.py"]


# ------------------------------------------------------------------ the shop default

def test_the_default_reads_sparsely():
    assert pd.default_on_bed(prefs_mod.DEFAULTS, "frame_front") is True
    assert pd.default_on_bed(None, "temple_left") is True
    assert pd.default_on_bed(BLOCKS_OFF, "base_curve_left") is False
    assert pd.default_on_bed(BLOCKS_OFF, "base_curve_right") is False
    assert pd.default_on_bed(BLOCKS_OFF, "temple_right") is True
    odd = {"part_defaults": {"temple": {"on_bed": "no"}}}
    assert pd.default_on_bed(odd, "temple_right") is True          # only an explicit false


def test_seeding_leaves_the_blocks_off_for_a_batch_shop(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    assert all(w.on_bed for w in workspaces)
    pd.seed_workspaces(workspaces, BLOCKS_OFF)
    ws = _by_kind(workspaces)
    assert ws[ComponentKind.BASE_CURVE_RIGHT].on_bed is False
    assert ws[ComponentKind.BASE_CURVE_LEFT].on_bed is False
    assert ws[ComponentKind.FRAME_FRONT].on_bed is True
    assert ws[ComponentKind.TEMPLE_LEFT].on_bed is True
    pd.seed_workspaces(workspaces, prefs_mod.DEFAULTS)
    assert all(w.on_bed for w in workspaces)


def test_the_switch_is_never_a_save_offer(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    pd.seed_workspaces(workspaces, prefs_mod.DEFAULTS)
    for w in workspaces:
        w.on_bed = False
    assert pd.departures(workspaces, prefs_mod.DEFAULTS) == []
    pd.seed_workspaces(workspaces, BLOCKS_OFF)
    for w in workspaces:
        w.on_bed = True
    assert pd.departures(workspaces, BLOCKS_OFF) == []


def _qt(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_parts_page_offers_the_default_and_reset_restores_on(tmp_path, monkeypatch):
    _qt(monkeypatch, tmp_path)
    from guildmodel.core.project.schema import ProgramZero
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsPage

    page = PartDefaultsPage(dict(prefs_mod.DEFAULTS))
    assert page.front_on_bed.isChecked() and page.temple_on_bed.isChecked()
    assert page.block_on_bed.isChecked()
    assert page.to_prefs() == pd.empty()                  # on is the entry's absence
    page.block_on_bed.setChecked(False)
    assert page.to_prefs() == BLOCKS_OFF["part_defaults"]
    page = PartDefaultsPage(BLOCKS_OFF)
    assert page.block_on_bed.isChecked() is False and page.front_on_bed.isChecked()
    page._set_block(pd.schema_default("base_curve_right"), ProgramZero())
    assert page.block_on_bed.isChecked() and page.to_prefs() == pd.empty()


# ------------------------------------------------------------------ the nest

def _op(name, tool, pts):
    return CamOp(name, paths=[[(x, y, 0.0) for x, y in pts]],
                 tool={**TOOLS[tool], "name": tool})


def _parts(labels_by_kind: dict) -> list:
    return [BedPart(kind, label, "",
                    [_op("Perimeter", "flat_3175", [(-5, -5), (5, 5)])],
                    {"Perimeter"}, set())
            for kind, label in labels_by_kind.items()]


def test_a_nest_subset_shares_its_placements_and_drops_the_rest_from_the_program():
    bed = Worktable.from_fixture_dict(FIXTURE)
    nest = nest_components_on_worktable(
        _parts({"frame_front": "Frame", "base_curve_right": "Block"}), bed)
    part = nest.subset(["Frame"])
    assert [pl.label for pl in part.placements] == ["Frame"]
    assert part.placements[0] is nest.placements[0]        # shared, not copied
    assert part.work_area == nest.work_area and part.unplaced == nest.unplaced
    prog = build_nest_program(part)
    assert {op.name for op in prog.ops} == {"Frame · Perimeter"}
    assert nest.subset([]).placements == []
    nest.placements[0].nudge(3.0, 0.0)                     # a nudge is seen through both
    assert part.placements[0].dx == nest.placements[0].dx


# ------------------------------------------------------------------ the window

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


def _nest_every_part(win):
    """Every workspace auto-placed on the Guild bed (M20): placements, no
    programs."""
    bed = Worktable.from_fixture_dict(FIXTURE)
    win._worktable = bed
    win.bed_canvas.set_worktable(bed)
    win._on_nest_components()
    nest = win._wt_nest
    assert len(nest.placements) == len(win._workspaces)
    return bed, nest


@pytest.mark.gui
def test_the_parts_rows_and_the_bed_follow_each_other(tmp_path, monkeypatch):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    _bed, nest = _nest_every_part(win)
    n = len(win._workspaces)
    assert n == 5
    assert len(win.bed_canvas._placements) == n == win._bed_parts_list.count()
    assert "5 on the bed" in win._bed_nest_status.text()

    ws = _by_kind(win._workspaces)[ComponentKind.BASE_CURVE_RIGHT]
    pl = nest.get(win._component_id(ws))
    win._rotate_placement(ws, pl, 90.0)
    win._on_component_stepped(pl.zone_id, 2.0, -1.0)
    before = (pl.dx, pl.dy, pl.rotation_deg)
    item = win._bed_parts_item(ws.label)
    assert item.checkState() == Qt.CheckState.Checked

    item.setCheckState(Qt.CheckState.Unchecked)              # the row's box
    assert ws.on_bed is False and win._dirty
    assert len(win.bed_canvas._placements) == n - 1
    assert ws.label not in {p["label"] for p in win.bed_canvas._placements}
    assert nest.get(win._component_id(ws)) is pl             # kept in the nest, hidden
    assert win._bed_parts_item(ws.label).text().endswith("(off)")
    assert "4 on the bed · 1 off" in win._bed_nest_status.text()
    assert win._bed_gen_btn.isEnabled() and win._bed_sim_enabled()

    win._bed_parts_item(ws.label).setCheckState(Qt.CheckState.Checked)
    assert ws.on_bed is True and len(win.bed_canvas._placements) == n
    again = nest.get(win._component_id(ws))
    assert again is pl and (again.dx, again.dy, again.rotation_deg) == before

    # picking a row selects the footprint; a click on the bed picks the row
    tl = _by_kind(win._workspaces)[ComponentKind.TEMPLE_LEFT]
    row = win._bed_parts_list.row(win._bed_parts_item(tl.label))
    win._bed_parts_list.setCurrentRow(row)
    pl_tl = nest.get(win._component_id(tl))
    assert win._selected_placement() is pl_tl
    assert win.bed_canvas.selected_placement_zone() == pl_tl.zone_id
    win._on_bed_placement_selected("")
    assert win._bed_parts_list.currentItem() is None
    win.bed_canvas.set_selected_placement(pl_tl.zone_id)
    win._on_bed_placement_selected(pl_tl.zone_id)
    assert win._bed_parts_list.currentItem() is win._bed_parts_item(tl.label)

    # Delete on the selected footprint unchecks it
    win.bed_canvas.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier))
    assert tl.on_bed is False
    assert win._selected_placement() is None
    assert win._bed_parts_item(tl.label).checkState() == Qt.CheckState.Unchecked

    # every part off: nothing to generate or simulate
    for w in win._workspaces:
        if w.on_bed:
            win._set_part_on_bed(w, False)
    assert win._bed_targets() == []
    assert not win._bed_gen_btn.isEnabled() and not win._bed_sim_enabled()
    assert "0 on the bed · 5 off" in win._bed_nest_status.text()


@pytest.mark.gui
def test_generate_leaves_a_part_off_and_says_so_on_the_sheet(tmp_path, monkeypatch):
    import guildmodel.gui.app as app_mod
    monkeypatch.setattr(app_mod.OpSummaryDialog, "exec", lambda self: 0)
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    _nest_every_part(win)
    ws = _by_kind(win._workspaces)
    front = ws[ComponentKind.FRAME_FRONT]
    win._set_part_on_bed(front, False)        # the castle relief is the slow part
    off = ws[ComponentKind.BASE_CURVE_RIGHT]
    win._set_part_on_bed(off, False)

    win._on_generate_worktable_nest(sync=True)
    setup = win._wt_setup
    assert setup["component"] == "worktable"
    on = sorted(p["label"] for p in setup["parts"])
    assert on == sorted(w.label for w in win._workspaces if w not in (off, front))
    assert setup["not_on_bed"] == [{"label": front.label, "kind": "frame_front"},
                                   {"label": off.label, "kind": "base_curve_right"}]
    text = win._wt_programs["worktable.nc"]
    assert f"{off.label} · Block Profile" not in text
    assert f"{ws[ComponentKind.BASE_CURVE_LEFT].label} · Block Profile" in text
    assert f"{ws[ComponentKind.TEMPLE_RIGHT].label} · Temple Profile" in text

    # with the part back on, the sheet names it and the program cuts it
    win._set_part_on_bed(off, True)
    win._on_generate_worktable_nest(sync=True)
    assert win._wt_setup["not_on_bed"] == [{"label": front.label, "kind": "frame_front"}]
    assert len(win._wt_setup["parts"]) == 4
    assert f"{off.label} · Block Profile" in win._wt_programs["worktable.nc"]


@pytest.mark.gui
def test_a_part_off_the_bed_is_saved_and_a_fresh_drawing_is_seeded(tmp_path, monkeypatch):
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    assert all(w.on_bed for w in win._workspaces)
    off = _by_kind(win._workspaces)[ComponentKind.TEMPLE_LEFT]
    win._set_part_on_bed(off, False)
    assert win._bed_parts_item(off.label).checkState().name == "Unchecked"
    path = tmp_path / "p.gmodel"
    assert win._save_gmodel_to(path, announce=False)

    again = _window(monkeypatch, tmp_path)
    again._open_project(path, remember=False)
    ws2 = _by_kind(again._workspaces)
    assert ws2[ComponentKind.TEMPLE_LEFT].on_bed is False
    assert ws2[ComponentKind.TEMPLE_LEFT].enabled is True
    assert all(w.on_bed for w in again._workspaces if w is not ws2[ComponentKind.TEMPLE_LEFT])
    assert again._bed_parts_item(off.label).checkState().name == "Unchecked"
    assert again._dirty is False

    # a batch shop's fresh drawing opens with the blocks off, the rest on; the
    # saved project above is not touched by the shop default
    prefs_mod.save(BLOCKS_OFF)
    third = _window(monkeypatch, tmp_path)
    third._load_model(_make_gdraw(tmp_path / "m2.gdraw"))
    ws3 = _by_kind(third._workspaces)
    assert ws3[ComponentKind.BASE_CURVE_RIGHT].on_bed is False
    assert ws3[ComponentKind.BASE_CURVE_LEFT].on_bed is False
    assert ws3[ComponentKind.FRAME_FRONT].on_bed and ws3[ComponentKind.TEMPLE_RIGHT].on_bed
    assert third._bed_parts_item(ws3[ComponentKind.BASE_CURVE_LEFT].label).checkState().name == "Unchecked"
    fourth = _window(monkeypatch, tmp_path)
    fourth._open_project(path, remember=False)
    ws4 = _by_kind(fourth._workspaces)
    assert ws4[ComponentKind.BASE_CURVE_RIGHT].on_bed is True   # the project's own word
    assert ws4[ComponentKind.TEMPLE_LEFT].on_bed is False
