"""Per-op path ordering for travel (BUILDPLAN M12.1).

Relief paths emit in contour-ring order, interleaving the separate regions so the tool
hops across the part; reordering them nearest-neighbour cuts the air without touching
the cut geometry or the climb sense.
"""
import math

from guildmodel.core.cam.castle_ops import order_paths_for_travel


def _travel(paths, start=(0.0, 0.0)):
    cur, t = start, 0.0
    for p in paths:
        t += math.hypot(p[0][0] - cur[0], p[0][1] - cur[1])
        cur = (p[-1][0], p[-1][1])
    return t


def _scattered():
    return [[(0, 0, 0), (1, 0, 0)], [(50, 0, 0), (51, 0, 0)],
            [(2, 0, 0), (3, 0, 0)], [(52, 0, 0), (53, 0, 0)]]


def test_orders_scattered_paths_to_cut_air():
    paths = _scattered()
    assert _travel(order_paths_for_travel(paths)) < _travel(paths)


def test_is_a_permutation_with_no_reversal():
    paths = _scattered()
    out = order_paths_for_travel(paths)
    assert len(out) == len(paths)
    # same path objects, unmodified — direction (climb/conventional) is preserved
    assert all(any(p is q for q in paths) for p in out)


def test_short_lists_pass_through():
    paths = [[(0, 0, 0), (1, 0, 0)], [(2, 0, 0), (3, 0, 0)]]
    assert order_paths_for_travel(paths) == paths
