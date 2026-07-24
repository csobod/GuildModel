"""Hinge pocket geometry.

Models a metal hinge seat as a (optionally tilted, optionally ramped) rectangular
pocket in the frame front or temple.  Uses the CHA.dll parameter vocabulary from
the OLGA plugin suite:

  RotationCharniere        — yaw of the hinge box about the Z axis (deg)
  EncombrementCharniere    — pocket footprint envelope (w × h, mm)
  ProfondeurPocheCharniere — flat pocket depth (mm)
  InclinaisonPocheCharniere— tilt of the pocket floor (deg)
  InclinaisonPente         — ramp lead-in angle (deg)
  RotationPenteCharniere   — ramp orientation (deg)
  ProfondeurPenteCharniere — depth at the deep end of the ramp (mm)

The actual machining is delegated to pocket.py; this module only builds geometry.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from shapely.affinity import rotate, translate
from shapely.geometry import Polygon


# ── Data models ────────────────────────────────────────────────────────────────

@dataclass
class HingeSpec:
    """Catalog entry describing the physical geometry of one hinge type.

    All lengths in mm, all angles in degrees.
    """
    name: str
    footprint_w_mm: float        # EncombrementCharniere width (along hinge axis)
    footprint_h_mm: float        # EncombrementCharniere height (across hinge axis)
    pocket_depth_mm: float       # ProfondeurPocheCharniere
    pocket_tilt_deg: float = 0.0 # InclinaisonPocheCharniere — floor tilt
    ramp_angle_deg: float = 0.0  # InclinaisonPente
    ramp_rotation_deg: float = 0.0  # RotationPenteCharniere
    ramp_depth_mm: float = 0.0   # ProfondeurPenteCharniere
    notes: str = ""

    def has_ramp(self) -> bool:
        return self.ramp_depth_mm > 0.0 and self.ramp_angle_deg > 0.0


@dataclass
class HingePlacement:
    """Where a hinge sits on the frame, in frame local coordinates (mm, deg).

    x, y     — pocket centre in frame XY plane
    rotation — RotationCharniere: yaw of the hinge box about Z (deg, CCW positive)
    face     — which side of the frame (front face vs back)
    """
    x: float
    y: float
    rotation_deg: float = 0.0
    face: Literal["front", "back"] = "front"


# ── Geometry builders ──────────────────────────────────────────────────────────

def hinge_pocket_polygon(placement: HingePlacement, spec: HingeSpec) -> Polygon:
    """Return the rotated, translated rectangular pocket footprint as a Shapely Polygon.

    The rectangle is centred on (placement.x, placement.y) and rotated by
    placement.rotation_deg.  Pass the result directly to pocket.hinge_pocket().

    Note: pocket.hinge_pocket() traces the boundary at full depth without inward
    tool-radius compensation — the caller must pre-offset this polygon inward by
    tool_radius_mm before passing it if tight dimensional accuracy is needed.
    """
    hw = spec.footprint_w_mm / 2.0
    hh = spec.footprint_h_mm / 2.0
    rect = Polygon([(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)])
    rotated = rotate(rect, placement.rotation_deg, origin=(0, 0), use_radians=False)
    return translate(rotated, placement.x, placement.y)


def ramp_entry_points(
    placement: HingePlacement,
    spec: HingeSpec,
) -> list[tuple[float, float, float]]:
    """Return (x, y, z) waypoints for the lead-in ramp into the pocket.

    The ramp starts at the pocket face at z=0 and descends to
    -spec.ramp_depth_mm over a horizontal run computed from ramp_angle_deg.
    Returns an empty list if the spec has no ramp.

    The ramp direction is (spec.ramp_rotation_deg + placement.rotation_deg),
    measuring from +X CCW.
    """
    if not spec.has_ramp():
        return []

    angle_rad = math.radians(spec.ramp_angle_deg)
    horizontal_run = spec.ramp_depth_mm / math.tan(angle_rad) if angle_rad > 1e-9 else 0.0

    direction_deg = spec.ramp_rotation_deg + placement.rotation_deg
    dir_rad = math.radians(direction_deg)
    dx = math.cos(dir_rad)
    dy = math.sin(dir_rad)

    # Start: pocket centre at z=0 surface; end: ramp_depth below, horizontal_run away
    x0, y0 = placement.x, placement.y
    x1 = x0 + dx * horizontal_run
    y1 = y0 + dy * horizontal_run

    return [
        (x0, y0, 0.0),
        (x1, y1, -spec.ramp_depth_mm),
    ]


# ── Catalog I/O ────────────────────────────────────────────────────────────────

def load_hinge_catalog(yaml_path: Path) -> dict[str, HingeSpec]:
    """Load a hinge catalog YAML and return a name → HingeSpec mapping."""
    with open(yaml_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    catalog: dict[str, HingeSpec] = {}
    for entry in data.get("hinges", []):
        spec = HingeSpec(
            name=entry["name"],
            footprint_w_mm=float(entry["footprint_w_mm"]),
            footprint_h_mm=float(entry["footprint_h_mm"]),
            pocket_depth_mm=float(entry["pocket_depth_mm"]),
            pocket_tilt_deg=float(entry.get("pocket_tilt_deg", 0.0)),
            ramp_angle_deg=float(entry.get("ramp_angle_deg", 0.0)),
            ramp_rotation_deg=float(entry.get("ramp_rotation_deg", 0.0)),
            ramp_depth_mm=float(entry.get("ramp_depth_mm", 0.0)),
            notes=str(entry.get("notes", "")),
        )
        catalog[spec.name] = spec

    return catalog
