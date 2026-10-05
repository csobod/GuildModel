"""A drawn ENGRAVING curve is cut as drawn; only text takes the centerline (v1.8.1).

Found 2026-10-05 on a temple carrying a six-armed logo drawn as one closed
spline on the ENGRAVING layer. Every closed ENGRAVING curve went through the
text-stroke centerline (the medial axis built for glyph outlines, M11 #7), and
the logo came out as a forked stick figure with a cluster of spurs — in the 3D
model, the cut simulation and the posted program alike.

The fix keeps the two kinds of engraving apart from the moment a ``.gdraw`` is
opened: the glyph contours outlined from the drawing's text objects are the
``text`` the centerline option acts on; what the maker drew on the layer is a
``graphic``. A drawn closed curve is a filled shape — the closed curves combine
even-odd, so a closed curve inside another is an island: an "O" is two circles,
a disc is one — and a drawn open curve is a stroke traced as drawn. A DXF cannot
tell text from drawing (GuildDraw outlines its text into plain closed splines at
export), so a DXF temple's curves all remain subject to the option, as they were.
"""
import json
import math
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
import yaml
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from guildmodel.core.cam.pocketing import fill_rings
from guildmodel.core.cam.temple_ops import (
    engrave_fill_stepover, generate_temple_program, graphic_engraving_curves,
)
from guildmodel.core.project.schema import TempleParams
from guildmodel.core.relief.flat import (
    build_temple_relief, place_temple_curves, place_temple_on_blank,
)

TOOLS = yaml.safe_load(
    (Path(__file__).parents[1] / "src/guildmodel/config/tools.yaml").read_text())
OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])
_SVG_NS = "http://www.w3.org/2000/svg"
BIT_R = TOOLS["engrave_vbit"]["radius_mm"]


def _asterisk(cx=0.0, cy=0.0, arm=3.0, half_w=0.6, n=6):
    """A closed n-armed logo outline, one valid ring (the Kasey temple icon's
    shape class): the union of n bars through the center."""
    from shapely.affinity import rotate
    from shapely.geometry import box
    bars = [rotate(box(-arm, -half_w, arm, half_w), 360.0 * k / n, origin=(0, 0))
            for k in range(n // 2)]                 # a bar through the center is two arms
    star = unary_union(bars)
    return [(cx + x, cy + y) for x, y in star.exterior.coords]


def _circle(cx, cy, r, n=64):
    pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
           for i in range(n)]
    return pts + [pts[0]]


def _xy_len(path):
    return LineString([(x, y) for x, y, *_ in path]).length


def _engraving_op(ops):
    return next(o for o in ops if o.name == "Engraving")


def _swept(paths, r=BIT_R):
    """The area the bit sweeps along `paths` (x, y[, z])."""
    return unary_union([LineString([(x, y) for x, y, *_ in p]).buffer(r) for p in paths])


def _bit_stays_inside(paths, shape, r=BIT_R, tol=1e-3):
    """Every point of every path (vertices and segment midpoints) lies inside
    `shape` and at least `r` from its edge and from each island — the bit never
    cuts outside the drawing. Checked point by point rather than through a
    buffer union, whose boundary coincides with the drawn edge on the boundary
    pass and leaves sub-micron slivers to floating point."""
    edges = [shape.exterior, *shape.interiors]
    for p in paths:
        pts = [(q[0], q[1]) for q in p]
        probes = pts + [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(pts, pts[1:], strict=False)]
        for q in probes:
            pt = Point(q)
            if not shape.covers(pt) or any(e.distance(pt) < r - tol for e in edges):
                return False
    return True


# ── the fill primitive ───────────────────────────────────────────────────────

def test_fill_rings_clear_a_disc_and_stand_off_a_hole():
    disc = Polygon(_circle(0, 0, 5))
    rings = fill_rings(disc, 0.25, 0.2)
    assert rings and all(r[0] == r[-1] for r in rings)
    swept = _swept(rings)
    assert swept.covers(Point(0, 0)) and swept.area > 0.95 * disc.area
    assert _bit_stays_inside(rings, disc)                  # never outside the shape

    ring = Polygon(_circle(0, 0, 5), [_circle(0, 0, 2)])  # an "O"
    rings = fill_rings(ring, 0.25, 0.2)
    swept = _swept(rings)
    assert not swept.intersects(Point(0, 0).buffer(1.9))   # the island stands
    assert swept.area > 0.9 * ring.area
    assert _bit_stays_inside(rings, ring)                  # a bit radius off the island too


def test_fill_rings_skip_a_shape_the_tool_cannot_enter():
    assert fill_rings(Polygon(_circle(0, 0, 0.2)), 0.25, 0.2) == []


def test_fill_stepover_follows_the_tool():
    assert engrave_fill_stepover(TOOLS["engrave_vbit"]) == pytest.approx(0.4 * 0.5)
    assert engrave_fill_stepover({"radius_mm": 1.0}) == pytest.approx(0.8)


# ── the program ─────────────────────────────────────────────────────────────

def test_a_closed_graphic_is_filled_whatever_the_option_says():
    logo = _asterisk(arm=4.0, half_w=1.0)
    poly = Polygon(logo)
    for centerline in (True, False):
        ops = generate_temple_program(
            OUTLINE, [], TempleParams(engrave_centerline=centerline), TOOLS,
            graphic_curves=[logo])
        eng = _engraving_op(ops)
        assert len(eng.paths) > 1, "a filled shape is several rings, not one trace"
        swept = _swept(eng.paths)
        # never outside the drawing (the op's 0.01 mm path simplification allowed)
        assert _bit_stays_inside(eng.paths, poly, tol=0.012)
        assert swept.area > 0.85 * poly.buffer(-BIT_R).buffer(BIT_R).area
        assert swept.covers(Point(2.0, 0.0))                 # down the middle of an arm
        zs = {round(z, 6) for p in eng.paths for _x, _y, z in p}
        assert len(zs) == 1


def test_a_closed_curve_inside_another_is_an_island():
    outer, inner = _circle(10, 0, 5), _circle(10, 0, 2)
    ops = generate_temple_program(OUTLINE, [], TempleParams(), TOOLS,
                                  graphic_curves=[outer, inner])
    swept = _swept(_engraving_op(ops).paths)
    # the "O"'s counter stands (the ring's chords sit a few µm inside its arc)
    assert not swept.intersects(Point(10, 0).buffer(1.95))
    assert swept.covers(Point(13.5, 0))                              # the ring is cut
    # the same two circles handed in the other order give the same cut
    ops2 = generate_temple_program(OUTLINE, [], TempleParams(), TOOLS,
                                   graphic_curves=[inner, outer])
    assert _swept(_engraving_op(ops2).paths).symmetric_difference(swept).area < 1e-6


def test_one_closed_curve_is_a_filled_disc():
    ops = generate_temple_program(OUTLINE, [], TempleParams(), TOOLS,
                                  graphic_curves=[_circle(10, 0, 3)])
    swept = _swept(_engraving_op(ops).paths)
    assert swept.covers(Point(10, 0)) and swept.covers(Point(12, 0))


def test_an_open_graphic_is_traced_as_drawn():
    stroke = [(-40.0, 0.0), (-30.0, 3.0), (-20.0, 0.0)]
    ops = generate_temple_program(OUTLINE, [], TempleParams(), TOOLS, graphic_curves=[stroke])
    eng = _engraving_op(ops)
    assert len(eng.paths) == 1
    assert [(x, y) for x, y, _z in eng.paths[0]] == stroke


def test_text_still_takes_the_centerline_beside_a_graphic():
    glyph = [(20, -2), (60, -2), (60, 2), (20, 2), (20, -2)]       # a 40 × 4 stroke
    logo = _asterisk(cx=-40, arm=4.0, half_w=1.0)
    ops = generate_temple_program(
        OUTLINE, [glyph], TempleParams(engrave_centerline=True), TOOLS,
        graphic_curves=[logo])
    eng = _engraving_op(ops)
    lengths = sorted(_xy_len(p) for p in eng.paths)
    # the glyph collapsed to one ~36–40 mm centerline …
    assert any(30 < ln < 41 for ln in lengths), lengths
    # … and the logo is filled, not centerlined: its arms' middles are swept
    logo_paths = [p for p in eng.paths if Polygon(logo).buffer(1e-6).covers(
        LineString([(x, y) for x, y, _ in p]))]
    assert _swept(logo_paths).covers(Point(-38.0, 0.0))
    # one Engraving op, one bit, one depth, for both
    zs = {round(z, 6) for p in eng.paths for _x, _y, z in p}
    assert len(zs) == 1


def test_a_dxf_temple_is_unchanged_every_closed_curve_takes_the_option():
    """Legacy semantics: with no graphics argument, a closed curve is text."""
    logo = _asterisk()
    on = generate_temple_program(OUTLINE, [logo], TempleParams(engrave_centerline=True), TOOLS)
    off = generate_temple_program(OUTLINE, [logo], TempleParams(engrave_centerline=False), TOOLS)
    assert (sum(_xy_len(p) for p in _engraving_op(on).paths)
            < sum(_xy_len(p) for p in _engraving_op(off).paths))


def test_graphic_engraving_curves_sorts_strokes_from_shapes():
    stroke = [(0.0, 0.0), (5.0, 1.0)]
    out = graphic_engraving_curves([stroke, _circle(20, 0, 3)], 0.25, 0.2)
    assert out[0] == stroke and len(out) > 2


def test_graphics_ride_the_blank_snap_with_the_outline():
    outline = Polygon([(-60, -6), (60, -6), (60, 6), (-60, 6)])
    hinge = [Polygon([(50, -5), (58, -5), (58, 5), (50, 5)])]
    text = [[(-40.0, 0.0), (40.0, 0.0)]]
    logo = _asterisk(cx=-20)
    p_out, p_hinge, p_text = place_temple_on_blank(outline, hinge, text, 170.0)
    p_logo = place_temple_curves([logo], outline, hinge, 170.0)
    # the same rigid motion: the logo's center moved exactly as the text did
    dx = p_text[0][0][0] - text[0][0][0]
    dy = p_text[0][0][1] - text[0][0][1]
    for (x, y), (px, py) in zip(logo, p_logo[0], strict=True):
        assert (px, py) == pytest.approx((x + dx, y + dy), abs=1e-9)
    assert place_temple_curves([], outline, hinge, 170.0) == []


# ── the relief (what the 3D model and the cut simulation show) ──────────────

def _z_at(relief, x, y):
    ox, oy = relief.field.origin
    res = relief.field.resolution
    return relief.field.z[int(round((y - oy) / res)), int(round((x - ox) / res))]


def test_relief_fills_the_drawn_shape_flat():
    t = TempleParams()
    logo = _asterisk(cx=0, cy=0, arm=4.0, half_w=1.0)
    relief = build_temple_relief(OUTLINE, t, graphic_curves=[logo], resolution=0.1)
    floor = t.blank_thickness_mm - t.engrave_depth_mm
    assert _z_at(relief, 2.0, 0.0) == pytest.approx(floor)      # down the middle of an arm
    assert _z_at(relief, 0.0, 0.0) == pytest.approx(floor)      # the hub
    assert _z_at(relief, 3.9, 0.0) == pytest.approx(floor)      # out to the tip
    # between the 0° and 60° arms, 1.75 mm clear of both axes
    assert _z_at(relief, 3.0, 1.75) == pytest.approx(t.blank_thickness_mm)


def test_relief_leaves_an_inner_closed_curve_standing():
    t = TempleParams()
    relief = build_temple_relief(OUTLINE, t, graphic_curves=[_circle(10, 0, 5), _circle(10, 0, 2)],
                                 resolution=0.1)
    floor = t.blank_thickness_mm - t.engrave_depth_mm
    assert _z_at(relief, 10.0, 0.0) == pytest.approx(t.blank_thickness_mm)   # the island
    assert _z_at(relief, 13.5, 0.0) == pytest.approx(floor)                  # the ring
    assert _z_at(relief, 16.0, 0.0) == pytest.approx(t.blank_thickness_mm)   # outside


def test_relief_grooves_an_open_graphic_as_a_stroke():
    t = TempleParams()
    relief = build_temple_relief(OUTLINE, t, graphic_curves=[[(-40.0, 0.0), (-20.0, 0.0)]],
                                 resolution=0.1)
    floor = t.blank_thickness_mm - t.engrave_depth_mm
    assert _z_at(relief, -30.0, 0.0) == pytest.approx(floor)
    assert _z_at(relief, -30.0, 1.0) == pytest.approx(t.blank_thickness_mm)


def test_relief_agrees_with_the_program_on_a_filled_shape():
    """Every carved cell lies inside the drawn shape, and the bit's sweep is carved."""
    t = TempleParams()
    logo = _asterisk(cx=10, cy=0, arm=4.0, half_w=1.0)
    relief = build_temple_relief(OUTLINE, t, graphic_curves=[logo], resolution=0.1)
    z = relief.field.z
    ox, oy = relief.field.origin
    res = relief.field.resolution
    rows, cols = np.nonzero((z < t.blank_thickness_mm - 1e-9) & relief.inside)
    poly = Polygon(logo).buffer(res + 1e-6)
    assert all(poly.covers(Point(ox + c * res, oy + r * res)) for r, c in zip(rows, cols, strict=True))
    ops = generate_temple_program(OUTLINE, [], t, TOOLS, graphic_curves=[logo])
    swept = _swept(_engraving_op(ops).paths)
    floor = t.blank_thickness_mm - t.engrave_depth_mm
    for x, y in ((12.0, 0.0), (10.0, 0.0), (11.0, 1.732)):   # 0° arm, hub, 60° arm
        if swept.covers(Point(x, y)):
            assert _z_at(relief, x, y) == pytest.approx(floor)


# ── the window: a .gdraw keeps the two apart from the moment it opens ───────

def _spline_ring(layer, pts):
    """A closed spline through pts (straight sides — no handles — is enough)."""
    return {"kind": "spline", "layer": layer, "closed": True,
            "nodes": [{"x": x, "y": y} for x, y in pts[:-1]]}


def _svg_bytes(state):
    ET.register_namespace("", _SVG_NS)
    root = ET.Element(f"{{{_SVG_NS}}}svg")
    meta = ET.SubElement(root, f"{{{_SVG_NS}}}metadata")
    meta.text = json.dumps(state)
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


def _make_gdraw(path):
    def line(layer, pts, closed=False):
        return {"kind": "line", "layer": layer, "closed": closed,
                "nodes": [{"x": x, "y": y} for x, y in pts]}
    front = {"curves": [
        line("OUTLINE", [(-60, -20), (60, -20), (60, 20), (-60, 20)], closed=True),
        line("LENS", [(20, -12), (45, -12), (45, 12), (20, 12)], closed=True),
        line("LENS", [(-45, -12), (-20, -12), (-20, 12), (-45, 12)], closed=True),
    ]}
    temple = {"curves": [
        line("OUTLINE", [(-70, -6), (70, -6), (70, 6), (-70, 6)], closed=True),
        _spline_ring("ENGRAVING", _asterisk(cx=-30)),         # the drawn logo
    ], "texts": [{"text": "GUILD", "family": "DejaVu Sans", "size_mm": 3.0,
                  "rotation": 0.0, "anchor_x": 10.0, "anchor_y": 1.5,
                  "layer": "ENGRAVING", "line_weight": 1.0}]}
    states = {"front": front, "temple_r": temple, "temple_l": {"curves": []},
              "hinge": {"curves": []}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"active_tab": "temple_r"}))
        for tab, st in states.items():
            zf.writestr(f"{tab}.svg", _svg_bytes(st))
    return path


def _window(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, name, lambda *a, **k: None)
    try:
        from guildmodel.gui.app import MainWindow
        win = MainWindow()
    except Exception as exc:                                  # pragma: no cover
        pytest.skip(f"no usable Qt/VTK platform: {exc}")
    win.view3d.show_mesh = lambda *a, **k: None
    win.view3d.show_flat = lambda *a, **k: None
    return win


@pytest.mark.gui
def test_the_window_keeps_drawn_curves_and_text_apart(monkeypatch, tmp_path):
    from guildmodel.core.project.schema import ComponentKind
    win = _window(monkeypatch, tmp_path)
    win.open_path(str(_make_gdraw(tmp_path / "logo.gdraw")))
    ws = next(w for w in win._workspaces if w.kind == ComponentKind.TEMPLE_RIGHT)

    text, graphics = ws.engraving_split()
    assert len(graphics) == 1, "the drawn logo is a graphic"
    assert len(graphics[0]) >= 30 and graphics[0][0] == pytest.approx(graphics[0][-1])
    assert text, "the text object was outlined into glyph contours"
    assert ws.engraving_text == text
    assert not any(c == graphics[0] for c in text)

    # the authored layer is untouched; the canvas sees both
    assert ws.layers["ENGRAVING"] == graphics
    shown = ws.display_layers()["ENGRAVING"]
    assert len(shown) == len(graphics) + len(text)

    # the build description carries the split, so model, sim and program agree
    i = win._workspaces.index(ws)
    spec = win._build_spec(i)
    assert spec["mode"] == "temple"
    assert spec["engraving"] == text and spec["graphics"] == graphics

    # the active working set follows the active tab
    win._activate_workspace(i)
    assert win._engraving_graphics == graphics and win._engraving_curves == text
    win.close()


def test_a_dxf_workspace_offers_every_curve_as_text():
    from guildmodel.core.project.schema import ComponentKind
    from guildmodel.gui.component_workspace import ComponentWorkspace, derive_workspace
    layers = {k: [] for k in ("OUTLINE", "LENS", "BRIDGE", "HINGE", "REF", "SCULPT", "ENGRAVING")}
    layers["OUTLINE"] = [[(-70, -6), (70, -6), (70, 6), (-70, 6), (-70, -6)]]
    layers["ENGRAVING"] = [_asterisk()]
    ws = ComponentWorkspace(kind=ComponentKind.FRAME_FRONT, label="", layers=layers)
    derive_workspace(ws)
    text, graphics = ws.engraving_split()
    assert len(text) == 1 and graphics == []
    assert ws.display_layers() is ws.layers
