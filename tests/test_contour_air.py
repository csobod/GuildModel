"""The contours cut where there is material (2.0).

On the shipped stock the pad block stands 4 mm over a 6 mm blank across the
nasal side, and every eyewire ring and the perimeter cross it. Each ring was
cut whole from the pad's top down, so above the blank's top most of every pass
was in air: a quarter of the contours' feed, about a minute a front. A pass
above the blank's top now cuts the ring's runs over the pad, going down and
coming out in air past its edge.

A stock whose floor steps, a pressed slab's (M25), is the mirror image: where
its bottom is high the passes reach the floor early and rode it whole to the
last. They now cut where they go deeper than the pass before, and the passes
before the last stop over the tabs, which such a ring had lost: the tab height
was the last pass's least depth along the ring, and that is nothing where the
floor is reached early.
"""
from pathlib import Path

import numpy as np
import pytest
import yaml

ROOT = Path(__file__).parents[1]
TOOLS = yaml.safe_load((ROOT / "src/guildmodel/config/tools.yaml").read_text())


@pytest.fixture(scope="module")
def demo():
    from guildmodel.core.geometry.regions import partition_zones
    from guildmodel.core.io_import.dxf import import_dxf
    from guildmodel.core.io_import.normalize import points_to_polygon

    raw = import_dxf(ROOT / "tests" / "fixtures" / "demo" / "GuildDraw DXF Export.dxf")
    partition = partition_zones(points_to_polygon(raw["OUTLINE"][0]),
                                [points_to_polygon(c) for c in raw["LENS"]], raw["SCULPT"])
    return partition, [points_to_polygon(c) for c in raw["COMPONENT"]]


def _closed(path) -> bool:
    return np.allclose(path[0][:2], path[-1][:2])


def test_runs_are_the_kept_stretches_with_one_vertex_past_each_end():
    from guildmodel.core.cam.castle_ops import _keep_runs

    keep = np.zeros(12, dtype=bool)
    keep[[2, 3, 4, 8]] = True
    runs = _keep_runs(keep)
    assert [list(r) for r in runs] == [[1, 2, 3, 4, 5], [7, 8, 9]]
    # a stretch across the ring's seam is one run, in the ring's direction
    keep = np.zeros(10, dtype=bool)
    keep[[8, 9, 0, 1]] = True
    assert [list(r) for r in _keep_runs(keep)] == [[7, 8, 9, 0, 1, 2]]
    assert _keep_runs(np.ones(5, dtype=bool)) is None        # the whole ring
    assert _keep_runs(np.zeros(5, dtype=bool)) == []


def _program(demo, castle=None, full=False, monkeypatch=None):
    from guildmodel.core.cam import castle_ops
    from guildmodel.core.cam.castle_ops import generate_castle_program
    from guildmodel.core.project.schema import CastleCamParams, CastleParams
    from guildmodel.core.zmap import castle_relief

    partition, hinges = demo
    castle = castle or CastleParams()
    relief = castle_relief(partition, castle, hinges, kernel="mesh", resolution=0.3)
    if full:
        monkeypatch.setattr(castle_ops, "_keep_runs", lambda keep: None)
    ops = generate_castle_program(relief, castle, hinges, TOOLS["flat_3175"],
                                  params=CastleCamParams(), tools_cfg=TOOLS)
    return {op.name: op for op in ops}, castle


def _cut(stock, ops, names):
    from guildmodel.core.stock import ToolShape, cut

    for name in names:
        op = ops[name]
        shape = ToolShape.from_tool(op.tool or TOOLS["flat_3175"])
        for path in op.paths:
            pts = np.asarray(path, dtype=np.float64)
            poses = [pts[0]]
            for a, b in zip(pts[:-1], pts[1:]):
                n = max(1, int(np.ceil(np.linalg.norm(b - a) / (stock.resolution / 4))))
                poses.extend(a + (b - a) * np.linspace(0, 1, n + 1)[1:, None])
            p = np.asarray(poses)
            cut(stock, np.column_stack([p, np.zeros(len(p)), np.zeros(len(p)), np.ones(len(p))]),
                shape)
    return stock.top(empty=-1.0).z


def _feed(op) -> float:
    return sum(float(np.linalg.norm(np.diff(np.asarray(p)[:, :2], axis=0), axis=1).sum())
               for p in op.paths)


def test_above_the_blank_only_the_pad_is_cut(demo, monkeypatch):
    """Side one on the shipped stock: a ring that crosses the pad is cut
    whole only below the blank's top, and the stock it leaves is the stock
    the whole rings left, with a fifth less feed in the contours."""
    from guildmodel.core.cam.castle_ops import AIR_ENTRY_MARGIN_MM, pad_footprint
    from guildmodel.core.relief.castle import stock_top_heightfield
    from guildmodel.core.relief.heightfield import Heightfield
    from guildmodel.core.stock import DexelStock

    ops, castle = _program(demo)
    stock_def = castle.stock
    T = float(stock_def.blank_thickness_mm)
    for name in ("Eyewires", "Perimeter"):
        op = ops[name]
        r = float((op.tool or TOOLS["flat_3175"])["radius_mm"])
        zone = pad_footprint(stock_def).buffer(r + AIR_ENTRY_MARGIN_MM + 1e-6)
        above = [p for p in op.paths if p[0][2] >= T - 1e-9]
        below = [p for p in op.paths if p[0][2] < T - 1e-9]
        assert above and all(not _closed(p) for p in above), name
        assert all(_closed(p) for p in below), name
        for p in above:
            # inside the pad's reach but the first and last point, in air past it
            from shapely.geometry import Point
            assert all(zone.contains(Point(q[:2])) for q in p[1:-1]), name
            assert not zone.buffer(-1e-3).contains(Point(p[0][:2]))

    full, _ = _program(demo, full=True, monkeypatch=monkeypatch)
    for name in ("Eyewires", "Perimeter"):
        assert _feed(ops[name]) < 0.85 * _feed(full[name]), name

    hf = stock_top_heightfield(stock_def, resolution=0.25, origin=(-90.0, -47.5),
                               shape=(int(95 / 0.25), int(180 / 0.25)))

    def blank():
        return DexelStock.from_heightfield(Heightfield(z=hf.z, origin=hf.origin,
                                                       resolution=hf.resolution),
                                           z_bottom=0.0)
    now = _cut(blank(), ops, ("Eyewires", "Perimeter"))
    before = _cut(blank(), full, ("Eyewires", "Perimeter"))
    differ = np.abs(now - before) > 1e-6
    # the engine samples the tool's footprint per pose, so a cell on the band's
    # very edge can fall either way; none further in
    assert differ.sum() <= 4


def test_a_stock_whose_floor_steps_keeps_its_tabs_and_cuts_only_where_it_deepens():
    """The curved contour (a pressed slab, M25): where the stock's bottom is
    high the passes reach the floor early. They rode it whole to the last,
    and the tab height, the last pass's least depth along the ring, was
    nothing there, so the ring kept no tabs at all (2.0). The passes before
    the last now stop over the tabs' tops, the last rises over every tab on
    both floors, and a pass cuts only where it goes deeper than the one before.
    The floor here is 0 left of x = 0 and 4 right of it, the top 10."""
    from shapely.geometry import Point, box

    from guildmodel.core.cam.castle_ops import contour_op
    from guildmodel.core.project.schema import CastleCamParams, HoldingParams
    from guildmodel.core.relief.heightfield import Heightfield

    res = 0.25
    xs = np.arange(-40.0, 40.0 + res / 2, res)
    X, _ = np.meshgrid(xs, xs)
    top = Heightfield(z=np.full(X.shape, 10.0), origin=(-40.0, -40.0), resolution=res)
    bottom = Heightfield(z=np.where(X < 0.0, 0.0, 4.0), origin=(-40.0, -40.0), resolution=res)
    holding = HoldingParams(strategy="tabs", tab_count=4, tab_width_mm=3.0, tab_height_mm=1.0)
    params = CastleCamParams(contour_stepdown_mm=1.5)
    op = contour_op("Perimeter", [box(-20, -20, 20, 20)], "outside", 1.5875, 0.0, 10.0, 0.4,
                    params, holding, surface_top=top, surface_bottom=bottom)
    last = np.asarray(op.paths[-1])
    assert _closed(last)
    left = last[:, 0] < -1.0
    right = last[:, 0] > 1.0
    assert np.isclose(last[left, 2], 1.0, atol=1e-6).any()          # tabs over the low floor
    assert np.isclose(last[right, 2], 5.0, atol=1e-6).any()         # and over the high one
    assert np.isclose(last[left, 2], 0.0, atol=1e-6).any() and np.isclose(last[right, 2], 4.0, atol=1e-6).any()
    for path in op.paths[:-1]:
        q = np.asarray(path)
        assert np.all(q[q[:, 0] > 1.0, 2] >= 5.0 - 1e-6)            # never into the tabs' tops
        assert np.all(q[q[:, 0] < -1.0, 2] >= 1.0 - 1e-6)
    # once the high side stands at its tabs' tops, the passes cut the low side alone
    opens = [np.asarray(q) for q in op.paths[:-1] if not _closed(q)]
    assert opens and all(np.all(q[1:-1, 0] < 0.5) for q in opens)
