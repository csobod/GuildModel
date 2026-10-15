"""A posted program as the stock engine reads it (BUILDPLAN M21 §6.2).

One parser where `core.sim.paths` grew two: `cutting_paths_from_program_grouped`
(the cuts, tagged by tool) and `motion_runs_from_program` (cuts and rapids,
tagged by op and tool). Both are views of the same walk through the program,
and keeping them apart is how the simulation came to parse a file twice and
disagree with itself about where a path began. `parse_program` walks it once
into `Run`s — a maximal stretch of same-class motion under one op and tool,
with the feed in force and the A word where a controller has one (M26) — and
everything else here is a view of those runs.

The simulation simulates the posted program (§6.5): the poses the kernel
cuts with are made from these runs, at a spacing chosen from the tool and
the grid, never from the ops the program was posted from.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

from .cutting import vertical_poses
from .tools import ToolShape

__all__ = ["Run", "cutting_paths", "machine_seconds", "parse_program", "poses_for_run",
           "spacing_for"]

Point3 = tuple[float, float, float]

_WORD = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")
# The post's tool announcements: "--- Tool T1: flat_2mm (2.00 mm) ---" and
# "--- Tool Change → T2: flat_3175 (3.18 mm) ---" (BUILDPLAN M6.1).
_TOOL_COMMENT = re.compile(r"Tool(?:\s*Change)?[^A-Za-z0-9]*T\d+:\s*(\S+)")
# The post's op sections: "--- Hinge Pockets ---".
_OP_COMMENT = re.compile(r"-{2,}\s*(.+?)\s*-{2,}")

#: Chord sag an arc is flattened to, mm, as the simulation has always done.
CHORD_MM = 0.3


@dataclass
class Run:
    """A stretch of same-class motion under one op and tool."""
    label: str                   # the op's section comment, "" before the first
    tool: str | None             # the tool announced, None before the first
    is_cut: bool                 # feed motion (G1/G2/G3) against a rapid (G0)
    feed_mmpm: float             # the F word in force, 0 when none has been given
    points: list = field(default_factory=list)   # (x, y, z, a): the path, a in degrees

    def xyz(self) -> np.ndarray:
        return np.asarray(self.points, dtype=np.float64)[:, :3]

    def length_mm(self) -> float:
        p = self.xyz()
        return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum()) if len(p) > 1 else 0.0


def _flatten_arc(cur, end, i, j, ccw, chord_mm):
    cx, cy = cur[0] + i, cur[1] + j
    R = math.hypot(i, j)
    a0 = math.atan2(cur[1] - cy, cur[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    sweep = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
    if abs(sweep) < 1e-9:
        sweep = 2 * math.pi if ccw else -2 * math.pi
    steps = max(1, int(abs(sweep) * R / max(chord_mm, 1e-3)))
    pts = []
    for k in range(1, steps + 1):
        a = a0 + sweep * (k / steps)
        z = cur[2] + (end[2] - cur[2]) * (k / steps)
        pts.append((cx + R * math.cos(a), cy + R * math.sin(a), z, end[3]))
    return pts


def parse_program(gcode: str, chord_mm: float = CHORD_MM) -> list[Run]:
    """Walk a GRBL-dialect program once into runs: modal G0/G1/G2/G3, G20/G21,
    G90/G91, X Y Z I J, the A word, the F word, G28/G30 as a break. Comments
    carry the op sections and the tool announcements. A run starts at the
    position the tool was at, so the motion is continuous, and a one-point
    run (a program's first move) is kept so a rapid from the start is seen."""
    x = y = z = a = 0.0
    motion = 0
    incremental = False
    scale = 1.0
    feed = 0.0
    tool: str | None = None
    label = ""
    runs: list[Run] = []
    cur: Run | None = None

    def flush():
        nonlocal cur
        if cur is not None and len(cur.points) >= 2:
            runs.append(cur)
        cur = None

    for raw in gcode.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith((";", "(")):
            body = s.lstrip(";(").strip()
            mt = _TOOL_COMMENT.search(body)
            if mt:
                tool = mt.group(1)
            else:
                mo = _OP_COMMENT.match(body)
                if mo and not mo.group(1).startswith("Tool"):
                    label = mo.group(1)
            continue
        for c in (";", "("):
            if c in s:
                s = s.split(c, 1)[0].strip()
        if not s:
            continue
        words = _WORD.findall(s)
        if not words:
            continue
        if any(w[0].upper() == "G" and w[1] in ("28", "30") for w in words):
            flush()
            continue
        for letter, num in words:
            L = letter.upper()
            if L == "G":
                g = int(round(float(num)))
                if g in (0, 1, 2, 3):
                    motion = g
                elif g == 20:
                    scale = 25.4
                elif g == 21:
                    scale = 1.0
                elif g == 90:
                    incremental = False
                elif g == 91:
                    incremental = True
            elif L == "F":
                feed = float(num) * scale
        d = {w[0].upper(): float(w[1]) * scale for w in words if w[0].upper() in "XYZIJ"}
        if "A" in {w[0].upper() for w in words}:
            d["A"] = float(next(w[1] for w in words if w[0].upper() == "A"))
        if not any(k in d for k in "XYZA"):
            continue
        nx = (x + d["X"]) if ("X" in d and incremental) else d.get("X", x)
        ny = (y + d["Y"]) if ("Y" in d and incremental) else d.get("Y", y)
        nz = (z + d["Z"]) if ("Z" in d and incremental) else d.get("Z", z)
        na = (a + d["A"]) if ("A" in d and incremental) else d.get("A", a)
        is_cut = motion in (1, 2, 3)
        if (cur is None or cur.is_cut != is_cut or cur.label != label
                or cur.tool != tool or (is_cut and abs(cur.feed_mmpm - feed) > 1e-9)):
            flush()
            cur = Run(label, tool, is_cut, feed if is_cut else 0.0, [(x, y, z, a)])
        if motion in (2, 3) and ("I" in d or "J" in d):
            cur.points += _flatten_arc((x, y, z, a), (nx, ny, nz, na), d.get("I", 0.0),
                                       d.get("J", 0.0), ccw=(motion == 3), chord_mm=chord_mm)
        else:
            cur.points.append((nx, ny, nz, na))
        x, y, z, a = nx, ny, nz, na
    flush()
    return runs


def cutting_paths(runs: list[Run]) -> list[tuple[list[Point3], str | None]]:
    """The cutting runs as ``(points, tool)`` pairs — what
    `sim.paths.cutting_paths_from_program_grouped` returns, from one walk.
    Consecutive cutting runs under one tool are one path there, whatever the
    op or feed, so they are joined here the same way."""
    out: list[tuple[list[Point3], str | None]] = []
    for run in runs:
        if not run.is_cut:
            continue
        pts = [(float(p[0]), float(p[1]), float(p[2])) for p in run.points]
        if out and out[-1][1] == run.tool and out[-1][0][-1] == pts[0]:
            out[-1] = (out[-1][0] + pts[1:], run.tool)
        else:
            out.append((pts, run.tool))
    return out


def spacing_for(shape: ToolShape, resolution: float) -> float:
    """How far apart the poses along a cut are placed: the grid step, and
    finer for a tool whose radius is under it, so no cell between two poses
    of a small tool goes uncut."""
    return float(min(resolution, max(shape.radius_mm * 0.5, resolution * 0.25)))


def poses_for_run(run: Run, spacing: float) -> np.ndarray:
    """Vertical poses along a run, `spacing` apart by XY arc length, with the
    run's own points kept — `sim.toolsim.densify`'s placement, so a stock cut
    from a run lands where the floor was stamped. The A word rides along in
    the pose for M26; in 1.9.0 every pose is vertical."""
    pts = run.xyz()
    if len(pts) < 2:
        return vertical_poses(pts)
    a, b = pts[:-1], pts[1:]
    d = np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])
    n = np.maximum(1, (d / spacing).astype(np.int64))
    seg = np.repeat(np.arange(len(a)), n)
    k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n) + 1
    frac = k / n[seg]
    return vertical_poses(np.vstack([pts[:1], a[seg] + (b[seg] - a[seg]) * frac[:, None]]))


def machine_seconds(run: Run, rapid_mmpm: float, feed_mmpm: float) -> float:
    """How long the machine spends on a run: its length at its feed, or the
    rapid rate for a rapid; `feed_mmpm` stands in where the program gave none.
    What weights the playback so time on screen tracks time on the machine."""
    rate = rapid_mmpm if not run.is_cut else (run.feed_mmpm or feed_mmpm)
    return run.length_mm() / max(rate, 1e-9) * 60.0
