"""Cut-time model for GRBL programs (BUILDPLAN M4.8).

The measuring stick for the cut-time-efficiency work: estimate how long a
posted program actually runs, op-by-op, so the gap to the Fusion control
(`Demo Project/Demo Program.nc`, ~10 min) is a number we can drive down rather
than guess at.

Two figures, both reported, each useful for a different reason:

  * **Cutting-only** length / feed time — assumption-free: it uses only the
    feed rates already programmed in the file and the cut geometry. This is the
    robust figure the regression budget test asserts on, because it does not
    depend on any machine-dynamics guess.

  * **Cycle estimate** — a faithful-but-compact reimplementation of GRBL's
    motion planner: trapezoidal acceleration, junction-deviation cornering
    (`$11`), and centripetal arc-speed limiting. This is what makes the
    *many-short-segment* penalty visible — the reason our real cycle time can
    exceed Fusion's even when our cut *length* is shorter. Rapids are planned in
    the same stream at the machine rapid rate (`$110/$111`).

The model parses the *posted program text* (not in-memory CamOps), so it
measures exactly what the controller runs — rapids, retracts, ramped lead-ins,
arcs — and works identically on our output and on the Fusion control.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# ----------------------------------------------------------------- dynamics

@dataclass(frozen=True)
class MachineDynamics:
    """Motion limits used by the cycle estimate. Defaults are a sane hobby-GRBL
    profile; `from_profile` pulls real per-machine values from a MachineProfile."""
    rapid_rate_mmpm: float = 3000.0     # GRBL $110/$111 max rate
    max_accel_mmps2: float = 500.0      # GRBL $120/$121
    junction_deviation_mm: float = 0.01  # GRBL $11
    min_junction_speed_mmps: float = 0.0

    @classmethod
    def from_profile(cls, profile) -> "MachineDynamics":
        """Build dynamics from a project.schema.MachineProfile (duck-typed)."""
        return cls(
            rapid_rate_mmpm=profile.rapid_rate_mmpm,
            max_accel_mmps2=profile.max_accel_mmps2,
            junction_deviation_mm=profile.junction_deviation_mm,
        )


# ----------------------------------------------------------------- moves

# canonical op names, matched from the section comments of either dialect
_CANON = [
    ("hinge", "Hinge Pockets"),
    ("rough", "Rough Relief"),
    ("fine", "Fine Relief"),
    ("eyewire", "Eyewires"),
    ("perimeter", "Perimeter"),
]


def _canon_op(text: str) -> str | None:
    low = text.lower()
    for key, name in _CANON:
        if key in low:
            return name
    return None


@dataclass
class _Segment:
    op: str
    rapid: bool
    length: float           # 3D path length (mm)
    nominal_mmps: float     # cruise speed cap (mm/s): feed, or rapid rate, or arc centripetal cap
    entry_dir: tuple[float, float, float]
    exit_dir: tuple[float, float, float]


@dataclass
class OpTime:
    name: str
    cut_mm: float = 0.0
    rapid_mm: float = 0.0
    cut_seconds: float = 0.0      # cutting-only (length/feed), no accel
    rapid_seconds: float = 0.0    # rapid length / rapid rate, no accel
    cycle_seconds: float = 0.0    # accel-aware (planner), cut + rapid

    @property
    def cutting_only_seconds(self) -> float:
        return self.cut_seconds + self.rapid_seconds


@dataclass
class CutTimeReport:
    ops: list[OpTime] = field(default_factory=list)
    dynamics: MachineDynamics = field(default_factory=MachineDynamics)
    n_tool_changes: int = 0           # tool-change blocks (BUILDPLAN M6.1)
    tool_change_seconds: float = 0.0  # nominal dwell over all changes

    def op(self, name: str) -> OpTime | None:
        return next((o for o in self.ops if o.name == name), None)

    @property
    def cut_mm(self) -> float:
        return sum(o.cut_mm for o in self.ops)

    @property
    def rapid_mm(self) -> float:
        return sum(o.rapid_mm for o in self.ops)

    @property
    def cutting_only_seconds(self) -> float:
        return sum(o.cutting_only_seconds for o in self.ops)

    @property
    def cycle_seconds(self) -> float:
        """Accel-aware motion time only (cut + rapid; excludes change dwell)."""
        return sum(o.cycle_seconds for o in self.ops)

    @property
    def total_seconds(self) -> float:
        """Motion cycle + tool-change dwell — the wall-clock estimate."""
        return self.cycle_seconds + self.tool_change_seconds


# ----------------------------------------------------------------- parsing

_WORD = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")


def _dir(a: tuple, b: tuple) -> tuple[float, float, float]:
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    return (dx / n, dy / n, dz / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def _arc_metrics(cur, end, i, j, ccw, accel, junc_v_cap):
    """Return (length_3d, nominal_mmps_cap, entry_dir, exit_dir) for a G2/G3.

    nominal cap is the centripetal speed limit sqrt(a*R) (small radii force a
    slowdown, as on GRBL); directions are the arc tangents at the ends.
    """
    cx, cy = cur[0] + i, cur[1] + j
    R = math.hypot(i, j)
    a0 = math.atan2(cur[1] - cy, cur[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    if ccw:
        sweep = (a1 - a0) % (2 * math.pi)
    else:
        sweep = (a0 - a1) % (2 * math.pi)
    if sweep < 1e-9:
        sweep = 2 * math.pi          # full circle
    arc_len = R * sweep
    dz = end[2] - cur[2]
    length = math.hypot(arc_len, dz)
    # tangent directions (planar); sign by sweep direction
    s = 1.0 if ccw else -1.0
    t0 = (-s * math.sin(a0), s * math.cos(a0), 0.0)
    t1 = (-s * math.sin(a1), s * math.cos(a1), 0.0)
    cap = math.sqrt(accel * R) if R > 1e-9 else junc_v_cap
    return length, cap, t0, t1


def _parse_segments(gcode: str, dyn: MachineDynamics) -> list[_Segment]:
    rapid_mmps = dyn.rapid_rate_mmpm / 60.0
    pos = (0.0, 0.0, 0.0)
    feed_mmps = 0.0
    motion = 0                       # 0=G0 1=G1 2=G2(cw) 3=G3(ccw)
    incremental = False
    unit_scale = 1.0                 # mm
    op = "Setup"
    segs: list[_Segment] = []

    for raw in gcode.splitlines():
        line = raw.strip()
        if not line:
            continue

        # --- section comments (op boundaries) ---------------------------
        if line.startswith("("):
            name = _canon_op(line.strip("()"))
            if name:
                op = name
            continue
        if line.startswith(";"):
            if "---" in line:
                name = _canon_op(line.strip("; -"))
                if name:
                    op = name
            continue
        # strip trailing inline comment
        for c in (";", "("):
            if c in line:
                line = line.split(c, 1)[0].strip()
        if not line:
            continue

        words = _WORD.findall(line)
        if not words:
            continue

        # G28/G30 homing: machine setup, not part cycle — skip and don't move
        if any(w[0].upper() == "G" and w[1] in ("28", "30") for w in words):
            continue

        nx, ny, nz = pos
        saw_axis = False
        for letter, num in words:
            L = letter.upper()
            v = float(num)
            if L == "G":
                g = int(round(v))
                if g in (0, 1, 2, 3):
                    motion = g
                elif g == 20:
                    unit_scale = 25.4
                elif g == 21:
                    unit_scale = 1.0
                elif g == 90:
                    incremental = False
                elif g == 91:
                    incremental = True
            elif L == "F":
                feed_mmps = (v * unit_scale) / 60.0
            elif L in "XYZIJ":
                pass  # handled below
        # axis words
        d = {w[0].upper(): float(w[1]) * unit_scale for w in words if w[0].upper() in "XYZIJ"}
        if "X" in d:
            nx = (pos[0] + d["X"]) if incremental else d["X"]; saw_axis = True
        if "Y" in d:
            ny = (pos[1] + d["Y"]) if incremental else d["Y"]; saw_axis = True
        if "Z" in d:
            nz = (pos[2] + d["Z"]) if incremental else d["Z"]; saw_axis = True
        if not saw_axis:
            continue

        end = (nx, ny, nz)
        if motion in (2, 3) and ("I" in d or "J" in d):
            i_off, j_off = d.get("I", 0.0), d.get("J", 0.0)
            length, cap, t0, t1 = _arc_metrics(
                pos, end, i_off, j_off, ccw=(motion == 3),
                accel=dyn.max_accel_mmps2, junc_v_cap=feed_mmps,
            )
            nominal = min(feed_mmps, cap) if feed_mmps > 0 else cap
            segs.append(_Segment(op, False, length, nominal, t0, t1))
        else:
            length = math.dist(pos, end)
            if length > 1e-12:
                dirv = _dir(pos, end)
                if motion == 0:
                    segs.append(_Segment(op, True, length, rapid_mmps, dirv, dirv))
                else:
                    nominal = feed_mmps if feed_mmps > 0 else rapid_mmps
                    segs.append(_Segment(op, False, length, nominal, dirv, dirv))
        pos = end

    return segs


# ----------------------------------------------------------------- planner

def _junction_speed(exit_dir, entry_dir, dyn: MachineDynamics) -> float:
    """GRBL junction-deviation cornering speed (mm/s) between two moves."""
    cos_phi = max(-1.0, min(1.0, sum(a * b for a, b in zip(exit_dir, entry_dir))))
    if cos_phi >= 1.0 - 1e-9:           # straight through
        return math.inf
    if cos_phi <= -1.0 + 1e-9:          # full reversal
        return dyn.min_junction_speed_mmps
    cos_half = math.sqrt((1.0 + cos_phi) / 2.0)
    R = dyn.junction_deviation_mm * cos_half / (1.0 - cos_half)
    return max(dyn.min_junction_speed_mmps, math.sqrt(dyn.max_accel_mmps2 * R))


def _seg_time(v_in: float, v_out: float, v_cruise: float, a: float, L: float) -> float:
    if L <= 1e-12 or v_cruise <= 1e-12:
        return 0.0
    v_in = min(v_in, v_cruise)
    v_out = min(v_out, v_cruise)
    d_acc = max(0.0, (v_cruise ** 2 - v_in ** 2) / (2 * a))
    d_dec = max(0.0, (v_cruise ** 2 - v_out ** 2) / (2 * a))
    if d_acc + d_dec <= L:
        d_cruise = L - d_acc - d_dec
        return (v_cruise - v_in) / a + (v_cruise - v_out) / a + d_cruise / v_cruise
    v_peak = math.sqrt((2 * a * L + v_in ** 2 + v_out ** 2) / 2.0)
    v_peak = max(v_peak, v_in, v_out, 1e-9)
    return (v_peak - v_in) / a + (v_peak - v_out) / a


def _plan(segs: list[_Segment], dyn: MachineDynamics) -> list[float]:
    """Forward/backward velocity planning; returns per-segment seconds."""
    n = len(segs)
    if n == 0:
        return []
    a = dyn.max_accel_mmps2
    # boundary speeds: v[0]=start at rest, v[n]=end at rest
    v = [0.0] * (n + 1)
    for k in range(1, n):
        jv = _junction_speed(segs[k - 1].exit_dir, segs[k].entry_dir, dyn)
        v[k] = min(jv, segs[k - 1].nominal_mmps, segs[k].nominal_mmps)
    # forward pass (accel-limited)
    for k in range(n):
        v[k + 1] = min(v[k + 1], math.sqrt(v[k] ** 2 + 2 * a * segs[k].length))
    # backward pass (decel-limited)
    for k in range(n - 1, -1, -1):
        v[k] = min(v[k], math.sqrt(v[k + 1] ** 2 + 2 * a * segs[k].length))
    return [_seg_time(v[k], v[k + 1], segs[k].nominal_mmps, a, segs[k].length)
            for k in range(n)]


# ----------------------------------------------------------------- public API

def count_tool_changes(gcode: str) -> int:
    """Number of tool-change blocks in a posted program (BUILDPLAN M6.1)."""
    return sum(1 for line in gcode.splitlines() if "Tool Change" in line)


def estimate_program(
    gcode: str,
    dynamics: MachineDynamics | None = None,
    tool_change_seconds: float = 0.0,
) -> CutTimeReport:
    """Parse a posted GRBL program and estimate its run time, op-by-op.

    `tool_change_seconds` is the nominal dwell charged per tool-change block
    (BUILDPLAN M6.1); it lands in `tool_change_seconds` / `total_seconds`, kept
    out of `cycle_seconds` so the motion estimate stays comparable across jobs.
    """
    dyn = dynamics or MachineDynamics()
    segs = _parse_segments(gcode, dyn)
    cycle = _plan(segs, dyn)

    n_changes = count_tool_changes(gcode)
    report = CutTimeReport(
        dynamics=dyn,
        n_tool_changes=n_changes,
        tool_change_seconds=n_changes * tool_change_seconds,
    )
    by_name: dict[str, OpTime] = {}
    order: list[str] = []
    for seg, t in zip(segs, cycle):
        ot = by_name.get(seg.op)
        if ot is None:
            ot = by_name[seg.op] = OpTime(seg.op)
            order.append(seg.op)
        ot.cycle_seconds += t
        if seg.rapid:
            ot.rapid_mm += seg.length
            ot.rapid_seconds += seg.length / max(seg.nominal_mmps, 1e-9)
        else:
            ot.cut_mm += seg.length
            ot.cut_seconds += seg.length / max(seg.nominal_mmps, 1e-9)
    report.ops = [by_name[n] for n in order]
    return report


def format_report(report: CutTimeReport, title: str = "") -> str:
    """A fixed-width op-by-op table for the log / setup sheet / CLI.

    Columns are consistent: 'cut min' is cutting motion only, 'rapid min' is
    rapid motion only, 'cycle min' is the accel-aware estimate of the two
    together. Every column's TOTAL is the column sum.
    """
    lines = []
    if title:
        lines.append(title)
    lines.append(
        f"{'Op':<16}{'cut mm':>9}{'rapid mm':>10}"
        f"{'cut min':>9}{'rapid min':>10}{'cycle min':>11}"
    )

    def row(name, cut_mm, rap_mm, cut_s, rap_s, cyc_s):
        return (f"{name:<16}{cut_mm:>9.0f}{rap_mm:>10.0f}"
                f"{cut_s / 60:>9.2f}{rap_s / 60:>10.2f}{cyc_s / 60:>11.2f}")

    for o in report.ops:
        lines.append(row(o.name, o.cut_mm, o.rapid_mm,
                         o.cut_seconds, o.rapid_seconds, o.cycle_seconds))
    lines.append(row(
        "TOTAL", report.cut_mm, report.rapid_mm,
        sum(o.cut_seconds for o in report.ops),
        sum(o.rapid_seconds for o in report.ops),
        report.cycle_seconds,
    ))
    if report.n_tool_changes:
        lines.append(
            f"{'Tool changes':<16}{report.n_tool_changes:>9}{'':>10}{'':>9}{'':>10}"
            f"{report.tool_change_seconds / 60:>11.2f}")
        lines.append(f"{'TOTAL w/ changes':<45}{report.total_seconds / 60:>11.2f}")
    return "\n".join(lines)


if __name__ == "__main__":          # ad-hoc baseline / tuning runs
    import sys
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8", errors="replace") as fh:
            rep = estimate_program(fh.read())
        print(format_report(rep, title=f"\n=== {path} ==="))
