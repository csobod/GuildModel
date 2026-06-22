"""M7.12 — cut-simulation playback snapshots (headless).

The scrubber needs the achieved floor at each op boundary as a monotonic
sequence. These gate the core `core/sim/playback.py` accumulator: one snapshot
per op, in order; material is only ever removed (monotone); and the last snapshot
equals a single full `achieved_floor` sweep of the same paths.
"""
from __future__ import annotations

import numpy as np
import pytest

from guildcam.core.cam.castle_ops import CamOp
from guildcam.core.sim.toolsim import ToolProfile, achieved_floor
from guildcam.core.sim.playback import (
    FloorSnapshot, simulate_steps, steps_from_ops,
)

SHAPE = (40, 40)
RES = 0.5
ORIGIN = (0.0, 0.0)
INIT_Z = 5.0


def _flat(r=1.0):
    return ToolProfile(kind="flat", radius_mm=r)


def _hline(y, z, x0=2.0, x1=18.0):
    return [(x0, y, z), (x1, y, z)]


def _steps():
    prof = _flat()
    return [
        ("Rough", prof, [_hline(8.0, 3.0)]),
        ("Fine", prof, [_hline(8.0, 2.0), _hline(10.0, 2.0)]),
        ("Perimeter", prof, [_hline(12.0, 1.0)]),
    ]


def test_one_snapshot_per_op_in_order():
    snaps = simulate_steps(_steps(), ORIGIN, SHAPE, RES, INIT_Z)
    assert [s.label for s in snaps] == ["Rough", "Fine", "Perimeter"]
    assert [s.op_index for s in snaps] == [0, 1, 2]
    assert all(isinstance(s, FloorSnapshot) for s in snaps)
    assert all(s.floor.shape == SHAPE for s in snaps)


def test_snapshots_are_monotonic():
    snaps = simulate_steps(_steps(), ORIGIN, SHAPE, RES, INIT_Z)
    # nothing is ever above the starting stock, and each step only removes material
    assert np.all(snaps[0].floor <= INIT_Z + 1e-9)
    for prev, cur in zip(snaps, snaps[1:]):
        assert np.all(cur.floor <= prev.floor + 1e-9)
    # the deeper passes actually cut something (not a no-op sequence)
    assert snaps[-1].floor.min() < snaps[0].floor.min() - 1e-6


def test_snapshots_are_independent_copies():
    snaps = simulate_steps(_steps(), ORIGIN, SHAPE, RES, INIT_Z)
    before = snaps[0].floor.copy()
    snaps[-1].floor[:] = -999.0          # mutating one must not touch another
    assert np.array_equal(snaps[0].floor, before)


def test_final_snapshot_equals_full_sweep():
    steps = _steps()
    prof = _flat()
    all_paths = [p for _, _, paths in steps for p in paths]
    full = achieved_floor(all_paths, prof, ORIGIN, SHAPE, RES, INIT_Z)
    last = simulate_steps(steps, ORIGIN, SHAPE, RES, INIT_Z)[-1].floor
    assert np.array_equal(last, full)


def test_empty_op_yields_unchanged_snapshot():
    prof = _flat()
    steps = [
        ("Cut", prof, [_hline(8.0, 2.0)]),
        ("Nothing", prof, []),            # an op with no cutting paths
    ]
    snaps = simulate_steps(steps, ORIGIN, SHAPE, RES, INIT_Z)
    assert len(snaps) == 2
    assert np.array_equal(snaps[0].floor, snaps[1].floor)


def test_progress_reports_each_step():
    seen: list[float] = []
    simulate_steps(_steps(), ORIGIN, SHAPE, RES, INIT_Z, progress=seen.append)
    assert len(seen) == 3
    assert seen[-1] == pytest.approx(1.0)
    assert seen == sorted(seen)           # monotonically increasing fraction


# ------------------------------------------------------------------ steps_from_ops

def _op(name, paths, tool=None):
    return CamOp(name=name, paths=paths, tool=tool)


def test_steps_from_ops_falls_back_to_default():
    default = _flat(1.5)
    ops = [_op("A", [_hline(8.0, 2.0)])]          # tool=None → default
    steps = steps_from_ops(ops, default)
    assert steps[0][0] == "A"
    assert steps[0][1] is default
    assert steps[0][2] == [_hline(8.0, 2.0)]


def test_steps_from_ops_uses_op_tool_dict():
    default = _flat(1.5)
    ops = [_op("A", [_hline(8.0, 2.0)],
               tool={"name": "ball_3", "type": "ball", "radius_mm": 1.5})]
    prof = steps_from_ops(ops, default)[0][1]
    assert prof.kind == "ball" and prof.radius_mm == 1.5
    assert prof is not default


def test_steps_from_ops_prefers_profiles_map():
    default = _flat(1.5)
    vbit = ToolProfile(kind="vbit", radius_mm=0.25, included_angle_deg=30.0)
    ops = [_op("Engrave", [_hline(8.0, 2.0)],
               tool={"name": "engrave_vbit", "type": "vbit", "radius_mm": 0.25})]
    steps = steps_from_ops(ops, default, profiles={"engrave_vbit": vbit})
    assert steps[0][1] is vbit


def test_steps_from_ops_preserves_order_and_count():
    default = _flat()
    ops = [_op("Hinge Pockets", [_hline(6.0, 3.5)]),
           _op("Rough", [_hline(8.0, 3.0)]),
           _op("Perimeter", [_hline(12.0, 0.4)])]
    steps = steps_from_ops(ops, default)
    assert [s[0] for s in steps] == ["Hinge Pockets", "Rough", "Perimeter"]
