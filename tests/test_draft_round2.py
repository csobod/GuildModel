"""The blueprint's second round (2026-11-05), the maker's review of 2.3.0
before publishing: the lettering (a font of the maker's choosing, measured
for the layout), the dimension value in a break in the line, the hinge
detail drawn from the pockets as drawn, and the ink and the paper."""
from __future__ import annotations

import math

import numpy as np
import pytest
from shapely.geometry import Polygon

from guildmodel.core.project.schema import (BLUEPRINT_COLOR_PRESETS, BlueprintSettings,
                                            DraftHinge, HingeKind, hex_color)


# ------------------------------------------------------------------ the settings

def test_the_settings_hold_the_lettering_and_the_colors():
    s = BlueprintSettings()
    assert s.font_family == "" and s.dim_text == "inline"
    assert (s.line_color, s.paper_color) == ("#000000", "#ffffff") and s.color_preset == "black"
    s = BlueprintSettings(font_family="  Courier New ", text_width_em=9, line_color="#FFF",
                          paper_color="#163A7A", dim_text="above")
    assert s.font_family == "Courier New" and s.text_width_em == 0.9
    assert (s.line_color, s.paper_color) == ("#ffffff", "#163a7a") and s.color_preset == "blueprint"
    assert BlueprintSettings(line_color="red", paper_color="").line_color == "#000000"
    assert hex_color("#AbC", "#000000") == "#aabbcc" and hex_color("nope", "#123456") == "#123456"
    for key, (label, line, paper) in BLUEPRINT_COLOR_PRESETS.items():
        assert label and BlueprintSettings(line_color=line, paper_color=paper).color_preset == key
    # a project saved before this round reads: the fields have defaults
    old = BlueprintSettings.model_validate({"paper": "a3", "owner": "shop"})
    assert old.font_family == "" and old.paper_color == "#ffffff"


# ------------------------------------------------------------------ the dimension's value

def _dim_strokes(view):
    return [st for st in view.strokes if st.style == "dim"]


def test_the_value_sits_in_a_break_in_the_line():
    from guildmodel.core.draft.sheet import View, linear_dim, set_lettering
    set_lettering(0.52, "inline")
    v = View("t", "t")
    linear_dim(v, (0.0, 0.0), (60.0, 0.0), 5.0, "60.0 [L]")
    # two extension lines and the line in two pieces, the text centered on it
    pieces = [st for st in _dim_strokes(v) if abs(st.pts[0][1] - 5.0) < 1e-9
              and abs(st.pts[1][1] - 5.0) < 1e-9]
    assert len(pieces) == 2
    left, right = sorted(pieces, key=lambda st: min(p[0] for p in st.pts))
    gap_lo, gap_hi = max(p[0] for p in left.pts), min(p[0] for p in right.pts)
    (t,) = v.texts
    assert t.valign == "middle" and t.align == "center" and t.y == pytest.approx(5.0)
    assert gap_lo < 30.0 < gap_hi, "the break is around the value's center"
    assert gap_hi - gap_lo == pytest.approx(t.width_mm + 2.0, abs=1e-6)
    set_lettering(0.52, "inline")


def test_the_value_above_the_line_on_request():
    from guildmodel.core.draft.sheet import View, linear_dim, set_lettering
    set_lettering(0.52, "above")
    try:
        v = View("t", "t")
        linear_dim(v, (0.0, 0.0), (60.0, 0.0), 5.0, "60.0 [L]")
        whole = [st for st in _dim_strokes(v) if len(st.pts) == 2
                 and abs(st.pts[0][1] - 5.0) < 1e-9 and abs(st.pts[1][1] - 5.0) < 1e-9]
        assert len(whole) == 1 and abs(whole[0].pts[1][0] - whole[0].pts[0][0]) == pytest.approx(60.0)
        (t,) = v.texts
        assert t.valign == "baseline" and t.y > 5.0
    finally:
        set_lettering(0.52, "inline")


def test_a_wide_value_goes_outside_a_short_dimension():
    from guildmodel.core.draft.sheet import View, linear_dim
    v = View("t", "t")
    linear_dim(v, (0.0, 0.0), (0.0, 5.0), 3.0, "5.1 [L]", along=(0.0, 1.0))
    (t,) = v.texts
    assert t.align == "left" and t.y > 5.0, "past the reading end, the top"
    v = View("t", "t")
    linear_dim(v, (0.0, 0.0), (0.0, 5.0), 3.0, "5.1 [L]", along=(0.0, 1.0), outside="start")
    (t,) = v.texts
    assert t.align == "right" and t.y < 0.0, "before the reading start, the bottom"
    assert abs(t.angle - 90.0) < 1e-9


def test_the_arc_breaks_for_its_value_when_it_sits_on_it():
    from guildmodel.core.draft.sheet import View, angular_dim
    v = View("t", "t")
    angular_dim(v, (0.0, 0.0), 30.0, 0.0, 90.0, "90°", label_radius=30.0)
    arcs = [st for st in _dim_strokes(v) if len(st.pts) > 2]
    assert len(arcs) == 2, "the arc in two pieces around the value"
    (t,) = v.texts
    assert math.hypot(t.x, t.y) == pytest.approx(30.0)
    v = View("t", "t")
    angular_dim(v, (0.0, 0.0), 30.0, 0.0, 90.0, "90°")       # the value beside the arc
    assert len([st for st in _dim_strokes(v) if len(st.pts) > 2]) == 1


def test_the_lettering_follows_the_font_width():
    from guildmodel.core.draft.sheet import Text, set_lettering
    set_lettering(0.7, "inline")
    try:
        assert Text(0, 0, "1234", 2.0).width_mm == pytest.approx(0.7 * 2.0 * 4)
    finally:
        set_lettering(0.52, "inline")


# ------------------------------------------------------------------ the hinge detail

def _fill(kind=HingeKind.RIVET):
    from guildmodel.core.draft import fill_hinge, fit_pocket
    pocket = Polygon([(56.0, -2.0), (66.0, -2.0), (66.0, 2.0), (56.0, 2.0)])
    outline = Polygon([(-70.0, -20.0), (70.0, -20.0), (70.0, 20.0), (-70.0, 20.0)])
    fit = fit_pocket(pocket, outline, (1.0, 0.0))
    return fill_hinge(DraftHinge(kind=kind), fit, None, 1.0, 1.0), pocket, fit


def test_the_detail_draws_the_pockets_as_drawn():
    from guildmodel.core.draft.hinges import hinge_detail, leaf_from_pocket
    fill, pocket, fit = _fill()
    # a front pocket with a rounded outer end, read toward the butt (+x)
    ring = [(56.0, -2.0), (65.0, -2.0), (66.0, 0.0), (65.0, 2.0), (56.0, 2.0)]
    leaf = leaf_from_pocket(ring, fit.direction, (0.0, 1.0), fit.setback_mm, 5.5, 1.0)
    assert leaf.reach == pytest.approx(5.0) and leaf.length == pytest.approx(10.0)
    assert leaf.half_width == pytest.approx(2.0) and leaf.setback_mm == pytest.approx(4.0)
    # the temple's, in its normalized frame, read toward the butt (-s)
    t_ring = [(3.0, -1.5), (11.0, -1.5), (11.0, 1.5), (3.0, 1.5)]
    t_leaf = leaf_from_pocket(t_ring, (-1.0, 0.0), (0.0, 1.0), 3.0, 4.0, 1.0)
    assert t_leaf.reach == pytest.approx(4.0) and t_leaf.length == pytest.approx(8.0)
    det = hinge_detail(fill, front_leaf=leaf, temple_leaf=t_leaf, axis_inset_mm=4.0,
                       axis_offset_mm=0.0)
    el, pl = det["elevation"], det["plan"]
    r = 0.5 * fill.spec.barrel_diameter_mm
    front_ring, temple_ring = el["visible"][0], el["visible"][1]
    # the front leaf's shape, its rounded end against the column on the left
    assert len(front_ring) == 5 and max(p[0] for p in front_ring) == pytest.approx(-r - 0.3)
    assert min(p[0] for p in front_ring) == pytest.approx(-r - 0.3 - 10.0)
    # the temple leaf opened flat to the right, its butt edge against the column
    assert min(p[0] for p in temple_ring) == pytest.approx(r + 0.3)
    assert max(p[0] for p in temple_ring) == pytest.approx(r + 0.3 + 8.0)
    # both leaves centered on the axis
    assert sum(p[1] for p in front_ring) / 5 == pytest.approx(0.0, abs=0.5)
    assert max(p[1] for p in temple_ring) == pytest.approx(1.5)
    labels = [t for _x, _y, t in el["labels"]]
    assert "front" in labels and "temple" in labels
    # the plan: the endpiece's section reaching the end face a temple's
    # thickness past the axis, its pocket sunk from the back face, the
    # temple's section straight back at the 90° stop with its pocket in
    # its inner face, the barrel's circle at the origin
    circle, endpiece, f_pocket, temple, t_pocket = pl["visible"][:5]
    assert max(p[0] for p in endpiece) == pytest.approx(4.0)
    assert max(p[1] for p in endpiece) == pytest.approx(0.0) and min(p[1] for p in endpiece) == pytest.approx(-5.5)
    assert max(p[0] for p in f_pocket) == pytest.approx(4.0 - 4.0) and min(p[1] for p in f_pocket) == pytest.approx(-1.0)
    assert min(p[0] for p in temple) == pytest.approx(0.0) and max(p[0] for p in temple) == pytest.approx(4.0)
    assert min(p[1] for p in t_pocket) == pytest.approx(3.0) and max(p[0] for p in t_pocket) == pytest.approx(1.0)
    assert max(math.hypot(x, y) for x, y in circle) == pytest.approx(r)
    assert any(t == "90°" for _x, _y, t in pl["labels"])


def test_the_detail_without_leaves_is_the_plates():
    from guildmodel.core.draft.hinges import hinge_detail
    fill, _pocket, _fit = _fill(HingeKind.SPRING)
    det = hinge_detail(fill)
    el = det["elevation"]
    assert len(el["visible"][0]) == 4 and any("spring box" in t for _x, _y, t in el["labels"])
    cleat = hinge_detail(_fill(HingeKind.HEAT_SET)[0])
    assert cleat["elevation"]["hidden"]


def test_the_assembly_carries_the_leaves(tmp_path):
    from guildmodel.core.draft import build_assembly
    from guildmodel.core.draft.sheet import _hinge_view
    from tests.test_draft_v230 import _inputs
    from guildmodel.core.project.schema import DraftParams
    fi, temples = _inputs()
    draft = DraftParams()
    asm = build_assembly(fi, temples, draft)
    side = asm.right
    assert side.front_leaf is not None and side.front_leaf.part_thickness_mm > 0
    assert side.temple_leaf is not None and side.temple_leaf.length > 0
    assert side.axis_inset_mm == pytest.approx(
        temples[0].params.blank_thickness_mm + draft.hinge.temple_inset_mm + draft.hinge.axis_offset_mm)
    v = _hinge_view(asm, 1.0)
    assert v is not None and any("opened flat" in t.text for t in v.texts)


# ------------------------------------------------------------------ the ink and the paper

@pytest.fixture
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_sheet_is_painted_in_its_colors_and_font(qapp, tmp_path):
    from guildmodel.core.draft.sheet import Sheet
    from guildmodel.gui.draft_render import (RenderStyle, export_pdf, export_svg,
                                             measure_text_width_em, render_png)
    sheet = Sheet(100.0, 60.0)
    sheet.rect(10, 10, 90, 50, "border")
    sheet.text(20, 20, "GuildModel", 6.0)
    s = BlueprintSettings(line_color="#ffffff", paper_color="#163a7a", font_family="DejaVu Serif")
    style = RenderStyle.from_settings(s)
    assert style.text_color("muted") != style.ink and style.text_color("warning").name() == "#ffb74d"
    img = render_png(sheet, dpi=50, style=style)
    from PySide6.QtGui import QColor
    assert QColor(img.pixel(2, 2)).name() == "#163a7a", "the paper"
    y = int(round(10 * 50 / 25.4))
    light = [QColor(img.pixel(x, yy)).lightnessF() for yy in range(y - 2, y + 3)
             for x in range(img.width())]
    assert max(light) > 0.6, "the border in the ink, white on the blue"
    pdf = tmp_path / "s.pdf"
    export_pdf(pdf, [sheet], style=style)
    assert pdf.stat().st_size > 500
    svg = tmp_path / "s.svg"
    export_svg(svg, sheet, style=style)
    text = svg.read_text(encoding="utf-8")
    assert "#163a7a" in text and "DejaVu Serif" in text
    # the measure is a fraction of the em, a serif wider than the default
    em = measure_text_width_em("")
    assert 0.3 <= em <= 0.9
    assert measure_text_width_em("DejaVu Serif") >= em - 0.05


def test_the_dxf_names_the_font(tmp_path):
    from guildmodel.core.draft.dxf_out import write_dxf
    from guildmodel.core.draft.sheet import Sheet
    sheet = Sheet(100.0, 60.0)
    sheet.rect(10, 10, 90, 50, "border")
    sheet.text(20, 20, "GuildModel", 6.0)
    path = tmp_path / "s.dxf"
    write_dxf(path, [sheet], "Courier New")
    import ezdxf
    doc = ezdxf.readfile(str(path))
    assert "BLUEPRINT" in doc.styles and doc.styles.get("BLUEPRINT").dxf.font == "Courier New.ttf"
    texts = list(doc.modelspace().query("TEXT"))
    assert texts and texts[0].dxf.style == "BLUEPRINT"


# ------------------------------------------------------------------ the prefs file

def test_an_old_prefs_file_drops_the_inflated_dialog_size(tmp_path, monkeypatch):
    import json
    from guildmodel.gui import prefs as prefs_mod
    f = tmp_path / "prefs.json"
    f.write_text(json.dumps({"prefs_version": 2, "prefs_dialog_size": [532, 936],
                             "draft": {"let_back_deg": 3.0, "hinge": {}}}))
    monkeypatch.setattr(prefs_mod, "_FILE", f)
    p = prefs_mod.load()
    assert p["prefs_dialog_size"] == [] and p["prefs_version"] == 3
    assert p["draft"]["splay_deg"] == 3.0 and "let_back_deg" not in p["draft"]
    # a file at version 3 keeps the size the maker set
    f.write_text(json.dumps({"prefs_version": 3, "prefs_dialog_size": [700, 500]}))
    assert prefs_mod.load()["prefs_dialog_size"] == [700, 500]


# ------------------------------------------------------------------ the sweep's findings

def test_a_dimension_against_its_direction_keeps_its_feet():
    """p2 before p1 along `along` (the first-angle plan's widths, a joint
    below the center): the extension lines stay perpendicular, the line
    breaks around the value, the arrows point outward."""
    from guildmodel.core.draft.sheet import View, linear_dim
    v = View("t", "t")
    linear_dim(v, (60.0, 0.0), (0.0, 0.0), 5.0, "60.0 [L]", along=(1.0, 0.0))
    dims = [st for st in v.strokes if st.style == "dim"]
    ext = [st for st in dims if abs(st.pts[0][0] - st.pts[1][0]) < 1e-9]
    assert len(ext) == 2 and {round(st.pts[0][0]) for st in ext} == {0, 60}, "vertical feet"
    pieces = sorted([st for st in dims if abs(st.pts[0][1] - 5.0) < 1e-9
                     and abs(st.pts[1][1] - 5.0) < 1e-9], key=lambda st: min(p[0] for p in st.pts))
    assert len(pieces) == 2
    assert max(p[0] for p in pieces[0].pts) < 30.0 < min(p[0] for p in pieces[1].pts)
    (t,) = v.texts
    assert t.x == pytest.approx(30.0) and abs(t.angle) < 1e-9
    # the arrowheads' tips at the feet, their bases inside the span
    tips = sorted(f.pts[0][0] for f in v.fills)
    assert tips == pytest.approx([0.0, 60.0])
    assert all(0.0 < f.pts[1][0] < 60.0 for f in v.fills)


def test_first_angle_sheet_composes_with_the_plan_below(tmp_path):
    from guildmodel.core.draft import build_assembly, compose_sheets, measure
    from guildmodel.core.project.schema import DraftParams
    from tests.test_draft_v230 import _inputs
    fi, temples = _inputs()
    asm = build_assembly(fi, temples, DraftParams())
    m = measure(asm)
    for projection in ("first", "third"):
        sheets = compose_sheets(asm, m, BlueprintSettings(projection=projection, paper="a3"),
                                job_name="t")
        placed = {p.view.key: p for p in sheets[0].placed}
        assert {"plan", "front", "side"} <= set(placed)
        if projection == "first":
            assert placed["plan"].y > placed["front"].y > placed["side"].y
        else:
            assert placed["plan"].y < placed["front"].y < placed["side"].y


def test_the_notes_wrap_to_their_column():
    from guildmodel.core.draft import build_assembly, measure
    from guildmodel.core.draft.sheet import _notes_views, set_lettering
    from guildmodel.core.project.schema import DraftParams
    from tests.test_draft_v230 import _inputs
    fi, temples = _inputs()
    asm = build_assembly(fi, temples, DraftParams())
    m = measure(asm)
    s = BlueprintSettings(notes="a long note for the factory " * 8)
    set_lettering(0.9, "inline")
    try:
        narrow, _t = _notes_views(asm, m, s, "acetate", width_mm=56.0)
        wide, _t = _notes_views(asm, m, s, "acetate", width_mm=120.0)
    finally:
        set_lettering(0.52, "inline")
    nb, wb = narrow.bbox(), wide.bbox()
    assert nb[2] - nb[0] <= 58.0, "no line wider than the column, in a wide font"
    assert len(narrow.texts) > len(wide.texts), "more lines in the narrow column"


def test_the_plate_lengths_follow_the_pockets_ray():
    from guildmodel.core.draft import fill_hinge, fit_pocket
    # a temple pocket longer along the temple (x) than across (y): the
    # plate is 8 long, the hinge 6.1 wide
    pocket = Polygon([(3.0, -3.05), (11.0, -3.05), (11.0, 3.05), (3.0, 3.05)])
    outline = Polygon([(0.0, -4.0), (140.0, -4.0), (140.0, 4.0), (0.0, 4.0)])
    fit = fit_pocket(pocket, outline, (-1.0, 0.0))
    assert fit.length_mm == pytest.approx(8.0) and fit.width_mm == pytest.approx(6.1)
    front = Polygon([(56.0, -5.0), (60.0, -5.0), (60.0, 5.0), (56.0, 5.0)])
    f_fit = fit_pocket(front, Polygon([(-70, -20), (70, -20), (70, 20), (-70, 20)]), (1.0, 0.0))
    fill = fill_hinge(DraftHinge(), f_fit, fit, 1.0, 1.0)
    assert fill.width_mm == pytest.approx(9.8) and fill.plate_length_mm == pytest.approx(4.0)
    assert fill.temple_plate_length_mm == pytest.approx(8.0)


def test_a_wide_stop_keeps_the_temple_outside_the_endpiece():
    from guildmodel.core.draft.hinges import hinge_detail
    fill, _pocket, _fit = _fill()
    fill = fill_hinge_at(fill, 180.0)
    det = hinge_detail(fill, axis_inset_mm=4.0, axis_offset_mm=0.0)
    circle, endpiece, _f_pocket, *rest = det["plan"]["visible"]
    for ring in rest:
        if len(ring) < 3:
            continue
        inside = [p for p in ring if p[0] < 4.0 - 1e-6 and p[1] < -1e-6]
        assert not inside, "no section corner inside the endpiece's quadrant"


def fill_hinge_at(fill, open_deg: float):
    from dataclasses import replace
    return replace(fill, spec=fill.spec.model_copy(update={"open_deg": open_deg}))
