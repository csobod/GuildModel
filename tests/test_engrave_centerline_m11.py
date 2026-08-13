"""Centerline (medial-axis) engraving — BUILDPLAN M11 #7.

Engraving text is exported as closed glyph outlines; we engrave a single fixed-depth
line down the center of each stroke (the medial axis) instead of tracing the outline.
"""
from pathlib import Path

import numpy as np
import yaml
from shapely.geometry import LineString, Polygon

from guildmodel.core.cam.engrave_centerline import engraving_centerlines
from guildmodel.core.cam.temple_ops import generate_temple_program
from guildmodel.core.project.schema import TempleParams

TOOLS = yaml.safe_load(
    (Path(__file__).parents[1] / "src/guildmodel/config/tools.yaml").read_text())
OUTLINE = Polygon([(-70, -6), (70, -6), (70, 6), (-70, 6)])


def _xy_len(path):
    return LineString([(x, y) for x, y, *_ in path]).length


# ── the medial-axis primitive ─────────────────────────────────────────────────
def test_thin_rect_collapses_to_one_centerline():
    cl = engraving_centerlines([[(0, 0), (40, 0), (40, 4), (0, 4), (0, 0)]], prune_len=3.0)
    assert len(cl) == 1
    ys = [y for _x, y in cl[0]]
    assert max(ys) - min(ys) < 0.2           # one line down the middle
    assert 1.8 < float(np.mean(ys)) < 2.2     # at half the 4 mm width


def test_O_counter_becomes_loop_inside_ink():
    th = np.linspace(0, 2 * np.pi, 48)
    outer = [(5 * np.cos(t), 5 * np.sin(t)) for t in th]; outer[-1] = outer[0]
    inner = [(3 * np.cos(t), 3 * np.sin(t)) for t in th]; inner[-1] = inner[0]
    cl = engraving_centerlines([outer, inner], prune_len=0.5)
    ink = Polygon(outer).symmetric_difference(Polygon(inner))
    assert cl and all(ink.buffer(0.1).contains(LineString(c)) for c in cl)


def test_centerline_shorter_than_tracing_the_outline():
    H = [(0, 0), (2, 0), (2, 9), (5, 9), (5, 0), (7, 0),
         (7, 20), (5, 20), (5, 11), (2, 11), (2, 20), (0, 20), (0, 0)]
    cl = engraving_centerlines([H], prune_len=1.5)
    assert 0 < sum(LineString(c).length for c in cl) < LineString(H).length
    assert all(Polygon(H).buffer(0.1).contains(LineString(c)) for c in cl)


def test_open_curves_pass_through_untouched():
    assert engraving_centerlines([[(0, 0), (10, 5), (20, 0)]]) == \
        [[(0.0, 0.0), (10.0, 5.0), (20.0, 0.0)]]


# ── temple program integration ────────────────────────────────────────────────
def test_temple_engrave_op_is_shorter_with_centerline():
    glyph = [[(0, 0), (40, 0), (40, 4), (0, 4), (0, 0)]]   # one closed glyph outline
    on = generate_temple_program(OUTLINE, glyph, TempleParams(engrave_centerline=True), TOOLS)
    off = generate_temple_program(OUTLINE, glyph, TempleParams(engrave_centerline=False), TOOLS)
    eng_on = next(o for o in on if o.name == "Engraving")
    eng_off = next(o for o in off if o.name == "Engraving")
    assert sum(_xy_len(p) for p in eng_on.paths) < sum(_xy_len(p) for p in eng_off.paths)


def test_open_engraving_unaffected_by_centerline_flag():
    strokes = [[(-40, 0), (-30, 3), (-20, 0)], [(10, -2), (40, -2)]]   # already centerlines
    on = generate_temple_program(OUTLINE, strokes, TempleParams(engrave_centerline=True), TOOLS)
    off = generate_temple_program(OUTLINE, strokes, TempleParams(engrave_centerline=False), TOOLS)
    eng_on = next(o for o in on if o.name == "Engraving")
    eng_off = next(o for o in off if o.name == "Engraving")
    assert sum(_xy_len(p) for p in eng_on.paths) == sum(_xy_len(p) for p in eng_off.paths)


def test_default_is_centerline_on():
    assert TempleParams().engrave_centerline is True
