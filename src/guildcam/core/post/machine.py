"""Machine-profile loading, output clamping, and program linting (BUILDPLAN M4.8).

A `MachineProfile` (project.schema) describes a GRBL-family controller's
capabilities. This module loads the shipped profiles (config/machines/*.yaml),
adapts the post's outputs to a profile (clamp feeds / plunge / spindle / depth
of cut, decide arc vs. linearized output), and lints a posted program against
the profile (feed ceilings, spindle range, work-envelope fit, arc support).

The aim of M4.8 task 3: the same frame should produce a *compliant* program on
any supported machine, or a clear, actionable warning when it cannot.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..project.schema import MachineProfile

# config/machines/ relative to the package root: core/post/machine.py ->
# parents[2] is src/guildcam/, where config/ lives.
_MACHINES_DIR = Path(__file__).resolve().parents[2] / "config" / "machines"


def machines_dir(config_dir: Path | None = None) -> Path:
    return Path(config_dir) / "machines" if config_dir else _MACHINES_DIR


def available_machines(config_dir: Path | None = None) -> list[tuple[str, str]]:
    """(name, display_name) for every shipped profile, Guild first."""
    out: list[tuple[str, str]] = []
    for f in sorted(machines_dir(config_dir).glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        out.append((data.get("name", f.stem), data.get("display_name", f.stem)))
    out.sort(key=lambda t: (t[0] != "guild_cnc", t[1]))
    return out


def load_machine_profile(name: str, config_dir: Path | None = None) -> MachineProfile:
    """Load a profile by name; fall back to the built-in Guild default."""
    path = machines_dir(config_dir) / f"{name}.yaml"
    if not path.exists():
        if name == "guild_cnc":
            return MachineProfile()
        raise FileNotFoundError(f"machine profile not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return MachineProfile(**data)


# ------------------------------------------------------------------ clamping

@dataclass
class ClampedOutputs:
    feed_rate_mmpm: float
    plunge_rate_mmpm: float
    spindle_rpm: int
    contour_stepdown_mm: float
    arc_tol_mm: float
    warnings: list[str] = field(default_factory=list)


def apply_machine_limits(
    profile: MachineProfile,
    *,
    feed_rate_mmpm: float,
    plunge_rate_mmpm: float,
    spindle_rpm: float,
    contour_stepdown_mm: float,
    requested_arc_tol_mm: float,
    material_max_doc_mm: float | None = None,
) -> ClampedOutputs:
    """Clamp requested feeds/plunge/spindle/DOC to the machine, and choose the
    arc tolerance (0 => linearize on controllers without reliable arcs).

    Every clamp that actually changes a value adds an actionable warning.
    """
    warns: list[str] = []

    feed = feed_rate_mmpm
    if feed > profile.max_feed_mmpm:
        warns.append(f"feed {feed:.0f} > machine max {profile.max_feed_mmpm:.0f} mm/min — clamped")
        feed = profile.max_feed_mmpm

    plunge = plunge_rate_mmpm
    if plunge > profile.max_plunge_mmpm:
        warns.append(f"plunge {plunge:.0f} > machine max {profile.max_plunge_mmpm:.0f} mm/min — clamped")
        plunge = profile.max_plunge_mmpm

    spindle = float(spindle_rpm)
    if spindle > profile.max_spindle_rpm:
        warns.append(f"spindle {spindle:.0f} > machine max {profile.max_spindle_rpm:.0f} RPM — clamped")
        spindle = profile.max_spindle_rpm
    elif profile.min_spindle_rpm and spindle < profile.min_spindle_rpm:
        warns.append(f"spindle {spindle:.0f} < machine min {profile.min_spindle_rpm:.0f} RPM — raised")
        spindle = profile.min_spindle_rpm

    doc_cap = profile.max_doc_mm
    if material_max_doc_mm is not None:
        doc_cap = min(doc_cap, material_max_doc_mm)
    stepdown = contour_stepdown_mm
    if stepdown > doc_cap:
        warns.append(f"stepdown {stepdown:.2f} > max depth-of-cut {doc_cap:.2f} mm — clamped")
        stepdown = doc_cap

    arc_tol = requested_arc_tol_mm
    if not profile.supports_arcs:
        if requested_arc_tol_mm > 0:
            warns.append("machine has no reliable arc support — linearizing curves to G1")
        arc_tol = 0.0

    return ClampedOutputs(feed, plunge, int(round(spindle)), stepdown, arc_tol, warns)


# ------------------------------------------------------------------ linting

_AXIS = re.compile(r"([XYZFS])\s*(-?\d*\.?\d+)")


def lint_program(text: str, profile: MachineProfile) -> list[str]:
    """Check a posted program against the profile. Returns actionable warnings.

    The part envelope (XY/Z span of all moves) must fit the machine work area —
    a necessary condition independent of where the operator sets work zero.
    Also flags feeds above the ceiling, spindle out of range, and G2/G3 emitted
    to a controller without arc support.
    """
    warns: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    x = y = z = None
    max_feed = 0.0
    spindles: list[float] = []
    has_arc = False

    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith((";", "(")):
            continue
        if s.startswith(("G2", "G3")) and not s[2:3].isdigit():
            has_arc = True
        words = dict((m[0], float(m[1])) for m in _AXIS.findall(s.split(";")[0]))
        if "X" in words:
            x = words["X"]; xs.append(x)
        if "Y" in words:
            y = words["Y"]; ys.append(y)
        if "Z" in words:
            z = words["Z"]; zs.append(z)
        if "F" in words:
            max_feed = max(max_feed, words["F"])
        if "S" in words:
            spindles.append(words["S"])

    if xs and ys:
        ext_x, ext_y = max(xs) - min(xs), max(ys) - min(ys)
        if ext_x > profile.work_area_x_mm or ext_y > profile.work_area_y_mm:
            warns.append(
                f"part envelope {ext_x:.0f}×{ext_y:.0f} mm exceeds work area "
                f"{profile.work_area_x_mm:.0f}×{profile.work_area_y_mm:.0f} mm")
    if zs and (max(zs) - min(zs)) > profile.work_area_z_mm:
        warns.append(
            f"Z travel {max(zs) - min(zs):.0f} mm exceeds work area Z "
            f"{profile.work_area_z_mm:.0f} mm")
    if max_feed > profile.max_feed_mmpm + 1e-6:
        warns.append(f"programmed feed {max_feed:.0f} exceeds machine max "
                     f"{profile.max_feed_mmpm:.0f} mm/min")
    for sp in spindles:
        if sp > profile.max_spindle_rpm + 1e-6:
            warns.append(f"spindle {sp:.0f} exceeds machine max "
                         f"{profile.max_spindle_rpm:.0f} RPM")
            break
        if profile.min_spindle_rpm and sp + 1e-6 < profile.min_spindle_rpm:
            warns.append(f"spindle {sp:.0f} below machine min "
                         f"{profile.min_spindle_rpm:.0f} RPM")
            break
    if has_arc and not profile.supports_arcs:
        warns.append("G2/G3 arcs present but machine profile reports no arc support")
    return warns
