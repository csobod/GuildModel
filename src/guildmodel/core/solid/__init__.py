"""B-Rep solid modelling (BUILDPLAN Stage 2).

The master representation of the frame. `core/relief` becomes a *derived* view
of this, produced by ray-casting for the CAM alone — see BREP-REWRITE-REPORT.md
§4.2 for why that direction matters: the drop-cutter is hardware-proven and
carries the INCIDENT-2026-07-29 fix, so it keeps consuming a `Heightfield` with
exactly today's semantics.

Importing this package loads OCP (~70 MB of shared libraries). Keep it off the
application startup path — import it where a solid is actually built.
"""
from .build import (build_castle_solid, build_terraces, castle_base,
                    clear_base_cache, zone_heights)
from .occ import BooleanError, cut_many, is_valid, volume
from .tessellate import Tessellation, tessellate
from .zmap import grid_for, solid_cam_relief, solid_to_relief, solid_to_zmap

__all__ = [
    "BooleanError",
    "Tessellation",
    "build_castle_solid",
    "build_terraces",
    "castle_base",
    "clear_base_cache",
    "cut_many",
    "grid_for",
    "is_valid",
    "solid_cam_relief",
    "solid_to_relief",
    "solid_to_zmap",
    "tessellate",
    "volume",
    "zone_heights",
]
