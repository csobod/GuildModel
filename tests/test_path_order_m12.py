"""Per-op path ordering for travel (BUILDPLAN M12.1).

Relief paths emit in contour-ring order, interleaving the separate regions so the tool
hops across the part; reordering them nearest-neighbor cuts the air without touching
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


# ── M12.2 spiral/morph stitching ───────────────────────────────────────────────
def test_stitch_merges_close_keeps_far_separate():
    import numpy as np
    from guildmodel.core.cam.castle_ops import _stitch_close_paths
    zgrid = np.full((60, 60), 5.0)            # flat drop-cutter surface
    p1 = [(0.0, 0.0, 5.0), (2.0, 0.0, 5.0)]
    p2 = [(3.0, 0.0, 5.0), (5.0, 0.0, 5.0)]   # 1 mm gap → stitched onto p1
    p3 = [(50.0, 0.0, 5.0), (52.0, 0.0, 5.0)]  # 45 mm gap → its own path/entry
    out = _stitch_close_paths([p1, p2, p3], zgrid, 0.0, 0.0, 1.0, max_gap=4.0)
    assert len(out) == 2
    assert out[0][0] == (0.0, 0.0, 5.0) and out[0][-1] == (5.0, 0.0, 5.0)
    assert out[1] == p3


def test_stitch_connector_rides_the_surface():
    import numpy as np
    from guildmodel.core.cam.castle_ops import _stitch_close_paths
    zgrid = np.full((60, 60), 5.0)
    p1 = [(0.0, 0.0, 5.0), (2.0, 0.0, 5.0)]
    p2 = [(5.0, 0.0, 5.0), (7.0, 0.0, 5.0)]   # 3 mm gap → connector with interior pts
    out = _stitch_close_paths([p1, p2], zgrid, 0.0, 0.0, 1.0, max_gap=4.0)
    assert len(out) == 1
    mids = [q for q in out[0] if 2.0 < q[0] < 5.0]
    assert mids and all(abs(q[2] - 5.0) < 1e-6 for q in mids)   # stays on the surface


# ── engraving strokes cut nearest-neighbor (V1-prep toolpath re-audit) ────────
def test_engrave_strokes_ordered_for_travel():
    """Engraving strokes arrive in draw/file order; the op must cut them
    nearest-neighbor — multi-stroke text otherwise hops the length of the
    part between strokes (measured 6× the necessary air)."""
    from guildmodel.core.cam.temple_ops import engrave_op
    # two clusters, interleaved in "file order" like real draw order
    strokes = [[(0.0, 0.0), (1.0, 0.0)], [(50.0, 0.0), (51.0, 0.0)],
               [(2.0, 0.0), (3.0, 0.0)], [(52.0, 0.0), (53.0, 0.0)]]
    op = engrave_op(strokes, depth_z=3.7, tool={"name": "engrave_vbit",
                                                "diameter_mm": 0.5})
    assert _travel(op.paths) < _travel(
        [[(x, y, 3.7) for x, y in s] for s in strokes])
    xs = [p[0][0] for p in op.paths]
    assert xs == sorted(xs)                   # near strokes grouped, one sweep
    assert all(len(p) == 2 for p in op.paths)  # geometry untouched
    assert all(p[0][2] == 3.7 for p in op.paths)
