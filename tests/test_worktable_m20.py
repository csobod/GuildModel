"""The Worktable, redone (BUILDPLAN M20 §5).

Placement apart from generation: a part's footprint — its blank and the
outline it cuts, in the frame its program is generated in — is placed on the
bed with no program in hand, the placement is saved with the project and
reopens where it was, and the program is generated at Generate, once per part,
cached by a key of everything it depends on. A placement that no longer
matches its key is *stale*; one whose grown footprint reaches a keep-out is in
*collision*; one whose zone is gone is *unplaced*. The M6.5 fixture-dict path
is retired.

The Qt-free half pins `core/cam/placement.py` and the schema; the window half
(marked `gui`) drives the redesigned panel: place, move, turn, generate, go
stale, save and reopen; Reload Drawing and the watcher chip; a drop on the
window and the title; Simulate Bed generating first. The flows the archived
plan asked for — the hotkey migration, the readiness dot's verdict — are pinned
here too.
"""
import ast
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml
from shapely.geometry import Polygon, box

from guildmodel.core.cam.castle_ops import CamOp, build_tool_settings, write_castle_program
from guildmodel.core.cam.layout import BedPart, build_nest_program, nest_components_on_worktable
from guildmodel.core.cam.placement import (
    Footprint, auto_place, bed_program_key, footprint_block, footprint_front,
    footprint_temple, footprint_violations, geometry_fingerprint, legacy_layout_to_nest,
    nest_from_placements, off_bed_violations, part_program_key, placed, placement_key,
    program_key, rotate_about_center, send_to_zone, snap_to_zone,
)
from guildmodel.core.post.grbl import GRBLPost
from guildmodel.core.project.schema import (
    BaseCurveBlockParams, BedLayout, BedRole, CastleCamParams, CastleParams, Component,
    ComponentKind, ComponentPlacement, MachineProfile, ProgramZero, ProjectSchema,
    TempleParams, Worktable, WorktableNest, WorktablePlacement, WorktableZone,
)
from guildmodel.gui import prefs as prefs_mod

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "guildmodel"
CONFIG = SRC / "config"
TOOLS = yaml.safe_load((CONFIG / "tools.yaml").read_text())
MATS = yaml.safe_load((CONFIG / "materials.yaml").read_text())
FIXTURE = yaml.safe_load((CONFIG / "fixtures" / "guild_cnc.yaml").read_text())

_SVG_NS = "http://www.w3.org/2000/svg"


def _rect_zone(zid, role, x0, y0, x1, y1):
    return WorktableZone(id=zid, role=role,
                         polygon=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _op(name, tool, pts):
    return CamOp(name, paths=[[(x, y, 0.0) for x, y in pts]],
                 tool={**TOOLS[tool], "name": tool})


def _fp(cid, kind, w=20.0, h=10.0, radius=1.0, rot=0.0):
    return Footprint(cid, kind, cid, box(-w / 2, -h / 2, w / 2, h / 2),
                     box(-w / 2 + 2, -h / 2 + 2, w / 2 - 2, h / 2 - 2), radius, rot)


# ------------------------------------------------------------------ the schema

def test_a_nest_round_trips_through_a_gmodel(tmp_path):
    from guildmodel.core.project.gmodel import load_gmodel, save_gmodel
    p = ProjectSchema(job_name="Bed")
    p.worktable_nest = WorktableNest(placements=[
        WorktablePlacement(component_id="front", zone_id="front", dx=201.123456,
                           dy=144.3, rotation_deg=0.0, program_key="k1:p1"),
        WorktablePlacement(component_id="temple_l", zone_id="temple_left", dx=54.8,
                           dy=147.3, rotation_deg=180.0),
    ], program_key="bed1")
    path = tmp_path / "bed.gmodel"
    save_gmodel(path, project=p, dxf_bytes=b"dxf")
    nest = load_gmodel(path).project.worktable_nest
    assert nest.program_key == "bed1"
    for a, b in zip(p.worktable_nest.placements, nest.placements):
        assert (a.component_id, a.zone_id, a.program_key) == (b.component_id, b.zone_id, b.program_key)
        assert (a.dx, a.dy, a.rotation_deg) == pytest.approx((b.dx, b.dy, b.rotation_deg), abs=1e-6)
    assert nest.get("temple_l").rotation_deg == 180.0
    assert nest.on_zone("front").component_id == "front"
    # a 1.8.x file has no nest
    assert ProjectSchema.model_validate({"job_name": "old"}).worktable_nest.placements == []


def test_the_nest_puts_replaces_and_removes():
    nest = WorktableNest()
    a = nest.put(WorktablePlacement(component_id="a", zone_id="z1"))
    nest.put(WorktablePlacement(component_id="a", zone_id="z2"))
    assert [pl.zone_id for pl in nest.placements] == ["z2"]
    assert nest.get("a") is not a
    assert nest.remove("a") and not nest.remove("a")
    assert nest.placements == []


def test_a_legacy_bed_layout_converts_to_a_nest():
    """A 1.7-era BedLayout (by kind, with the old base_curve_block kind) lands
    on the project's components of that kind."""
    comps = [Component.for_kind(ComponentKind.FRAME_FRONT, id="front"),
             Component.for_kind(ComponentKind.BASE_CURVE_RIGHT, id="bc_r"),
             Component.for_kind(ComponentKind.BASE_CURVE_LEFT, id="bc_l")]
    layout = BedLayout(placements=[
        ComponentPlacement(kind="frame_front", label="Frame", fixture_zone="front",
                           x_mm=201.1, y_mm=144.3),
        ComponentPlacement(kind="base_curve_block", label="Block",
                           fixture_zone="bc_template_right", x_mm=54.8, y_mm=147.3),
        ComponentPlacement(kind="base_curve_block", label="Block 2",
                           fixture_zone="bc_template_left", x_mm=54.8, y_mm=50.0),
        ComponentPlacement(kind="temple", label="T", fixture_zone="temple_left"),
    ])
    nest = legacy_layout_to_nest(layout, comps)
    assert {pl.component_id: pl.zone_id for pl in nest.placements} == {
        "frame_front": "front", "base_curve_right": "bc_template_right",
        "base_curve_left": "bc_template_left"}               # no temple to receive the last
    assert nest.get("frame_front").dx == pytest.approx(201.1)
    assert legacy_layout_to_nest(None, comps).placements == []


# ------------------------------------------------------------------ placing

def test_auto_place_fills_zones_by_role_and_leaves_the_placed_alone():
    bed = Worktable(zones=[
        _rect_zone("f_b", BedRole.FRAME_FRONT, 0, 100, 180, 185),
        _rect_zone("f_a", BedRole.FRAME_FRONT, 0, 0, 180, 85),     # lower: first
        _rect_zone("tr", BedRole.TEMPLE_RIGHT, 200, 0, 380, 40),
        _rect_zone("tl", BedRole.TEMPLE_LEFT, 200, 50, 380, 90),
    ])
    nest = WorktableNest()
    nest.put(WorktablePlacement(component_id="front2", zone_id="f_a", dx=93.0, dy=40.0))
    fps = [_fp("front", "frame_front"), _fp("front2", "frame_front"),
           _fp("temple_r", "temple_right"), _fp("temple_l", "temple_left", rot=180.0),
           _fp("bc_r", "base_curve_right")]
    made = auto_place(fps, bed, nest)
    assert [pl.component_id for pl in made] == ["front", "temple_r", "temple_l"]
    assert nest.get("front").zone_id == "f_b"                      # f_a was taken
    assert nest.get("front2").dx == 93.0                           # untouched
    assert nest.get("temple_r").rotation_deg == 0.0
    assert nest.get("temple_l").rotation_deg == 180.0              # its default
    assert (nest.get("temple_l").dx, nest.get("temple_l").dy) == (290.0, 70.0)
    assert nest.get("bc_r") is None                                # no zone of its role
    # a placement whose zone is gone is placed again
    nest.put(WorktablePlacement(component_id="temple_r", zone_id="gone", dx=1, dy=1))
    made = auto_place(fps, bed, nest)
    assert [pl.component_id for pl in made] == ["temple_r"]
    assert nest.get("temple_r").zone_id == "tr"


def test_re_placing_from_nothing_restores_the_role_order():
    bed = Worktable.from_fixture_dict(FIXTURE)
    fps = [_fp(k, k) for k in ("frame_front", "temple_right", "temple_left",
                               "base_curve_right", "base_curve_left")]
    nest = WorktableNest()
    auto_place(fps, bed, nest)
    assert {pl.component_id: pl.zone_id for pl in nest.placements} == {
        "frame_front": "front", "temple_right": "temple_right", "temple_left": "temple_left",
        "base_curve_right": "bc_template_right", "base_curve_left": "bc_template_left"}
    for pl in nest.placements:
        assert (pl.dx, pl.dy) == pytest.approx(bed.zone(pl.zone_id).bbox_center(), abs=1e-3)


def test_move_turn_send_and_snap():
    fp = _fp("t", "temple_right", w=40, h=10)
    pl = WorktablePlacement(component_id="t", zone_id="z", dx=100.0, dy=50.0)
    rotate_about_center(fp, pl, 90.0)
    assert pl.rotation_deg == 90.0
    c = placed(fp.blank, pl).centroid
    assert (c.x, c.y) == pytest.approx((100.0, 50.0))              # the blank stayed put
    x0, y0, x1, y1 = placed(fp.blank, pl).bounds
    assert (x1 - x0, y1 - y0) == pytest.approx((10.0, 40.0))
    rotate_about_center(fp, pl, 270.0)
    assert pl.rotation_deg == 0.0 and (pl.dx, pl.dy) == pytest.approx((100.0, 50.0))
    zone = _rect_zone("z", BedRole.TEMPLE_RIGHT, 80, 40, 120, 60)   # center (100, 50)
    pl.dx = 102.5
    assert snap_to_zone(fp, pl, zone) and (pl.dx, pl.dy) == (100.0, 50.0)
    pl.dx = 104.0                                   # a blank its pocket's size, pushed past the wall
    assert snap_to_zone(fp, pl, zone) and pl.dx == 100.0    # comes back flush, which is centered
    roomy = _rect_zone("r", BedRole.TEMPLE_RIGHT, 0, 40, 200, 60)
    pl.dx = 60.0                                    # 40 mm from either end and the center: stays
    assert not snap_to_zone(fp, pl, roomy) and pl.dx == 60.0
    other = _rect_zone("o", BedRole.TEMPLE_RIGHT, 0, 0, 40, 20)
    send_to_zone(fp, pl, other)
    assert (pl.zone_id, pl.dx, pl.dy) == ("o", 20.0, 10.0)


# ------------------------------------------------------------------ clearance

def test_footprint_clearance_half_a_millimeter_in_and_out():
    """The cut grown by the tool radius: 0.5 mm into a keep-out is flagged,
    0.5 mm clear of it is not; the blank off the bed is its own message."""
    bed = Worktable(work_area_width_mm=100, work_area_height_mm=100, zones=[
        _rect_zone("z", BedRole.FRAME_FRONT, 0, 0, 100, 100),
        _rect_zone("clamp", BedRole.KEEP_OUT, 60, 0, 100, 100),
    ])
    fp = _fp("f", "frame_front", w=20, h=10, radius=1.0)       # cut x ∈ [-8, 8], grown to ±9
    pl = WorktablePlacement(component_id="f", zone_id="z", dx=51.5, dy=50.0)  # 9 + 51.5 = 60.5
    assert len(footprint_violations(fp, pl, bed)) == 1
    pl.dx = 50.5                                                  # 59.5: half a millimeter clear
    assert footprint_violations(fp, pl, bed) == []
    assert off_bed_violations(fp, pl, bed) == []
    pl.dx = 5.0                                                   # the blank runs off at x = -5
    assert off_bed_violations(fp, pl, bed) == ["f: its blank runs off the bed"]


# ------------------------------------------------------------------ keys

def test_the_keys_move_with_what_the_program_depends_on():
    t = TempleParams()
    base = dict(cam_overrides=None, material="acetate", machine="guild_cnc",
                geometry="g1", tools={"flat_3175": TOOLS["flat_3175"]})
    k = part_program_key("temple_right", t, CastleCamParams(), **base)
    assert k == part_program_key("temple_right", TempleParams(), CastleCamParams(), **base)
    assert k != part_program_key("temple_left", t, CastleCamParams(), **base)
    assert k != part_program_key("temple_right", t.model_copy(update={"engrave_depth_mm": 0.5}),
                                 CastleCamParams(), **base)
    assert k != part_program_key("temple_right", t, CastleCamParams(feed_rate_mmpm=900), **base)
    for field, val in (("material", "acetal"), ("machine", "nova"), ("geometry", "g2"),
                       ("tools", {"flat_3175": {**TOOLS["flat_3175"], "radius_mm": 2.0}})):
        assert k != part_program_key("temple_right", t, CastleCamParams(), **{**base, field: val})

    layers = {"OUTLINE": [[(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]]}
    assert geometry_fingerprint(layers) == geometry_fingerprint(
        {"OUTLINE": [[(0.0, 0.00001), (10.0, 0.0), (10.0, 5.0)]]})     # a tenth of a micron
    assert geometry_fingerprint(layers) != geometry_fingerprint(
        {"OUTLINE": [[(0.0, 0.001), (10.0, 0.0), (10.0, 5.0)]]})
    assert geometry_fingerprint(layers, (1.0, 2.0)) != geometry_fingerprint(layers, (0.0, 0.0))

    bed = Worktable.from_fixture_dict(FIXTURE)
    zone = bed.zone("temple_right")
    pl = WorktablePlacement(component_id="t", zone_id="temple_right", dx=10, dy=20, rotation_deg=0)
    pk = placement_key(pl, zone, bed)
    assert pk == placement_key(pl.model_copy(), zone, bed)
    assert pk != placement_key(pl.model_copy(update={"dx": 10.5}), zone, bed)
    assert pk != placement_key(pl.model_copy(update={"rotation_deg": 90.0}), zone, bed)
    assert pk != placement_key(pl, bed.zone("temple_left"), zone and bed)
    bed2 = bed.model_copy(update={"hold_down_height_mm": 12.0})
    assert pk != placement_key(pl, zone, bed2)
    bed3 = bed.model_copy(update={"program_zero": ProgramZero(x_ref="center", y_ref="center")})
    assert pk != placement_key(pl, zone, bed3)
    assert program_key("a", "b") == "a:b"
    assert bed_program_key(["x:1", "y:2"]) == bed_program_key(["y:2", "x:1"])
    assert bed_program_key(["x:1"]) != bed_program_key(["x:1", "y:2"])


# ------------------------------------------------------------------ the nest from placements

def test_the_nest_from_placements_posts_what_the_old_nest_posted():
    """For a part placed at its zone's center, unrotated and unnudged, the
    saved placement yields the same ops — and the same posted program, byte
    for byte — as the one-shot nest placed by origin."""
    bed = Worktable.from_fixture_dict(FIXTURE)
    frame = BedPart("frame_front", "Frame", "",
                    [_op("Perimeter", "flat_3175", [(-5, -5), (5, 5)])],
                    {"Perimeter"}, set(), place_by_origin=True, component_id="front")
    block = BedPart("base_curve_right", "Block", "",
                    [_op("Drill Holes", "drill_m4_clear", [(0, 0)]),
                     _op("Block Profile", "flat_3175", [(-4, -4), (4, 4)])],
                    {"Block Profile"}, {"Drill Holes"}, place_by_origin=True, component_id="bc_r")
    old = nest_components_on_worktable([frame, block], bed)
    nest = WorktableNest()
    for part, zid in ((frame, "front"), (block, "bc_template_right")):
        cx, cy = bed.zone(zid).bbox_center()
        nest.put(WorktablePlacement(component_id=part.component_id, zone_id=zid,
                                    dx=round(cx, 3), dy=round(cy, 3)))
    new = nest_from_placements([frame, block], nest, bed)
    assert new.unplaced == []
    for a, b in zip(old.placements, new.placements):
        assert (a.zone_id, a.rotation_deg) == (b.zone_id, b.rotation_deg)
        assert (a.dx, a.dy) == pytest.approx((b.dx, b.dy), abs=1e-9)
        for oa, ob in zip(a.ops, b.ops):
            for pa, pb in zip(oa.paths, ob.paths):
                for qa, qb in zip(pa, pb):
                    assert qa == pytest.approx(qb, abs=1e-9)   # the old path moved by the unrounded center

    def post(n):
        prog = build_nest_program(n)
        machine = MachineProfile()
        acetate = MATS["acetate"]
        ts, _ = build_tool_settings(prog.ops, TOOLS, default_feed=acetate["feed_rate_mmpm"],
                                    default_plunge=acetate["plunge_rate_mmpm"],
                                    default_spindle=acetate["spindle_rpm"], machine=machine)
        first = ts[prog.ops[0].tool_name]
        p = GRBLPost("worktable", "acetate", first.diameter_mm, first.spindle_rpm,
                     first.feed_rate_mmpm, first.plunge_rate_mmpm, safe_z_mm=20.0)
        write_castle_program(prog.ops, p, side="Worktable", tool_settings=ts,
                             tool_change_mode=machine.tool_change_mode,
                             contour_op_names=prog.contour_op_names,
                             drill_op_names=prog.drill_op_names, peck_depth_mm=1.5)
        return p.to_string()

    assert post(old) == post(new)
    # a placement whose zone is gone leaves the part unplaced, not an exception
    nest.get("bc_r").zone_id = "gone"
    part = nest_from_placements([frame, block], nest, bed)
    assert [p.label for p in part.unplaced] == ["Block"]
    assert [p.label for p in part.placements] == ["Frame"]


# ------------------------------------------------------------------ footprints

def test_footprints_of_each_kind():
    front = footprint_front("front", "Frame Front", box(-50, -20, 50, 20), CastleParams(),
                            CastleCamParams(), TOOLS)
    st = CastleParams().stock
    assert front.blank.bounds == pytest.approx((-st.blank_length_mm / 2, -st.blank_width_mm / 2,
                                                st.blank_length_mm / 2, st.blank_width_mm / 2))
    assert len(front.extras) == 1 and front.tool_radius_mm > 0 and front.rotation_default_deg == 0

    outline = Polygon([(-70, -3), (70, -3), (70, 3), (-70, 3)])
    hinge = [Polygon([(58, -2), (66, -2), (66, 2), (58, 2)])]
    t = TempleParams()
    temple = footprint_temple("temple_r", "temple_right", "Temple R", outline, hinge, t, TOOLS)
    assert temple.cut.bounds[2] == pytest.approx(t.blank_length_mm / 2)   # snapped to the end
    assert temple.rotation_default_deg == 0.0
    loose = footprint_temple("temple_l", "temple_left", "Temple L", outline, hinge,
                             t.model_copy(update={"snap_to_blank_end": False}), TOOLS)
    assert loose.rotation_default_deg == 180.0 and loose.cut.bounds == outline.bounds
    assert temple.tool_radius_mm == max(TOOLS[n]["radius_mm"]
                                        for n in (t.engrave_tool, t.hinge_tool, t.profile_tool))

    lens = Polygon([(100, 100), (140, 100), (140, 126), (100, 126)])
    blk = footprint_block("bc_r", "base_curve_right", "BC R", lens, BaseCurveBlockParams(), TOOLS)
    assert blk.cut.centroid.coords[0] == pytest.approx((0.0, 0.0))
    assert blk.tool_radius_mm == TOOLS[BaseCurveBlockParams().profile_tool]["radius_mm"]


# ------------------------------------------------------------------ the retired path

def test_no_caller_of_the_retired_path_remains():
    names = {"build_bed_program", "bed_clearance_violations", "place_ops_at_zone",
             "zone_center", "BedProgram"}
    found = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in names:
                found.append(f"{path.relative_to(SRC)}: {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in names:
                found.append(f"{path.relative_to(SRC)}: .{node.attr}")
    assert found == []


# ------------------------------------------------------------------ the flows

def test_the_hotkey_migration_drops_a_save_as_chord(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    (tmp_path / "prefs.json").write_text(json.dumps(
        {"hotkeys": {"simulate": "Ctrl+Shift+S", "build": "F7", "save_project_as": "Ctrl+Shift+S"}}),
        encoding="utf-8")
    p = prefs_mod.load()
    assert "simulate" not in p["hotkeys"]                          # back to its default, F6
    assert p["hotkeys"]["build"] == "F7"
    assert p["hotkeys"]["save_project_as"] == "Ctrl+Shift+S"
    assert p["prefs_version"] == 2 and p["build_on_open"] is True
    # a file already at version 2 is left alone
    (tmp_path / "prefs.json").write_text(json.dumps(
        {"prefs_version": 2, "hotkeys": {"simulate": "Ctrl+Shift+S"}}), encoding="utf-8")
    assert prefs_mod.load()["hotkeys"]["simulate"] == "Ctrl+Shift+S"


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


def _make_gdraw(path, temple_half=70):
    """A front whose lenses are 40 mm wide: the Guild bed's block screws stand
    10 mm either side of the block's center and must sit inside the lens ring,
    as they do on a real block, and the front's screws inside its eyewires."""
    front = {"curves": [
        _line("OUTLINE", [(-75, -24), (75, -24), (75, 24), (-75, 24)], closed=True),
        _line("LENS", [(22, -13), (62, -13), (62, 13), (22, 13)], closed=True),
        _line("LENS", [(-62, -13), (-22, -13), (-22, 13), (-62, 13)], closed=True),
        _line("SCULPT", [(0, -24), (0, 24)]),
        _line("SCULPT", [(42, -24), (42, 24)]),
        _line("HINGE", [(66, -5), (74, -5), (74, 5), (66, 5)], closed=True),
    ]}
    h = temple_half
    temple = {"curves": [
        _line("OUTLINE", [(-h, -6), (h, -6), (h, 6), (-h, 6)], closed=True),
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


def _qt(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _window(monkeypatch, tmp_path):
    _qt(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QMessageBox
    import guildmodel.gui.app as app_mod
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(app_mod.OpSummaryDialog, "exec", lambda self: 0)
    try:
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    win.view3d.show_mesh = lambda *a, **k: None
    win.view3d.show_flat = lambda *a, **k: None
    return win


def _bed_up(win, bed=None):
    bed = bed or Worktable.from_fixture_dict(FIXTURE)
    win._worktable = bed
    win.bed_canvas.set_worktable(bed)
    return bed


@pytest.mark.gui
def test_the_bed_places_moves_turns_generates_goes_stale_and_reopens(tmp_path, monkeypatch):
    import guildmodel.core.cam.temple_ops as temple_ops
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    bed = _bed_up(win)
    ws = _by_kind(win._workspaces)
    front, tr, tl = (ws[ComponentKind.FRAME_FRONT], ws[ComponentKind.TEMPLE_RIGHT],
                     ws[ComponentKind.TEMPLE_LEFT])
    win._set_part_on_bed(front, False)             # the castle relief is the slow part

    # Auto-place: every part on its role zone, instantly, no program
    win._on_nest_components()
    nest = win._wt_nest
    assert len(nest.placements) == 5 and all(w.bed_ops is None for w in win._workspaces)
    assert nest.get(win._component_id(tr)).zone_id == "temple_right"
    assert win._placement_state(tr)[0] == "stale"                  # placed, no program yet
    assert win._bed_program_state()[0] == "stale"
    assert win._bed_gen_btn.isEnabled() and win._bed_sim_btn.isEnabled()
    assert not win._bed_sheet_btn.isEnabled()

    # move and turn, by the canvas's keys
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    pl = nest.get(win._component_id(tr))
    win._on_bed_placement_selected("temple_right")
    win.bed_canvas.set_selected_placement("temple_right")
    before = (pl.dx, pl.dy)
    win.bed_canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right,
                                           Qt.KeyboardModifier.NoModifier))
    assert (pl.dx, pl.dy) == pytest.approx((before[0] + 0.1, before[1]))
    win.bed_canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up,
                                           Qt.KeyboardModifier.ShiftModifier))
    assert (pl.dx, pl.dy) == pytest.approx((before[0] + 0.1, before[1] + 1.0))
    win.bed_canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R,
                                           Qt.KeyboardModifier.NoModifier))
    assert pl.rotation_deg == pytest.approx(90.0)
    win.bed_canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_R,
                                           Qt.KeyboardModifier.ShiftModifier))
    assert pl.rotation_deg == pytest.approx(0.0)
    assert win._bed_nudge_x.value() == pytest.approx(pl.dx)

    # Generate: every placed part is built once; the chips read placed
    calls = []
    real = temple_ops.generate_temple_program
    monkeypatch.setattr(temple_ops, "generate_temple_program",
                        lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    win._on_generate_worktable_nest(sync=True)
    assert len(calls) == 2                                         # both temples
    assert "worktable.nc" in win._wt_programs and win._wt_setup["component"] == "worktable"
    assert win._bed_program_state()[0] == "placed"
    assert all(win._placement_state(w)[0] == "placed" for w in (tr, tl))
    assert win._placement_state(front)[0] == "off"
    assert win._bed_sheet_btn.isEnabled()
    assert nest.program_key == win._current_bed_key()

    # a parameter edit on one temple marks that temple stale and no other
    tl.temple_params = tl.temple_params.model_copy(update={"engrave_depth_mm": 0.45})
    win._refresh_nest_render()
    assert win._placement_state(tl)[0] == "stale"
    assert win._placement_state(tr)[0] == "placed"
    assert win._bed_program_state()[0] == "stale"
    calls.clear()
    win._on_generate_worktable_nest(sync=True)
    assert len(calls) == 1                                         # only the stale part
    assert win._bed_program_state()[0] == "placed"

    # a nudge marks that part stale; a role change marks the part on that zone
    win._on_component_stepped("temple_right", 0.5, 0.0)
    assert win._placement_state(tr)[0] == "stale"
    assert win._placement_state(tl)[0] == "placed"
    win._on_generate_worktable_nest(sync=True)
    bed.set_role("temple_left", BedRole.KEEP_OUT)
    win._refresh_nest_render()
    assert win._placement_state(tl)[0] != "placed"
    bed.set_role("temple_left", BedRole.TEMPLE_LEFT)
    win._refresh_nest_render()
    assert win._placement_state(tl)[0] == "placed"

    # save, reopen: every placement identical, the chips still placed
    path = tmp_path / "p.gmodel"
    assert win._save_gmodel_to(path, announce=False)
    again = _window(monkeypatch, tmp_path)
    again._open_project(path, remember=False)
    assert len(again._wt_nest.placements) == 5
    for a in nest.placements:
        b = again._wt_nest.get(a.component_id)
        assert (a.zone_id, a.program_key) == (b.zone_id, b.program_key)
        assert (a.dx, a.dy, a.rotation_deg) == pytest.approx((b.dx, b.dy, b.rotation_deg), abs=1e-6)
    assert again._wt_programs == win._wt_programs
    assert again._bed_program_state()[0] == "placed"
    assert all(w.last_programs == {} for w in again._workspaces)   # nothing leaked
    again._on_show_worktable()
    assert again._act_export_nc.isEnabled() and not again._dirty


@pytest.mark.gui
def test_reload_keeps_the_settings_and_marks_the_programs_stale(tmp_path, monkeypatch):
    win = _window(monkeypatch, tmp_path)
    path = _make_gdraw(tmp_path / "m.gdraw")
    win._load_model(path)
    assert win._act_reload.isEnabled() and win._source_path == path
    _bed_up(win)
    win._on_nest_components()
    tr = _by_kind(win._workspaces)[ComponentKind.TEMPLE_RIGHT]
    tr.temple_params = tr.temple_params.model_copy(update={"engrave_depth_mm": 0.45})
    tr.last_programs = {"temple.nc": "G0 X0"}
    tr.program_stored = tr.program_fresh = True
    win._set_part_on_bed(_by_kind(win._workspaces)[ComponentKind.BASE_CURVE_LEFT], False)
    placements = {pl.component_id: (pl.dx, pl.dy) for pl in win._wt_nest.placements}
    width_before = tr.outline_poly.bounds[2] - tr.outline_poly.bounds[0]

    # the drawing changes on disk: the chip lights, never a dialog
    _make_gdraw(path, temple_half=80)
    assert win._reload_chip.isHidden()
    win._on_source_file_changed(str(path))
    assert not win._reload_chip.isHidden()

    win._on_reload_drawing()
    ws = _by_kind(win._workspaces)
    tr2 = ws[ComponentKind.TEMPLE_RIGHT]
    assert tr2 is not tr
    assert tr2.temple_params.engrave_depth_mm == 0.45              # kept
    assert ws[ComponentKind.BASE_CURVE_LEFT].on_bed is False       # kept
    assert tr2.outline_poly.bounds[2] - tr2.outline_poly.bounds[0] == pytest.approx(width_before + 20)
    assert tr2.last_programs == {} and not tr2.program_stored      # stale, dropped
    assert {pl.component_id: (pl.dx, pl.dy) for pl in win._wt_nest.placements} == placements
    assert win._reload_chip.isHidden() and win._dirty
    assert win._source_path == path


@pytest.mark.gui
def test_a_drop_opens_the_file_and_the_title_carries_the_version(tmp_path, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl
    from guildmodel import __version__
    win = _window(monkeypatch, tmp_path)
    assert win.acceptDrops()
    path = _make_gdraw(tmp_path / "m.gdraw")

    class Drop:
        def __init__(self, urls):
            self._mime = QMimeData()
            self._mime.setUrls([QUrl.fromLocalFile(str(u)) for u in urls])
            self.accepted = self.ignored = False

        def mimeData(self):
            return self._mime

        def acceptProposedAction(self):
            self.accepted = True

        def ignore(self):
            self.ignored = True

    text = tmp_path / "notes.txt"
    text.write_text("x")
    ev = Drop([text])
    win.dragEnterEvent(ev)
    assert ev.ignored and not ev.accepted
    ev = Drop([path])
    win.dragEnterEvent(ev)
    assert ev.accepted
    win.dropEvent(ev)
    assert len(win._workspaces) == 5
    assert win.windowTitle() == f"GuildModel {__version__} — m.gdraw"
    win._mark_dirty()
    assert win.windowTitle().endswith("m.gdraw*")
    assert win.canvas._caption.startswith("Back view (posterior)")   # the front is active


@pytest.mark.gui
def test_simulate_bed_generates_first_then_starts_the_bed_worker(tmp_path, monkeypatch):
    from PySide6.QtCore import QThread
    import guildmodel.gui.app as app_mod
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    _bed_up(win)
    ws = _by_kind(win._workspaces)
    win._set_part_on_bed(ws[ComponentKind.FRAME_FRONT], False)
    win._on_nest_components()
    win._on_show_worktable()
    assert win._act_simulate.isEnabled()                           # placed: the sim can run

    orig = win._on_generate_worktable_nest
    generated = []
    monkeypatch.setattr(win, "_on_generate_worktable_nest",
                        lambda **kw: (generated.append(1), orig(sync=True, **kw))[1])
    started = []
    monkeypatch.setattr(QThread, "start", lambda self, *a, **k: started.append(self))

    win._on_simulate_bed()
    assert generated == [1]                                        # stale: generated first
    assert win._bed_program_state()[0] == "placed"
    assert isinstance(win._sim_worker, app_mod.BedSimWorker)
    assert sorted(pl.label for pl in win._sim_worker.placements) == sorted(
        w.label for w in win._workspaces if w is not ws[ComponentKind.FRAME_FRONT])
    assert len(started) == 1
    # current: a second Simulate Bed does not generate again
    win._bed_removal = None
    win._sim_thread = None
    win._on_simulate_bed()
    assert generated == [1] and len(started) == 2


@pytest.mark.gui
def test_a_leaked_worktable_program_is_healed_on_open(tmp_path, monkeypatch):
    """A 1.8.x project wrote the bed program onto the component behind the
    Worktable tab, as the top-level job and in that component's own directory.
    On open it is taken as the bed's, and the component, which never cut it,
    gets nothing back."""
    from guildmodel.core.project.gmodel import save_gmodel
    win = _window(monkeypatch, tmp_path)
    path = _make_gdraw(tmp_path / "m.gdraw")
    win._load_model(path)
    proj = win._build_project_schema()
    tr = next(c for c in proj.components if c.kind == ComponentKind.TEMPLE_RIGHT)
    tr.has_program = True
    leaked = {"programs": {"worktable.nc": "G21\nG0 X0\n"}, "setup": {"component": "worktable"},
              "machine": None, "report": None}
    gm = tmp_path / "old.gmodel"
    save_gmodel(gm, project=proj, gdraw_bytes=path.read_bytes(),
                programs=leaked["programs"], setup=leaked["setup"],
                component_artifacts={tr.id: leaked})

    again = _window(monkeypatch, tmp_path)
    again._open_project(gm, remember=False)
    assert again._wt_programs == leaked["programs"]
    assert again._wt_setup == {"component": "worktable"}
    ws = _by_kind(again._workspaces)
    assert ws[ComponentKind.TEMPLE_RIGHT].last_programs == {}
    assert not ws[ComponentKind.TEMPLE_RIGHT].program_stored
    assert again._last_programs == {}
    # and once saved again it sits in the bed's own slot, still the top-level job
    out = tmp_path / "healed.gmodel"
    assert again._save_gmodel_to(out, announce=False)
    import zipfile
    names = zipfile.ZipFile(out).namelist()
    assert "components/worktable/program/worktable.nc" in names
    assert "program/worktable.nc" in names
    assert not any(n.startswith(f"components/{tr.id}/") for n in names)


# ------------------------------------------------------------------ session two (2026-10-14)

def test_a_flat_simulation_carves_the_blank_as_listed(tmp_path, monkeypatch):
    """The temple's playback block is its 170 × 30 blank, centered on the
    design origin, the snapped temple at its end — not the relief grid
    cropped to the cut."""
    pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from guildmodel.gui.app import FlatSimWorker

    outline = Polygon([(-70, -3), (70, -3), (70, 3), (-70, 3)])
    hinge = [Polygon([(58, -2), (66, -2), (66, 2), (58, 2)])]
    t = TempleParams()
    worker = FlatSimWorker("temple", outline=outline, temple=t, hinge_polys=hinge,
                           engraving=[], graphics=[], cam_params=CastleCamParams(),
                           material_name="acetate", resolution=0.6)
    done, errs = [], []
    worker.finished.connect(lambda r, lines, plan: done.append((r, plan)))
    worker.error.connect(lambda tb: errs.append(tb))
    worker.run()
    assert errs == [], errs[0] if errs else ""
    report, plan = done[0]
    assert plan.origin == pytest.approx((-t.blank_length_mm / 2, -t.blank_width_mm / 2))
    rows, cols = plan.stock_top.shape if hasattr(plan, "stock_top") else plan.floor_at(0).shape
    assert (cols * 0.6, rows * 0.6) == pytest.approx((t.blank_length_mm, t.blank_width_mm), abs=0.6)
    # the verdict grid is the relief's: smaller than the blank, as before
    assert report.floor.shape[1] * report.resolution < t.blank_length_mm


@pytest.mark.gui
def test_the_bed_sim_reads_the_posted_program_and_carves_the_blanks(tmp_path, monkeypatch):
    """After Generate the bed simulation takes the posted worktable.nc and the
    cached reliefs: `simulate_component` is never called, the one cut on the
    posting grid is the playback (M21 §6.5), its stock spans the placed
    blanks, and the temple sits snapped at its blank's end on the bed as it
    does on its own tab."""
    import guildmodel.core.sim as sim_pkg
    import guildmodel.gui.app as app_mod
    from guildmodel.core.cam.placement import placed
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    bed = _bed_up(win)
    ws = _by_kind(win._workspaces)
    win._set_part_on_bed(ws[ComponentKind.FRAME_FRONT], False)
    win._on_nest_components()
    win._on_generate_worktable_nest(sync=True)
    assert win._wt_programs

    # the snap holds on the bed: the temple's cut ends where its blank ends
    tr = ws[ComponentKind.TEMPLE_RIGHT]
    fp = win._footprint_for(tr)
    pl = win._wt_nest.get(win._component_id(tr))
    assert tr.temple_params.snap_to_blank_end and tr.temple_params.stock_side == "right"
    assert placed(fp.cut, pl).bounds[2] == pytest.approx(placed(fp.blank, pl).bounds[2], abs=1e-6)

    def no_regeneration(*a, **k):
        raise AssertionError("the bed sim regenerated a part")
    monkeypatch.setattr(sim_pkg, "simulate_component", no_regeneration)
    from guildmodel.core.relief.castle import PREVIEW_RES_MM
    targets = win._bed_targets()
    reliefs = {w.label: w.bed_ops["relief"] for w in targets if w.bed_ops.get("relief") is not None}
    worker = app_mod.BedSimWorker(
        [win._build_spec(win._workspaces.index(w)) for w in targets], win._nest.placements,
        (bed.work_area_width_mm, bed.work_area_height_mm),
        cam_params=win.params.effective_cam_params(), material_name="acetate",
        program_text=win._wt_programs["worktable.nc"], reliefs=reliefs,
        playback_resolution=PREVIEW_RES_MM)
    done, errs = [], []
    worker.finished.connect(lambda r, lines, plan: done.append((r, plan)))
    worker.error.connect(lambda tb: errs.append(tb))
    worker.run()
    assert errs == [], errs[0] if errs else ""
    report, plan = done[0]
    assert report.completeness.body_cells > 0
    assert report.status() in {"ok", "warn", "fail"}
    from guildmodel.core.relief.castle import CUT_RES_MM
    assert plan.resolution == pytest.approx(CUT_RES_MM)      # the verdict's cut, played
    assert report.resolution == pytest.approx(CUT_RES_MM)
    # the playback stock spans every placed blank (the temples' 170 mm, the blocks' 70)
    x0, y0 = plan.origin
    rows, cols = plan.stock_top.shape
    for w in targets:
        f = win._footprint_for(w)
        p = win._wt_nest.get(win._component_id(w))
        bx0, by0, bx1, by1 = placed(f.blank, p).bounds
        assert x0 <= bx0 + 1e-6 and y0 <= by0 + 1e-6
        assert x0 + cols * plan.resolution >= bx1 - 1e-6
        assert y0 + rows * plan.resolution >= by1 - 1e-6


@pytest.mark.gui
def test_the_panel_is_quiet_iconed_and_folds_the_screws(tmp_path, monkeypatch):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    from guildmodel.gui.style import theme
    win = _window(monkeypatch, tmp_path)
    win._on_show_worktable()
    win._on_load_default_bed()

    # a wheel over an unfocused field changes nothing; a focused one takes it
    spin = win._bed_holddown_spin
    before = spin.value()
    spin.clearFocus()

    def wheel():
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(spin, ev)
        return ev

    ev = wheel()
    assert spin.value() == before and not ev.isAccepted()
    assert spin.focusPolicy() == Qt.FocusPolicy.StrongFocus
    win.show()
    spin.setFocus()
    QApplication.processEvents()
    if spin.hasFocus():
        wheel()
        assert spin.value() == pytest.approx(before + spin.singleStep())

    # icons on every button that has one, in both themes
    names = {name for _btn, name in win._wt_icon_buttons}
    assert {"bed-load", "bed-guild", "bed-save", "bed-default", "zone-remove", "edit-undo",
            "edit-redo", "nest-place", "nest-replace", "sheet", "op-gcode", "sim-cut"} <= names
    for dark in (True, False):
        win._apply_worktable_icons(dark)
        assert all(not btn.icon().isNull() for btn, _ in win._wt_icon_buttons)
    assert win._bed_load_btn.toolTip().startswith("Load DXF/BED")

    # the headers are headings, styled by the theme, not lit buttons
    for grp in (win._wt_group_bed, win._wt_group_zones, win._wt_group_parts,
                win._wt_group_program):
        assert grp.header.objectName() == "collapsibleHeader"
        assert grp.header.styleSheet() == ""
    for dark in (True, False):
        assert "QToolButton#collapsibleHeader:checked" in theme.stylesheet(dark)

    # the screws fold away and stay folded across a refresh; a screw picked on the bed unfolds them
    tree = win._bed_region_list
    assert tree.topLevelItem(1).text(0).startswith("Hold-downs (24)")
    assert not tree.topLevelItem(1).isExpanded()
    win._refresh_worktable_panel()
    assert not tree.topLevelItem(1).isExpanded()
    screw = next(z.id for z in win._worktable.keep_outs())
    win._select_bed_region(screw)
    assert tree.topLevelItem(1).isExpanded()
    assert tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == screw
    win._refresh_worktable_panel()                      # the screw still selected: stays open
    assert tree.topLevelItem(1).isExpanded()
    win._select_bed_region(None)
    win.bed_canvas.set_selected(None)
    tree.topLevelItem(1).setExpanded(False)             # the maker folds it again
    win._refresh_worktable_panel()
    assert not tree.topLevelItem(1).isExpanded()


@pytest.mark.gui
def test_a_tab_walk_keeps_the_3d_view(tmp_path, monkeypatch):
    """The view chosen on a component survives a visit to the Worktable, and a
    tab visited in 3D whose model is not built is given the 3D page and a quiet
    build, not a fall-back to 2D."""
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    assert win._current_view == 0 and win._component_view == 0
    win._switch_view(1)                                   # the maker picks 3D
    assert win._component_view == 1 and win.stack.currentIndex() == 1
    win._on_show_worktable()
    assert win._current_view == 0 and win._component_view == 1   # the bed has no 3D
    win._activate_workspace(1)                            # back to a temple, unbuilt
    assert win._current_view == 1 and win.stack.currentIndex() == 1
    assert 1 in win._lazy_built                           # its build is scheduled
    win._activate_workspace(2)
    assert win._current_view == 1 and 2 in win._lazy_built
    win._switch_view(2, run=False)                        # Sim with nothing cached
    assert win._current_view in (0, 1)
    win._switch_view(0)
    win._activate_workspace(0)
    assert win._current_view == 0 and win._component_view == 0


# ------------------------------------------------------------------ the zone's stop (session two)

def test_a_zone_stop_registers_the_blank_flush_with_its_orientation_kept():
    """A 160 mm blank in a 170 mm zone: centered with no stop; flush left or
    right against a stop; still flush, the same way round, after a 180° flip;
    a corner stop flushes both axes."""
    from guildmodel.core.cam.placement import register_to_zone, zone_register_delta
    zone = _rect_zone("t", BedRole.TEMPLE_RIGHT, 100, 40, 270, 70)        # 170 × 30
    fp = _fp("t", "temple_right", w=160, h=30)
    pl = WorktablePlacement(component_id="t", zone_id="t", dx=185.0, dy=55.0)   # centered
    assert zone_register_delta(fp, pl, zone) == pytest.approx((0.0, 0.0))
    assert not register_to_zone(fp, pl, zone)
    zone.stop_x = "left"
    assert register_to_zone(fp, pl, zone)
    assert placed(fp.blank, pl).bounds[0] == pytest.approx(100.0)       # flush left
    assert pl.dy == 55.0                                                 # still centered in Y
    rotate_about_center(fp, pl, 180.0)
    assert pl.rotation_deg == 180.0
    assert placed(fp.blank, pl).bounds[0] == pytest.approx(100.0)       # the flip kept its place
    zone.stop_x = "right"
    register_to_zone(fp, pl, zone)
    assert placed(fp.blank, pl).bounds[2] == pytest.approx(270.0)       # flush right, still flipped
    assert pl.rotation_deg == 180.0
    zone.stop_y = "top"
    register_to_zone(fp, pl, zone)
    assert placed(fp.blank, pl).bounds[3] == pytest.approx(70.0)
    zone.stop_x, zone.stop_y = "none", "bottom"
    register_to_zone(fp, pl, zone)
    assert placed(fp.blank, pl).bounds[1] == pytest.approx(40.0)
    assert (placed(fp.blank, pl).bounds[0] + placed(fp.blank, pl).bounds[2]) / 2 == pytest.approx(185.0)


def test_auto_place_a_drag_and_send_all_register_against_the_stop():
    from guildmodel.core.cam.placement import snap_to_zone
    bed = Worktable(zones=[
        _rect_zone("tr", BedRole.TEMPLE_RIGHT, 100, 0, 270, 30),
        _rect_zone("tl", BedRole.TEMPLE_LEFT, 100, 40, 270, 70),
    ])
    bed.zone("tr").stop_x = "left"
    bed.zone("tl").stop_x = "right"
    fps = [_fp("temple_r", "temple_right", w=160, h=30),
           _fp("temple_l", "temple_left", w=160, h=30, rot=180.0)]
    nest = WorktableNest()
    auto_place(fps, bed, nest)
    pr, pl_ = nest.get("temple_r"), nest.get("temple_l")
    assert placed(fps[0].blank, pr).bounds[0] == pytest.approx(100.0)   # flush left
    assert placed(fps[1].blank, pl_).bounds[2] == pytest.approx(270.0)  # flush right, flipped
    assert pl_.rotation_deg == 180.0
    # a drag that ends within 3 mm of the stop snaps to it
    pr.dx += 2.0
    assert snap_to_zone(fps[0], pr, bed.zone("tr"))
    assert placed(fps[0].blank, pr).bounds[0] == pytest.approx(100.0)
    # pushed past the pocket's far wall it comes back flush to that wall, stop or no stop
    pr.dx += 30.0
    assert snap_to_zone(fps[0], pr, bed.zone("tr"))
    assert placed(fps[0].blank, pr).bounds[2] == pytest.approx(270.0)
    # with no stop, a drop near an end snaps to it, near the center to the center,
    # and elsewhere stays put
    bed.zone("tr").stop_x = "none"
    pr.dx -= 2.0                                                         # 2 mm off the right wall
    assert snap_to_zone(fps[0], pr, bed.zone("tr"))
    assert placed(fps[0].blank, pr).bounds[2] == pytest.approx(270.0)
    pr.dx -= 4.0                                                         # 4 mm off the wall: 1 mm off center
    assert snap_to_zone(fps[0], pr, bed.zone("tr"))
    assert (placed(fps[0].blank, pr).bounds[0] + placed(fps[0].blank, pr).bounds[2]) / 2 == pytest.approx(185.0)
    wide = _rect_zone("w", BedRole.TEMPLE_RIGHT, 0, 0, 300, 30)         # 140 mm of play
    pw = WorktablePlacement(component_id="t", zone_id="w", dx=100.0, dy=15.0)   # ends 20, 180: nothing near
    assert not snap_to_zone(fps[0], pw, wide)
    # sent to another zone, it registers against that zone's stop
    nest.remove("temple_l")
    bed.zone("tl").role = BedRole.TEMPLE_RIGHT
    send_to_zone(fps[0], pr, bed.zone("tl"))
    assert placed(fps[0].blank, pr).bounds[2] == pytest.approx(270.0)
    # the stop rides with the bed file
    from guildmodel.core.cam.worktable import load_bed, save_bed
    import tempfile
    bed.zone("tr").stop_x = "left"
    p = Path(tempfile.mkdtemp()) / "stops.bed"
    save_bed(bed, p)
    assert load_bed(p).zone("tr").stop_x == "left"
    assert WorktableZone(id="z").stop_x == "none" and WorktableZone(id="z").stop_y == "none"


@pytest.mark.gui
def test_the_stop_combos_and_snap_on_the_panel(tmp_path, monkeypatch):
    """The screenshot's case: a temple blank shorter than its zone, flipped
    180° and dragged by hand to one end. Setting the zone's stop (undoable,
    saved with the bed) and pressing Snap, or S on the canvas, puts it flush
    to that end as it is; the other stop sends it flush to the other end."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from guildmodel.core.cam.placement import placed
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    bed = _bed_up(win)
    ws = _by_kind(win._workspaces)
    tr = ws[ComponentKind.TEMPLE_RIGHT]
    tr.temple_params = tr.temple_params.model_copy(update={"blank_length_mm": 160.0})
    win._on_nest_components()
    pl = win._wt_nest.get(win._component_id(tr))
    zone = bed.zone("temple_right")
    zx0, _, zx1, _ = zone.bbox()
    fp = win._footprint_for(tr)
    assert (placed(fp.blank, pl).bounds[0] + placed(fp.blank, pl).bounds[2]) / 2 == pytest.approx((zx0 + zx1) / 2, abs=1e-3)

    # the maker flips it and drags it off to the right by hand
    win._on_bed_placement_selected("temple_right")
    win.bed_canvas.set_selected_placement("temple_right")
    win._rotate_selected_placement(180.0)
    win._on_component_stepped("temple_right", 4.0, 0.0)
    assert pl.rotation_deg == 180.0

    # the zone's stop is set on the panel: undoable, the stop combos follow the selection
    win.bed_canvas.set_selected("temple_right")
    win._select_bed_region("temple_right")
    assert win._bed_stop_x.isEnabled()
    win._bed_stop_x.setCurrentIndex(win._bed_stop_x.findData("right"))
    assert zone.stop_x == "right" and win._bed_undo_btn.isEnabled()
    win._on_wt_undo()
    assert win._worktable.zone("temple_right").stop_x == "none"
    win._on_wt_redo()
    assert win._worktable.zone("temple_right").stop_x == "right"
    zone = win._worktable.zone("temple_right")
    pl = win._wt_nest.get(win._component_id(tr))

    # Snap: flush right, the flip kept
    win._on_bed_placement_selected("temple_right")
    win._on_snap_selected_placement()
    assert placed(fp.blank, pl).bounds[2] == pytest.approx(zx1, abs=1e-3)
    assert pl.rotation_deg == 180.0
    # with no stop at all, Snap reads which end the part is nearer (never the
    # center: there are 5 mm of play a side): 2 mm off the right end it goes back
    # flush right; 8 mm off it is nearer the left end and goes there; a stop then
    # wins over nearness
    zone.stop_x = "none"
    win._on_component_stepped("temple_right", -2.0, 0.0)
    win._on_snap_selected_placement()
    assert placed(fp.blank, pl).bounds[2] == pytest.approx(zx1, abs=1e-3)
    win._on_component_stepped("temple_right", -8.0, 0.0)
    win._on_snap_selected_placement()
    assert placed(fp.blank, pl).bounds[0] == pytest.approx(zx0, abs=1e-3)
    win._on_component_stepped("temple_right", 8.0, 0.0)
    # the other stop: S on the canvas sends it flush left, still flipped
    zone.stop_x = "left"
    win.bed_canvas.set_selected_placement("temple_right")
    win.bed_canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_S,
                                           Qt.KeyboardModifier.NoModifier))
    assert placed(fp.blank, pl).bounds[0] == pytest.approx(zx0, abs=1e-3)
    assert pl.rotation_deg == 180.0
    # a drag ending near the stop snaps back to it
    win._on_component_nudged("temple_right", 2.0, 0.0)
    assert placed(fp.blank, pl).bounds[0] == pytest.approx(zx0, abs=1e-3)
    assert win._bed_snap_btn.isEnabled()
