"""GRBL G-code post-processor.

Emits standard GRBL dialect only: G0/G1/G2/G3, G20/G21, G90, M3/M5.
No canned cycles (GRBL lacks them).
M0 program pause is used between sides, or two separate .nc files are emitted
(two-file is the safer default for non-expert users).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


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

    def plunge(self, z: float) -> None:
        self.feed(z=z, feed=self.plunge_rate_mmpm)

    def safe_retract(self) -> None:
        self.rapid(z=self.safe_z_mm)

    def program_pause(self, message: str = "Flip stock and re-register on dowel pins") -> None:
        self._lines.append(f"; {message}")
        self._lines.append("M0")

    def end_program(self) -> None:
        self._lines += ["M5", "G0 Z" + f"{self.safe_z_mm:.3f}", "M30"]

    def emit_polyline(self, points: list[tuple[float, float, float]], first_move_is_plunge: bool = True) -> None:
        if not points:
            return
        x0, y0, z0 = points[0]
        self.safe_retract()
        self.rapid(x=x0, y=y0)
        if first_move_is_plunge:
            self.plunge(z0)
        else:
            self.feed(x=x0, y=y0, z=z0)
        for x, y, z in points[1:]:
            self.feed(x=x, y=y, z=z)

    def to_string(self) -> str:
        return "\n".join(self._lines) + "\n"

    def write(self, path: Path) -> None:
        path.write_text(self.to_string(), encoding="utf-8")
