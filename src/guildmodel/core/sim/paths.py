"""Extract cutting polylines for the simulator (BUILDPLAN M5).

Two sources:
  * a posted GRBL program (ours or an external control like Fusion) — modal
    parse, arcs flattened to chords, rapids dropped;
  * in-memory CamOps — the toolpaths straight from generation.

Both return ``list[list[(x, y, z)]]`` of cutting moves only.
"""
from __future__ import annotations

import math
import re

Point3 = tuple[float, float, float]

_WORD = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")


def _flatten_arc(cur, end, i, j, ccw, chord_mm=0.3):
    cx, cy = cur[0] + i, cur[1] + j
    R = math.hypot(i, j)
    a0 = math.atan2(cur[1] - cy, cur[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    if ccw:
        sweep = (a1 - a0) % (2 * math.pi)
    else:
        sweep = -((a0 - a1) % (2 * math.pi))
    if abs(sweep) < 1e-9:
        sweep = (2 * math.pi if ccw else -2 * math.pi)
    steps = max(1, int(abs(sweep) * R / max(chord_mm, 1e-3)))
    pts = []
    for k in range(1, steps + 1):
        a = a0 + sweep * (k / steps)
        z = cur[2] + (end[2] - cur[2]) * (k / steps)
        pts.append((cx + R * math.cos(a), cy + R * math.sin(a), z))
    return pts


# Tool announce comments the post emits: "--- Tool T1: flat_2mm (2.00 mm) ---"
# and "--- Tool Change → T2: flat_3175 (3.18 mm) ---" (BUILDPLAN M6.1).
_TOOL_COMMENT = re.compile(r"Tool(?:\s*Change)?[^A-Za-z0-9]*T\d+:\s*(\S+)")


def cutting_paths_from_program_grouped(
    gcode: str, chord_mm: float = 0.3,
) -> list[tuple[list[Point3], str | None]]:
    """Like ``cutting_paths_from_program`` but tag each cutting polyline with the
    active tool name, tracked from the post's tool-announce comments. Paths
    before any announcement (e.g. an external control) get ``None``."""
    x = y = z = 0.0
    motion = 0
    incremental = False
    scale = 1.0
    tool: str | None = None
    out: list[tuple[list[Point3], str | None]] = []
    cur: list[Point3] = []
    cur_tool: str | None = None

    def _flush():
        nonlocal cur, cur_tool
        if len(cur) >= 1:
            out.append((cur, cur_tool))
        cur = []

    for raw in gcode.splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith((";", "(")):
            m = _TOOL_COMMENT.search(s)
            if m:
                tool = m.group(1)
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
            _flush()
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
        d = {w[0].upper(): float(w[1]) * scale for w in words if w[0].upper() in "XYZIJ"}
        nx = (x + d["X"]) if ("X" in d and incremental) else d.get("X", x)
        ny = (y + d["Y"]) if ("Y" in d and incremental) else d.get("Y", y)
        nz = (z + d["Z"]) if ("Z" in d and incremental) else d.get("Z", z)
        if not (("X" in d) or ("Y" in d) or ("Z" in d)):
            continue
        if motion == 0:
            _flush()
        elif motion in (2, 3) and ("I" in d or "J" in d):
            if not cur:
                cur = [(x, y, z)]
                cur_tool = tool
            cur += _flatten_arc((x, y, z), (nx, ny, nz),
                                d.get("I", 0.0), d.get("J", 0.0),
                                ccw=(motion == 3), chord_mm=chord_mm)
        else:
            if not cur:
                cur = [(x, y, z)]
                cur_tool = tool
            cur.append((nx, ny, nz))
        x, y, z = nx, ny, nz
    _flush()
    return [(p, t) for p, t in out if len(p) >= 1]


def cutting_paths_from_program(gcode: str, chord_mm: float = 0.3) -> list[list[Point3]]:
    """Modal-parse a GRBL program into cutting polylines (G1/G2/G3); arcs
    flattened to chords; rapids (G0) split the polylines."""
    x = y = z = 0.0
    motion = 0
    incremental = False
    scale = 1.0
    paths: list[list[Point3]] = []
    cur: list[Point3] = []

    def _flush():
        nonlocal cur
        if len(cur) >= 1:
            paths.append(cur)
        cur = []

    for raw in gcode.splitlines():
        s = raw.strip()
        if not s or s.startswith((";", "(")):
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
            _flush()
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
        d = {w[0].upper(): float(w[1]) * scale for w in words if w[0].upper() in "XYZIJ"}
        nx = (x + d["X"]) if ("X" in d and incremental) else d.get("X", x)
        ny = (y + d["Y"]) if ("Y" in d and incremental) else d.get("Y", y)
        nz = (z + d["Z"]) if ("Z" in d and incremental) else d.get("Z", z)
        if not (("X" in d) or ("Y" in d) or ("Z" in d)):
            continue
        if motion == 0:
            _flush()                       # rapid breaks the cutting polyline
        elif motion in (2, 3) and ("I" in d or "J" in d):
            if not cur:
                cur = [(x, y, z)]
            cur += _flatten_arc((x, y, z), (nx, ny, nz),
                                d.get("I", 0.0), d.get("J", 0.0),
                                ccw=(motion == 3), chord_mm=chord_mm)
        else:                              # G1 feed
            if not cur:
                cur = [(x, y, z)]
            cur.append((nx, ny, nz))
        x, y, z = nx, ny, nz
    _flush()
    return [p for p in paths if len(p) >= 1]


_OP_COMMENT = re.compile(r"-{2,}\s*(.+?)\s*-{2,}")


def motion_runs_from_program(
    gcode: str, chord_mm: float = 0.3,
) -> list[tuple[str, str | None, list[Point3], bool]]:
    """Parse the FULL posted motion — cuts AND rapids — into ordered runs for the
    playback (BUILDPLAN M8 Part B). Each run is ``(op_label, tool_name, polyline,
    is_cut)``: a maximal stretch of same-class motion (rapid G0 vs feed G1/2/3) under
    one op/tool. Rapids are kept (so the playback animates the retract / traverse /
    descend) and flagged ``is_cut=False`` so the simulator removes no material along
    them. Arcs are flattened; a run starts at the tool's current position so the
    motion is continuous."""
    x = y = z = 0.0
    motion = 0
    incremental = False
    scale = 1.0
    tool: str | None = None
    label = ""
    runs: list = []
    cur: list[Point3] = []
    cur_key = None                      # (is_cut, label, tool)

    def _flush():
        nonlocal cur, cur_key
        if len(cur) >= 2 and cur_key is not None:
            runs.append((cur_key[1], cur_key[2], cur, cur_key[0]))
        cur = []
        cur_key = None

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
            _flush()
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
        d = {w[0].upper(): float(w[1]) * scale for w in words if w[0].upper() in "XYZIJ"}
        if not (("X" in d) or ("Y" in d) or ("Z" in d)):
            continue
        nx = (x + d["X"]) if ("X" in d and incremental) else d.get("X", x)
        ny = (y + d["Y"]) if ("Y" in d and incremental) else d.get("Y", y)
        nz = (z + d["Z"]) if ("Z" in d and incremental) else d.get("Z", z)
        is_cut = motion in (1, 2, 3)
        key = (is_cut, label, tool)
        if key != cur_key:
            _flush()
            cur = [(x, y, z)]
            cur_key = key
        if motion in (2, 3) and ("I" in d or "J" in d):
            cur += _flatten_arc((x, y, z), (nx, ny, nz),
                                d.get("I", 0.0), d.get("J", 0.0),
                                ccw=(motion == 3), chord_mm=chord_mm)
        else:
            cur.append((nx, ny, nz))
        x, y, z = nx, ny, nz
    _flush()
    return runs


def cutting_paths_from_ops(ops, names=None) -> list[list[Point3]]:
    """Cutting polylines straight from CamOps (optionally a subset by op name)."""
    out: list[list[Point3]] = []
    for op in ops:
        if names is not None and op.name not in names:
            continue
        for path in op.paths:
            out.append([(float(p[0]), float(p[1]), float(p[2])) for p in path])
    return out
