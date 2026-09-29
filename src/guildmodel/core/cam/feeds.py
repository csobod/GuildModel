"""Feeds & speeds / chip-load calculator (BUILDPLAN M7.10).

Pure functions tying the tool (flutes / diameter) to the program's feed and
spindle, so the maker can check the *chip load* (feed per tooth) and *surface
speed* the CAM tab is about to post — and a material's chip-load window flags a
cut that's too light (rubbing) or too heavy. No persistence; the CAM tab reads
these and the per-material window from `materials.yaml`.

  chip load   = feed / (spindle · flutes)            [mm per tooth]
  surface vc  = π · diameter · spindle               [m/min]
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def chip_load_mm(feed_mmpm: float, rpm: float, flutes: int) -> float | None:
    """Feed per tooth (mm/tooth). None when rpm or flutes is non-positive."""
    if rpm <= 0 or flutes <= 0:
        return None
    return feed_mmpm / (rpm * flutes)


def feed_from_chip_load_mmpm(chip_load_mm: float, rpm: float, flutes: int) -> float:
    """The feed (mm/min) that yields a target chip load — the inverse."""
    return chip_load_mm * rpm * flutes


def surface_speed_m_per_min(diameter_mm: float, rpm: float) -> float:
    """Cutting (surface) speed vc in m/min = π · D · n."""
    return math.pi * (diameter_mm / 1000.0) * rpm


def chip_load_status(chip_load_mm: float | None,
                     lo: float | None, hi: float | None) -> str:
    """Classify a chip load against a material's window:
    ``"low"`` (rubbing), ``"ok"``, ``"high"`` (overloaded), or ``"unknown"``."""
    if chip_load_mm is None or lo is None or hi is None:
        return "unknown"
    if chip_load_mm < lo:
        return "low"
    if chip_load_mm > hi:
        return "high"
    return "ok"


# ------------------------------------------------------------------ the Cut tab's row

#: CastleCamParams' feed, plunge and spindle: the Cut tab's material row, which
#: is filled from the project material.
ROW_FEED_FIELDS: tuple[str, ...] = ("feed_rate_mmpm", "plunge_rate_mmpm", "spindle_rpm")


def material_key(name) -> str:
    """A material's preset key from its display name, as the posting paths read it."""
    return (str(name or "").split() or ["acetate"])[0].lower()


def for_material(cam, material, project_material):
    """`cam` for a part cut from `material` (2026-09-29).

    The Cut tab's feed, plunge and spindle are the project material's. A part cut
    from another (a base-curve block in acetal among acetate parts) gets them
    unset, so the machine clamp fills them from its own material's preset; the
    part's own overrides go on after this and still win. Without it the per-tool
    feeds cut a lone block at the acetate front's feeds, and the bed always had."""
    if material_key(material) == material_key(project_material):
        return cam
    return cam.model_copy(update=dict.fromkeys(ROW_FEED_FIELDS))


# ------------------------------------------------------------------ per-tool feeds

@dataclass(frozen=True)
class ResolvedFeeds:
    """The feeds one tool cuts at, before the machine clamp, and where each came
    from: ``"project"`` (the tool's row on the Cut tab), ``"tool"`` (the library
    entry's own feeds) or ``"material"`` (the program's own feeds — the Cut
    tab's material row, or the preset)."""
    feed_rate_mmpm: float
    plunge_rate_mmpm: float
    spindle_rpm: int
    sources: tuple[str, str, str]

    def source_label(self) -> str:
        """One tag for the row: the strongest source in play."""
        if "project" in self.sources:
            return "this project"
        if "tool" in self.sources:
            return "tool library"
        return "material"


def resolve_tool_feeds(
    tool: dict | None,
    *,
    default_feed: float,
    default_plunge: float,
    default_spindle: float,
    override=None,
) -> ResolvedFeeds:
    """Resolve one tool's feed, plunge and spindle (2026-09-27).

    Field by field: the project's per-tool setting (`override`, a `ToolFeeds` or
    a plain dict), else the tool's own library feeds (`tool`, a tools.yaml
    entry), else the program's defaults — so a project that sets only the feed
    keeps the library's plunge and spindle. This is the one place the precedence
    lives: `castle_ops.build_tool_settings` posts with it and the Cut tab shows
    it, so what the maker reads is what the machine gets.
    """
    t = tool or {}

    def _override(field: str):
        if override is None:
            return None
        if isinstance(override, dict):
            return override.get(field)
        return getattr(override, field, None)

    def pick(field: str, default: float) -> tuple[float, str]:
        v = _override(field)
        if v:
            return float(v), "project"
        v = t.get(field)
        if v:
            return float(v), "tool"
        return float(default or 0.0), "material"

    feed, s_feed = pick("feed_rate_mmpm", default_feed)
    plunge, s_plunge = pick("plunge_rate_mmpm", default_plunge)
    spindle, s_spindle = pick("spindle_rpm", default_spindle)
    return ResolvedFeeds(feed, plunge, int(round(spindle)), (s_feed, s_plunge, s_spindle))
