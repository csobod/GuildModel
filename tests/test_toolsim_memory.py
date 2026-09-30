"""The cut simulation stamps in batches (2026-09-30).

`_stamp_points` broadcast every tool position of a path against every cell of
the tool's footprint in one go. A 1 mm tool on a 0.02 mm grid is 7,854 cells,
one pocket path is 50,000 positions, and the temporaries came to 15 GB: the
hinge pocket finishing test took the maker's machine down mid-suite. A minimum
is the same taken in parts, so batching changes nothing in the result."""
import numpy as np
import pytest

from guildmodel.core.sim import toolsim
from guildmodel.core.sim.toolsim import ToolProfile, achieved_floor, densify


def _reference(P, kernel, origin, resolution, shape, init_z):
    """The floor one position at a time: no broadcast to get wrong."""
    di, dj, dz = kernel
    floor = np.full(shape, float(init_z))
    rows, cols = shape
    for x, y, z in P:
        c = int(np.round((x - origin[0]) / resolution)) + di
        r = int(np.round((y - origin[1]) / resolution)) + dj
        ok = (c >= 0) & (c < cols) & (r >= 0) & (r < rows)
        np.minimum.at(floor, (r[ok], c[ok]), (z + dz)[ok])
    return floor


@pytest.mark.parametrize("tool", [
    ToolProfile(kind="flat", radius_mm=1.0),
    ToolProfile(kind="ball", radius_mm=1.5875),
    ToolProfile(kind="toroid", radius_mm=1.5875, corner_radius_mm=0.5),
    ToolProfile(kind="vbit", radius_mm=1.0, included_angle_deg=60.0),
])
def test_batched_stamping_gives_the_same_floor(tool, monkeypatch):
    rng = np.random.default_rng(7)
    res, shape, origin = 0.1, (120, 120), (-6.0, -6.0)
    pts = np.cumsum(rng.normal(0, 0.5, size=(60, 3)), axis=0)   # wanders off the grid
    pts[:, 2] = rng.uniform(-3.0, 0.0, 60)
    path = [tuple(p) for p in pts]
    want = _reference(densify(path, res), tool.kernel(res), origin, res, shape, 99.0)
    for budget in (1, 997, 2_000_000):                # one position a batch, odd, shipped
        monkeypatch.setattr(toolsim, "_STAMP_BUDGET", budget)
        got = achieved_floor([path], tool, origin, shape, res, init_z=99.0)
        assert np.array_equal(got, want), budget


def test_a_batch_stays_within_the_budget(monkeypatch):
    """The broadcast is what ran away: count its elements."""
    seen = []
    real = np.minimum

    class Spy:
        def __call__(self, *args, **kwargs):           # np.minimum(a, b), as the kernel uses
            return real(*args, **kwargs)

        def at(self, floor, index, values):
            seen.append(values.size)
            return real.at(floor, index, values)

    monkeypatch.setattr(toolsim.np, "minimum", Spy())
    tool = ToolProfile(kind="flat", radius_mm=1.0)
    res = 0.05
    path = [(0.0, 0.0, -1.0), (200.0, 0.0, -1.0)]      # 4,000 positions x 1,257 cells
    achieved_floor([path], tool, (-2.0, -2.0), (80, 4080), res, init_z=9.0)
    assert len(seen) > 1
    assert max(seen) <= toolsim._STAMP_BUDGET


def test_a_tool_that_stamps_nothing_is_a_no_op():
    floor = achieved_floor([[(0.0, 0.0, -1.0), (5.0, 0.0, -1.0)]],
                           ToolProfile(kind="groove", radius_mm=1.0),
                           (-1.0, -1.0), (20, 70), 0.1, init_z=9.0)
    assert (floor == 9.0).all()
