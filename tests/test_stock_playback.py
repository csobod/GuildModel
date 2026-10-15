"""The cut as a timeline over a stock, and what the viewer draws of it
(BUILDPLAN M21 §6.8 task 6, §6.4).

A `StockPlan` plays the posted program over a dexel stock: forward by
`stamp_forward`, to any position by `floor_to` from a keyframe. Its final
top is the floor the verdict reads; its keyframes are compact; a rapid moves
the tool and carves nothing. The block the viewer draws from it is closed,
and the undercut tint marks what the sheet alone cannot show.
"""
import numpy as np
import pytest

from guildmodel.core.stock import (DexelStock, Run, ToolShape, parse_program)
from guildmodel.core.stock.playback import (StockPlan, build_stock_plan, floor_to,
                                            stamp_forward, steps_to_runs)
from guildmodel.core.stock.surface import (block_faces, block_points, elevation_colors,
                                           occupancy_grid, undercut_tint)

FLAT = ToolShape(kind="flat", radius_mm=1.0)
GROOVE = ToolShape.from_tool(dict(type="groove", radius_mm=2.75, flute_length_mm=2.0,
                                  groove_depth_mm=0.75, groove_width_mm=2.0,
                                  neck_diameter_mm=3.5))

PROGRAM = """; GuildModel - t
G90
G21
G0 Z10.0
; --- Hinge Pockets ---
; --- Tool T1: flat_2mm (2.00 mm) ---
G0 X-3.0 Y0.0
G1 Z2.0 F300
G1 X3.0 Y0.0 F600
G0 Z10.0
; --- Perimeter ---
G0 X0.0 Y-3.0
G1 Z1.0 F300
G1 X0.0 Y3.0 F600
G0 Z10.0
M30
"""


def _runs(stock_res=0.2):
    return [(r, FLAT) for r in parse_program(PROGRAM)]


def _stock():
    return DexelStock.from_box(-5, -5, 5, 5, 0.0, 4.0, 0.2)


def test_the_plan_cuts_to_the_end_and_its_keyframes_are_compact():
    plan = build_stock_plan(_runs(), _stock(), keyframes=4)
    assert plan.n_positions > 10
    assert plan.cursor == plan.n_positions
    # the last keyframe is exact, the rest float32 and one layer deep
    assert plan.keyframes[-1][1].z_top.dtype == np.float64
    assert all(s.z_top.dtype == np.float32 for _, s in plan.keyframes[:-1])
    assert all(s.z_top.shape[0] == 1 for _, s in plan.keyframes)
    final = plan.final_top()
    r, c = plan.stock.cells_of(0.0, 0.0)
    assert final[r, c] == pytest.approx(1.0)                  # both passes crossed the center
    r, c = plan.stock.cells_of(2.5, 0.0)
    assert final[r, c] == pytest.approx(2.0)                  # the first pass only
    assert plan.stock_top[r, c] == 4.0                        # the uncut blank


def test_a_rapid_moves_the_tool_and_carves_nothing():
    plan = build_stock_plan(_runs(), _stock(), keyframes=4)
    rapid = [i for i, cut in enumerate(plan.seg_cut) if not cut]
    assert rapid, "the program has rapids"
    s0, s1 = plan.seg_bounds[rapid[-1]], plan.seg_bounds[rapid[-1] + 1]
    before = floor_to(plan, s0).copy()
    after = floor_to(plan, s1)
    assert np.array_equal(before, after)
    assert plan.label_at(s0) == "Perimeter"
    # and it is coarser than a cut, so it plays fast
    cut_i = next(i for i, cut in enumerate(plan.seg_cut) if cut)
    per_mm_cut = (plan.seg_bounds[cut_i + 1] - plan.seg_bounds[cut_i]) / 6.0
    per_mm_rapid = (s1 - s0) / 10.0
    assert per_mm_rapid < per_mm_cut


def test_scrubbing_is_monotone_and_returns_to_the_exact_end():
    plan = build_stock_plan(_runs(), _stock(), keyframes=3)
    final = plan.final_top().copy()
    tops = [floor_to(plan, i) for i in range(0, plan.n_positions + 1, 3)]
    for a, b in zip(tops, tops[1:]):
        assert (b <= a + 1e-5).all()
    assert np.array_equal(floor_to(plan, plan.n_positions), final)
    # forward from the middle lands where the keyframe path lands
    mid = plan.n_positions // 2
    floor_to(plan, mid)
    stamp_forward(plan, mid, plan.n_positions)
    assert np.allclose(plan.stock.top(empty=plan.z_bottom).z, final, atol=1e-5)


def test_the_plan_is_the_floor_the_sweep_gives():
    from guildmodel.core.sim.toolsim import ToolProfile, achieved_floor_grouped
    stock = _stock()
    plan = build_stock_plan(_runs(), stock, keyframes=2, spacing=0.2)
    paths = [([tuple(p[:3]) for p in r.points], "flat_1") for r, _ in _runs() if r.is_cut]
    floor = achieved_floor_grouped(paths, {"flat_1": ToolProfile(kind="flat", radius_mm=1.0)},
                                   ToolProfile(), stock.origin, stock.shape, 0.2, 4.0)
    assert np.array_equal(plan.final_top(), floor)


def test_steps_become_runs_with_shapes():
    from guildmodel.core.sim.toolsim import ToolProfile
    steps = [("Pockets", ToolProfile(kind="flat", radius_mm=1.0),
              [[(0, 0, 1), (1, 0, 1)], [(2, 0, 1), (3, 0, 1)]], True),
             ("Traverse", ToolProfile(kind="ball", radius_mm=0.5), [[(3, 0, 1), (0, 0, 5)]], False)]
    runs = steps_to_runs(steps)
    assert [r.label for r, _ in runs] == ["Pockets", "Pockets", "Traverse"]
    assert [r.is_cut for r, _ in runs] == [True, True, False]
    assert runs[2][1].kind == "ball" and runs[2][1].radius_mm == 0.5


def test_the_undercut_is_tinted_and_shown_solid():
    stock = DexelStock.from_box(-5, -5, 5, 5, 0.0, 6.0, 0.25)
    run = Run("Lens Groove", "groove_drageoir", True, 300.0, [(0, 0, 2.0, 0), (0.5, 0, 2.0, 0)])
    plan = build_stock_plan([(run, GROOVE)], stock, keyframes=2)
    assert plan.has_undercut()
    top = plan.final_top()
    colors = elevation_colors(np.r_[top.ravel(), np.zeros(top.size)], 6.0)
    plain = colors.copy()
    undercut_tint(colors, plan.stock, top.size)
    changed = (colors != plain).any(axis=1)
    assert changed[:top.size].any() and not changed[top.size:].any()
    occ, origin3, spacing = occupancy_grid(plan.stock, 0.25)
    r, c = plan.stock.cells_of(2.0, 0.0)
    column = occ[:, r, c]
    assert column.any() and not column.all()                 # material, a slot, material


def test_the_block_is_closed():
    import pyvista as pv
    top = np.full((6, 8), 3.0)
    footprint = np.ones((6, 8), dtype=bool)
    footprint[0, :] = False                                  # a notch of missing columns
    pts = block_points(top, (0.0, 0.0), 0.5, 0.0)
    faces = block_faces(footprint)
    mesh = pv.PolyData(pts, faces).triangulate().clean()
    assert mesh.n_open_edges == 0
    assert mesh.volume == pytest.approx(3.0 * 3.5 * 2.0, rel=0.01)   # 7 x 4 cells of 0.5
    # the top sheet's points come first and are the ones a tick rewrites
    n = top.size
    pts[:n, 2] = 1.0
    mesh2 = pv.PolyData(pts, faces).triangulate().clean()
    assert mesh2.volume == pytest.approx(1.0 * 3.5 * 2.0, rel=0.01)
