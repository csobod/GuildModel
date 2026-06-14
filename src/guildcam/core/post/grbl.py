"""GRBL G-code post-processor.

Emits standard GRBL dialect only: G0/G1/G2/G3, G20/G21, G90, M3/M5.
No canned cycles (GRBL lacks them).
M0 program pause is used between sides, or two separate .nc files are emitted
(two-file is the safer default for non-expert users).
"""
from __future__ import annotations
import bisect
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def _cumlen(xy: list[tuple[float, float]]) -> list[float]:
    cum = [0.0]
    for k in range(1, len(xy)):
        cum.append(cum[-1] + math.dist(xy[k - 1], xy[k]))
    return cum


def _interp_xy(xy: list[tuple[float, float]], cum: list[float], s: float) -> tuple[float, float]:
    s = max(0.0, min(s, cum[-1]))
    k = bisect.bisect_left(cum, s)
    if k <= 0:
        return xy[0]
    if k >= len(xy):
        return xy[-1]
    s0, s1 = cum[k - 1], cum[k]
    t = 0.0 if s1 <= s0 else (s - s0) / (s1 - s0)
    return (xy[k - 1][0] + (xy[k][0] - xy[k - 1][0]) * t,
            xy[k - 1][1] + (xy[k][1] - xy[k - 1][1]) * t)


def _lap_from(xy: list[tuple[float, float]], cum: list[float], start_s: float) -> list[tuple[float, float]]:
    """One full lap of a closed loop (xy[0]==xy[-1]) starting at arc-length
    start_s, going forward and returning to that same point."""
    sp = _interp_xy(xy, cum, start_s)
    n = len(xy)
    out = [sp]
    out += [xy[k] for k in range(n) if cum[k] > start_s + 1e-9]   # …→ end(==P0)
    for k in range(1, n):                                          # P0 → just before start
        if cum[k] < start_s - 1e-9:
            out.append(xy[k])
        else:
            break
    out.append(sp)
    return out


@dataclass
class GRBLPost:
    job_name: str
    material: str
    tool_diameter_mm: float
    spindle_rpm: int
    feed_rate_mmpm: float       # cutting feed, mm/min
    plunge_rate_mmpm: float     # plunge feed, mm/min
    safe_z_mm: float = 5.0
    units: str = "mm"           # "mm" or "inch"
    comment_char: str = ";"

    _lines: list[str] = field(default_factory=list, repr=False, init=False)

    def header(self, side: str, timestamp: datetime | None = None) -> None:
        ts = (timestamp or datetime.now()).strftime("%Y-%m-%d %H:%M")
        self._lines += [
            f"; GuildCAM — {self.job_name}",
            f"; Side: {side}",
            f"; Material: {self.material}",
            f"; Tool: {self.tool_diameter_mm:.2f} mm diameter",
            f"; Spindle: {self.spindle_rpm} RPM",
            f"; Feed: {self.feed_rate_mmpm:.0f} mm/min  Plunge: {self.plunge_rate_mmpm:.0f} mm/min",
            f"; Generated: {ts}",
            "",
            "G90" + ("  ; absolute mode" if True else ""),
            "G21" if self.units == "mm" else "G20",
            f"G0 Z{self.safe_z_mm:.3f}",
        ]

    def comment(self, text: str) -> None:
        self._lines.append(f"{self.comment_char} {text}")

    def spindle_on(self) -> None:
        self._lines.append(f"M3 S{self.spindle_rpm}")

    def spindle_off(self) -> None:
        self._lines.append("M5")

    def rapid(self, x: float | None = None, y: float | None = None, z: float | None = None) -> None:
        parts = ["G0"]
        if x is not None:
            parts.append(f"X{x:.4f}")
        if y is not None:
            parts.append(f"Y{y:.4f}")
        if z is not None:
            parts.append(f"Z{z:.4f}")
        self._lines.append(" ".join(parts))

    def feed(self, x: float | None = None, y: float | None = None, z: float | None = None, feed: float | None = None) -> None:
        parts = ["G1"]
        if x is not None:
            parts.append(f"X{x:.4f}")
        if y is not None:
            parts.append(f"Y{y:.4f}")
        if z is not None:
            parts.append(f"Z{z:.4f}")
        f = feed if feed is not None else self.feed_rate_mmpm
        parts.append(f"F{f:.0f}")
        self._lines.append(" ".join(parts))

    def arc(
        self, x: float, y: float, z: float | None,
        i: float, j: float, ccw: bool, feed: float | None = None,
    ) -> None:
        """Circular arc to (x, y[, z]) about centre offset (i, j) from the
        current position. ccw -> G3, cw -> G2 (G17 plane; z makes it helical)."""
        parts = ["G3" if ccw else "G2", f"X{x:.4f}", f"Y{y:.4f}"]
        if z is not None:
            parts.append(f"Z{z:.4f}")
        parts += [f"I{i:.4f}", f"J{j:.4f}"]
        f = feed if feed is not None else self.feed_rate_mmpm
        parts.append(f"F{f:.0f}")
        self._lines.append(" ".join(parts))

    def plunge(self, z: float) -> None:
        self.feed(z=z, feed=self.plunge_rate_mmpm)

    def safe_retract(self) -> None:
        self.rapid(z=self.safe_z_mm)

    def program_pause(self, message: str = "Flip stock and re-register on dowel pins") -> None:
        self._lines.append(f"; {message}")
        self._lines.append("M0")

    def end_program(self) -> None:
        self._lines += ["M5", "G0 Z" + f"{self.safe_z_mm:.3f}", "M30"]

    def _emit_moves(self, pts: list[tuple[float, float, float]], arc_tol: float) -> None:
        """Feed through pts[1:] (current position is pts[0]); arc-fit if asked."""
        if arc_tol > 0:
            from .arcfit import fit_arcs
            cur = pts[0]
            for mv in fit_arcs(pts, tol_mm=arc_tol):
                end = mv[1]
                if mv[0] == "arc":
                    (cx, cy), ccw = mv[2], mv[3]
                    self.arc(end[0], end[1], end[2], cx - cur[0], cy - cur[1], ccw)
                else:
                    self.feed(x=end[0], y=end[1], z=end[2])
                cur = end
        else:
            for x, y, z in pts[1:]:
                self.feed(x=x, y=y, z=z)

    def _emit_ramped_loop(
        self, pts: list[tuple[float, float, float]], ramp_height: float,
        ramp_angle_deg: float, arc_tol: float,
    ) -> None:
        """Partial-lap ramped lead-in for a closed constant-Z contour loop.

        Feed down through cleared air to one stepdown above the cut, ramp down to
        full depth over a short lead-in distance (set by the ramp angle, capped
        to the loop perimeter), then cut one full finish lap at depth. This
        replaces the old full-lap-ramp + full-finish-lap (two laps per depth
        pass) with ~1 + lead-in/perimeter laps — roughly halving contour cut
        length while still leaving a clean full-depth wall (no slot-plunge).

        A non-positive ramp angle (or a loop shorter than the lead-in) degrades
        to ramping the whole lap, i.e. the original two-lap behaviour.
        """
        z_cut = pts[0][2]
        z_top = z_cut + ramp_height
        xy = [(p[0], p[1]) for p in pts]          # closed: xy[0] == xy[-1]
        cum = _cumlen(xy)
        total = cum[-1] or 1.0
        if ramp_angle_deg and ramp_angle_deg > 0:
            ramp_dist = min(total, ramp_height / math.tan(math.radians(ramp_angle_deg)))
        else:
            ramp_dist = total
        ramp_dist = max(ramp_dist, 1e-9)

        # controlled descent through air to the ramp-start height (never a rapid
        # below safe Z — keeps the tool out of uncleared stock)
        self.feed(z=z_top, feed=self.plunge_rate_mmpm)

        # Phase A — ramp z_top -> z_cut over the first ramp_dist of the loop
        for k in range(1, len(xy)):
            if cum[k] >= ramp_dist - 1e-9:
                break
            z = z_top + (z_cut - z_top) * (cum[k] / ramp_dist)
            self.feed(x=xy[k][0], y=xy[k][1], z=z, feed=self.plunge_rate_mmpm)
        pr = _interp_xy(xy, cum, ramp_dist)
        self.feed(x=pr[0], y=pr[1], z=z_cut, feed=self.plunge_rate_mmpm)

        # Phase B — one full finish lap at depth, starting/ending at the ramp end
        lap = _lap_from(xy, cum, ramp_dist)
        self._emit_moves([(x, y, z_cut) for x, y in lap], arc_tol)

    def emit_polyline(
        self,
        points: list[tuple[float, float, float]],
        first_move_is_plunge: bool = True,
        arc_tol: float = 0.0,
        ramp_height: float = 0.0,
        ramp_angle_deg: float = 8.0,
    ) -> None:
        if not points:
            return
        pts = [(float(a), float(b), float(c)) for a, b, c in points]
        x0, y0, z0 = pts[0]
        self.safe_retract()
        self.rapid(x=x0, y=y0)

        closed = (len(pts) >= 4
                  and abs(pts[0][0] - pts[-1][0]) < 1e-6
                  and abs(pts[0][1] - pts[-1][1]) < 1e-6)
        const_z = (max(p[2] for p in pts) - min(p[2] for p in pts)) < 1e-6
        if ramp_height > 0 and closed and const_z:
            self._emit_ramped_loop(pts, ramp_height, ramp_angle_deg, arc_tol)
            return

        if first_move_is_plunge:
            self.plunge(z0)
        else:
            self.feed(x=x0, y=y0, z=z0)
        self._emit_moves(pts, arc_tol)

    def to_string(self) -> str:
        return "\n".join(self._lines) + "\n"

    def write(self, path: Path) -> None:
        path.write_text(self.to_string(), encoding="utf-8")
