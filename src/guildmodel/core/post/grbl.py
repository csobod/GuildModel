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
class ToolSetting:
    """Per-tool output context for a multi-tool program (BUILDPLAN M6.1).

    Assembled by the caller (tool geometry from tools.yaml; feeds either the
    tool's own override or the material preset; all clamped to the machine). The
    post swaps these in at each tool-change block; `number` is the Tn slot,
    assigned by first appearance.
    """
    number: int
    name: str
    diameter_mm: float
    feed_rate_mmpm: float
    plunge_rate_mmpm: float
    spindle_rpm: int


@dataclass
class GRBLPost:
    job_name: str
    material: str
    tool_diameter_mm: float
    spindle_rpm: int
    feed_rate_mmpm: float       # cutting feed, mm/min
    plunge_rate_mmpm: float     # plunge feed, mm/min
    safe_z_mm: float = 5.0
    # Rapid-descent floor just above the stock (BUILDPLAN M8): a plunge rapids (G0)
    # down to this height — clear of all stock — then *feeds* the last bit into the
    # cut. Without it every plunge feeds the full distance from safe Z at the plunge
    # rate, which dominates the cycle when there are many short relief passes. None
    # disables it (feed the whole plunge, original behavior). Must be >= stock top.
    feed_plane_mm: float | None = None
    units: str = "mm"           # "mm" or "inch"
    comment_char: str = ";"
    # Rigid work-zero offset added to every emitted coordinate (BUILDPLAN M6.2).
    # The toolpaths stay in the design frame; this shifts the posted output so the
    # chosen datum (e.g. the stock blank's lower-left/top) lands at G54 zero. Arc
    # I/J are center-relative and translation-invariant, so they are not offset.
    work_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    # Collision-aware pass linking (BUILDPLAN M8): between cutting passes, retract
    # only to `link_clearance_z_mm` (just above the stock) instead of the full safe
    # Z — UNLESS the straight hop to the next pass would pass within a `link_keepouts`
    # circle (a work-holding screw standing proud of the stock), in which case it
    # keeps the full safe Z. None disables it (always safe Z, the original behavior).
    link_clearance_z_mm: float | None = None
    link_keepouts: tuple = ()      # (cx, cy, radius) screw keep-outs, design coords

    _lines: list[str] = field(default_factory=list, repr=False, init=False)
    _last_xy: tuple | None = field(default=None, init=False, repr=False)
    # Last commanded Z (work coords); None = unknown (program start / after a tool
    # change, where the operator or the M6 macro re-establishes Z). Lets a pure-Z
    # rapid that wouldn't move be dropped — e.g. the back-to-back safe-Z retracts an
    # op-end + the next op's approach (or a tool change) would otherwise emit.
    _last_z: float | None = field(default=None, init=False, repr=False)

    def header(self, side: str, timestamp: datetime | None = None,
               initial_retract: bool = True) -> None:
        ts = (timestamp or datetime.now()).strftime("%Y-%m-%d %H:%M")
        self._lines += [
            f"; GuildModel — {self.job_name}",
            f"; Side: {side}",
            f"; Material: {self.material}",
            f"; Tool: {self.tool_diameter_mm:.2f} mm diameter",
            f"; Spindle: {self.spindle_rpm} RPM",
            f"; Feed: {self.feed_rate_mmpm:.0f} mm/min  Plunge: {self.plunge_rate_mmpm:.0f} mm/min",
            f"; Generated: {ts}",
            "",
            "G90  ; absolute mode",
            "G21" if self.units == "mm" else "G20",
            "G17  ; XY arc plane",
        ]
        # The first cutting pass always takes a full safe-Z retract before any XY move
        # (its prior position is unknown), so a header retract is redundant. On an
        # auto-tool-change machine (mode "m6") the M6 that follows raises Z itself — so
        # emitting one here just adds a wasted Z bob before the tool change. Skip it
        # there; keep it for manual starts where no M6 re-establishes Z.
        if initial_retract:
            self.rapid(z=self.safe_z_mm)

    def comment(self, text: str) -> None:
        self._lines.append(f"{self.comment_char} {text}")

    def spindle_on(self) -> None:
        self._lines.append(f"M3 S{self.spindle_rpm}")

    def spindle_off(self) -> None:
        self._lines.append("M5")

    def rapid(self, x: float | None = None, y: float | None = None, z: float | None = None) -> None:
        # A pure-Z rapid to the height we're already at moves nothing — drop it.
        if (x is None and y is None and z is not None
                and self._last_z is not None and abs(z - self._last_z) < 1e-6):
            return
        ox, oy, oz = self.work_offset
        parts = ["G0"]
        if x is not None:
            parts.append(f"X{x + ox:.4f}")
        if y is not None:
            parts.append(f"Y{y + oy:.4f}")
        if z is not None:
            parts.append(f"Z{z + oz:.4f}")
            self._last_z = z
        self._lines.append(" ".join(parts))

    def feed(self, x: float | None = None, y: float | None = None, z: float | None = None, feed: float | None = None) -> None:
        ox, oy, oz = self.work_offset
        parts = ["G1"]
        if x is not None:
            parts.append(f"X{x + ox:.4f}")
        if y is not None:
            parts.append(f"Y{y + oy:.4f}")
        if z is not None:
            parts.append(f"Z{z + oz:.4f}")
            self._last_z = z
        f = feed if feed is not None else self.feed_rate_mmpm
        parts.append(f"F{f:.0f}")
        self._lines.append(" ".join(parts))

    def arc(
        self, x: float, y: float, z: float | None,
        i: float, j: float, ccw: bool, feed: float | None = None,
    ) -> None:
        """Circular arc to (x, y[, z]) about center offset (i, j) from the
        current position. ccw -> G3, cw -> G2 (G17 plane; z makes it helical).
        I/J are center-relative, so the work offset (a translation) leaves them
        unchanged; only the absolute X/Y/Z endpoint shifts."""
        ox, oy, oz = self.work_offset
        parts = ["G3" if ccw else "G2", f"X{x + ox:.4f}", f"Y{y + oy:.4f}"]
        if z is not None:
            parts.append(f"Z{z + oz:.4f}")
            self._last_z = z
        parts += [f"I{i:.4f}", f"J{j:.4f}"]
        f = feed if feed is not None else self.feed_rate_mmpm
        parts.append(f"F{f:.0f}")
        self._lines.append(" ".join(parts))

    def plunge(self, z: float) -> None:
        self.feed(z=z, feed=self.plunge_rate_mmpm)

    def peck_drill(
        self, x: float, y: float, z_top: float, z_bottom: float,
        peck_depth: float, approach_mm: float = 1.0,
    ) -> None:
        """Peck-drill a hole at (x, y) from z_top down to z_bottom (BUILDPLAN
        M6.4). GRBL has no canned cycle, so this is an explicit G83 full-retract
        peck: plunge `peck_depth`, rapid out to clear chips, rapid back to just
        above the cut, repeat. The work offset is applied by rapid/feed."""
        # A non-positive peck depth would never advance the loop below — guard the
        # primitive (the schema/UI floor it, but a hand-edited project must not
        # hang the worker): drill the hole in one full-depth plunge instead.
        if peck_depth <= 1e-9:
            peck_depth = max(z_top - z_bottom, 1e-9)
        self._last_xy = None          # a drill isn't a linkable cutting pass
        approach = z_top + approach_mm
        self.safe_retract()
        self.rapid(x=x, y=y)
        self.rapid(z=approach)
        z = z_top
        first = True
        while z > z_bottom + 1e-9:
            z_next = max(z_bottom, z - peck_depth)
            if not first:
                self.rapid(z=z + 0.3)            # rapid down to just above last peck
            self.feed(z=z_next, feed=self.plunge_rate_mmpm)
            self.rapid(z=approach)               # full retract to clear chips
            z = z_next
            first = False

    def safe_retract(self) -> None:
        self.rapid(z=self.safe_z_mm)

    def reset_link(self) -> None:
        """Forget the last cut position so the next pass takes a full safe-Z retract
        (used after a move the post can't link-check — drills, tool changes)."""
        self._last_xy = None

    @staticmethod
    def _pt_seg_dist(px, py, ax, ay, bx, by) -> float:
        dx, dy = bx - ax, by - ay
        if dx == 0.0 and dy == 0.0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def _link_retract(self, x_to: float, y_to: float) -> None:
        """Retract before traversing to (x_to, y_to). Lifts only to the low clearance
        plane when that hop provably clears every work-holding screw; otherwise (or
        when linking is disabled / the prior position is unknown) a full safe-Z
        retract. The fail-safe is the full retract — a low hop is taken ONLY when
        proven clear."""
        a = self._last_xy
        if self.link_clearance_z_mm is None or a is None:
            self.safe_retract()
            return
        for cx, cy, r in self.link_keepouts:
            if self._pt_seg_dist(cx, cy, a[0], a[1], x_to, y_to) < r:
                self.safe_retract()       # the hop passes near a proud screw — clear it
                return
        self.rapid(z=self.link_clearance_z_mm)

    def _rapid_to_feed_plane(self, z_target: float) -> None:
        """Rapid (G0) down to the feed plane before a plunge, so only the cut portion
        is fed (BUILDPLAN M8). No-op when no feed plane is set or it's already at/below
        the target — the plunge then feeds the whole way (original behavior). The feed
        plane is above the stock, so this never rapids into material."""
        fp = self.feed_plane_mm
        if fp is not None and fp > z_target + 1e-6:
            self.rapid(z=fp)

    def initial_tool_load(self, number: int) -> None:
        """Emit the program's first tool change so a controller with a tool-length
        probe (Carbide Motion + BitSetter / Nomad) loads and measures the tool before
        cutting — the spindle is still off here, so it probes safely (BUILDPLAN M8)."""
        self._lines.append(f"M6 T{number}")
        self._last_z = None           # the probe/macro re-establishes Z

    def program_pause(self, message: str = "Flip stock and re-register on dowel pins") -> None:
        self._lines.append(f"; {message}")
        self._lines.append("M0")
        self._last_z = None           # operator may have jogged Z during the pause

    def apply_tool(self, ts: "ToolSetting") -> None:
        """Adopt a tool's geometry/feeds as the current output context, without
        emitting a change block (used for the program's first tool). Announces it
        with a parseable comment so the sim / cut-time model can attribute moves."""
        self.tool_diameter_mm = ts.diameter_mm
        self.feed_rate_mmpm = ts.feed_rate_mmpm
        self.plunge_rate_mmpm = ts.plunge_rate_mmpm
        self.spindle_rpm = ts.spindle_rpm
        self.comment(f"--- Tool T{ts.number}: {ts.name} ({ts.diameter_mm:.2f} mm) ---")

    def tool_change(self, ts: "ToolSetting", mode: str = "m0",
                    message: str | None = None) -> None:
        """Emit a tool-change block, then adopt the new tool (BUILDPLAN M6.1).

        Spindle stop, retract to safe Z, then either an automatic ``M6 Tn``
        (mode "m6") or a manual-change ``M0`` pause with an operator prompt
        (mode "m0"); the operator re-establishes tool length / re-zeroes Z per
        the machine's policy, and the spindle restarts at the new tool's RPM.
        """
        self.comment(f"--- Tool Change -> T{ts.number}: {ts.name} ({ts.diameter_mm:.2f} mm) ---")
        self.spindle_off()
        self._last_xy = None          # new tool: next pass takes a full safe-Z retract
        self.safe_retract()
        if mode == "m6":
            self._lines.append(f"M6 T{ts.number}")
        else:
            self.comment(message or (f"Load tool T{ts.number}: {ts.name} "
                                     f"({ts.diameter_mm:.2f} mm), set tool length, then resume"))
            self._lines.append("M0")
        self._last_z = None           # M6 macro / probe / manual re-zero re-establishes Z
        self.comment("Re-zero Z to the tool tip per machine tool-length policy")
        self.tool_diameter_mm = ts.diameter_mm
        self.feed_rate_mmpm = ts.feed_rate_mmpm
        self.plunge_rate_mmpm = ts.plunge_rate_mmpm
        self.spindle_rpm = ts.spindle_rpm
        self.spindle_on()

    def end_program(self) -> None:
        self._lines += ["M5", f"G0 Z{self.safe_z_mm + self.work_offset[2]:.3f}", "M30"]

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
        to ramping the whole lap, i.e. the original two-lap behavior.
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

        # rapid down to the feed plane (above stock), then a controlled feed to the
        # ramp-start height — never a rapid below the stock top
        self._rapid_to_feed_plane(z_top)
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
        return (pr[0], pr[1])      # the tool ends here, not at pts[-1] (pass linking)

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
        self._link_retract(x0, y0)           # links from the PREVIOUS pass's real end
        self.rapid(x=x0, y=y0)

        closed = (len(pts) >= 4
                  and abs(pts[0][0] - pts[-1][0]) < 1e-6
                  and abs(pts[0][1] - pts[-1][1]) < 1e-6)
        const_z = (max(p[2] for p in pts) - min(p[2] for p in pts)) < 1e-6
        if ramp_height > 0 and closed and const_z:
            # The ramped lap ends at the ramp-end point, not pts[-1] — record where the
            # tool actually is so the next pass's link retract checks the right segment.
            self._last_xy = self._emit_ramped_loop(pts, ramp_height, ramp_angle_deg, arc_tol)
            return

        if first_move_is_plunge:
            self._rapid_to_feed_plane(z0)    # rapid the air, feed only the cut (M8)
            self.plunge(z0)
        else:
            self.feed(x=x0, y=y0, z=z0)
        self._emit_moves(pts, arc_tol)
        self._last_xy = (pts[-1][0], pts[-1][1])    # next pass links from this pass's end

    def to_string(self) -> str:
        return "\n".join(self._lines) + "\n"

    def write(self, path: Path) -> None:
        path.write_text(self.to_string(), encoding="utf-8")
