"""The C++ stock kernel agrees with the NumPy reference bit for bit
(BUILDPLAN M21 §6.9: every tool shape, every thread count, three grids).

Skipped where `guildmodel_stock` is not installed — a runner without a
compiler runs the suite on the reference alone, which is the point of having
one. Where it is installed, the two paths must be the same arrays: the floor
of a heightfield job, the split intervals of the groove form, the merge count
of a column that ran out of slots.
"""
import numpy as np
import pytest

from guildmodel.core.stock import (DexelStock, ToolShape, cut, cut_reference,
                                   poses_from_path, vertical_poses)

ext = pytest.importorskip("guildmodel_stock")

TOOLS = {
    "flat": dict(type="flat", radius_mm=1.0),
    "ball": dict(type="ball", radius_mm=1.5875),
    "toroid": dict(type="toroid", radius_mm=1.5875, corner_radius_mm=0.5),
    "vbit": dict(type="vbit", radius_mm=1.0, included_angle_deg=60.0),
    "groove": dict(type="groove", radius_mm=2.75, flute_length_mm=2.0, groove_depth_mm=0.75,
                   groove_width_mm=2.0, neck_diameter_mm=3.5),
}


def _path(seed, n=80, z_lo=-3.0, z_hi=0.0):
    rng = np.random.default_rng(seed)
    pts = np.cumsum(rng.normal(0, 0.5, size=(n, 3)), axis=0)
    pts[:, 2] = rng.uniform(z_lo, z_hi, n)
    return [tuple(p) for p in pts]


def _same(a: DexelStock, b: DexelStock) -> None:
    assert np.array_equal(a.count, b.count)
    live = np.arange(a.k)[:, None, None] < a.count[None]
    assert np.array_equal(a.z_top[live], b.z_top[live])
    assert np.array_equal(a.z_bot[live], b.z_bot[live])
    assert a.overflow_merges == b.overflow_merges


@pytest.mark.parametrize("tool", list(TOOLS))
@pytest.mark.parametrize("res", [0.3, 0.15, 0.1])
@pytest.mark.parametrize("threads", [1, 2, 20])
def test_the_kernel_is_bit_identical_to_the_reference(tool, res, threads):
    shape = ToolShape.from_tool(TOOLS[tool])
    grid, origin = (int(12 / res), int(14 / res)), (-6.0, -7.0)
    want = DexelStock.from_box(-100, -100, 100, 100, -50.0, 9.0, res, origin=origin, shape=grid)
    got = want.copy()
    poses = poses_from_path(_path(11), res)
    cut_reference(want, poses, shape)
    cut(got, poses, shape, threads=threads)
    _same(want, got)


def test_the_kernel_splits_and_merges_as_the_reference_does():
    shape = ToolShape.from_tool(TOOLS["groove"])
    want = DexelStock.from_box(-6, -6, 6, 6, 0.0, 14.0, 0.2, k=2)
    got = want.copy()
    poses = vertical_poses([(0.0, 0.0, 2.0), (0.5, 0.0, 6.0), (0.0, 0.5, 10.0)])
    cut_reference(want, poses, shape)
    cut(got, poses, shape, threads=3)
    assert want.overflow_merges > 0
    _same(want, got)
    assert want.undercut().any()


def test_the_kernel_runs_the_whole_program_in_pose_order_per_column():
    """Two tools over the same ground, several paths each: the batch and the
    thread count never change the answer."""
    flat, ball = ToolShape.from_tool(TOOLS["flat"]), ToolShape.from_tool(TOOLS["ball"])
    res = 0.15
    a = DexelStock.from_box(-100, -100, 100, 100, -50.0, 9.0, res, origin=(-6.0, -6.0),
                            shape=(90, 90))
    b, c = a.copy(), a.copy()
    paths = [poses_from_path(_path(s), res) for s in range(5)]
    for i, p in enumerate(paths):
        shape = flat if i % 2 else ball
        cut_reference(a, p, shape)
        cut(b, p, shape, threads=1)
        cut(c, p, shape, threads=20)
    _same(a, b)
    _same(a, c)


def test_the_kernel_rejects_a_grid_that_disagrees():
    z = np.zeros((2, 4, 4))
    with pytest.raises(Exception):
        ext.cut_vertical(z, z, np.zeros((3, 4), dtype=np.uint8), 0.0, 0.0, 0.1,
                         np.zeros((1, 3)), np.zeros(1, np.int64), np.zeros(1, np.int64),
                         np.zeros(1), np.zeros(1), 1)


def test_the_micro_benchmark_stays_in_its_class():
    """The §18.6 shape of job — a 1.2 mm ball at 0.02 mm, 2,821 cells a
    position — scaled to a tenth of its million positions, under a bound
    loose enough for any machine: the gate is a catastrophe guard here and a
    measurement in `scripts/spike_dexel.py`."""
    import time
    shape = ToolShape.from_tool(dict(type="ball", radius_mm=0.6))
    res = 0.02
    stock = DexelStock.from_box(-1e9, -1e9, 1e9, 1e9, -50.0, 1.0, res,
                                origin=(0.0, 0.0), shape=(1000, 2000))
    rng = np.random.default_rng(1)
    tips = np.column_stack([rng.uniform(1, 39, 100_000), rng.uniform(1, 19, 100_000),
                            rng.uniform(-1.0, 0.5, 100_000)])
    t0 = time.perf_counter()
    cut(stock, vertical_poses(tips), shape, threads=0)
    dt = time.perf_counter() - t0
    assert len(shape.footprint(res)) == 2821
    assert dt < 5.0, f"{dt:.2f} s for 10^5 positions"
