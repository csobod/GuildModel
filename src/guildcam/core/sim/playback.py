"""Per-op cut-simulation snapshots for the playback scrubber (BUILDPLAN M7.12).

The cut-sim (M5) sweeps every cutting move at once → the final achieved floor.
The scrubber needs the floor *at each op boundary* — a monotonic sequence the GUI
steps through to watch the cut build up. This module accumulates the same
tool-profile Z-buffer stamping as :func:`toolsim.achieved_floor`, capturing a copy
of the running floor after each op (a "snapshot").

Because every stamp is a ``np.minimum`` (material is only ever removed), each
snapshot is ≤ the previous one everywhere, and the last snapshot equals a single
full :func:`achieved_floor` sweep of the same paths — so the scrubber's final
frame agrees with the headline report (geometric Z-buffer only, no physics).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .toolsim import ToolProfile, _stamp_path

Point3 = tuple[float, float, float]

#: One playback step: a label, the tool profile to sweep with, and its cutting
#: paths (machine/design-frame, the same frame as the relief grid origin).
Step = tuple[str, ToolProfile, list[list[Point3]]]


@dataclass
class FloorSnapshot:
    """The cumulative achieved floor after one op (BUILDPLAN M7.12)."""
    op_index: int
    label: str
    floor: np.ndarray = field(repr=False)


def steps_from_ops(
    ops, default: ToolProfile, *, profiles: dict | None = None,
) -> list[Step]:
    """Build playback steps from CamOps — one step per op, in cut order.

    Each op is swept with its own tool profile: a `profiles` entry keyed by the
    op's tool name (multi-tool jobs, M6.1), else the op's own ``tool`` dict, else
    `default`. Op paths are copied to plain float triples (decoupled from the ops).
    """
    profiles = profiles or {}
    steps: list[Step] = []
    for op in ops:
        name = op.tool_name
        if name is not None and name in profiles:
            prof = profiles[name]
        elif getattr(op, "tool", None):
            prof = ToolProfile.from_tool(op.tool)
        else:
            prof = default
        paths = [[(float(p[0]), float(p[1]), float(p[2])) for p in path]
                 for path in op.paths]
        steps.append((op.name, prof, paths))
    return steps


def simulate_steps(
    steps: list[Step],
    origin: tuple[float, float],
    shape: tuple[int, int],
    resolution: float,
    init_z: float,
    *,
    point_spacing: float | None = None,
    progress: Callable[[float], None] | None = None,
) -> list[FloorSnapshot]:
    """Accumulate `steps` into one Z-buffer floor, snapshotting after each op.

    Returns one :class:`FloorSnapshot` per step (the cumulative floor, copied).
    Cells no tool has passed over yet keep `init_z`. Monotonic by construction:
    every step only stamps ``np.minimum`` onto the running floor, so each
    snapshot floor ≤ the previous one everywhere. Tool kernels are cached per
    distinct profile (keyed including the V-bit angle, matching `achieved_floor_grouped`).
    """
    floor = np.full(shape, float(init_z), dtype=np.float64)
    spacing = point_spacing or resolution
    kernels: dict = {}

    def _kern(prof: ToolProfile):
        key = (prof.kind, prof.radius_mm, prof.corner_radius_mm,
               prof.included_angle_deg)
        if key not in kernels:
            kernels[key] = prof.kernel(resolution)
        return kernels[key]

    snaps: list[FloorSnapshot] = []
    n = max(1, len(steps))
    for i, (label, prof, paths) in enumerate(steps):
        kern = _kern(prof)
        for path in paths:
            if len(path) < 1:
                continue
            _stamp_path(floor, path, kern, origin, resolution, shape, spacing)
        snaps.append(FloorSnapshot(i, label, floor.copy()))
        if progress is not None:
            progress((i + 1) / n)
    return snaps
