"""The stock engine's reference path (BUILDPLAN M21 §6.8 task 2, §6.9).

The dexel grid replaces the heightfield the simulation has used since M5, so
the first thing to pin is that it *is* the heightfield where a heightfield was
enough: a one-interval stock cut by a top-down tool reads back bit for bit as
`achieved_floor` stamps it, for every tool type, at three resolutions. Then
what the heightfield could not do: the groove form splits an interval, a tool
from below removes from the bottom, a column that runs out of slots fills its
thinnest void and says so. The general pose agrees with the footprint on a
vertical axis, and the C++ kernel, when it is installed, agrees with the
reference at every thread count (`test_stock_kernel`).
"""
import logging

import numpy as np
import pytest

from guildmodel.core.relief.heightfield import Heightfield
from guildmodel.core.sim.toolsim import ToolProfile, achieved_floor, densify
from guildmodel.core.stock import (DexelStock, ToolShape, cut, cut_reference,
                                   poses_from_path, vertical_poses)

TOOLS = {
    "flat": dict(type="flat", radius_mm=1.0),
    "ball": dict(type="ball", radius_mm=1.5875),
    "toroid": dict(type="toroid", radius_mm=1.5875, corner_radius_mm=0.5),
    "vbit": dict(type="vbit", radius_mm=1.0, included_angle_deg=60.0),
}
GROOVE = dict(type="groove", radius_mm=2.75, flute_length_mm=2.0, groove_depth_mm=0.75,
              groove_width_mm=2.0, neck_diameter_mm=3.5, shank_diameter_mm=6.0)


def _wandering_path(seed=7, n=60):
    rng = np.random.default_rng(seed)
    pts = np.cumsum(rng.normal(0, 0.5, size=(n, 3)), axis=0)   # wanders off the grid
    pts[:, 2] = rng.uniform(-3.0, 0.0, n)
    return [tuple(p) for p in pts]


# ------------------------------------------------------- the heightfield case

@pytest.mark.parametrize("tool", list(TOOLS))
@pytest.mark.parametrize("res", [0.3, 0.15, 0.1])
def test_a_one_interval_stock_is_the_heightfield_bit_for_bit(tool, res):
    """The gate: `achieved_floor`'s floor and the dexel's top are the same
    array, not a close one."""
    shape, profile = ToolShape.from_tool(TOOLS[tool]), ToolProfile.from_tool(TOOLS[tool])
    grid, origin, init_z = (int(12 / res), int(12 / res)), (-6.0, -6.0), 9.0
    path = _wandering_path()
    floor = achieved_floor([path], profile, origin, grid, res, init_z)
    stock = DexelStock.from_box(-100, -100, 100, 100, -50.0, init_z, res,
                                origin=origin, shape=grid)
    cut_reference(stock, poses_from_path(path, res), shape)
    assert np.array_equal(stock.top().z, floor)
    # the footprint and the kernel are the same cells with the same drops
    fp = shape.footprint(res)
    di, dj, dz = profile.kernel(res)
    assert np.array_equal(fp.di, di) and np.array_equal(fp.dj, dj)
    assert np.array_equal(fp.z_lo, dz) and not fp.finite


def test_from_heightfield_reads_back_as_itself():
    z = np.where(np.add.outer(np.arange(20), np.arange(30)) % 7 < 4, 5.0, 3.0)
    z[:3, :] = 0.0
    hf = Heightfield(z=z, origin=(1.0, 2.0), resolution=0.2)
    stock = DexelStock.from_heightfield(hf, z_bottom=0.0)
    assert np.array_equal(stock.top().z, z)
    assert np.array_equal(stock.count > 0, z > 0.0)
    assert stock.volume() == pytest.approx(z.sum() * 0.04)


def test_cutting_through_empties_the_column_and_the_volume_follows():
    stock = DexelStock.from_box(0, 0, 10, 10, 0.0, 4.0, 0.5)
    v0 = stock.volume()
    assert v0 == pytest.approx(10 * 10 * 4 + 0, rel=0.15)      # cell-center sampling
    cut_reference(stock, vertical_poses([(5.0, 5.0, 2.0)]), ToolShape.from_tool(TOOLS["flat"]))
    r, c = stock.cells_of(5.0, 5.0)
    assert stock.column(r, c) == [(2.0, 0.0)]
    cut_reference(stock, vertical_poses([(5.0, 5.0, -1.0)]), ToolShape.from_tool(TOOLS["flat"]))
    assert stock.column(r, c) == [] and stock.count[r, c] == 0
    assert stock.top(empty=-9.0).z[r, c] == -9.0
    assert stock.volume() < v0


# ---------------------------------------------------------- the undercuts

def test_the_groove_form_splits_an_interval():
    """The drageoir's head takes a slot out of the wall and leaves the material
    above it — two intervals where a heightfield has no answer."""
    shape = ToolShape.from_tool(GROOVE)
    fp = shape.footprint(0.1)
    assert fp.finite
    stock = DexelStock.from_box(-5, -5, 5, 5, 0.0, 6.0, 0.1)
    cut_reference(stock, vertical_poses([(0.0, 0.0, 2.0)]), shape)
    # at the root radius the head is its full 2 mm tall: a slot from 2.0 to 4.0
    r, c = stock.cells_of(2.0, 0.0)
    (t1, b1), (t2, b2) = stock.column(r, c)
    assert (t1, b1) == pytest.approx((6.0, 4.0)) and (t2, b2) == pytest.approx((2.0, 0.0))
    # at the apex the V has closed: the column keeps nearly all its height
    r, c = stock.cells_of(2.7, 0.0)
    col = stock.column(r, c)
    assert len(col) == 2 and col[0][1] - col[1][0] < 0.3
    # under the neck the tool goes up for ever: a plain cut from the tip
    r, c = stock.cells_of(0.0, 0.0)
    assert stock.column(r, c) == [(2.0, 0.0)]
    assert stock.undercut().any()
    # the heightfield simulator stamps nothing for this form
    assert ToolProfile.from_tool(GROOVE).kernel(0.1)[0].size == 0


def test_a_tool_from_below_removes_from_the_bottom():
    shape = ToolShape.from_tool(TOOLS["flat"])
    stock = DexelStock.from_box(-5, -5, 5, 5, 0.0, 6.0, 0.1)
    poses = np.array([[0.0, 0.0, 1.5, 0.0, 0.0, -1.0]])     # axis pointing down: from below
    cut_reference(stock, poses, shape)
    r, c = stock.cells_of(0.0, 0.0)
    assert stock.column(r, c) == [(6.0, 1.5)]
    assert stock.bottom().z[r, c] == 1.5
    r, c = stock.cells_of(3.0, 0.0)
    assert stock.column(r, c) == [(6.0, 0.0)]                 # outside the radius


def test_a_column_out_of_slots_fills_its_thinnest_void_and_says_so():
    shape = ToolShape.from_tool(GROOVE)
    stock = DexelStock.from_box(-5, -5, 5, 5, 0.0, 12.0, 0.2, k=2)
    cut_reference(stock, vertical_poses([(0.0, 0.0, 2.0)]), shape)     # slot 2..4 at the root
    assert stock.overflow_merges == 0
    cut_reference(stock, vertical_poses([(0.0, 0.0, 8.0)]), shape)     # slot 8..10: a third interval
    assert stock.overflow_merges > 0
    r, c = stock.cells_of(2.0, 0.0)
    col = stock.column(r, c)
    assert len(col) == 2
    # material was kept, never lost: the thinner of the two voids is filled
    total = sum(t - b for t, b in col)
    assert total >= 12.0 - 2.0 - 2.0 + 0.0 - 1e-9
    assert total > 8.0                                           # one slot filled back in


def test_the_snapshot_is_float32_and_reads_the_same_top():
    stock = DexelStock.from_box(0, 0, 4, 4, 0.0, 3.0, 0.25)
    snap = stock.snapshot()
    assert snap.z_top.dtype == np.float32 and snap.count.dtype == np.uint8
    assert np.array_equal(snap.top(), stock.top().z)


def test_to_volume_marks_the_material_between_the_intervals():
    shape = ToolShape.from_tool(GROOVE)
    stock = DexelStock.from_box(-5, -5, 5, 5, 0.0, 6.0, 0.5)
    cut_reference(stock, vertical_poses([(0.0, 0.0, 2.0)]), shape)
    occ, (ox, oy, z0) = stock.to_volume(0.5)
    r, c = stock.cells_of(2.0, 0.0)
    column = occ[:, r, c]
    zs = z0 + (np.arange(occ.shape[0]) + 0.5) * 0.5
    assert column[(zs > 4.0) & (zs < 6.0)].all()
    assert not column[(zs > 2.0) & (zs < 4.0)].any()
    assert column[(zs > 0.0) & (zs < 2.0)].all()


# ------------------------------------------------------------- the general pose

@pytest.mark.parametrize("tool", list(TOOLS) + ["groove"])
def test_the_general_pose_agrees_with_the_footprint_when_vertical(tool):
    shape = ToolShape.from_tool(GROOVE if tool == "groove" else TOOLS[tool])
    res = 0.1
    fp = shape.footprint(res)
    xs, ys = fp.di * res + 0.3, fp.dj * res - 0.7
    lo, hi = shape.column_intervals((0.3, -0.7, 1.5), (0.0, 0.0, 1.0), xs, ys)
    assert np.allclose(lo, 1.5 + fp.z_lo, atol=1e-9)
    assert np.array_equal(np.isfinite(hi), np.isfinite(fp.z_hi))
    assert np.allclose(hi[np.isfinite(hi)], 1.5 + fp.z_hi[np.isfinite(fp.z_hi)], atol=1e-9)


@pytest.mark.parametrize("tool", list(TOOLS))
def test_a_tilted_tool_still_occupies_the_right_column(tool):
    """Tilt a tool 20° and ask for the column through its own axis a little
    way up: inside, from the body's lower surface on that column up."""
    shape = ToolShape.from_tool(TOOLS[tool])
    a = np.array([np.sin(np.radians(20.0)), 0.0, np.cos(np.radians(20.0))])
    tip = np.array([0.0, 0.0, 0.0])
    on_axis = tip + 3.0 * a                       # a point 3 mm up the axis
    lo, hi = shape.column_intervals(tip, a, [on_axis[0]], [on_axis[1]])
    # the column enters the leaning body below the axis point and leaves it
    # above: a tilted tool, unlike a vertical one, does not go up for ever
    # on any column
    assert lo[0] < on_axis[2] < hi[0] and np.isfinite(hi[0])
    # and a column well clear of the tool is missed
    lo, hi = shape.column_intervals(tip, a, [-20.0], [0.0])
    assert lo[0] > hi[0]
    # the reference cuts with it and removes less than a vertical tool of the
    # same radius lowered to the same depth would from the same column
    stock = DexelStock.from_box(-8, -8, 8, 8, 0.0, 6.0, 0.2)
    before = stock.volume()
    cut_reference(stock, np.array([[0.0, 0.0, 3.0, *a]]), shape)
    assert stock.volume() < before


# ------------------------------------------------------------- the checks

def test_a_rapid_through_stock_is_seen_and_never_stamped():
    from guildmodel.core.stock import collisions
    shape = ToolShape.from_tool(TOOLS["flat"])
    stock = DexelStock.from_box(-5, -5, 5, 5, 0.0, 6.0, 0.2)
    before = stock.volume()
    rapids = vertical_poses([(0.0, 0.0, 8.0), (0.0, 0.0, 5.0), (9.0, 9.0, 1.0), (0.0, 0.0, 6.0)])
    hit = collisions(stock, rapids, shape)
    assert hit.tolist() == [False, True, False, False]   # above, through, off the stock, flush
    assert stock.volume() == before                       # tested, never stamped


def test_the_shank_entering_stock_is_seen():
    from guildmodel.core.stock import collisions, shank_shape
    tool = dict(type="flat", diameter_mm=2.0, radius_mm=1.0, flute_length_mm=6.0,
                shank_diameter_mm=4.0)
    shank = shank_shape(tool)
    assert shank is not None and shank.radius_mm == 2.0
    stock = DexelStock.from_box(-5, -5, 5, 5, 0.0, 10.0, 0.2)
    # the cutter itself fits a pocket 2.4 mm wide; the shank, 6 mm up, does not
    # — but only once the tip is below 4 mm, where the shank reaches the top
    poses = vertical_poses([(0.0, 0.0, 5.0), (0.0, 0.0, 3.0)])
    hit = collisions(stock, poses, shank, lift=tool["flute_length_mm"])
    assert hit.tolist() == [False, True]
    assert shank_shape(dict(type="ball", radius_mm=1.0)) is None


# ------------------------------------------------------------- the dispatch

def test_cut_falls_back_to_the_reference_with_one_log_line(monkeypatch, caplog):
    from guildmodel.core.stock import cutting as cut_mod
    monkeypatch.setattr(cut_mod, "extension_available", lambda: False)
    monkeypatch.setattr(cut_mod, "_EXT_WARNED", False)
    shape = ToolShape.from_tool(TOOLS["ball"])
    path = _wandering_path(3)
    a = DexelStock.from_box(-100, -100, 100, 100, -50.0, 9.0, 0.2, origin=(-6.0, -6.0), shape=(60, 60))
    b = a.copy()
    with caplog.at_level(logging.INFO, logger="guildmodel.core.stock.cutting"):
        cut(a, poses_from_path(path, 0.2), shape)
        cut(a, poses_from_path(path, 0.2), shape)
    cut_reference(b, poses_from_path(path, 0.2), shape)
    cut_reference(b, poses_from_path(path, 0.2), shape)
    assert np.array_equal(a.top().z, b.top().z)
    assert sum("NumPy reference" in r.message for r in caplog.records) == 1


def test_the_stock_package_imports_no_kernel_and_no_qt():
    import ast
    import pathlib
    root = pathlib.Path(__file__).parents[1] / "src" / "guildmodel" / "core" / "stock"
    banned = ("guildmodel.core.model", "guildmodel.core.solid", "guildmodel.core.cam",
              "guildmodel.core.forming", "PySide6", "manifold3d", "OCP")
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                # relative imports: resolve two dots to core
                if node.level >= 2:
                    mod = "guildmodel.core." + mod
                names = [mod]
            for n in names:
                assert not any(n.startswith(b) for b in banned), (path.name, n)
