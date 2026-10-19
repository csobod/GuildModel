"""Layer vocabulary: single source of truth for all GuildModel layer names and styles.

GuildDraw exports layers; GuildModel consumes them.  All layer-name strings and
display styles are defined here so importers, validators, and GUI widgets stay
in sync without hardcoding strings in multiple places.

Layer contract (GuildDraw → GuildModel):
  OUTLINE   — frame outer profile; exactly one required; drives profile cut.
  LENS      — lens apertures; exactly two required; drives lens pocket + groove.
  BRIDGE    — bridge cutaway path; optional; drives angled bridge cut.
  COMPONENT — pocket outlines for what mounts on the posterior: hinges,
              bridges, endpieces, bridge bars; optional; drives the Component
              Pockets op. HINGE until 2.0: every drawing made before says
              HINGE, and it is read as COMPONENT (`LAYER_ALIASES`).
  REF       — construction / reference geometry; imported but never machined.
  SCULPT    — back-surface scallop guide curves (GuildDraw Phase 14); optional.
  ENGRAVING — temple arm engraving marks (GuildDraw Phase 14, v2 machining).
  INLAY     — a seat for a plaque, a laminate or a plate (GuildDraw 2.0; front
              and temples); closed; nested curves are steps; one inside a
              COMPONENT curve is a step in its pocket's floor. Read and
              shown now; modeled and cut by the inlay milestone (BUILDPLAN
              §8a), with depth and face kept here per inlay.
"""
from __future__ import annotations

# Every layer name GuildModel will import (others are logged as unrecognized)
ALL_LAYERS: frozenset[str] = frozenset({
    "OUTLINE",
    "LENS",
    "BRIDGE",
    "COMPONENT",
    "REF",
    "SCULPT",
    "ENGRAVING",
    "INLAY",
})

# Layers that drive machining toolpaths (REF is display-only)
MACHINED_LAYERS: frozenset[str] = frozenset({
    "OUTLINE",
    "LENS",
    "BRIDGE",
    "COMPONENT",
    "SCULPT",
    "ENGRAVING",
    "INLAY",
})

# 2D canvas display styles: layer → (color_hex, line_width_px)
# Order here controls the order checkboxes appear in the params panel.
LAYER_STYLES: dict[str, tuple[str, float]] = {
    "OUTLINE":   ("#1a1a1a", 2.0),
    "LENS":      ("#1a6cbf", 1.5),
    "COMPONENT": ("#d94f1a", 1.5),
    "BRIDGE":    ("#2e8040", 1.0),
    "SCULPT":    ("#8040bf", 1.0),   # purple — back-surface scallop guide
    "ENGRAVING": ("#1a9a9a", 0.8),   # teal — temple engraving
    "INLAY":     ("#a67c00", 1.5),   # gold — a seat for a plaque or a plate (2.0)
    "REF":       ("#888888", 0.8),
}

#: Layer names a drawing may carry for a layer GuildModel reads under another
#: name. HINGE became COMPONENT in 2.0, and every drawing, library entry and
#: DXF made before says HINGE: the alias is permanent.
LAYER_ALIASES: dict[str, str] = {"HINGE": "COMPONENT"}


def canonical_layer(name):
    """The layer GuildModel reads `name` as: upper-cased, an alias resolved.
    Anything that is not a string comes back as it is."""
    if not isinstance(name, str):
        return name
    up = name.upper()
    return LAYER_ALIASES.get(up, up)
