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

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from .toolsim import ToolProfile, _stamp_path, _stamp_points, densify

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


def motion_steps_from_program(
    gcode: str, default: ToolProfile, *, profiles: dict | None = None,
    rapid_mmpm: float = 3000.0, feed_mmpm: float = 750.0, base_spacing: float = 0.4,
) -> list[tuple]:
    """Playback steps for the FULL posted motion — cuts AND rapids (BUILDPLAN M8
    Part B). Each step is ``(label, profile, [polyline], is_cut, spacing)``. Rapids
    are kept (so the playback animates the retract / traverse / descend) and flagged
    ``is_cut=False`` so no material is removed along them. The per-step SPACING
    time-weights the run: a rapid is densified at ``base_spacing·rapid/feed`` (coarser
    → fewer frames → it plays back fast), a cut at ``base_spacing`` — so the uniform
    scrubber spends time ∝ length/rate and its duration tracks the real cycle."""
    from .paths import motion_runs_from_program
    profiles = profiles or {}
    cut_sp = max(1e-3, base_spacing)
    rapid_sp = max(cut_sp, base_spacing * rapid_mmpm / max(1.0, feed_mmpm))
    steps = []
    for label, tool, poly, is_cut in motion_runs_from_program(gcode):
        prof = profiles[tool] if (tool and tool in profiles) else default
        steps.append((label, prof, [poly], is_cut, cut_sp if is_cut else rapid_sp))
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


# ------------------------------------------------------------------ M7.12.1 remaining-stock

@dataclass
class RemovalPlayback:
    """A fine-grained remaining-stock animation (BUILDPLAN M7.12.1).

    ``frames[k]`` is the remaining-stock top (a heightfield, independent copies)
    after the k-th timeline step — the uncut block ``stock_top`` progressively
    carved down to the finished part. Monotone (material only ever removed), so the
    GUI can scrub freely; the last frame is the fully-cut result. Each op always
    ends on a frame, so ``op_boundaries[j]`` is the frame index where op
    ``op_labels[j]`` finishes — the M7.12 op-scrubber rides this same timeline.
    """
    frames: list                      # list[np.ndarray] — remaining stock per frame
    frame_labels: list                # op label being cut at each frame
    op_labels: list                   # one label per op, in cut order
    op_boundaries: list               # frame index at each op's end (len == op_labels)
    stock_top: np.ndarray = field(repr=False)
    origin: tuple = (0.0, 0.0)
    resolution: float = 0.3
    frame_cursors: list = field(default_factory=list)   # tool (x,y,z) at each frame (M7.12.2)
    op_tool_geom: dict = field(default_factory=dict)     # op label → tool geom (M7.12.2; GUI fills)
    keep_outs: list = field(default_factory=list)        # [(cx,cy,r)] machine coords (M7.12.3)
    collision_frames: list = field(default_factory=list) # per-frame hold-down hit bool (M7.12.3)
    hold_down_height_mm: float = 0.0                      # hold-down post height (M7.12.3)

    @property
    def n_frames(self) -> int:
        return len(self.frames)


def tool_profile_dims(geom: dict) -> dict:
    """The cutter+shank+holder dimensions for a tool geom (BUILDPLAN M7.12.2/.3) —
    the single source of truth shared by the moving-tool mesh (`Viewer3D._tool_mesh`)
    and the hold-down collision check, so the drawn tool and the tested envelope
    always agree. Local Z has the tip at 0: flute [0, flute_h] r=R, shank
    [flute_h, +shank_h] r=shank_r, holder above r=holder_r."""
    g = geom or {}
    R = max(0.2, float(g.get("radius_mm", 1.5875)))
    flute_h = float(g.get("flute_length_mm") or 0.0) or max(8.0, 4.0 * R)
    shank_r = max(R, (float(g.get("shank_diameter_mm") or 0.0) / 2.0) or max(R, 3.0))
    holder_r = max(shank_r * 2.2, 8.0)
    return {"R": R, "flute_h": flute_h, "shank_r": shank_r, "holder_r": holder_r,
            "shank_h": max(10.0, flute_h), "holder_h": 14.0}


def tool_envelope(geom: dict) -> tuple[float, float]:
    """(cutting radius, holder/collet radius) — the widest part of the tool."""
    d = tool_profile_dims(geom)
    return d["R"], d["holder_r"]


def tool_radius_below(geom: dict, z_tip: float, height: float) -> float:
    """The widest tool radius within the height band ``[z_tip, height]`` above the
    bed (BUILDPLAN M7.12.3): the part of the tool low enough to foul a hold-down of
    the given height. Returns 0 when the whole tool clears (tip at/above `height`)."""
    if z_tip >= height:
        return 0.0
    d = tool_profile_dims(geom)
    if height <= z_tip + d["flute_h"]:
        return d["R"]
    if height <= z_tip + d["flute_h"] + d["shank_h"]:
        return d["shank_r"]
    return d["holder_r"]


def simulate_removal(
    steps: list[Step],
    stock_top: np.ndarray,
    origin: tuple[float, float],
    resolution: float,
    *,
    frames: int = 60,
    point_spacing: float | None = None,
    progress: Callable[[float], None] | None = None,
) -> RemovalPlayback:
    """Animate the remaining stock being carved at ~`frames` timeline steps (M7.12.1).

    Unlike :func:`simulate_steps` (one snapshot per op, from a uniform ``init_z``),
    this starts from the real ``stock_top`` heightfield and snapshots at fine
    move-batch granularity — the uncut block progressively reduced. Every op ends on
    a frame (so ``op_boundaries`` indexes ``frames``); ``pending`` resets per op, so
    batches never straddle an op boundary. Material is only ever removed
    (``np.minimum``), so the sequence is monotone and the last frame is the full cut.
    """
    stock_top = np.asarray(stock_top, dtype=np.float64)
    shape = stock_top.shape
    spacing = point_spacing or resolution
    floor = stock_top.copy()

    kernels: dict = {}

    def _kern(prof: ToolProfile):
        key = (prof.kind, prof.radius_mm, prof.corner_radius_mm,
               prof.included_angle_deg)
        if key not in kernels:
            kernels[key] = prof.kernel(resolution)
        return kernels[key]

    # Pre-densify each op's paths into one positions array (so frames can stamp
    # sub-path batches) + count the total tool positions for the batch size.
    op_runs: list = []                # (label, kernel, positions N×3)
    total = 0
    for label, prof, paths in steps:
        chunks = [densify(p, spacing) for p in paths if len(p) >= 1]
        P = np.vstack(chunks) if chunks else np.empty((0, 3), dtype=np.float64)
        op_runs.append((label, _kern(prof), P))
        total += len(P)

    frames_out: list = []
    frame_labels: list = []
    op_labels: list = []
    op_boundaries: list = []
    frame_cursors: list = []          # tool (x,y,z) at each frame (the moving tool, M7.12.2)
    nan3 = (float("nan"), float("nan"), float("nan"))

    if total == 0:                    # nothing to cut — a single uncut frame
        frames_out.append(floor.copy())
        frame_labels.append(op_runs[0][0] if op_runs else "")
        frame_cursors.append(nan3)
        for label, _, _ in op_runs:
            op_labels.append(label)
            op_boundaries.append(0)
        if progress is not None:
            progress(1.0)
        return RemovalPlayback(frames_out, frame_labels, op_labels, op_boundaries,
                               stock_top, tuple(origin), resolution,
                               frame_cursors=frame_cursors)

    batch = max(1, math.ceil(total / max(1, frames)))
    pending = 0
    cursor = nan3                     # last stamped tool position
    for label, kern, P in op_runs:
        op_labels.append(label)
        i, M = 0, len(P)
        while i < M:
            take = int(min(batch - pending, M - i))
            _stamp_points(floor, P[i:i + take], kern, origin, resolution, shape)
            i += take
            pending += take
            cursor = (float(P[i - 1][0]), float(P[i - 1][1]), float(P[i - 1][2]))
            if pending >= batch:
                frames_out.append(floor.copy())
                frame_labels.append(label)
                frame_cursors.append(cursor)
                pending = 0
        # Force a frame at the op boundary (remainder pending, or an empty op) so
        # op markers always align to a frame and pending resets between ops.
        if pending > 0 or M == 0:
            frames_out.append(floor.copy())
            frame_labels.append(label)
            frame_cursors.append(cursor)   # empty op keeps the previous position
            pending = 0
        op_boundaries.append(len(frames_out) - 1)
        if progress is not None:
            progress(len(op_labels) / max(1, len(op_runs)))

    return RemovalPlayback(frames_out, frame_labels, op_labels, op_boundaries,
                           stock_top, tuple(origin), resolution,
                           frame_cursors=frame_cursors)


# ------------------------------------------------------------------ M7.12 position plan
#
# The frame model above plays the cut as discrete batches — the block steps down a
# chunk per frame and the tool teleports between batch-end cursors. The PLAN model
# below keeps the *full densified toolpath* and a few sparse keyframes, so the GUI
# can drive the tool along its exact path while stamping material **up to the tool's
# position** — the tool and the material removal stay in sync, and the motion is as
# fine as the toolpath itself.


@dataclass
class RemovalPlan:
    """The full densified cut as a position list + sparse keyframes (BUILDPLAN M7.12).

    ``positions`` (M×3) are every tool position in cut order; ``seg_bounds`` slices
    them into same-tool segments (each with a stamp ``kernel`` + op ``label``).
    ``keyframes`` are ``(position_index, floor_copy)`` snapshots for fast scrubbing.
    The GUI keeps a running floor: forward play stamps ``positions[a:b]`` into it
    (cheap), scrubbing recomputes from the nearest keyframe. The tool sits at
    ``positions[i]`` — exactly where the material is being removed.
    """
    stock_top: np.ndarray = field(repr=False)
    origin: tuple
    resolution: float
    positions: np.ndarray = field(repr=False)
    seg_bounds: list                 # cumulative position counts, len = n_segments + 1
    seg_kernel: list = field(repr=False)
    seg_label: list
    seg_cut: list = field(default_factory=list)   # per-seg: True=cuts material, False=rapid
    op_tool_geom: dict = field(default_factory=dict)
    keyframes: list = field(default_factory=list, repr=False)
    keep_outs: list = field(default_factory=list)
    # Verified lens-groove rings (V1): the side-cut V is outside the Z-buffer
    # block, so the GUI draws its true path — one (x, y, z_apex) ring per lens.
    groove_rings: list = field(default_factory=list)
    collision_pos: np.ndarray = field(default=None, repr=False)
    hold_down_height_mm: float = 0.0

    @property
    def n_positions(self) -> int:
        return len(self.positions)

    @property
    def shape(self):
        return self.stock_top.shape

    def seg_of(self, idx: int) -> int:
        import bisect
        s = bisect.bisect_right(self.seg_bounds, idx) - 1
        return max(0, min(s, len(self.seg_label) - 1))

    def label_at(self, idx: int) -> str:
        return self.seg_label[self.seg_of(idx)] if self.seg_label else ""

    def cursor_at(self, idx: int):
        if self.n_positions == 0:
            return None
        i = max(0, min(int(idx), self.n_positions - 1))
        p = self.positions[i]
        return (float(p[0]), float(p[1]), float(p[2]))


def build_removal_plan(
    steps: list[Step],
    stock_top: np.ndarray,
    origin: tuple[float, float],
    resolution: float,
    *,
    keyframes: int = 16,
    point_spacing: float | None = None,
) -> RemovalPlan:
    """Densify `steps` into one ordered position list + sparse keyframes (M7.12)."""
    stock_top = np.asarray(stock_top, dtype=np.float64)
    shape = stock_top.shape
    spacing = point_spacing or resolution
    kernels: dict = {}

    def _kern(prof: ToolProfile):
        key = (prof.kind, prof.radius_mm, prof.corner_radius_mm, prof.included_angle_deg)
        if key not in kernels:
            kernels[key] = prof.kernel(resolution)
        return kernels[key]

    seg_pos: list = []
    seg_kernel: list = []
    seg_label: list = []
    seg_cut: list = []
    for step in steps:
        label, prof, paths = step[0], step[1], step[2]
        is_cut = step[3] if len(step) > 3 else True       # 3-tuple steps = all cuts
        sp = step[4] if len(step) > 4 else spacing         # per-step time-weighted spacing
        chunks = [densify(p, sp) for p in paths if len(p) >= 1]
        if not chunks:
            continue
        seg_pos.append(np.vstack(chunks))
        seg_kernel.append(_kern(prof))
        seg_label.append(label)
        seg_cut.append(bool(is_cut))

    positions = np.vstack(seg_pos) if seg_pos else np.empty((0, 3))
    seg_bounds = [0]
    for P in seg_pos:
        seg_bounds.append(seg_bounds[-1] + len(P))
    total = len(positions)

    floor = stock_top.copy()
    keyframes_list = [(0, floor.copy())]
    if total:
        step = max(1, total // max(1, keyframes))
        gidx, target = 0, step
        for si, P in enumerate(seg_pos):
            kern = seg_kernel[si]
            cut = seg_cut[si]
            i, n = 0, len(P)
            while i < n:
                take = max(1, min(n - i, target - gidx))
                if cut:                          # rapids move the tool but remove nothing
                    _stamp_points(floor, P[i:i + take], kern, origin, resolution, shape)
                i += take
                gidx += take
                if gidx >= target and gidx < total:
                    keyframes_list.append((gidx, floor.copy()))
                    target += step
        keyframes_list.append((total, floor.copy()))

    return RemovalPlan(stock_top, tuple(origin), resolution, positions, seg_bounds,
                       seg_kernel, seg_label, seg_cut=seg_cut, keyframes=keyframes_list)


def plan_stamp_forward(plan: RemovalPlan, floor: np.ndarray, a: int, b: int) -> None:
    """Stamp ``plan.positions[a:b]`` into ``floor`` in place (spanning segments)."""
    a = max(0, int(a))
    b = min(plan.n_positions, int(b))
    if a >= b:
        return
    for si in range(len(plan.seg_label)):
        if plan.seg_cut and not plan.seg_cut[si]:     # don't remove material on rapids
            continue
        s0, s1 = plan.seg_bounds[si], plan.seg_bounds[si + 1]
        lo, hi = max(a, s0), min(b, s1)
        if lo < hi:
            _stamp_points(floor, plan.positions[lo:hi], plan.seg_kernel[si],
                          plan.origin, plan.resolution, plan.shape)


def plan_floor_to(plan: RemovalPlan, target: float) -> np.ndarray:
    """A fresh floor stamped up to position `target`, from the nearest keyframe."""
    target = max(0, min(int(round(target)), plan.n_positions))
    kf_idx, kf_floor = plan.keyframes[0]
    for ki, kfl in plan.keyframes:
        if ki <= target:
            kf_idx, kf_floor = ki, kfl
        else:
            break
    floor = kf_floor.copy()
    plan_stamp_forward(plan, floor, kf_idx, target)
    return floor


def plan_collisions(plan: RemovalPlan, keep_outs: list,
                    hold_down_height_mm: float) -> np.ndarray:
    """Per-position hold-down collision flags for the plan (BUILDPLAN M7.12.3) —
    the position analog of :func:`bed.bed_collision_frames`, Z-aware and vectorised
    per segment."""
    M = plan.n_positions
    flags = np.zeros(M, dtype=bool)
    if not keep_outs or M == 0:
        return flags
    for si in range(len(plan.seg_label)):
        s0, s1 = plan.seg_bounds[si], plan.seg_bounds[si + 1]
        P = plan.positions[s0:s1]
        d = tool_profile_dims(plan.op_tool_geom.get(plan.seg_label[si]))
        z = P[:, 2]
        r = np.where(
            z >= hold_down_height_mm, 0.0,
            np.where(hold_down_height_mm <= z + d["flute_h"], d["R"],
                     np.where(hold_down_height_mm <= z + d["flute_h"] + d["shank_h"],
                              d["shank_r"], d["holder_r"])))
        for cx, cy, kr in keep_outs:
            dist2 = (P[:, 0] - cx) ** 2 + (P[:, 1] - cy) ** 2
            flags[s0:s1] |= (r > 0) & (dist2 < (kr + r) ** 2)
    return flags
