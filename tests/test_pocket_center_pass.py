"""A pocket's passes overlap at its middle (2.0, from the maker's Adjutor).

A hinge slot exactly two diameters wide, 4.0 mm for the 2 mm end mill, was
cleared by one ring a tool radius in: the next ring, a stepover further in,
did not fit, and the ring's passes met on the slot's center line with no
overlap at all. On paper that is a fin of no thickness; under an end mill a
hair under size it is a real one; in the simulation it was a column of cells
standing the pocket's full depth, in whichever pocket the grid fell on badly,
so one side of the frame showed it and the other did not. Where the passes
would overlap at the middle by less than a tenth of the diameter, the cascade
now goes once round the core it leaves: the hinge pockets, the inlay seats
and the filled engraving alike. A pocket whose passes overlap already posts
as before.
"""
import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, MultiLineString, box

from guildmodel.core.cam.pocketing import CENTER_OVERLAP, core_rings, fill_rings

R = 1.0                     # flat_2mm
STEP = 1.2                  # the shipped pocket stepover


def _slot(cx: float, cy: float, width: float, length: float):
    """An upright stadium, as the drawing's hinge slots are."""
    half = (length - width) / 2.0
    return LineString([(cx, cy - half), (cx, cy + half)]).buffer(width / 2.0, quad_segs=32)


def _deepest(region, rings, r: float = R, grid: float = 0.02) -> float:
    """How far the tool-center region's deepest point lies from a pass."""
    t = region.buffer(-r, join_style="round")
    x0, y0, x1, y1 = t.bounds
    xs, ys = np.meshgrid(np.arange(x0, x1 + grid, grid), np.arange(y0, y1 + grid, grid))
    pts = shapely.points(xs.ravel(), ys.ravel())
    pts = pts[shapely.contains(t, pts)]
    lines = MultiLineString([[tuple(p[:2]) for p in ring] for ring in rings])
    return float(shapely.distance(pts, lines).max())


def _hinge_rings(poly):
    from guildmodel.core.cam.castle_ops import _SCALE, _poly_rings
    return [[(p[0] / _SCALE, p[1] / _SCALE) for p in ring] + [(ring[0][0] / _SCALE, ring[0][1] / _SCALE)]
            for ring in _poly_rings(poly, R, STEP)]


def test_a_slot_two_diameters_wide_gets_a_pass_down_its_middle():
    slot = _slot(61.417, 5.629, 4.0, 9.5)
    rings = _hinge_rings(slot)
    assert len(rings) == 1
    assert _deepest(slot, rings) == pytest.approx(R, abs=0.01)     # met with no overlap
    extra = core_rings(slot, R, STEP)
    assert len(extra) == 1
    assert _deepest(slot, rings + extra) < R * (1.0 - CENTER_OVERLAP)
    from guildmodel.core.cam.castle_ops import hinge_pocket_op
    from guildmodel.core.project.schema import CastleCamParams
    op = hinge_pocket_op([slot], 4.5, 5.5, R, CastleCamParams())
    pts = np.vstack([np.asarray(p) for p in op.paths])
    middle = pts[np.abs(pts[:, 2] - 4.5) < 1e-6]
    assert np.abs(middle[:, 0] - 61.417).min() < 0.15                # a pass runs down the middle


@pytest.mark.parametrize("width", [5.0, 6.0, 7.3])
def test_a_pocket_whose_passes_overlap_already_posts_as_before(width):
    slot = _slot(0.0, 0.0, width, 12.0)
    assert core_rings(slot, R, STEP) == []
    assert _deepest(slot, _hinge_rings(slot)) <= R * (1.0 - CENTER_OVERLAP)


@pytest.mark.parametrize("cx", [61.417, -61.417])
def test_neither_side_of_the_frame_shows_a_fin_in_the_simulation(cx):
    """The playback's 0.15 mm grid on the maker's front, origin (-85, -42.5):
    the pocket at +61.417 stood a column of cells the pocket's depth along
    its center line, the one at -61.417 none."""
    from guildmodel.core.cam.castle_ops import hinge_pocket_op
    from guildmodel.core.project.schema import CastleCamParams
    from guildmodel.core.stock import DexelStock, ToolShape, cut, poses_from_path
    res = 0.15
    slot = _slot(cx, 5.629, 4.0, 9.5)
    ox = -85.0 + round((cx - 6.0 + 85.0) / res) * res
    oy = -42.5 + round((-1.0 + 42.5) / res) * res
    stock = DexelStock.from_box(-1e9, -1e9, 1e9, 1e9, 0.0, 5.5, res, origin=(ox, oy),
                                shape=(int(16.0 / res), int(12.0 / res)))
    shape = ToolShape.from_tool({"type": "flat", "radius_mm": R})
    for path in hinge_pocket_op([slot], 4.5, 5.5, R, CastleCamParams()).paths:
        cut(stock, poses_from_path(path, res), shape)
    top = stock.top(empty=np.nan).z
    rows, cols = top.shape
    xs, ys = np.meshgrid(ox + np.arange(cols) * res, oy + np.arange(rows) * res)
    # off the walls, where a cell straddles the edge either way
    floor = shapely.contains_xy(slot.buffer(-0.3), xs, ys)
    assert floor.sum() > 300
    assert float(np.nanmax(top[floor])) == pytest.approx(4.5), "a fin stands in the pocket"


def test_a_seat_and_a_filled_shape_close_their_middles_too():
    from guildmodel.core.cam.inlay_ops import _seat_rings
    seat = _slot(0.0, 0.0, 4.2, 10.0)          # the middle 1.1 mm from the ring: a 0.2 mm fin
    outer, rings = _seat_rings(seat, R, STEP)
    assert len(rings) == 2 and _deepest(seat, rings) < R * (1.0 - CENTER_OVERLAP)
    strip = box(-10.0, -2.1, 10.0, 2.1)
    filled = fill_rings(strip, R, STEP)
    assert len(filled) == 2 and _deepest(strip, filled) < R * (1.0 - CENTER_OVERLAP)
    # a fill whose passes overlap is unchanged
    assert len(fill_rings(box(-10.0, -2.5, 10.0, 2.5), R, STEP)) == 2
