"""The cut as a timeline over a stock (BUILDPLAN M21 §6.2 and §6.4): every
pose of the posted program in order, a live stock the playhead carves, and
sparse keyframes to scrub from.

The shape of `sim.playback.RemovalPlan`, which the viewer has driven since
M7.12 — positions, segments with a label and a tool, keyframes, a cursor —
with the stock engine underneath: the segments are the program's runs, the
tool is a `ToolShape`, a keyframe is a `DexelSnapshot`, and carving forward is
`cut`, so playing the whole program costs what the verdict cost and a scrub
restores the nearest keyframe and cuts on from there. The keyframes are
float32 but the last, which is exact: the rest state and the verdict read the
same stock.

Machine time weights the timeline (§6.4): each run's poses are spaced so a
rapid at 3000 mm/min passes in proportion to a cut at its feed, and the
scrubber's uniform steps track the real cycle.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

from .cutting import cut, vertical_poses
from .dexel import DexelSnapshot, DexelStock
from .program import Run, poses_for_run, spacing_for
from .tools import Footprint, ToolShape

__all__ = ["SetupsPlan", "StockPlan", "build_stock_plan", "floor_to", "stamp_forward",
           "steps_to_runs"]

#: Where the machine rapids, mm/min, when the program does not say.
RAPID_MMPM = 3000.0


@dataclass
class StockPlan:
    """The timeline. `stock` is live: `stamp_forward` carves it to the playhead
    and `floor_to` resets it to any position. `stock0` is the uncut blank."""
    stock: DexelStock
    stock0: DexelSnapshot
    origin: tuple
    resolution: float
    positions: np.ndarray = field(repr=False)       # (M, 3) tool tips, in order
    poses: np.ndarray = field(repr=False)           # (M, 6) the same with axes
    seg_bounds: list                                 # cumulative counts, len = n + 1
    seg_shape: list = field(repr=False)
    seg_footprint: list = field(repr=False)
    seg_label: list = field(default_factory=list)
    seg_cut: list = field(default_factory=list)
    seg_feed: list = field(default_factory=list)
    op_tool_geom: dict = field(default_factory=dict)
    keyframes: list = field(default_factory=list, repr=False)   # [(position, DexelSnapshot)]
    keep_outs: list = field(default_factory=list)
    groove_rings: list = field(default_factory=list)
    collision_pos: np.ndarray = field(default=None, repr=False)
    hold_down_height_mm: float = 0.0
    cursor: int = 0                                  # how far `stock` is carved
    z_bottom: float = 0.0                            # the block's underside, for a column cut through

    # --- the RemovalPlan interface the viewer and the collision check read

    @property
    def n_positions(self) -> int:
        return len(self.positions)

    @property
    def shape(self):
        return self.stock.shape

    @property
    def stock_top(self) -> np.ndarray:
        """The uncut blank's top, for a replay from the start."""
        return self.stock0.top(empty=self.z_bottom)

    def final_top(self) -> np.ndarray:
        """The fully cut top, exact."""
        return (self.keyframes[-1][1].top(empty=self.z_bottom) if self.keyframes
                else self.stock_top)

    def has_undercut(self) -> bool:
        return bool((self.keyframes[-1][1].count > 1).any()) if self.keyframes else False

    def seg_of(self, idx: int) -> int:
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

    def nbytes(self) -> int:
        live = self.stock.z_top.nbytes + self.stock.z_bot.nbytes + self.stock.count.nbytes
        return int(live + self.stock0.nbytes + sum(s.nbytes for _, s in self.keyframes)
                   + self.positions.nbytes + self.poses.nbytes)


def steps_to_runs(steps, tools_cfg: dict | None = None) -> list[tuple[Run, ToolShape]]:
    """`sim.playback` steps — ``(label, ToolProfile, paths[, is_cut[, spacing]])``
    — as runs with shapes, for the bed's fallback path that has ops and no
    program. The profile's numbers make the shape; the tool table, when given,
    supplies the groove form's dimensions by name."""
    out = []
    for step in steps:
        label, prof, paths = step[0], step[1], step[2]
        is_cut = bool(step[3]) if len(step) > 3 else True
        shape = ToolShape(kind=prof.kind, radius_mm=prof.radius_mm,
                          corner_radius_mm=prof.corner_radius_mm,
                          included_angle_deg=prof.included_angle_deg)
        if prof.kind == "groove" and tools_cfg:
            for t in tools_cfg.values():
                if t.get("type") == "groove" and abs(float(t["radius_mm"]) - prof.radius_mm) < 1e-9:
                    shape = ToolShape.from_tool(t)
                    break
        for path in paths:
            if len(path) < 1:
                continue
            pts = [(float(p[0]), float(p[1]), float(p[2]), 0.0) for p in path]
            out.append((Run(label, None, is_cut, 0.0, pts), shape))
    return out


def build_stock_plan(runs, stock: DexelStock, *, keyframes: int = 16,
                     rapid_mmpm: float = RAPID_MMPM, feed_mmpm: float = 750.0,
                     spacing: float | None = None) -> StockPlan:
    """The timeline for `runs` — ``[(Run, ToolShape)]`` in program order — over
    `stock`, which is cut to the end on the way and kept as the plan's live
    stock. A cut run is posed `spacing` apart (the grid, or finer for a small
    tool); a rapid coarser in proportion to its speed, so it plays fast and
    carves nothing."""
    stock0 = stock.snapshot()
    seg_pos, seg_poses, seg_shape, seg_fp, seg_label, seg_cut, seg_feed = [], [], [], [], [], [], []
    fps: dict = {}
    for run, shape in runs:
        if len(run.points) < 1:
            continue
        sp = spacing if spacing is not None else spacing_for(shape, stock.resolution)
        if not run.is_cut:
            sp = max(sp, sp * rapid_mmpm / max(1.0, run.feed_mmpm or feed_mmpm))
        poses = poses_for_run(run, sp)
        key = (shape, stock.resolution)
        if key not in fps:
            fps[key] = shape.footprint(stock.resolution)
        seg_pos.append(poses[:, :3])
        seg_poses.append(poses)
        seg_shape.append(shape)
        seg_fp.append(fps[key])
        seg_label.append(run.label)
        seg_cut.append(bool(run.is_cut))
        seg_feed.append(float(run.feed_mmpm))
    positions = np.vstack(seg_pos) if seg_pos else np.empty((0, 3))
    poses = np.vstack(seg_poses) if seg_poses else np.empty((0, 6))
    bounds = [0]
    for P in seg_pos:
        bounds.append(bounds[-1] + len(P))
    live = stock.count > 0
    z_bottom = float(np.nanmin(stock.bottom(empty=np.nan).z[live])) if live.any() else 0.0
    plan = StockPlan(stock, stock0, tuple(stock.origin), stock.resolution, positions, poses,
                     bounds, seg_shape, seg_fp, seg_label, seg_cut, seg_feed,
                     z_bottom=z_bottom if np.isfinite(z_bottom) else 0.0)
    total = plan.n_positions
    frames = [(0, stock0)]
    if total:
        step = max(1, total // max(1, keyframes))
        target = step
        while target < total:
            stamp_forward(plan, plan.cursor, target)
            frames.append((target, stock.snapshot()))
            target += step
        stamp_forward(plan, plan.cursor, total)
    frames.append((total, stock.snapshot(exact=True)))
    plan.keyframes = frames
    return plan


def stamp_forward(plan: StockPlan, a: int, b: int) -> None:
    """Carve the live stock with positions ``a:b`` (rapids pass over it)."""
    a = max(0, int(a))
    b = min(plan.n_positions, int(b))
    if a >= b:
        return
    for si in range(len(plan.seg_label)):
        s0, s1 = plan.seg_bounds[si], plan.seg_bounds[si + 1]
        lo, hi = max(a, s0), min(b, s1)
        if lo >= hi:
            continue
        if plan.seg_cut[si]:
            cut(plan.stock, plan.poses[lo:hi], plan.seg_shape[si],
                footprint=plan.seg_footprint[si])
    plan.cursor = max(plan.cursor, b)


def floor_to(plan: StockPlan, target: float) -> np.ndarray:
    """The top surface with the cut carried to `target`, the live stock reset
    to the nearest keyframe at or before it and carved on from there."""
    target = max(0, min(int(round(target)), plan.n_positions))
    kf_idx, kf_snap = plan.keyframes[0]
    for ki, snap in plan.keyframes:
        if ki <= target:
            kf_idx, kf_snap = ki, snap
        else:
            break
    plan.stock.restore(kf_snap)
    plan.cursor = kf_idx
    stamp_forward(plan, kf_idx, target)
    return plan.stock.top(empty=plan.z_bottom).z


@dataclass
class SetupsPlan:
    """Setups' timelines as one (2.0): the anterior cut first, the flip, then
    the posterior, each `StockPlan` over its own stock as the machine holds
    it, all on one grid. The viewer drives it as it drives one plan: the
    positions run on across the setups, and past a flip the live stock is the
    next setup's, which starts as the last one's turned over.

    `names` prefix each setup's labels ("" for none); `flips` describe each
    boundary: ``{"label": ..., "axis": "y" | "x", "point": (x, y, z)}``, the
    line the blank turns about, through `point`."""
    plans: list
    names: list = field(default_factory=list)
    flips: list = field(default_factory=list)
    cursor: int = 0
    active: int = 0

    is_setups = True

    def __post_init__(self) -> None:
        names = list(self.names) + [""] * (len(self.plans) - len(self.names))
        self.names = names[:len(self.plans)]
        self.offsets = [0]
        for plan in self.plans:
            self.offsets.append(self.offsets[-1] + plan.n_positions)
        self.positions = (np.vstack([p.positions for p in self.plans])
                          if self.plans else np.empty((0, 3)))
        self.poses = (np.vstack([p.poses for p in self.plans])
                      if self.plans else np.empty((0, 6)))
        self.seg_bounds, self.seg_label, self.seg_cut, self.seg_feed = [0], [], [], []
        self.seg_shape, self.seg_footprint = [], []
        self.op_tool_geom = {}
        for k, plan in enumerate(self.plans):
            off = self.offsets[k]
            prefix = f"{self.names[k]} · " if self.names[k] else ""
            for si in range(len(plan.seg_label)):
                self.seg_bounds.append(off + plan.seg_bounds[si + 1])
                # a setup's moves before its first op are the setup itself:
                # the flip, for every setup after the first
                label = plan.seg_label[si] or ("Flip" if k else "")
                self.seg_label.append(prefix + label)
            self.seg_cut += list(plan.seg_cut)
            self.seg_feed += list(plan.seg_feed)
            self.seg_shape += list(plan.seg_shape)
            self.seg_footprint += list(plan.seg_footprint)
            for op, geom in (plan.op_tool_geom or {}).items():
                self.op_tool_geom[prefix + op] = geom
        cps = [p.collision_pos for p in self.plans]
        self.collision_pos = (np.concatenate([c if c is not None else np.zeros(p.n_positions, bool)
                                              for c, p in zip(cps, self.plans)])
                              if any(c is not None for c in cps) else None)

    # --- what the viewer reads of a plan
    @property
    def n_positions(self) -> int:
        return self.offsets[-1]

    @property
    def origin(self):
        return self.plans[0].origin

    @property
    def resolution(self) -> float:
        return self.plans[0].resolution

    @property
    def shape(self):
        return self.plans[0].shape

    @property
    def z_bottom(self) -> float:
        return float(min(p.z_bottom for p in self.plans))

    @property
    def stock(self) -> DexelStock:
        return self.plans[self.active].stock

    @property
    def stock_top(self) -> np.ndarray:
        return self.plans[0].stock0.top(empty=self.z_bottom)

    @property
    def keep_outs(self) -> list:
        return self.plans[-1].keep_outs

    @property
    def groove_rings(self) -> list:
        return self.plans[-1].groove_rings

    @property
    def hold_down_height_mm(self) -> float:
        return max(float(p.hold_down_height_mm or 0.0) for p in self.plans)

    @property
    def flip_indices(self) -> list:
        return self.offsets[1:-1]

    def final_top(self) -> np.ndarray:
        return self.plans[-1].final_top()

    def has_undercut(self) -> bool:
        return any(p.has_undercut() for p in self.plans)

    def setup_at(self, idx: int) -> int:
        """The setup position `idx` falls in; a flip's own index is the next
        setup's start."""
        k = bisect.bisect_right(self.offsets, int(idx)) - 1
        return max(0, min(k, len(self.plans) - 1))

    def seg_of(self, idx: int) -> int:
        s = bisect.bisect_right(self.seg_bounds, idx) - 1
        return max(0, min(s, len(self.seg_label) - 1))

    def label_at(self, idx: int) -> str:
        return self.seg_label[self.seg_of(idx)] if self.seg_label else ""

    def flip_label_at(self, idx: int) -> str:
        """The flip's sentence when `idx` is the boundary it happens at."""
        for k, at in enumerate(self.flip_indices):
            if int(idx) == at and k < len(self.flips):
                return str(self.flips[k].get("label", ""))
        return ""

    def cursor_at(self, idx: int):
        if self.n_positions == 0:
            return None
        i = max(0, min(int(idx), self.n_positions - 1))
        p = self.positions[i]
        return (float(p[0]), float(p[1]), float(p[2]))

    def nbytes(self) -> int:
        return int(sum(p.nbytes() for p in self.plans))

    # --- the timeline
    def floor_to(self, target: float) -> np.ndarray:
        target = max(0, min(int(round(target)), self.n_positions))
        k = self.setup_at(target)
        self.active = k
        floor_to(self.plans[k], target - self.offsets[k])
        self.cursor = target
        return self.plans[k].stock.top(empty=self.z_bottom).z

    def stamp_forward(self, floor: np.ndarray, a: int, b: int) -> None:
        """Carve positions ``a:b`` into the setups they fall in and write the
        live setup's top into `floor`; crossing a flip starts the next setup
        from its own blank, the last one's result turned over."""
        a = max(0, int(a))
        b = min(self.n_positions, int(b))
        if a < b:
            ka, kb = self.setup_at(a), self.setup_at(b)
            for k in range(ka, kb + 1):
                off = self.offsets[k]
                lo, hi = max(a, off), min(b, self.offsets[k + 1])
                if k != ka:
                    floor_to(self.plans[k], 0)          # the next setup's blank
                if lo < hi:
                    stamp_forward(self.plans[k], lo - off, hi - off)
            self.active = kb
            self.cursor = max(self.cursor, b)
        floor[...] = self.plans[self.active].stock.top(empty=self.z_bottom).z
