"""B-Rep solid modelling (BUILDPLAN Stage 2).

The master representation of the frame. `core/relief` becomes a *derived* view
of this, produced by ray-casting for the CAM alone — see BREP-REWRITE-REPORT.md
§4.2 for why that direction matters: the drop-cutter is hardware-proven and
carries the INCIDENT-2026-07-29 fix, so it keeps consuming a `Heightfield` with
exactly today's semantics.

Importing this package loads OCP (~70 MB of shared libraries). Keep it off the
application startup path — import it where a solid is actually built.
"""
from .build import build_castle_solid, build_terraces, zone_heights
from .occ import BooleanError, is_valid, volume

__all__ = [
    "BooleanError",
    "build_castle_solid",
    "build_terraces",
    "is_valid",
    "volume",
    "zone_heights",
]
