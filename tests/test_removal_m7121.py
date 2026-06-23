"""M7.12.1 — remaining-stock removal playback (headless).

`simulate_removal` carves the real stock heightfield down at fine (move-batch)
granularity, for the volumetric 3D sim. Gates: the sequence is monotone and
bounded by the stock, the final frame equals a full one-shot removal, op
boundaries align to frames, untouched stock is preserved, and the frame count is
finer than op granularity.
"""
from __future__ import annotations

import numpy as np
import pytest

from guildcam.core.sim.toolsim import ToolProfile, densify, _stamp_points
from guildcam.core.sim.playback import (
    RemovalPlayback, simulate_removal, steps_from_ops,
)

SHAPE = (40, 40)
RES = 0.5
ORIGIN = (0.0, 0.0)


def _flat(r=1.0):
    return ToolProfile(kind="flat", radius_mm=r)


def _hline(y, z, x0=2.0, x1=18.0):
    return [(x0, y, z), (x1, y, z)]


def _stock(top=5.0):
    return np.full(SHAPE, float(top), dtype=np.float64)


def _steps():
    prof = _flat()
    return [
        ("Rough", prof, [_hline(8.0, 3.0)]),
        ("Fine", prof, [_hline(8.0, 2.0), _hline(10.0, 2.0)]),
        ("Perimeter", prof, [_hline(12.0, 1.0)]),
    ]


def _full_removal(stock_top, steps):
    """Reference: stamp every op's densified positions into the stock once."""
    ref = np.asarray(stock_top, dtype=np.float64).copy()
    for _, prof, paths in steps:
        kern = prof.kernel(RES)
        for p in paths:
            _stamp_points(ref, densify(p, RES), kern, ORIGIN, RES, ref.shape)
    return ref


def test_returns_removal_playback():
    pb = simulate_removal(_steps(), _stock(), ORIGIN, RES, frames=20)
    assert isinstance(pb, RemovalPlayback)
    assert pb.n_frames == len(pb.frames) == len(pb.frame_labels)
    assert all(f.shape == SHAPE for f in pb.frames)


def test_monotone_and_bounded_by_stock():
    stock = _stock(5.0)
    pb = simulate_removal(_steps(), stock, ORIGIN, RES, frames=30)
    for f in pb.frames:
        assert np.all(f <= stock + 1e-9)          # never more than the uncut block
    for prev, cur in zip(pb.frames, pb.frames[1:]):
        assert np.all(cur <= prev + 1e-9)         # material only ever removed
    assert pb.frames[-1].min() < stock.min() - 1e-6   # something actually got cut


def test_final_frame_equals_full_removal():
    stock = _stock(5.0)
    steps = _steps()
    pb = simulate_removal(steps, stock, ORIGIN, RES, frames=17)
    assert np.array_equal(pb.frames[-1], _full_removal(stock, steps))


def test_starts_from_two_level_stock_and_preserves_untouched():
    stock = _stock(5.0)
    stock[2:8, 2:8] = 7.0                         # a raised pad block, far from the cuts
    pb = simulate_removal(_steps(), stock, ORIGIN, RES, frames=20)
    # frame 0 begins from the real stock (not a uniform init_z)
    assert pb.frames[-1][2:8, 2:8].max() == pytest.approx(7.0)   # untouched pad preserved
    # a corner the tool never reaches keeps the blank height
    assert pb.frames[-1][-1, -1] == pytest.approx(5.0)


def test_op_boundaries_align_to_frames():
    steps = _steps()
    pb = simulate_removal(steps, _stock(), ORIGIN, RES, frames=25)
    assert pb.op_labels == ["Rough", "Fine", "Perimeter"]
    assert len(pb.op_boundaries) == len(steps)
    assert pb.op_boundaries == sorted(pb.op_boundaries)         # increasing
    assert pb.op_boundaries[-1] == pb.n_frames - 1             # last op ends on the last frame
    for j, b in enumerate(pb.op_boundaries):
        assert 0 <= b < pb.n_frames
        assert pb.frame_labels[b] == pb.op_labels[j]


def test_op_boundary_frame_is_full_op_result():
    """The frame at an op boundary holds that op's cumulative cut (the M7.12
    op-snapshot), so the op-scrubber can ride this finer timeline."""
    steps = _steps()
    pb = simulate_removal(steps, _stock(), ORIGIN, RES, frames=40)
    # after the first op, the deeper later ops have not been applied yet
    first = pb.frames[pb.op_boundaries[0]]
    assert first.min() == pytest.approx(3.0)      # Rough cuts to z=3
    assert pb.frames[pb.op_boundaries[-1]].min() == pytest.approx(1.0)   # Perimeter to z=1


def test_fine_granularity_beats_op_count():
    # one op, a long path → many tool positions → many frames at frames=50
    long_op = [("Sweep", _flat(), [_hline(6.0, 2.0, 2.0, 38.0)])]
    pb_fine = simulate_removal(long_op, _stock(), ORIGIN, RES, frames=50)
    assert pb_fine.n_frames > 5                   # finer than per-op
    # frames=1 collapses to one frame per op (coarsest)
    pb_coarse = simulate_removal(_steps(), _stock(), ORIGIN, RES, frames=1)
    assert pb_coarse.n_frames == len(_steps())


def test_empty_steps_single_uncut_frame():
    stock = _stock(5.0)
    pb = simulate_removal([], stock, ORIGIN, RES, frames=10)
    assert pb.n_frames == 1
    assert np.array_equal(pb.frames[0], stock)


def test_empty_op_still_marks_a_boundary():
    steps = [("Cut", _flat(), [_hline(8.0, 2.0)]),
             ("Skip", _flat(), [])]               # an op with no cutting paths
    pb = simulate_removal(steps, _stock(), ORIGIN, RES, frames=10)
    assert pb.op_labels == ["Cut", "Skip"]
    assert len(pb.op_boundaries) == 2
    # the empty op removes nothing → its boundary frame equals the previous cut
    assert np.array_equal(pb.frames[pb.op_boundaries[1]],
                          pb.frames[pb.op_boundaries[0]])


def test_frames_are_independent_copies():
    pb = simulate_removal(_steps(), _stock(), ORIGIN, RES, frames=12)
    snap0 = pb.frames[0].copy()
    pb.frames[-1][:] = -999.0
    assert np.array_equal(pb.frames[0], snap0)


def test_frame_cursors_track_the_tool():
    """frame_cursors give the tool (x,y,z) at each frame — the moving tool (M7.12.2)."""
    pb = simulate_removal(_steps(), _stock(), ORIGIN, RES, frames=25)
    assert len(pb.frame_cursors) == pb.n_frames
    assert all(len(c) == 3 for c in pb.frame_cursors)
    assert all(np.all(np.isfinite(c)) for c in pb.frame_cursors)
    # the final cursor is the end of the last op's last path (Perimeter → x=18,y=12,z=1)
    assert np.allclose(pb.frame_cursors[-1], (18.0, 12.0, 1.0))
    # every cursor's z is one of the cut depths the ops ran at
    depths = {3.0, 2.0, 1.0}
    assert all(round(c[2], 3) in depths for c in pb.frame_cursors)


def test_empty_op_cursor_holds_previous_position():
    steps = [("Cut", _flat(), [_hline(8.0, 2.0)]),
             ("Skip", _flat(), [])]
    pb = simulate_removal(steps, _stock(), ORIGIN, RES, frames=10)
    # the empty op's boundary frame keeps the prior tool position (tool didn't move)
    assert np.allclose(pb.frame_cursors[pb.op_boundaries[1]],
                       pb.frame_cursors[pb.op_boundaries[0]])


def test_empty_steps_cursor_is_nan():
    pb = simulate_removal([], _stock(), ORIGIN, RES, frames=10)
    assert len(pb.frame_cursors) == 1
    assert np.all(np.isnan(pb.frame_cursors[0]))


def test_bed_removal_two_disjoint_parts():
    """The whole-bed volumetric removal (M7.12.3) stamps each part's stock onto one
    cropped machine grid and carves the combined steps."""
    from guildcam.core.sim.bed import BedRemovalPart, simulate_bed_removal
    prof = _flat()
    stock_a = np.full((20, 20), 5.0)          # 10×10 mm at 0.5
    steps_a = [("A · cut", prof, [[(2.0, 5.0, 2.0), (8.0, 5.0, 2.0)]])]
    stock_b = np.full((20, 20), 4.0)
    steps_b = [("B · cut", prof, [[(32.0, 5.0, 1.0), (38.0, 5.0, 1.0)]])]
    parts = [BedRemovalPart(steps_a, stock_a, (0.0, 0.0), 0.0, 0.0),
             BedRemovalPart(steps_b, stock_b, (0.0, 0.0), 30.0, 0.0)]   # B 30 mm to the right
    pb = simulate_bed_removal(parts, resolution=0.5, frames=30)
    assert pb.stock_top.max() == pytest.approx(5.0)        # part A's blank
    assert pb.origin[0] <= 0.0 and pb.origin[1] <= 0.0     # cropped corner (minus margin)
    for prev, cur in zip(pb.frames, pb.frames[1:]):
        assert np.all(cur <= prev + 1e-9)                  # monotone across both parts
    assert pb.frames[-1].min() <= 1.0 + 1e-6              # part B cut to z=1
    assert pb.op_labels == ["A · cut", "B · cut"]          # both parts' ops, in order


def test_bed_removal_empty():
    from guildcam.core.sim.bed import simulate_bed_removal
    pb = simulate_bed_removal([], resolution=0.5)
    assert pb.n_frames == 1


def test_steps_from_ops_feeds_removal():
    """The M7.12 steps_from_ops builder drives simulate_removal unchanged."""
    from guildcam.core.cam.castle_ops import CamOp
    ops = [CamOp(name="Rough", paths=[_hline(8.0, 3.0)]),
           CamOp(name="Perimeter", paths=[_hline(12.0, 1.0)])]
    pb = simulate_removal(steps_from_ops(ops, _flat()), _stock(), ORIGIN, RES, frames=15)
    assert pb.op_labels == ["Rough", "Perimeter"]
    assert pb.frames[-1].min() == pytest.approx(1.0)
