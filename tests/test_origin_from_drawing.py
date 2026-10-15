"""Placement by the drawing's origin (2026-10-14).

A maker draws against GuildDraw's grid: the temple core on the zero line, the
stock blank guide centered on the origin, several drawings of one design laid
out against the same origin so every cut registers alike. GuildModel's blank
is centered on the design origin too, and the import keeps the origin, so the
drawing's zero is the blank's center. Until this round the temple snap
centered the outline's bounding box across the blank anyway, which put an
asymmetric temple (a dropped tip) off the core, and drew the core guide
through the middle of the box rather than down the core.

Each kind now has an `origin_from_drawing` switch, on by default:

* a temple keeps the drawing's y = 0 on the blank's center line when snapped
  (`relief.flat.temple_snap_offset`); the snap along the blank is untouched,
  and the core guide is drawn down the center line whatever the placement;
* a frame front is cut as drawn (what it always was); off, the drawing is
  centered on the blank at intake (`component_workspace.place_front_on_blank`),
  layers, exact curves and outlined text together, and toggling back restores
  it exactly;
* a base-curve block is always centered (its position in the front means
  nothing for a standalone block) and has no switch.

The window half (marked `gui`) pins the Stock tab toggle: the active front's
geometry, canvas and caches follow it.
"""
import json
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pytest
from shapely.geometry import Polygon, box

from guildmodel.core.geometry.curves import NurbsCurve, OffsetCurve, translated
from guildmodel.core.project.schema import CastleParams, ComponentKind, TempleParams
from guildmodel.core.relief.flat import (
    place_temple_curves, place_temple_on_blank, temple_core_guide, temple_snap_transform,
)
from guildmodel.gui import part_defaults as pd
from guildmodel.gui import prefs as prefs_mod
from guildmodel.gui.component_workspace import (
    ComponentWorkspace, build_workspaces_from_gdraw, derive_workspace, place_front_on_blank,
)

_SVG_NS = "http://www.w3.org/2000/svg"


# ------------------------------------------------------------------ a drawing

def _line(layer, pts, closed=False):
    return {"kind": "line", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _spline(layer, pts, closed=True):
    return {"kind": "spline", "layer": layer, "closed": closed,
            "nodes": [{"x": x, "y": y} for x, y in pts]}


def _svg_bytes(state):
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


#: A front drawn well off its origin: outline x 10..130, y 20..60 in scene
#: space, lenses, two SCULPT cuts, a hinge. Its bounding-box center is
#: (70, 40) in scene space; the import's (x, y) -> (-x, -y) puts it at (-70, -40).
def _off_origin_front():
    return {"curves": [
        _spline("OUTLINE", [(10, 20), (130, 20), (130, 60), (10, 60)]),
        _line("LENS", [(90, 28), (115, 28), (115, 52), (90, 52)], closed=True),
        _line("LENS", [(25, 28), (50, 28), (50, 52), (25, 52)], closed=True),
        _line("SCULPT", [(70, 20), (70, 60)]),
        _line("SCULPT", [(100, 20), (100, 60)]),
        _line("HINGE", [(120, 35), (128, 35), (128, 45), (120, 45)], closed=True),
    ]}


def _asymmetric_temple():
    """A temple on the core line whose tip drops below it (scene space, Y down,
    so the drop is +y here and lands at -y in the model)."""
    return {"curves": [
        _line("OUTLINE", [(-70, -3), (70, -3), (70, 3), (-50, 3), (-50, 15), (-70, 15)],
              closed=True),
        _line("HINGE", [(58, -2), (66, -2), (66, 2), (58, 2)], closed=True),
    ]}


def _make_gdraw(path, front=None, temple=None):
    states = {"front": front or _off_origin_front(),
              "temple_r": temple or _asymmetric_temple(),
              "temple_l": {"curves": []}, "hinge": {"curves": []}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "front"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))
    return path


def _by_kind(workspaces):
    return {w.kind: w for w in workspaces}


# ------------------------------------------------------------------ the schema

def test_both_switches_default_on_and_old_files_load_that_way():
    assert TempleParams().origin_from_drawing is True
    assert CastleParams().origin_from_drawing is True
    old_temple = TempleParams().model_dump()
    old_temple.pop("origin_from_drawing")
    assert TempleParams(**old_temple).origin_from_drawing is True
    old_castle = CastleParams().model_dump()
    old_castle.pop("origin_from_drawing")
    assert CastleParams(**old_castle).origin_from_drawing is True


# ------------------------------------------------------------------ the temple

def _dropped_tip():
    shaft = box(-70.0, -3.0, 70.0, 3.0)                 # on the core line
    tip = box(-70.0, -15.0, -50.0, -3.0)                # drops 12 mm below it
    outline = shaft.union(tip)
    hinge = [box(58.0, -2.0, 66.0, 2.0)]                # hinge at +x
    eng = [[(-40.0, 0.0), (40.0, 0.0)]]
    return outline, hinge, eng


def test_a_snapped_temple_keeps_its_core_line_on_the_blank_center():
    outline, hinge, eng = _dropped_tip()
    o, h, e = place_temple_on_blank(outline, hinge, eng, 170.0)
    assert o.bounds[2] == pytest.approx(85.0)           # butted to the +x end as ever
    assert o.bounds[1] == pytest.approx(-15.0)          # the tip still hangs below…
    assert o.bounds[3] == pytest.approx(3.0)            # …and the shaft still sits on y = 0
    assert e[0][0][1] == pytest.approx(0.0)             # the engraving stayed on the core line
    assert all(p.bounds[1] < 0 < p.bounds[3] for p in h)


def test_centering_across_the_blank_is_still_there_when_asked():
    outline, hinge, eng = _dropped_tip()
    o, _h, _e = place_temple_on_blank(outline, hinge, eng, 170.0, origin_from_drawing=False)
    assert (o.bounds[1] + o.bounds[3]) / 2.0 == pytest.approx(0.0)
    assert o.bounds[2] == pytest.approx(85.0)


def test_the_flip_to_the_other_end_spins_about_the_origin_so_the_core_line_holds():
    """Sending the hinge to the left end rotates the temple 180° about the origin;
    y = 0 maps onto itself, so the shaft stays on the core and the tip, as it
    physically would when the blank is spun, now hangs the other way."""
    outline, hinge, eng = _dropped_tip()
    flipped, dx, dy = temple_snap_transform(outline, hinge, 170.0, stock_side="left")
    assert flipped is True and dy == 0.0
    o, h, _e = place_temple_on_blank(outline, hinge, eng, 170.0, stock_side="left")
    assert o.bounds[0] == pytest.approx(-85.0)          # butted to the -x end
    assert (o.bounds[1], o.bounds[3]) == pytest.approx((-3.0, 15.0))
    assert h[0].centroid.x < 0


def test_snap_transform_matches_placement_for_either_setting():
    outline, hinge, eng = _dropped_tip()
    for side in ("right", "left"):
        for by_origin in (True, False):
            flipped, dx, dy = temple_snap_transform(
                outline, hinge, 170.0, stock_side=side, origin_from_drawing=by_origin)
            placed, _, _ = place_temple_on_blank(
                outline, hinge, eng, 170.0, stock_side=side, origin_from_drawing=by_origin)
            sgn = -1.0 if flipped else 1.0
            xs = [sgn * x + dx for x, _ in outline.exterior.coords]
            ys = [sgn * y + dy for _, y in outline.exterior.coords]
            assert placed.bounds == pytest.approx((min(xs), min(ys), max(xs), max(ys)))
            # the drawn graphics ride the same motion
            gfx = place_temple_curves([[(0.0, 0.0), (10.0, 1.0)]], outline, hinge, 170.0,
                                      stock_side=side, origin_from_drawing=by_origin)
            assert gfx[0][0] == pytest.approx((dx, dy))


def test_the_core_guide_runs_down_the_blank_center_line_as_placed():
    """What the maker sees in 3D: the bar on the shaft, the tip clear of it."""
    outline, hinge, _ = _dropped_tip()
    t = TempleParams()
    o, h, _ = place_temple_on_blank(outline, hinge, [], t.blank_length_mm)
    gx0, gy0, gx1, gy1 = temple_core_guide(o, h, t).bounds
    assert (gy0 + gy1) / 2.0 == pytest.approx(0.0)
    assert gx1 == pytest.approx(85.0)                   # in from the hinge end
    assert (gx1 - gx0) == pytest.approx(t.core_guide_length_mm)
    # with the old centering the same bar would sit below the shaft
    oc, hc, _ = place_temple_on_blank(outline, hinge, [], t.blank_length_mm,
                                      origin_from_drawing=False)
    assert oc.bounds[3] == pytest.approx(9.0)           # the shaft's top edge, 6 mm up
    assert temple_core_guide(oc, hc, t).bounds[3] == pytest.approx(1.0)


def test_core_guide_size_is_a_parameter():
    outline, hinge, _ = _dropped_tip()
    t = TempleParams(core_guide_width_mm=1.2, core_guide_length_mm=90.0)
    o, h, _ = place_temple_on_blank(outline, hinge, [], t.blank_length_mm)
    gx0, gy0, gx1, gy1 = temple_core_guide(o, h, t).bounds
    assert (gy1 - gy0) == pytest.approx(1.2)
    assert (gx1 - gx0) == pytest.approx(90.0)
    with pytest.raises(Exception):
        TempleParams(core_guide_width_mm=0.0)


# ------------------------------------------------------------------ curves

def test_translated_moves_the_hull_and_keeps_the_rest():
    c = NurbsCurve(control_points=[(0, 0), (1, 2), (3, 1)], knots=[0, 0, 0, 1, 1, 1],
                   degree=2, closed=False, weights=[1.0, 2.0, 1.0], layer="OUTLINE")
    t = translated(c, 5.0, -2.0)
    assert np.allclose(t.control_points, [(5, -2), (6, 0), (8, -1)])
    assert np.array_equal(t.knots, c.knots) and t.degree == 2 and t.closed is False
    assert np.array_equal(t.weights, c.weights) and t.layer == "OUTLINE"
    assert np.allclose(c.control_points, [(0, 0), (1, 2), (3, 1)])   # the source is untouched
    off = translated(OffsetCurve(basis=c, distance=0.6, layer="LENS"), 1.0, 1.0)
    assert off.distance == 0.6 and off.layer == "LENS"
    assert np.allclose(off.basis.control_points, [(1, 1), (2, 3), (4, 2)])
    assert translated(None, 1.0, 1.0) is None


# ------------------------------------------------------------------ the front

def test_a_front_is_cut_as_drawn_by_default(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    front = _by_kind(workspaces)[ComponentKind.FRAME_FRONT]
    before = front.outline_poly.bounds
    assert place_front_on_blank(front, True) is False
    assert front.drawing_offset == (0.0, 0.0)
    assert front.outline_poly.bounds == before
    cx = (before[0] + before[2]) / 2.0
    assert cx == pytest.approx(-70.0)                   # off the origin, as the maker drew it


def test_centering_a_front_moves_everything_and_toggling_back_restores_it(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    front = _by_kind(workspaces)[ComponentKind.FRAME_FRONT]
    front.engraving_text = [[(-70.0, -40.0), (-60.0, -40.0)]]      # as the GUI would outline it
    layers0 = {k: [list(c) for c in v] for k, v in front.layers.items()}
    poles0 = front.curves["OUTLINE"][0].control_points.copy()
    boxing0 = front.boxing
    lens_od0 = front.lens_od.bounds

    assert place_front_on_blank(front, False) is True
    ox, oy = front.drawing_offset
    assert (ox, oy) == pytest.approx((70.0, 40.0))
    minx, miny, maxx, maxy = front.outline_poly.bounds
    assert ((minx + maxx) / 2.0, (miny + maxy) / 2.0) == pytest.approx((0.0, 0.0))
    # every layer, the exact curves and the outlined text made the same trip
    for lyr, curves in layers0.items():
        for c0, c1 in zip(curves, front.layers[lyr], strict=True):
            for (x0, y0), (x1, y1) in zip(c0, c1, strict=True):
                assert (x1 - x0, y1 - y0) == pytest.approx((ox, oy))
    assert np.allclose(front.curves["OUTLINE"][0].control_points - poles0, (ox, oy))
    assert front.engraving_text[0][0] == pytest.approx((0.0, 0.0))
    # the derived geometry followed; the boxing dimensions did not change
    assert front.lens_od.bounds != lens_od0
    assert front.partition is not None and front.castle_ready
    assert front.boxing is boxing0
    # idempotent
    assert place_front_on_blank(front, False) is False

    assert place_front_on_blank(front, True) is True
    assert front.drawing_offset == (0.0, 0.0)
    for lyr, curves in layers0.items():
        for c0, c1 in zip(curves, front.layers[lyr], strict=True):
            for (x0, y0), (x1, y1) in zip(c0, c1, strict=True):
                assert (x1, y1) == pytest.approx((x0, y0))
    assert np.allclose(front.curves["OUTLINE"][0].control_points, poles0)
    assert front.lens_od.bounds == pytest.approx(lens_od0)


def test_a_temple_and_a_block_are_not_placed_at_intake(tmp_path):
    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    ws = _by_kind(workspaces)
    temple = ws[ComponentKind.TEMPLE_RIGHT]
    bounds = temple.outline_poly.bounds
    assert place_front_on_blank(temple, False) is False
    assert temple.outline_poly.bounds == bounds
    # both lenses of this off-origin front sit on one side, so both templates
    # are "left"; any one of them will do
    block = next(w for w in workspaces
                 if w.kind in (ComponentKind.BASE_CURVE_RIGHT, ComponentKind.BASE_CURVE_LEFT))
    assert place_front_on_blank(block, False) is False
    empty = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="", layers={})
    derive_workspace(empty)
    assert place_front_on_blank(empty, False) is False


# ------------------------------------------------------------------ shop defaults

def test_the_switch_is_a_shop_default_and_a_save_offer(tmp_path):
    assert "origin_from_drawing" in pd.PARAM_FIELDS["frame_front"]
    assert "origin_from_drawing" in pd.PARAM_FIELDS["temple"]
    assert pd.Departure("temple", "origin_from_drawing", False).text() == (
        "Temples: origin from drawing off")
    assert pd.Departure("frame_front", "origin_from_drawing", True).text() == (
        "Frame Front: origin from drawing on")
    assert pd.sparse_params("frame_front", CastleParams(origin_from_drawing=False)) == {
        "origin_from_drawing": False}
    assert pd.sparse_params("frame_front", CastleParams()) == {}

    workspaces, _ = build_workspaces_from_gdraw(_make_gdraw(tmp_path / "m.gdraw"))
    pd.seed_workspaces(workspaces, prefs_mod.DEFAULTS)
    assert pd.departures(workspaces, prefs_mod.DEFAULTS) == []
    ws = _by_kind(workspaces)
    ws[ComponentKind.FRAME_FRONT].castle_params = CastleParams(origin_from_drawing=False)
    ws[ComponentKind.TEMPLE_RIGHT].temple_params = (
        ws[ComponentKind.TEMPLE_RIGHT].temple_params.model_copy(
            update={"origin_from_drawing": False}))
    fields = {(d.group, d.field) for d in pd.departures(workspaces, prefs_mod.DEFAULTS)}
    assert fields == {("frame_front", "origin_from_drawing"), ("temple", "origin_from_drawing")}

    shop = {**prefs_mod.DEFAULTS, "part_defaults": {
        "frame_front": {"params": {"origin_from_drawing": False}},
        "temple": {"params": {"origin_from_drawing": False}},
        "base_curve": {}}}
    assert pd.default_params(shop, "frame_front").origin_from_drawing is False
    assert pd.default_params(shop, "temple_left").origin_from_drawing is False


# ------------------------------------------------------------------ the window

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
def test_the_stock_tab_switch_moves_the_active_front_and_back(tmp_path, monkeypatch):
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    ws = _by_kind(win._workspaces)
    front = ws[ComponentKind.FRAME_FRONT]
    assert win._active_workspace() is front
    assert win.params.front_origin_from_drawing.isChecked() is True
    as_drawn = front.outline_poly.bounds
    assert (as_drawn[0] + as_drawn[2]) / 2.0 == pytest.approx(-70.0)
    assert win.canvas._layers["OUTLINE"][0][0] == pytest.approx(front.layers["OUTLINE"][0][0])
    front.stage_cache["pockets"] = object()                   # a mesh of the old frame

    win.params.front_origin_from_drawing.setChecked(False)
    assert front.drawing_offset == pytest.approx((70.0, 40.0))
    b = front.outline_poly.bounds
    assert ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0) == pytest.approx((0.0, 0.0))
    assert win._outline_poly is front.outline_poly              # the working set follows
    assert win.canvas._layers["OUTLINE"][0][0] == pytest.approx(front.layers["OUTLINE"][0][0])
    assert front.stage_cache == {} and front.mesh_built is False
    assert win.params.castle_params().origin_from_drawing is False
    assert win._dirty is True

    # the choice rides the workspace across a tab switch and back
    win._activate_workspace(win._workspaces.index(ws[ComponentKind.TEMPLE_RIGHT]))
    win._activate_workspace(win._workspaces.index(front))
    assert win.params.front_origin_from_drawing.isChecked() is False
    assert front.castle_params.origin_from_drawing is False

    win.params.front_origin_from_drawing.setChecked(True)
    assert front.drawing_offset == (0.0, 0.0)
    assert front.outline_poly.bounds == pytest.approx(as_drawn)


@pytest.mark.gui
def test_a_temple_tab_switch_follows_the_snap(tmp_path, monkeypatch):
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    ws = _by_kind(win._workspaces)
    win._activate_workspace(win._workspaces.index(ws[ComponentKind.TEMPLE_RIGHT]))
    p = win.params
    assert p.temple_origin_from_drawing.isChecked() is True
    assert p.temple_origin_from_drawing.isEnabled() is True
    p.temple_snap_blank.setChecked(False)
    assert p.temple_origin_from_drawing.isEnabled() is False
    p.temple_snap_blank.setChecked(True)
    p.temple_origin_from_drawing.setChecked(False)
    p.temple_core_width.setValue(1.5)
    t = p.temple_params()
    assert t.origin_from_drawing is False and t.core_guide_width_mm == 1.5
    # the blank box in the 2D view is drawn from the same transform
    frame = win._temple_snap_frame()
    assert frame is not None
    flipped, dx, dy = frame
    assert dy != 0.0                                          # centering the width moves it
    p.temple_origin_from_drawing.setChecked(True)
    assert win._temple_snap_frame()[2] == 0.0


@pytest.mark.gui
def test_a_centered_front_survives_save_and_reopen_and_is_a_shop_default(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from guildmodel.gui.widgets.part_defaults_page import PartDefaultsOffer
    win = _window(monkeypatch, tmp_path)
    win._load_model(_make_gdraw(tmp_path / "m.gdraw"))
    front = _by_kind(win._workspaces)[ComponentKind.FRAME_FRONT]
    win.params.front_origin_from_drawing.setChecked(False)
    centered = front.outline_poly.bounds
    path = tmp_path / "p.gmodel"
    assert win._save_gmodel_to(path, announce=False)

    # Save offers the departure in the maker's words
    shown = []
    monkeypatch.setattr(PartDefaultsOffer, "exec",
                        lambda dlg: (shown.append([cb.text() for cb in dlg.line_checks]),
                                     QDialog.DialogCode.Rejected)[1])
    win._maybe_prompt_part_defaults()
    assert shown == [["Frame Front: origin from drawing off"]]

    # the saved placement comes back: geometry, dock and canvas alike
    again = _window(monkeypatch, tmp_path)
    again._open_project(path, remember=False)
    front2 = _by_kind(again._workspaces)[ComponentKind.FRAME_FRONT]
    assert front2.castle_params.origin_from_drawing is False
    assert front2.drawing_offset == pytest.approx((70.0, 40.0))
    assert front2.outline_poly.bounds == pytest.approx(centered)
    assert again.params.front_origin_from_drawing.isChecked() is False
    assert again.canvas._layers["OUTLINE"][0][0] == pytest.approx(front2.layers["OUTLINE"][0][0])
    assert again._dirty is False

    # a shop that centers every front centers a fresh drawing on open
    prefs_mod.save({**prefs_mod.DEFAULTS, "part_defaults": {
        "frame_front": {"params": {"origin_from_drawing": False}},
        "temple": {}, "base_curve": {}}})
    third = _window(monkeypatch, tmp_path)
    third._load_model(_make_gdraw(tmp_path / "m2.gdraw"))
    front3 = _by_kind(third._workspaces)[ComponentKind.FRAME_FRONT]
    assert front3.drawing_offset == pytest.approx((70.0, 40.0))
    assert third.params.front_origin_from_drawing.isChecked() is False
