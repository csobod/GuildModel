"""Typed tool model (BUILDPLAN M7.8).

Promotes the loose ``config/tools.yaml`` entries to a validated `ToolSpec` so the
tool library (the `gui.tool_store` + the Preferences ▸ Tools editor) and the M7.9
visualizer have one definition of a tool. `ToolSpec.to_tool_dict()` emits exactly
the dict shape the existing consumers read (`resolve_tool`, `build_tool_settings`,
`ToolProfile.from_tool`, the drop-cutter) — `type` / `diameter_mm` / `radius_mm` /
`corner_radius_mm` / `flutes` / optional per-tool feeds — so the typed model is a
drop-in over the raw YAML, never a break.

`radius_mm` is always derived from the diameter (every shipped tool already has
``radius == diameter / 2``); the model is the single source of that truth.
"""
from __future__ import annotations

from pydantic import BaseModel

# tool types the geometry understands. `vbit` carries an included angle for the
# M7.9 visualizer / engraving profile; `groove` is a side-cutting V-form (the
# lens-bevel drageoir, V1) — never swept by the top-down cut sim; the others
# map to ToolProfile kinds.
TOOL_TYPES = ("flat", "ball", "toroid", "vbit", "groove")

# Optional per-tool feed/limit fields (None = fall back to the material preset).
_FEED_FIELDS = ("feed_rate_mmpm", "plunge_rate_mmpm", "spindle_rpm", "max_doc_mm")


class ToolSpec(BaseModel):
    """One cutting tool. The library key (its stable id) is stored alongside, in
    the tool_store map; this model holds the geometry + feeds."""

    display_name: str = ""
    type: str = "flat"                       # flat | ball | toroid | vbit | groove
    diameter_mm: float = 3.175
    corner_radius_mm: float = 0.0            # toroid corner radius
    included_angle_deg: float = 0.0          # vbit included (tip) angle
    groove_depth_mm: float = 0.0             # groove form: radial V depth
    groove_width_mm: float = 0.0             # groove form: V opening height
    neck_diameter_mm: float = 0.0            # groove form: relieved neck above the head
    flutes: int = 1
    flute_length_mm: float = 0.0             # usable cutting depth (0 = unspecified)
    shank_diameter_mm: float = 0.0
    number: int = 0                          # stable T-number (0 = auto-assign)
    feed_rate_mmpm: float | None = None
    plunge_rate_mmpm: float | None = None
    spindle_rpm: float | None = None
    max_doc_mm: float | None = None
    notes: str = ""

    @property
    def radius_mm(self) -> float:
        return self.diameter_mm / 2.0

    @classmethod
    def from_dict(cls, data: dict) -> "ToolSpec":
        """Read one ``tools.yaml`` entry (back-compatible: the new fields are
        optional and default; ``radius_mm`` in the file is ignored — derived)."""
        d = dict(data or {})
        d.pop("radius_mm", None)             # derived from diameter
        d.pop("_deleted", None)              # a store tombstone, never a field
        known = set(cls.model_fields)
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_tool_dict(self) -> dict:
        """The dict the existing CAM/post/sim consumers read (incl. the derived
        ``radius_mm``); feeds/limits are omitted when unset, matching today's YAML."""
        out: dict = {
            "display_name": self.display_name or "",
            "type": self.type,
            "diameter_mm": self.diameter_mm,
            "radius_mm": self.radius_mm,
            "corner_radius_mm": self.corner_radius_mm,
            "flutes": self.flutes,
        }
        if self.type == "vbit" and self.included_angle_deg:
            out["included_angle_deg"] = self.included_angle_deg
        if self.type == "groove":
            out["groove_depth_mm"] = self.groove_depth_mm
            out["groove_width_mm"] = self.groove_width_mm
            if self.neck_diameter_mm:
                out["neck_diameter_mm"] = self.neck_diameter_mm
        if self.flute_length_mm:
            out["flute_length_mm"] = self.flute_length_mm
        if self.shank_diameter_mm:
            out["shank_diameter_mm"] = self.shank_diameter_mm
        if self.number:
            out["number"] = self.number
        for f in _FEED_FIELDS:
            v = getattr(self, f)
            if v is not None:
                out[f] = v
        if self.notes:
            out["notes"] = self.notes
        return out

    def to_yaml(self) -> dict:
        """The dict persisted to ``~/.guildmodel/tools.yaml`` (same shape as a shipped
        entry, so the raw shipped+user merge stays consumer-complete)."""
        return self.to_tool_dict()
