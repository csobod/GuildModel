"""Z-profile guard: measure a posted program's vertical behaviour, per operation.

**Why this exists.** Corner Optical caught the Fine Relief sawtooth by reading a
Mach3 toolpath display and writing their own analyzer, because nothing in this
pipeline measures its own output. The investigation that followed then went
wrong three times, and every wrong turn had the same shape: a number nobody had
looked at. `INCIDENT-2026-07-29` (a bed program built at preview resolution,
E-stopped on real hardware) is the same failure a year earlier.

So this module is deliberately dumb and total. It measures **every operation**,
not the one under suspicion — the Hyde Park sawtooth hid for four releases in
the `Features` op while the investigation stared at `Fine Relief`.

**What a reversal is.** Two consecutive cutting moves, both with real XY travel,
whose Z direction flips. Rapids and plunges break a run and are excluded along
with the transitions across them — a retract to clearance is ordinary machine
motion; a direction reversal *under load at feed* is what beats the Z axis up.
This is Corner Optical's definition, kept deliberately, so their numbers and
ours stay directly comparable.

**Amplitude matters more than count.** Our clean fixtures reverse Z about once
per 100 mm at a median amplitude of 0.024 mm — noise on the last digit, and a
raw per-100 mm figure weights it the same as a 4 mm plunge. `per100` therefore
counts only reversals above `AMPLITUDE_FLOOR_MM`, and `max_amplitude_mm` is
reported separately because one bad move is enough to matter.

**Why there is no flat-topped-excursion metric, on purpose** *(calibrated and
rejected, 2026-08-15)*. The reversal definition needs the two flanks to be
consecutive, so a climb-flat-descend "bump" — the exact shape of riding up onto
uncut stock and across it — moves no severity axis at all; a 0.907 mm connector
ride measured precisely zero here. The obvious fix, scoring interior peaks by
min(rise, fall), was built as a probe and calibrated against every program we
have, and it cannot work: clean, correct programs carry legitimate 5.75 mm
bumps, because contour rings genuinely climb zone ramps (bridge, endpiece) and
come back down, while the worst genuine abuse topped out at 4.94 — the metric
does not order abuse above health. What made the abusive bumps abusive was that
the ground under them was MASKED, i.e. there was nothing to cut — knowledge
only the emitter has. So that class is policed at emission, where the mask is
known (`relief_link_max_rise_mm`, on both the gap links and the stitch
connectors), and this module measures the dynamics that need no such context.
Do not re-derive the bump metric without new evidence; the probe's numbers are
in FINE-RELIEF-SAWTOOTH.md.
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field

#: A reversal smaller than this is measurement noise, not machine abuse. Our
#: three shipped fixtures sit at a 0.024 mm median across every operation.
AMPLITUDE_FLOOR_MM = 0.1

#: Moves steeper than this are near-plunges taken at cutting feed. Corner
#: Optical reported this share and it is the single most diagnostic number in
#: their report: 6% on the frame they refused to run, 0% on every clean fixture.
STEEP_DEG = 71.0

_NUM = re.compile(r"([XYZF])(-?\d*\.?\d+)")
_OP = re.compile(r";\s*---\s*(.+?)\s*---")
_EPS = 1e-6


@dataclass
class Limits:
    """Thresholds for `severity()` / `warnings()`.

    Calibrated against every program we have rather than picked round:

    ===========================  =======  =======  =====  ========
    program                      per100   max mm   steep  verdict
    ===========================  =======  =======  =====  ========
    demo / gabriel / aviator     <= 0.9    0.50     1%    ok
    Hyde Park v1.1.0 (refused)     13.4    1.62     6%    error
    Hyde Park pre-fix Features     37.3    3.88    13%    error
    Hyde Park post-fix Features     5.7    4.33     2%    error
    ===========================  =======  =======  =====  ========

    `fail_per100` is 10 and not 15 so that the program Corner Optical refused to
    run scores the way its maker scored it. There is two orders of margin below
    that to the shipped fixtures, so this is not a tight fit to one sample.

    The post-fix row is `error` on amplitude alone, and correctly: the feature
    rings still cross the nosepad tower wall. The guard is not supposed to go
    quiet because the density improved.
    """
    warn_per100: float = 5.0
    warn_max_mm: float = 1.0
    warn_steep_frac: float = 0.05
    fail_per100: float = 10.0
    fail_max_mm: float = 3.0
    fail_steep_frac: float = 0.10


@dataclass
class OpProfile:
    """One operation's Z behaviour."""
    name: str
    moves: int = 0
    xy_mm: float = 0.0
    z_travel_mm: float = 0.0
    reversals: int = 0              # every flip, including noise
    significant: int = 0            # flips above AMPLITUDE_FLOOR_MM
    median_amplitude_mm: float = 0.0
    p90_amplitude_mm: float = 0.0
    max_amplitude_mm: float = 0.0
    steep_moves: int = 0
    amplitudes: list = field(default_factory=list, repr=False)

    @property
    def per100(self) -> float:
        """Significant reversals per 100 mm of cutting XY travel."""
        return (self.significant / self.xy_mm * 100.0) if self.xy_mm else 0.0

    @property
    def steep_fraction(self) -> float:
        return (self.steep_moves / self.moves) if self.moves else 0.0

    def severity(self, limits: "Limits | None" = None) -> str:
        """"ok" | "warning" | "error" against `limits`."""
        lim = limits or Limits()
        if (self.per100 > lim.fail_per100 or self.max_amplitude_mm > lim.fail_max_mm
                or self.steep_fraction > lim.fail_steep_frac):
            return "error"
        if (self.per100 > lim.warn_per100 or self.max_amplitude_mm > lim.warn_max_mm
                or self.steep_fraction > lim.warn_steep_frac):
            return "warning"
        return "ok"

    def message(self) -> str:
        return (f"{self.name}: {self.significant} Z reversals over "
                f"{AMPLITUDE_FLOOR_MM} mm ({self.per100:.1f} per 100 mm), "
                f"worst {self.max_amplitude_mm:.2f} mm, "
                f"{100 * self.steep_fraction:.0f}% of moves over {STEEP_DEG:.0f}°")

    def comment(self) -> str:
        """One `.nc` header line, so a program carries its own provenance."""
        return (f"{self.name}: {self.significant} rev>{AMPLITUDE_FLOOR_MM}mm, "
                f"{self.per100:.1f}/100mm, max {self.max_amplitude_mm:.2f}mm, "
                f"Z {self.z_travel_mm:.0f}mm, "
                f"{100 * self.steep_fraction:.0f}% >{STEEP_DEG:.0f}deg")


def _finish(p: OpProfile) -> OpProfile:
    a = sorted(p.amplitudes)
    if a:
        p.median_amplitude_mm = statistics.median(a)
        p.p90_amplitude_mm = a[min(len(a) - 1, int(len(a) * 0.9))]
        p.max_amplitude_mm = a[-1]
    return p


def measure_runs(runs, name: str = "") -> OpProfile:
    """Profile a list of cutting polylines — each an iterable of (x, y, z).

    Every polyline is one continuous cutting run: callers split on rapids and
    plunges, which is what `measure_paths` and `measure_program` do.
    """
    p = OpProfile(name=name)
    for run in runs:
        pts = list(run)
        prev_dz = 0.0
        for (x0, y0, z0), (x1, y1, z1) in zip(pts, pts[1:]):
            d = math.hypot(x1 - x0, y1 - y0)
            if d <= _EPS:
                prev_dz = 0.0            # a pure plunge breaks the run
                continue
            dz = z1 - z0
            p.moves += 1
            p.xy_mm += d
            p.z_travel_mm += abs(dz)
            if math.degrees(math.atan2(abs(dz), d)) > STEEP_DEG:
                p.steep_moves += 1
            if dz and prev_dz and (dz > 0) != (prev_dz > 0):
                p.reversals += 1
                p.amplitudes.append(abs(dz))
                if abs(dz) >= AMPLITUDE_FLOOR_MM:
                    p.significant += 1
            prev_dz = dz
    return _finish(p)


def measure_paths(op) -> OpProfile:
    """Profile a `CamOp` before it is posted — cheap, structured, post-agnostic.

    A `CamOp` path is already one continuous cutting run, so no splitting is
    needed; the post's rapids sit *between* paths.
    """
    return measure_runs(op.paths, getattr(op, "name", ""))


def measure_program(text: str) -> dict[str, OpProfile]:
    """Profile a posted program, per `; --- Name ---` section.

    Works on any program this app posts, including one a maker emails back — the
    case this whole module was written for. Sections with no cutting moves (tool
    changes, headers) come back with zeroed profiles and are dropped.
    """
    out: dict[str, OpProfile] = {}
    cur = None
    runs: list[list] = []
    run: list = []
    x = y = z = 0.0

    def flush():
        if cur is None:
            return
        if len(run) > 1:
            runs.append(list(run))
        prof = measure_runs(runs, cur)
        if prof.moves:
            out[cur] = prof

    for line in text.splitlines():
        m = _OP.match(line.strip())
        if m:
            flush()
            cur, runs, run = m.group(1), [], []
            continue
        code = line.split(";")[0].strip()
        g = re.match(r"G(0|1|2|3)\b", code)
        if not g:
            continue
        v = dict(_NUM.findall(code))
        nx, ny = float(v.get("X", x)), float(v.get("Y", y))
        nz = float(v.get("Z", z))
        rapid = g.group(1) == "0"
        if rapid or math.hypot(nx - x, ny - y) <= _EPS:
            if len(run) > 1:
                runs.append(list(run))
            run = []
        else:
            if not run:
                run = [(x, y, z)]
            run.append((nx, ny, nz))
        x, y, z = nx, ny, nz
    flush()
    return out


def warnings(profiles, limits: "Limits | None" = None) -> list[str]:
    """Actionable strings for the inspector, worst first — `lint_program`'s shape.

    `profiles` is either the dict from `measure_program` or an iterable of
    `OpProfile`. A clean program yields `[]`.
    """
    lim = limits or Limits()
    items = (profiles.values() if isinstance(profiles, dict) else list(profiles))
    flagged = [p for p in items if p.severity(lim) != "ok"]
    flagged.sort(key=lambda p: (p.severity(lim) != "error", -p.max_amplitude_mm))
    return [p.message() for p in flagged]


def header_lines(profiles) -> list[str]:
    """`.nc` comment lines recording what was measured, for the program header.

    A posted program that carries its own Z profile is one a maker can quote a
    number from instead of describing what a toolpath display looked like.
    """
    items = (profiles.values() if isinstance(profiles, dict) else list(profiles))
    lines = [f"; Z profile (reversal = Z flips between two cutting moves; "
             f"floor {AMPLITUDE_FLOOR_MM} mm)"]
    lines += [f";   {p.comment()}" for p in items if p.moves]
    return lines


def annotate(text: str, profiles=None) -> str:
    """Return `text` with its Z profile inserted after the leading comment block."""
    profiles = measure_program(text) if profiles is None else profiles
    lines = text.splitlines()
    i = 0
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith(";")):
        i += 1
    return "\n".join(lines[:i] + header_lines(profiles) + lines[i:]) + "\n"
