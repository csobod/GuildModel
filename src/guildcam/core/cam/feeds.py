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
