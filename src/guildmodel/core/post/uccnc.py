"""UCCNC G-code post-processor (2.3.1): the controller STEPCRAFT machines run.

A dialect of the GRBL post, not a second emitter: the motion — the rapids and
feeds, the arcs, the ramped lead-ins, the drills, the pass linking — is
`GRBLPost`'s word for word, and what changes is what the controller reads
around it. Modeled on Autodesk's certified "STEPCRAFT UCCNC" post
(`stepcraft uccnc.cps`, revision 44229, with its tool changer on), which the
makers who run these machines post from today:

- comments in parentheses, ASCII, never nested;
- G64 (constant velocity) modal, and the work offset always named;
- every retract that leaves the work, before a tool change and at the end, to
  the top of Z travel in machine coordinates, ``G90 G53 G0 Z0``;
- a tool changer's ``T<n> M6``, then the length offset ``G43 H<n>``; the
  number is the pocket the changer fetches, so a tool without its own number
  is refused rather than numbered by machining order;
- ``S M3``, and a spin-up dwell in milliseconds (``G4 P`` is ms on UCCNC);
- arcs in the XY plane, I/J incremental, none sweeping more than 90 degrees.

M27 (BUILDPLAN §12) replaces this with a record stream and a profile-driven
emitter; this module is the first dialect that emitter has to reproduce.
"""
from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from .grbl import GRBLPost, PostError, ToolSetting

#: The longest comment text on one line: the certified post keeps lines to 80.
COMMENT_WIDTH = 76

#: The widest sweep one arc block carries (the certified post's own limit),
#: and the radii outside which an arc goes out as a straight feed.
MAX_SWEEP_DEG = 90.0
MIN_ARC_RADIUS_MM = 0.01
MAX_ARC_RADIUS_MM = 1000.0

# The symbols GuildModel writes, spelled in ASCII; a comment's own delimiters
# become brackets and commas.
_SPELLED = {"·": "-", "→": "->", "—": "-", "–": "-", "×": "x", "°": " deg",
            "▸": ">", "≥": ">=", "≤": "<=", "±": "+/-", "Ø": "D", "ø": "D",
            "µ": "u", "(": "[", ")": "]", ";": ","}


def program_label(text: str) -> str:
    """`text` as a UCCNC comment carries it: printable ASCII, single-spaced,
    no parentheses or semicolons. The simulations read op labels back out of
    the program's comments, so a lookup keyed by an op's own name keys it
    through here too (`BedSimWorker`)."""
    out: list[str] = []
    for ch in str(text):
        if ch in _SPELLED:
            out.append(_SPELLED[ch])
        elif " " <= ch <= "~":
            out.append(ch)
        else:
            folded = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append("".join(c for c in folded if " " <= c <= "~" and c not in "();"))
    return " ".join("".join(out).split())


def _and(names: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def comment_lines(text: str) -> list[str]:
    """`text` as parenthesized comment lines, wrapped at `COMMENT_WIDTH`."""
    lines: list[str] = []
    for raw in str(text).splitlines():
        body = program_label(raw)
        if body.startswith("---"):
            # a section marker stays whole, however long: the simulations and
            # the Z profile read the op and the tool off its one line
            lines.append(f"({body})")
            continue
        while len(body) > COMMENT_WIDTH:
            cut = body.rfind(" ", 0, COMMENT_WIDTH)
            cut = cut if cut > 0 else COMMENT_WIDTH
            lines.append(f"({body[:cut].rstrip()})")
            body = body[cut:].lstrip()
        if body:
            lines.append(f"({body})")
    return lines


@dataclass
class UCCNCPost(GRBLPost):
    """`GRBLPost` with UCCNC's words around the motion (see the module)."""

    comment_char: str = "("
    #: The tool currently loaded, for the pocket check before each ``M6``.
    _tool: ToolSetting | None = field(default=None, init=False, repr=False)

    #: Every program names its tool, single-tool ones too: a tool changer needs
    #: the pocket even when there is nothing to change to.
    names_every_tool = True

    # ------------------------------------------------------------- words

    def comment(self, text: str) -> None:
        self._lines += comment_lines(text)

    def _modal_block(self) -> list[str]:
        """What a macro may have left otherwise, named again after it."""
        return ["G90", "G64", self.wcs or "G54"]

    def _retract_top(self) -> None:
        """To the top of Z travel in machine coordinates (needs a homed machine,
        as the certified post does)."""
        self._lines.append("G90 G53 G0 Z0")
        self._last_z = None
        self._last_xy = None

    def header(self, side: str, timestamp: datetime | None = None,
               initial_retract: bool = True) -> None:
        ts = (timestamp or datetime.now()).strftime("%Y-%m-%d %H:%M")
        for text in (f"GuildModel - {self.job_name}", f"Side: {side}",
                     f"Material: {self.material}",
                     f"Tool: {self.tool_diameter_mm:.2f} mm diameter",
                     f"Spindle: {self.spindle_rpm} RPM",
                     f"Feed: {self.feed_rate_mmpm:.0f} mm/min  "
                     f"Plunge: {self.plunge_rate_mmpm:.0f} mm/min",
                     f"Generated: {ts}", "Post: UCCNC (STEPCRAFT)"):
            self.comment(text)
        self._lines += ["", "G90", "G21" if self.units == "mm" else "G20", "G17", "G64"]
        if self.index_a_deg is not None:
            self.rotary_index(self.index_a_deg)
        self._lines.append(self.wcs or "G54")
        self._lines += list(self.preamble)
        # every program starts from the top of Z travel, whatever the tool was
        # left at; the first pass then comes down to its safe height
        self._retract_top()

    def spindle_on(self, *, starting: bool = True) -> None:
        self._lines.append(f"S{self.spindle_rpm} M3")
        if starting and self.spindle_spinup_s > 0:
            self._lines.append(f"G4 P{int(round(self.spindle_spinup_s * 1000))}")

    def program_pause(self, message: str = "Flip stock and re-register on dowel pins") -> None:
        self.comment(message)
        self._lines.append("M0")
        self._last_z = None
        self._last_xy = None

    def probe_z_block(self, *a, **k) -> list[str]:
        raise PostError(
            "Re-probe Z after the flip writes G38.2 and G10 L20, which the UCCNC post "
            "does not carry yet: turn the re-probe off and re-zero Z at the flip's pause")

    # ------------------------------------------------------------- tools

    def _check_tool(self, ts: ToolSetting) -> None:
        """A tool the program can name: the simulations find the tool by the
        name its comment carries, and a changer fetches the pocket its number
        names."""
        if program_label(ts.name) != ts.name:
            raise PostError(
                f"the tool {ts.name!r} has a character a UCCNC comment cannot carry: "
                "rename it in Preferences ▸ Tools")

    def check_tools(self, tool_settings: dict | None, mode: str) -> None:
        """Every tool the changer will fetch, checked before a word is written,
        and every one without its own pocket named at once: one at a time, a
        maker fixed a tool and met the next."""
        if mode != "m6" or not tool_settings:
            return
        missing = [ts.name for ts in tool_settings.values() if not ts.numbered]
        if missing:
            raise PostError(
                "on a tool changer each tool is fetched by its pocket number, and "
                f"{_and(missing)} "
                f"{'has none of its own' if len(missing) == 1 else 'have none of their own'} "
                "(0, auto, or a number another tool already has). Set each one's "
                "pocket as its Tool number in Preferences ▸ Tools")

    def _load_tool(self, number: int) -> None:
        ts = self._tool
        if ts is None or ts.number != number or not ts.numbered:
            name = ts.name if ts is not None else "the program's tool"
            raise PostError(
                f"{name} has no tool number of its own, or shares it with another "
                f"tool: the tool changer fetches the pocket T{number} names. Set its "
                "pocket as its Tool number in Preferences ▸ Tools")
        self._lines += [f"T{number} M6", f"G43 H{number}", *self._modal_block()]
        self._last_z = None
        self._last_xy = None

    def apply_tool(self, ts: ToolSetting) -> None:
        self._check_tool(ts)
        self._tool = ts
        super().apply_tool(ts)

    def initial_tool_load(self, number: int) -> None:
        self._load_tool(number)

    def tool_change(self, ts: ToolSetting, mode: str = "m0",
                    message: str | None = None) -> None:
        """Spindle stop, the top of Z, then the changer's ``T M6`` and the
        length offset (mode "m6"), or a manual change behind ``M0``."""
        self._check_tool(ts)
        self._tool = ts
        self.comment(f"--- Tool Change -> T{ts.number}: {ts.name} ({ts.diameter_mm:.2f} mm) ---")
        self.spindle_off()
        self._retract_top()
        if mode == "m6":
            self._load_tool(ts.number)
        else:
            self.comment(message or (f"Load tool T{ts.number}: {ts.name} "
                                     f"({ts.diameter_mm:.2f} mm), set tool length, then resume"))
            self._lines.append("M0")
            self._lines += self._modal_block()
        self.tool_diameter_mm = ts.diameter_mm
        self.feed_rate_mmpm = ts.feed_rate_mmpm
        self.plunge_rate_mmpm = ts.plunge_rate_mmpm
        self.spindle_rpm = ts.spindle_rpm
        self.spindle_on()

    # ------------------------------------------------------------- ends

    def end_side(self, pause: str | None = None) -> None:
        self._lines.append("M5")
        self._retract_top()
        if self.index_a_deg is not None:
            self.unwind()
        if pause:
            self.program_pause(pause)

    def end_program(self) -> None:
        self._lines.append("M5")
        self._retract_top()
        if self.index_a_deg is not None:
            self.unwind()
        self._lines.append("M30")

    # ------------------------------------------------------------- arcs

    def _emit_moves(self, pts: list[tuple[float, float, float]], arc_tol: float) -> None:
        if arc_tol <= 0:
            super()._emit_moves(pts, arc_tol)
            return
        from .arcfit import fit_arcs
        cur = pts[0]
        for mv in fit_arcs(pts, tol_mm=arc_tol):
            end = mv[1]
            if mv[0] == "arc":
                (cx, cy), ccw = mv[2], mv[3]
                self._split_arc(cur, end, cx, cy, ccw)
            else:
                self.feed(x=end[0], y=end[1], z=end[2])
            cur = end

    def _split_arc(self, start, end, cx: float, cy: float, ccw: bool) -> None:
        """One fitted arc as blocks of at most `MAX_SWEEP_DEG`, Z shared out
        along the sweep (a helix stays one); a radius out of range feeds straight."""
        r = math.hypot(start[0] - cx, start[1] - cy)
        if not MIN_ARC_RADIUS_MM <= r <= MAX_ARC_RADIUS_MM:
            self.feed(x=end[0], y=end[1], z=end[2])
            return
        a0 = math.atan2(start[1] - cy, start[0] - cx)
        a1 = math.atan2(end[1] - cy, end[0] - cx)
        if math.hypot(end[0] - start[0], end[1] - start[1]) < 1e-9:
            sweep = 2.0 * math.pi                      # a full circle
        else:
            sweep = ((a1 - a0) if ccw else (a0 - a1)) % (2.0 * math.pi)
        n = max(1, math.ceil(math.degrees(sweep) / MAX_SWEEP_DEG - 1e-9))
        prev = start
        for k in range(1, n + 1):
            if k == n:
                p = end
            else:
                t = k / n
                a = a0 + (sweep * t if ccw else -sweep * t)
                p = (cx + r * math.cos(a), cy + r * math.sin(a),
                     start[2] + (end[2] - start[2]) * t)
            self.arc(p[0], p[1], p[2], cx - prev[0], cy - prev[1], ccw)
            prev = p

    # ------------------------------------------------------------- output

    def to_string(self) -> str:
        """The program, every line UCCNC's: a ``;`` note a shared caller wrote
        (a preamble, a re-zero note) becomes a parenthesized line of its own."""
        out: list[str] = []
        for line in self._lines:
            code, sep, note = line.partition(";")
            if not sep or line.lstrip().startswith("("):
                out.append(line)
                continue
            out += comment_lines(note)
            if code.strip():
                out.append(code.rstrip())
        text = "\n".join(out) + "\n"
        text.encode("ascii")            # a non-ASCII character is a post bug: say so
        return text
